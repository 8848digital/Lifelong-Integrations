import urllib.parse
from datetime import datetime, timedelta

import frappe
import requests

from lifelong_integrations.lifelong_integrations.api.live_site_api import (
    live_site_connection, remote_get_list)
from lifelong_integrations.lifelong_integrations.doctype.freshdesk_api_log.freshdesk_api_log import \
    freshdesk_log
from lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.freshdesk_settings import \
    get_merged_freshdesk_settings


def get_filters_for_ticket(freshdesk):
	"""Build a Freshdesk ticket search query string from the configured ticket filter rows."""
	query = []
	for row in freshdesk.get("ticket_filters") or []:
		technical_name = row.get("technical_name")
		value = row.get("value")
		if technical_name and value is not None:
			if row.get("is_integer"):
				query.append(f"""{technical_name}:{value}""")
			else:
				query.append(f"""{technical_name}:'{urllib.parse.quote_plus(value)}'""")
	return " AND ".join(query)


def get_created_date_filter(freshdesk, in_iso_format=False):
	"""Return a date filter clause limiting tickets to those created/updated since the configured sync window."""
	today = datetime.now()
	filter_date = None
	if freshdesk.get("sync_ticket_before_days"):
		filter_date = today - timedelta(days=freshdesk.get("sync_ticket_before_days"))
	if filter_date:
		if not in_iso_format:
			return f"""created_at:>'{str(filter_date.date())}'"""
		else:
			return f"""updated_since={filter_date.isoformat()}"""


def filter_ticket_by_sub_code(tickets):
	"""Keep tickets that are Spares Requested (pending on Spares AND sub code Spares Requested) or Replacement (pending on Replacement OR sub code Replacement Requested)."""
	res = []
	for ticket in tickets:
		if custom_fields := ticket.get("custom_fields"):
			cf_sub_code_spare_cond = False
			cf_pending_on_spare_cond = False
			cf_sub_code_replacement_cond = False
			cf_pending_on_replacement_cond = False
			for cf in custom_fields:
				if "cf_sub_code" in cf and custom_fields[cf] == "Spares Requested":
					cf_sub_code_spare_cond = True
				if "cf_pending_on" in cf and custom_fields[cf] == "Spares":
					cf_pending_on_spare_cond = True
				if "cf_sub_code" in cf and custom_fields[cf] == "Replacement Requested":
					cf_sub_code_replacement_cond = True
				if "cf_pending_on" in cf and custom_fields[cf] == "Replacement":
					cf_pending_on_replacement_cond = True
			if (cf_pending_on_spare_cond and cf_sub_code_spare_cond) or (
				cf_pending_on_replacement_cond or cf_sub_code_replacement_cond
			):
				res.append(ticket)
	return res


def filter_new_tickets(tickets):
	"""Keep only open/pending tickets that don't yet have a quotation, or are flagged for a quotation update."""
	tickets = [
		t for t in tickets if t.get("id") and str(t.get("status")) not in ["4", "5"]
	]
	if not tickets:
		return []

	freshdesk_ids = [t.get("id") for t in tickets]
	quotations = remote_get_list(
		"Quotation",
		filters={
			"docstatus": ["!=", 2],
			"freshdesk_id": ["in", freshdesk_ids],
		},
		fields=["freshdesk_id"],
	)
	existing_ids = {q.get("freshdesk_id") for q in quotations}

	res = []
	for ticket in tickets:
		custom_fields = ticket.get("custom_fields") or {}
		if ticket.get("id") not in existing_ids or custom_fields.get("cf_update_quotation"):
			res.append(ticket)
	return res


def get_tickets(freshdesk=None, from_scheduler=False, page=None, wait_time=None):
	"""Fetch tickets from Freshdesk (paginated, with rate-limit retry) and dispatch quotation creation for each."""
	if wait_time:
		# To Handle Rate Limit error from FreshDesk API
		import time

		time.sleep(wait_time)

	if not freshdesk:
		freshdesk = get_merged_freshdesk_settings()
	if not freshdesk.get("enable") or not freshdesk.get("fetch_tickets"):
		return

	query_str = get_filters_for_ticket(freshdesk)
	date_filter = get_created_date_filter(freshdesk, False if query_str else True)
	default_ticket_per_page = 30
	current_ticket_count = 0
	if not page:
		page = 1
	endpoint = freshdesk.get("host")
	max_page_limit = 10
	if query_str:
		endpoint += f"""/api/v2/search/tickets?query="{query_str} And {date_filter}" """
	else:
		max_page_limit = 300
		endpoint += f"/api/v2/tickets?{date_filter}"

	headers = {"Content-Type": "application/json"}
	tickets = []
	total_ticket_count = 0
	try:
		while True:
			resp = requests.get(
				endpoint + f"&page={page}", headers=headers, auth=(freshdesk.get("api_key"), "X")
			)
			if from_scheduler and resp.status_code == 429:
				frappe.enqueue(
					get_tickets,
					freshdesk=freshdesk,
					from_scheduler=from_scheduler,
					page=page,
					wait_time=75,  # Wait 1.25 mins and start sending API requests
					timeout=500,
				)
				break
			current_ticket_count += default_ticket_per_page
			if resp.status_code in range(200, 300) and resp.content:
				resp_json = resp.json()
				results = resp_json["results"] if query_str else resp_json
				filtered_tickets = filter_ticket_by_sub_code(results)
				freshdesk_log(
					response=resp,
					endpoint=endpoint + f"&page={page}",
					api="GET TICKETS",
					message=filtered_tickets or [{}],
				)
				if query_str:
					total_ticket_count = resp_json["total"]
				else:
					total_ticket_count = total_ticket_count + len(results) + 1
				tickets.extend(filtered_tickets)
			else:
				freshdesk_log(response=resp, endpoint=endpoint + f"&page={page}", api="GET TICKETS")
			page += 1
			if current_ticket_count >= total_ticket_count or page > max_page_limit:
				break
		tickets = filter_new_tickets(tickets)
	except Exception:
		freshdesk_log(api="GET Tickets", endpoint=endpoint)

	for ticket in tickets:
		frappe.enqueue(
			create_quotation_on_live_site,
			queue="long",
			timeout=300,
			ticket=ticket,
			enqueue_after_commit=True,
		)


def create_quotation_on_live_site(ticket):
	"""Call the live site's whitelisted endpoint to create/update a quotation for a single Freshdesk ticket."""
	base_url, headers = live_site_connection()
	url = f"{base_url}/api/method/freshdesk_integration.freshdesk_integration.doctype.freshdesk_integration.utility_functions.create_update_quotation.create_quotation"

	response = None
	try:
		response = requests.post(url, headers=headers, json={"ticket": ticket}, timeout=120)
		response.raise_for_status()
	except Exception:
		freshdesk_log(
			api="CREATE QUOTATION (remote)",
			endpoint=url,
			response=getattr(response, "text", None) or str(response),
		)
