import json

import frappe
import requests

from lifelong_integrations.lifelong_integrations.api.live_site_api import \
    live_site_connection
from lifelong_integrations.lifelong_integrations.doctype.freshdesk_api_log.freshdesk_api_log import \
    freshdesk_log
from lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.freshdesk_settings import \
    get_merged_freshdesk_settings

Max_Retry_Limit = 5
LIVE_MODULE = "freshdesk_integration.freshdesk_integration.customizations.quotation.api.ticket_webhook_api"


@frappe.whitelist()
def check_stock_availability(
	ticket=None, check_inventory=False, retry_attempt=0, wait_time=None
):
	"""Webhook entrypoint that validates stock for a FreshDesk ticket and pushes the result back to FreshDesk.

	Retries itself via `frappe.enqueue` (see `validate_stock`) when FreshDesk rate-limits the
	ticket GET request, giving up after `Max_Retry_Limit` attempts.
	"""
	if retry_attempt >= Max_Retry_Limit:
		freshdesk_log(
			api="Update Stock Status to FreshDesk",
			endpoint=ticket,
			message=f"Skipped because Max Retry Limit ({Max_Retry_Limit}) Reached",
		)
		return
	if wait_time:
		# To Handle Rate Limit error from FreshDesk Get Ticket API
		import time

		time.sleep(wait_time)

	if isinstance(check_inventory, str):
		check_inventory = json.loads(check_inventory)

	if not check_inventory:
		return
	request_data = {}
	freshdesk = get_merged_freshdesk_settings()
	try:
		request_data = {
			"headers": dict(frappe.request.headers),
			"url": frappe.request.url,
			"args": frappe.form_dict,
		}
	except Exception:
		freshdesk_log(
			api="Failed to fetch request data", status_code=500, message=f"Ticket ID: {ticket}"
		)
	data = {}  # -For logging in try...except
	try:
		data = validate_stock(freshdesk, ticket, check_inventory, retry_attempt=retry_attempt)
		if data["stock_msg"]:
			data["stock_msg"] += "\n\n"
		data = f"""{data["stock_msg"]}{data["error_msg"]}
        """
		data = {
			"helpdesk_ticket": {
				"custom_field": {
					f"{freshdesk.get('freshdesk_stock_status_field')}_1934677": data,
					"cf_check_for_inventory_1934677": False,
				}
			}
		}
		endpoint = f"""{freshdesk.get("host")}/helpdesk/tickets/{ticket}.json"""
		headers = {"Content-Type": "application/json"}
		res = requests.put(
			endpoint,
			auth=(freshdesk.get("api_key"), "X"),
			headers=headers,
			data=json.dumps(data),
		)
		freshdesk_log(
			api="Update Stock Status to FreshDesk",
			response=res,
			request_data={**request_data, **data},
			endpoint=endpoint,
		)
	except Exception:
		freshdesk_log(
			api="Update Stock Status to FreshDesk",
			response=data,
			request_data=request_data,
			message=f"Ticket ID: {ticket}",
			status_code=500,
		)
	return data


def validate_stock(freshdesk, ticket=None, check_inventory=True, retry_attempt=0):
	"""Fetch the FreshDesk ticket, extract requested items/quantities, and check them against stock (via live site).

	Item list is built one of two ways: if the ticket's `cf_pending_on` custom field is
	"Replacement" and `cf_sub_code` is "Replacement Requested", it's treated as a product
	replacement ticket and the single item in `cf_erp_model` is used with qty 1. Otherwise,
	items/quantities are read from the fixed set of `item_code_fields` custom field pairs.

	The actual stock-availability check (Item existence, stock balance report, delivered/open
	qty lookups) runs on live site via `get_stock_status_for_items`, since those doctypes
	only exist there. On a 429 from FreshDesk, re-enqueues `check_stock_availability` after a delay.

	Returns a dict with `stock_msg` (per-item availability summary) and `error_msg`
	(missing ticket/warehouse or rate-limit messaging).
	"""
	stock_msg = ""
	error_msg = ""
	if not check_inventory:
		return {
			"stock_msg": stock_msg,
			"error_msg": error_msg,
		}
	if not ticket:
		error_msg += "Ticket ID is Missing In API. Kindly Check the Webhook\n"
		return {
			"stock_msg": stock_msg,
			"error_msg": error_msg,
		}

	if not freshdesk.get("warehouse"):
		error_msg += "Warehouse is Missing In FreshDesk Integration. Kindly Check the ERP\n"
		return {
			"stock_msg": stock_msg,
			"error_msg": error_msg,
		}

	headers = {"Content-Type": "application/json"}
	endpoint = freshdesk.get("host") + f"/api/v2/tickets/{ticket}"
	ticket_resp = requests.get(
		endpoint, auth=(freshdesk.get("api_key"), "X"), headers=headers
	)
	content = ticket_resp.content
	freshdesk_log(
		response=ticket_resp,
		endpoint=endpoint,
		api="GET TICKETS - Update Stock Status to FreshDesk",
	)
	if ticket_resp.status_code == 429:
		retry_attempt += 1
		if retry_attempt < Max_Retry_Limit:
			frappe.enqueue(
				check_stock_availability,
				ticket=ticket,
				check_inventory=check_inventory,
				retry_attempt=retry_attempt,
				wait_time=75,  # Wait 1.25 mins,
				timeout=150,
			)
			error_msg += f"The stock status could not be updated at the moment due to a temporary issue. It will be updated automatically, usually within a few minutes. Please check again shortly.\n(Retry-{retry_attempt})"
		else:
			error_msg += "The stock status could not be updated due to a temporary issue. Please try again after some time. If the issue persists, please contact the technical team."
		return {
			"stock_msg": stock_msg,
			"error_msg": error_msg,
		}
	elif ticket_resp.status_code in range(200, 300) and content:
		ticket_json = ticket_resp.json()
		grouped_items = {}
		custom_fields = ticket_json.get("custom_fields")
		is_product_replacement_ticket = (
			custom_fields.get("cf_pending_on") == "Replacement"
			and custom_fields.get("cf_sub_code") == "Replacement Requested"
		)
		if is_product_replacement_ticket:
			grouped_items[custom_fields.get("cf_erp_model")] = 1
		else:
			item_code_fields = [
				{"item_field": "cf_model_2", "qty_field": "cf_spare_description_2238169"},
				{"item_field": "cf_model129305", "qty_field": "cf_spare_name"},
				{"item_field": "cf_model89249", "qty_field": "cf_spare_name563282"},
				{"item_field": "cf_spare_name_4", "qty_field": "cf_spare_quantity_4"},
				{"item_field": "cf_spare_name_5", "qty_field": "cf_spare_quantity_5"},
			]
			for field in item_code_fields:
				item_code = custom_fields.get(field["item_field"])
				qty = frappe.utils.flt(custom_fields.get(field["qty_field"])) or 1
				grouped_items.setdefault(item_code, 0)
				grouped_items[item_code] += qty

		stock_msg = get_stock_status_from_live(
			ticket=ticket_json["id"],
			grouped_items=grouped_items,
			warehouse=freshdesk.get("warehouse"),
		)
	return {
		"stock_msg": stock_msg,
		"error_msg": error_msg,
	}


def get_stock_status_from_live(ticket, grouped_items, warehouse):
	"""Call live site to run the actual stock-availability check for the given items."""
	base_url, headers = live_site_connection()
	url = f"{base_url}/api/method/{LIVE_MODULE}.get_stock_status_for_items"
	resp = requests.post(
		url,
		headers=headers,
		json={"ticket": ticket, "grouped_items": grouped_items, "warehouse": warehouse},
		timeout=60,
	)
	resp.raise_for_status()
	return resp.json().get("message") or ""
