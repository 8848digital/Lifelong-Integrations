import json

import frappe
import requests

from lifelong_integrations.lifelong_integrations.api.live_site_api import \
    live_site_connection
from lifelong_integrations.lifelong_integrations.doctype.freshdesk_api_log.freshdesk_api_log import \
    freshdesk_log
from lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.freshdesk_settings import \
    get_merged_freshdesk_settings

LIVE_MODULE = "freshdesk_integration.freshdesk_integration.doctype.freshdesk_integration.utility_functions.update_ticket"


def get_tickets_to_update_from_live():
	"""Fetch the pending ticket transaction-update payload from live site."""
	base_url, headers = live_site_connection()
	url = f"{base_url}/api/method/{LIVE_MODULE}.get_tickets_to_update_api"
	resp = requests.get(url, headers=headers, timeout=60)
	resp.raise_for_status()
	return resp.json().get("message") or {}


def update_custom_object_to_quotation_on_live(quotation, data):
	"""Push the Freshdesk custom-object response back to live site's Quotation Related Transactions."""
	base_url, headers = live_site_connection()
	url = f"{base_url}/api/method/{LIVE_MODULE}.update_custom_object_to_quotation_api"
	resp = requests.post(
		url, headers=headers, json={"quotation": quotation, "data": data}, timeout=60
	)
	resp.raise_for_status()


def update_transaction_details_in_ticket(freshdesk, ticket, ticket_details=None):
	"""Push quotation/sales order/shipment tracking details into the corresponding custom fields on a Freshdesk ticket."""
	if not ticket_details:
		return
	fieldmap = {
		"cf_quotation_id_1934677": "quotation_id",
		"cf_sales_order_1934677": "sales_order_id",
		"cf_so_date_1934677": "transaction_date",
		"cf_tracking_id_spare_1934677": "tracking_id",
		"cf_tracking_status_1934677": "tracking_status",
		"cf_delivery_date_1934677": "delivery_date",
		"cf_dispatch_date_and_time_1934677": "pickup_at",
	}
	data = {
		"helpdesk_ticket": {
			"custom_field": {
				key: ticket_details.get(value) or ""
				for key, value in fieldmap.items()
				if value in ticket_details
			}
		}
	}
	endpoint = f"""{freshdesk.get("host")}/helpdesk/tickets/{ticket}.json"""
	headers = {"Content-Type": "application/json"}
	res = requests.put(
		endpoint, auth=(freshdesk.get("api_key"), "X"), headers=headers, data=json.dumps(data)
	)
	freshdesk_log(
		response=res,
		endpoint=endpoint,
		api="Update TICKET Details in Ticket",
		request_data=data,
		doc=frappe._dict(
			{"doctype": "Quotation", "name": ticket_details.get("quotation_id")}
		),
	)


def update_tickets():
	"""Push pending Quotation/Sales Order/Delivery Note/Shipment updates as custom objects to Freshdesk and update the linked tickets' custom fields."""
	freshdesk = get_merged_freshdesk_settings()
	headers = {"Content-Type": "application/json"}
	if not freshdesk.get("enable") or not freshdesk.get("update_ticket_status"):
		return
	endpoint = ""
	try:
		tickets_to_update = get_tickets_to_update_from_live()
		voucher_wise_fields_to_update = {
			"Quotation": ["quotation_id"],
			"Sales Order": ["sales_order_id", "transaction_date"],
			"Delivery Note": [],
			"Shipment": ["tracking_id", "tracking_status", "pickup_at", "delivery_date"],
		}
		for ticket in tickets_to_update:
			ticket_fields_to_update = {}
			for voucher in ["Quotation", "Sales Order", "Delivery Note", "Shipment"]:
				if not tickets_to_update[ticket].get(voucher):
					continue
				if voucher in voucher_wise_fields_to_update:
					for field in voucher_wise_fields_to_update[voucher]:
						ticket_fields_to_update.setdefault(field, None)
				for key, value in tickets_to_update[ticket][voucher].items():
					if voucher == "Quotation":
						ticket_fields_to_update["quotation_id"] = value.get("transaction_id")
					elif voucher == "Sales Order":
						ticket_fields_to_update["sales_order_id"] = value.get("transaction_id")
						ticket_fields_to_update["transaction_date"] = value.get("transaction_date")
					elif voucher == "Shipment":
						ticket_fields_to_update["tracking_id"] = value.get("tracking_id")
						ticket_fields_to_update["tracking_status"] = value.get("tracking_status")
						ticket_fields_to_update["delivery_date"] = value.get("delivery_date")
						ticket_fields_to_update["pickup_at"] = value.get("pickup_at")
					endpoint = freshdesk.get("host")
					try:
						if value.get("transaction_details_1"):
							value["transaction_details_1"] = int(value["transaction_details_1"])
						if value.get("quantity"):
							value["quantity"] = int(value["quantity"])
						if value.get("doc_status"):
							value["doc_status"] = int(value["doc_status"])

						quotation = value["quotation"]
						del value["quotation"]
						if value["method"] == "Create":
							del value["method"]
							endpoint += """/api/v2/custom_objects/schemas/3962686/records/"""
							data = {"data": value}
							res = requests.post(
								endpoint,
								auth=(freshdesk.get("api_key"), "X"),
								headers=headers,
								data=json.dumps(data),
							)
						elif value["method"] == "Update":
							endpoint += (
								f"""/api/v2/custom_objects/schemas/3962686/records/{value["display_id"]}"""
							)
							data = {"display_id": value["display_id"], "version": value["version"] or 1}
							del value["display_id"]
							del value["version"]
							del value["method"]
							data["data"] = value
							res = requests.put(
								endpoint,
								auth=(freshdesk.get("api_key"), "X"),
								headers=headers,
								data=json.dumps(data),
							)
						if res.content:
							res_json = res.json()
							if res_json.get("error_type") or res_json.get("error"):
								if (
									res_json.get("errors")
									and res_json["error_type"] == "CONSTRAINT_VIOLATION"
									and res_json["errors"][0]["name"] == "version"
								):
									version_req = requests.get(
										endpoint, auth=(freshdesk.get("api_key"), "X"), headers=headers
									)
									if version_req.content:
										version_json = version_req.json()
										if version_json.get("version"):
											data["version"] = version_json["version"]
											# - Version error will raise only in existing records, so make a put request to update
											res = requests.put(
												endpoint,
												auth=(freshdesk.get("api_key"), "X"),
												headers=headers,
												data=json.dumps(data),
											)
											if res.content:
												res_json = res.json()
												if not res_json.get("error_type") and not res_json.get("error"):
													update_custom_object_to_quotation_on_live(quotation, res_json)
							else:
								update_custom_object_to_quotation_on_live(quotation, res_json)

						freshdesk_log(
							response=res,
							endpoint=endpoint,
							api="Update TICKET Details",
							request_data=data,
							doc=frappe._dict(
								{"doctype": value.get("voucher_type"), "name": value.get("transaction_id")}
							),
						)
					except Exception:
						freshdesk_log(
							endpoint=endpoint,
							api="Update TICKET Details",
							doc=frappe._dict(
								{"doctype": value.get("voucher_type"), "name": value.get("transaction_id")}
							),
							request_data=value,
						)
			update_transaction_details_in_ticket(
				freshdesk, ticket, ticket_details=ticket_fields_to_update
			)
	except Exception:
		freshdesk_log(endpoint=endpoint, api="Update TICKET Details")
