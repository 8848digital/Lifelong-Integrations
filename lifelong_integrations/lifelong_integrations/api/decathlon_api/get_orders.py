# Copyright (c) 2026 8848 Digital LLP. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use
# of this file, via any medium, is strictly prohibited without prior
# written permission from 8848 Digital LLP.

"""Decathlon -> UniCommerce order sync: Get Orders button, 6-hourly scheduler and API."""

import json

import frappe
import requests
from frappe import _
from frappe.utils import cint

from lifelong_integrations.lifelong_integrations.api.decathlon_api.order_payload import (
    get_channel, get_field_mapping, get_mapping_channel)
from lifelong_integrations.lifelong_integrations.api.decathlon_api.unicommerce_client import (
    LOG_CREATE_SALE_ORDER, LOG_GET_ORDERS, REQUEST_TIMEOUT,
    create_decathlon_log, get_unicommerce_connection, parse_json,
    push_order_to_unicommerce)
from lifelong_integrations.lifelong_integrations.doctype.decathlon_settings.decathlon_settings import \
    get_order_period

DECATHLON_SETTINGS = "Decathlon Settings"
DECATHLON_DATE_FORMAT = "%Y-%m-%d"


@frappe.whitelist()
def get_orders():
	"""
	Get orders from Decathlon for the period in Decathlon Settings and send
	them to UniCommerce. Orders are always fetched and logged; they are sent
	to UniCommerce only when a Channel is set on the Decathlon Field Mapping,
	otherwise the push is skipped and a log says why.

	**Endpoint:** `/api/method/lifelong_integrations.lifelong_integrations.api.decathlon_api.get_orders.get_orders`
	**HTTP Method:** GET or POST
	**Parameters:** None (reads Decathlon Settings).
	**Response:**
	```json
	{
	        "success": true,
	        "orders": [...],
	        "order_ids": ["IN123-A"],
	        "push_skipped": false,
	        "summary": "Fetched 1 order(s) from Decathlon ...",
	        "unicommerce": {"success": true, "total_orders": 1, "counts": {...}, "results": [...]}
	}
	```
	"unicommerce" is present only when orders were pushed.
	"""
	settings = frappe.get_doc(DECATHLON_SETTINGS)
	start, end = get_order_period(settings)

	data, period = __fetch_decathlon_orders(settings, start, end)
	orders = data.get("orders") or []
	order_ids = [order.get("order_id") for order in orders if order.get("order_id")]

	result = {
		"success": True,
		"orders": orders,
		"order_ids": order_ids,
		"push_skipped": False,
	}

	if not orders:
		result["summary"] = _("No orders found in Decathlon for {0}.").format(period)
		return result

	if not get_channel():
		message = (
			f"Fetched {len(orders)} order(s) from Decathlon for {period}, but did not send "
			f"them to UniCommerce because Channel is not set in the Decathlon Field Mapping. "
			f"Set the Channel and click Get Orders again to send them."
		)
		create_decathlon_log(
			title=f"{len(orders)} order(s) not sent to UniCommerce: Channel not set",
			log_type=LOG_CREATE_SALE_ORDER,
			status="Skipped",
			payload={"order_ids": order_ids},
			message=message,
			error_message="Channel is not set in Field Mapping for integration Decathlon.",
		)
		result["push_skipped"] = True
		result["summary"] = message
		return result

	unicommerce_result = create_unicommerce_order(data)
	result["unicommerce"] = unicommerce_result

	counts = unicommerce_result["counts"]
	result["summary"] = _(
		"Fetched {0} order(s) from Decathlon for {1}.<br>"
		"Created in UniCommerce: {2}<br>"
		"Already in UniCommerce: {3}<br>"
		"Failed: {4}<br><br>"
		"See Decathlon Logs for details."
	).format(
		len(orders),
		period,
		counts["Success"],
		counts["Skipped"],
		counts["Failed"],
	)

	return result


def get_orders_scheduler():
	"""
	Scheduled every 6 hours (see hooks.py). Runs the same steps as the Get
	Orders button, but only when Get Orders Automatically is ticked in
	Decathlon Settings. Errors are logged instead of raised.

	Returns:
	        None
	"""
	if not cint(frappe.db.get_single_value(DECATHLON_SETTINGS, "enable_auto_sync")):
		return

	try:
		get_orders()
	except Exception as exc:
		frappe.db.rollback()
		create_decathlon_log(
			title="Scheduled Get Orders failed",
			log_type=LOG_GET_ORDERS,
			status="Failed",
			message=(
				"The scheduled run (every 6 hours) stopped before finishing. "
				"Earlier logs from this run show any orders already processed."
			),
			error_message=str(exc),
			traceback=frappe.get_traceback(),
		)


@frappe.whitelist()
def create_unicommerce_order(data):
	"""
	Create Decathlon orders in UniCommerce, one sale order per Decathlon
	order, with one log per order holding the payload sent, UniCommerce's
	response and any error. A 401 logs in again once; the new token is
	reused for the remaining orders.

	**Endpoint:** `/api/method/lifelong_integrations.lifelong_integrations.api.decathlon_api.get_orders.create_unicommerce_order`
	**HTTP Method:** GET or POST
	**Parameters:**
	        - data (dict | str, required): Decathlon orders response, as a dict
	          or JSON string, e.g. {"orders": [...]}.
	**Response:**
	```json
	{
	        "success": true,
	        "total_orders": 2,
	        "counts": {"Success": 1, "Skipped": 0, "Failed": 1},
	        "results": [{"order_id": "IN123-A", "status": "Success", "http_status": 200, "error": null}]
	}
	```
	"""
	if isinstance(data, str):
		try:
			data = json.loads(data)
		except json.JSONDecodeError:
			frappe.throw(_("Invalid JSON data provided."))

	if not isinstance(data, dict):
		frappe.throw(_("Order data must be a dictionary or JSON object."))

	mapping = get_field_mapping()
	channel = get_mapping_channel()
	connection = get_unicommerce_connection()

	results = []
	counts = {"Success": 0, "Skipped": 0, "Failed": 0}

	for order in data.get("orders", []):
		order_id = order.get("order_id")
		order_result = push_order_to_unicommerce(
			order, order_id, mapping, channel, connection
		)
		counts[order_result["status"]] += 1
		results.append(order_result)

	return {
		"success": True,
		"total_orders": len(results),
		"counts": counts,
		"results": results,
	}


def __fetch_decathlon_orders(settings, start, end):
	"""
	Get orders from Decathlon for the given period and log the result.
	Stops with an error (after logging it) if the call fails.

	Parameters:
	        settings (Document, required): Decathlon Settings (url, token).
	        start (date, required): First day of the period.
	        end (date, required): Last day of the period.

	Returns:
	        tuple[dict, str]: Decathlon's response ({"orders": [...], ...}) and
	        the period as text, e.g. "2026-10-12 to 2026-10-15".
	"""
	url = f"https://{settings.url}/api/orders"
	params = {
		"only_null_channel": "false",
		"start_date": start.strftime(DECATHLON_DATE_FORMAT),
		"end_date": end.strftime(DECATHLON_DATE_FORMAT),
		"customer_debited": "true",
		"payment_workflow": "PAY_ON_ACCEPTANCE",
	}
	period = f"{params['start_date']} to {params['end_date']}"

	try:
		response = requests.get(
			url,
			params=params,
			headers={"Authorization": settings.token},
			timeout=REQUEST_TIMEOUT,
		)
	except requests.exceptions.RequestException as exc:
		create_decathlon_log(
			title="Get orders from Decathlon failed: could not connect",
			log_type=LOG_GET_ORDERS,
			status="Failed",
			request_url=url,
			payload=params,
			message=f"Could not connect to Decathlon to get orders for {period}.",
			error_message=str(exc),
			traceback=frappe.get_traceback(),
		)
		frappe.throw(_("Could not connect to Decathlon. See Decathlon Logs."))

	data = parse_json(response)

	if not response.ok or not isinstance(data, dict):
		create_decathlon_log(
			title="Get orders from Decathlon failed",
			log_type=LOG_GET_ORDERS,
			status="Failed",
			http_status=response.status_code,
			request_url=url,
			payload=params,
			response=response.text,
			message=f"Decathlon did not return orders for {period}.",
			error_message=(
				f"HTTP {response.status_code}"
				if not response.ok
				else "Decathlon returned a response that is not valid JSON."
			),
		)
		frappe.throw(
			_("Decathlon returned an error (HTTP {0}). See Decathlon Logs.").format(
				response.status_code
			)
		)

	orders = data.get("orders") or []
	create_decathlon_log(
		title=f"Got {len(orders)} order(s) from Decathlon",
		log_type=LOG_GET_ORDERS,
		status="Success",
		http_status=response.status_code,
		request_url=url,
		payload=params,
		response=data,
		message=f"Fetched {len(orders)} order(s) from Decathlon for {period}.",
	)

	return data, period
