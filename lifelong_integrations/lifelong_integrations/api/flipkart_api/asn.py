"""Flipkart ASN + Invoice on the gateway.

The ERP site builds the payloads and calls these methods (API key auth); the
gateway owns the Flipkart credentials, sends the request and keeps one
Flipkart Consignment per ERP Shipment. Flipkart's callbacks (webhook.py)
update that record, and the result is pushed back to the ERP Shipment.

Flow (ASN API contract):
1. schedule_consignment -> POST /v1/forward_consignment/schedule (or /schedule/update)
2. Flipkart callback with forwardConsignmentId
3. dispatch_consignment -> POST /v1/forward_consignment/dispatch/{nonboxlabel|boxlabel}
4. Flipkart document-acknowledgement callback
Invoices: submit_invoice -> POST /v1/forward_consignment/invoice
"""

import json

import frappe

from lifelong_integrations.lifelong_integrations.api.flipkart_api.utils import (
	call_erp,
	call_flipkart,
	create_api_log,
	new_request_id,
)

SCHEDULE_PATH = "/v1/forward_consignment/schedule"
SCHEDULE_UPDATE_PATH = "/v1/forward_consignment/schedule/update"
DISPATCH_PATHS = {
	"Non Box Label": "/v1/forward_consignment/dispatch/nonboxlabel",
	"Box Label": "/v1/forward_consignment/dispatch/boxlabel",
}
INVOICE_PATH = "/v1/forward_consignment/invoice"
ERP_UPDATE_CONSIGNMENT = "lifelong_automation.lifelong_automation.flipkart.asn.update_consignment_status"

CONSIGNMENT_FIELDS = [
	"name",
	"shipment",
	"status",
	"forward_consignment_id",
	"scheduled_dispatch_date",
	"ship_from_id",
	"ship_to_id",
	"dispatch_mode",
	"message",
]


@frappe.whitelist()
def schedule_consignment(shipment, payload):
	"""Schedule a new consignment, or move the date of an already scheduled one."""
	payload = frappe.parse_json(payload)
	consignment = _get_or_new_consignment(shipment)
	is_update = bool(consignment.forward_consignment_id)

	if is_update:
		payload["forwardConsignmentId"] = consignment.forward_consignment_id
		path = SCHEDULE_UPDATE_PATH
		extra_headers = {"X-Forward-Consignment-Id": consignment.forward_consignment_id}
	else:
		payload.pop("forwardConsignmentId", None)
		path = SCHEDULE_PATH
		extra_headers = None

	request_id = new_request_id()
	result = call_flipkart(
		api="Flipkart Consignment Schedule Update" if is_update else "Flipkart Consignment Schedule",
		path=path,
		payload=payload,
		reference=shipment,
		request_id=request_id,
		extra_headers=extra_headers,
	)

	consignment.update(
		{
			"scheduled_dispatch_date": payload.get("scheduledDispatchDate"),
			"ship_from_id": payload.get("shipFromId"),
			"ship_to_id": payload.get("shipToId"),
			"schedule_payload": json.dumps(payload, indent=4),
		}
	)
	if result.ok:
		consignment.schedule_request_id = request_id
		# An update keeps the consignment Scheduled; a new one waits for the callback.
		consignment.status = "Scheduled" if is_update else "Schedule Requested"
		consignment.message = f"Accepted by Flipkart (messageId {result.message_id or '-'})"
	else:
		if not is_update:
			consignment.status = "Schedule Failed"
		consignment.message = result.error
	consignment.save(ignore_permissions=True)
	frappe.db.commit()
	return _result(result, consignment)


@frappe.whitelist()
def dispatch_consignment(shipment, payload, dispatch_mode="Non Box Label"):
	payload = frappe.parse_json(payload)
	if dispatch_mode not in DISPATCH_PATHS:
		frappe.throw(f"Unknown dispatch mode {dispatch_mode}")

	consignment = _get_consignment(shipment)
	if not consignment.forward_consignment_id:
		frappe.throw(
			f"Shipment {shipment} has no Flipkart forwardConsignmentId yet. "
			"Wait for the schedule confirmation from Flipkart."
		)
	payload["forwardConsignmentId"] = consignment.forward_consignment_id

	request_id = new_request_id()
	result = call_flipkart(
		api=f"Flipkart ASN Dispatch ({dispatch_mode})",
		path=DISPATCH_PATHS[dispatch_mode],
		payload=payload,
		reference=shipment,
		request_id=request_id,
		extra_headers={"X-Forward-Consignment-Id": consignment.forward_consignment_id},
	)

	consignment.dispatch_mode = dispatch_mode
	consignment.dispatch_payload = json.dumps(payload, indent=4)
	if result.ok:
		consignment.dispatch_request_id = request_id
		consignment.status = "Dispatch Requested"
		consignment.message = f"Accepted by Flipkart (messageId {result.message_id or '-'})"
	else:
		consignment.status = "Dispatch Failed"
		consignment.message = result.error
	consignment.save(ignore_permissions=True)
	frappe.db.commit()
	return _result(result, consignment)


@frappe.whitelist()
def submit_invoice(shipment, sales_invoice, payload):
	payload = frappe.parse_json(payload)
	consignment = _get_consignment(shipment)
	if not consignment.forward_consignment_id:
		frappe.throw(f"Shipment {shipment} has no Flipkart forwardConsignmentId yet")
	payload["consignmentId"] = consignment.forward_consignment_id

	result = call_flipkart(
		api="Flipkart Invoice",
		path=INVOICE_PATH,
		payload=payload,
		reference=sales_invoice,
		extra_headers={"x-client-ref-id": payload.get("invoiceNumber") or sales_invoice},
	)
	return {
		"ok": result.ok,
		"status_code": result.status_code,
		"request_id": result.request_id,
		"message_id": result.message_id,
		"error": result.error,
	}


@frappe.whitelist()
def get_consignment(shipment):
	name = frappe.db.get_value("Flipkart Consignment", {"shipment": shipment}, "name")
	if not name:
		return None
	return frappe.db.get_value("Flipkart Consignment", name, CONSIGNMENT_FIELDS, as_dict=True)


def push_consignment_status(consignment_name):
	"""Background job after a Flipkart callback: copy the result to the ERP Shipment."""
	values = frappe.db.get_value("Flipkart Consignment", consignment_name, CONSIGNMENT_FIELDS, as_dict=True)
	if not values:
		return
	try:
		status_code, _message, resp = call_erp(ERP_UPDATE_CONSIGNMENT, {"consignment": values}, timeout=60)
		if status_code != 200:
			raise Exception(f"ERP returned HTTP {status_code}: {resp.text[:500]}")
		frappe.db.set_value("Flipkart Consignment", consignment_name, "erp_synced", 1)
		frappe.db.commit()
	except Exception as e:
		frappe.db.rollback()
		create_api_log(
			api="Push Consignment Status to ERP",
			direction="Outbound",
			status="Failed",
			reference=values.shipment,
			payload=values,
			response={"error": str(e)},
			traceback=frappe.get_traceback(),
		)


def scheduled_push_consignment_status():
	"""Scheduler: retry callback results the ERP did not receive."""
	names = frappe.get_all(
		"Flipkart Consignment",
		filters={"erp_synced": 0, "status": ["in", ["Scheduled", "Schedule Failed", "Accepted", "Rejected"]]},
		pluck="name",
	)
	for name in names:
		push_consignment_status(name)


def _get_or_new_consignment(shipment):
	name = frappe.db.get_value("Flipkart Consignment", {"shipment": shipment}, "name")
	if name:
		return frappe.get_doc("Flipkart Consignment", name)
	doc = frappe.new_doc("Flipkart Consignment")
	doc.shipment = shipment
	doc.status = "Schedule Requested"
	doc.flags.ignore_permissions = True
	return doc


def _get_consignment(shipment):
	name = frappe.db.get_value("Flipkart Consignment", {"shipment": shipment}, "name")
	if not name:
		frappe.throw(f"Shipment {shipment} has not been scheduled with Flipkart yet")
	return frappe.get_doc("Flipkart Consignment", name)


def _result(result, consignment):
	return {
		"ok": result.ok,
		"status_code": result.status_code,
		"request_id": result.request_id,
		"message_id": result.message_id,
		"error": result.error,
		"consignment": {field: consignment.get(field) for field in CONSIGNMENT_FIELDS},
	}
