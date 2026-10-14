"""Flipkart POs on the gateway: push to the ERP site, status updates, PO_ACK."""

import json

import frappe
from frappe.utils import now_datetime

from lifelong_integrations.lifelong_integrations.api.flipkart_api.utils import (
	call_erp,
	call_flipkart,
	create_api_log,
	get_settings,
)

ERP_PROCESS_PO = "lifelong_automation.lifelong_automation.flipkart.po.process_flipkart_po"
PO_ACK_PATH = "/v1/vendor/po/ack"

# ERP result -> Flipkart PO Data status
ERP_RESULT_STATUS = {
	"created": "Created",
	"duplicate": "Created",
	"edit_applied": "Edit Applied",
	"edit_review": "Edit Review",
}


def scheduled_push_pending_pos():
	"""Scheduler (every 5 min): retry anything the on-receipt push did not finish."""
	settings = get_settings()
	if settings.enabled and settings.auto_push_to_erp:
		push_pending_pos()


@frappe.whitelist()
def push_pending_pos(po_data_name=None):
	"""Send Initiated POs to the ERP site (oldest first, so a PO_CREATE goes before its edits)."""
	filters = {"status": "Initiated"}
	if po_data_name:
		filters["name"] = po_data_name
	names = frappe.get_all("Flipkart PO Data", filters=filters, pluck="name", order_by="creation asc")

	summary = {"success": 0, "failed": 0}
	for name in names:
		if push_po_to_erp(name):
			summary["success"] += 1
		else:
			summary["failed"] += 1
	return summary


def push_po_to_erp(po_data_name):
	doc = frappe.get_doc("Flipkart PO Data", po_data_name)
	payload = {
		"po_data": json.loads(doc.purchase_order),
		"po_data_name": doc.name,
		"event_type": doc.event_type,
	}
	try:
		status_code, result, resp = call_erp(ERP_PROCESS_PO, payload)
		result = result or {}
		status = ERP_RESULT_STATUS.get(result.get("status"))
		if status_code != 200 or not status:
			raise Exception(result.get("error") or f"ERP returned HTTP {status_code}: {resp.text[:1000]}")

		doc.status = status
		doc.sync_via = "Quotation"
		doc.sync_doc = result.get("quotation_name")
		doc.sync_message = result.get("message") or ""
		doc.save(ignore_permissions=True)
		create_api_log(
			api=f"Push PO to ERP | {doc.event_type}",
			direction="Outbound",
			status="Success",
			status_code=status_code,
			reference=doc.po_number,
			payload={"po_data_name": doc.name},
			response=result,
		)
		return True

	except Exception as e:
		frappe.db.rollback()
		doc.reload()
		doc.status = "Failed"
		doc.sync_message = str(e)[:1000]
		doc.save(ignore_permissions=True)
		create_api_log(
			api=f"Push PO to ERP | {doc.event_type}",
			direction="Outbound",
			status="Failed",
			reference=doc.po_number,
			payload={"po_data_name": doc.name},
			response={"error": str(e)},
			traceback=frappe.get_traceback(),
		)
		return False


@frappe.whitelist()
def retry_po(po_data_name):
	doc = frappe.get_doc("Flipkart PO Data", po_data_name)
	if doc.status != "Failed":
		frappe.throw("Only Failed POs can be retried")
	doc.status = "Initiated"
	doc.sync_message = ""
	doc.save()
	frappe.db.commit()
	return push_pending_pos(po_data_name=po_data_name)


# ---------------------------------------------------------------------------
# Called by the ERP site (API key auth)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_pending_flipkart_pos():
	"""For the ERP 'Fetch Flipkart POs' button: Initiated POs, oldest first."""
	return frappe.get_all(
		"Flipkart PO Data",
		filters={"status": "Initiated"},
		fields=["name", "po_number", "event_type", "purchase_order"],
		order_by="creation asc",
	)


@frappe.whitelist()
def update_po_status(po_data_name, status, sync_doc=None, message=None):
	if not frappe.db.exists("Flipkart PO Data", po_data_name):
		return {"status": "not_found"}
	doc = frappe.get_doc("Flipkart PO Data", po_data_name)
	doc.status = status
	if sync_doc:
		doc.sync_via = "Quotation"
		doc.sync_doc = sync_doc
	if message is not None:
		doc.sync_message = message
	doc.save(ignore_permissions=True)
	return {"status": "updated"}


@frappe.whitelist()
def reset_flipkart_po_by_quotation(quotation_name, po_number=None):
	"""ERP Quotation cancelled/deleted: re-queue the latest version of that PO.

	The latest record may be a PO_EDIT; the ERP then builds the new Quotation
	from the edited payload.
	"""
	filters = {"po_number": po_number} if po_number else {"sync_doc": quotation_name}
	name = frappe.db.get_value("Flipkart PO Data", filters, "name", order_by="creation desc")
	if not name:
		log_remote_error(
			"Flipkart PO Reset", f"No Flipkart PO Data for Quotation {quotation_name} / PO {po_number}"
		)
		return {"status": "not_found"}

	doc = frappe.get_doc("Flipkart PO Data", name)
	doc.status = "Initiated"
	doc.sync_via = None
	doc.sync_doc = None
	doc.sync_message = f"Re-queued: Quotation {quotation_name} was cancelled or deleted"
	doc.save(ignore_permissions=True)
	return {"status": "reset", "po_data_name": name}


@frappe.whitelist()
def log_remote_error(title, message, status="Failed", reference=None):
	create_api_log(api=title, direction="Inbound", status=status, reference=reference, traceback=message)
	return {"status": "logged"}


@frappe.whitelist()
def send_po_ack(po_number):
	"""Send PO_ACK (status 'accepted') for a PO_CREATE. Sent once per PO; repeats are no-ops."""
	create_name = frappe.db.get_value(
		"Flipkart PO Data",
		{"po_number": po_number, "event_type": "PO_CREATE"},
		"name",
		order_by="creation asc",
	)
	if not create_name:
		frappe.throw(f"No PO_CREATE received for Flipkart PO {po_number}")

	doc = frappe.get_doc("Flipkart PO Data", create_name)
	if doc.ack_status == "Sent":
		return {"status": "already_sent", "ack_sent_on": str(doc.ack_sent_on)}

	result = call_flipkart(
		api="Flipkart PO ACK",
		path=PO_ACK_PATH,
		payload={"purchaseOrderNumber": po_number, "status": "accepted"},
		reference=po_number,
		extra_headers={
			"x-client-ref-id": po_number,
			"X_DOCUMENT_TYPE": "PO",
			"X_EVENT_SOURCE": "EDI",
			"X_EVENT_NAME": "accepted",
		},
	)

	if result.ok:
		doc.ack_status = "Sent"
		doc.ack_sent_on = now_datetime()
		doc.ack_correlation_id = (result.body or {}).get("correlationId") or result.message_id
		doc.ack_error = ""
	else:
		doc.ack_status = "Failed"
		doc.ack_error = (result.error or "")[:1000]
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	return {
		"status": "sent" if result.ok else "failed",
		"status_code": result.status_code,
		"error": result.error,
		"ack_sent_on": str(doc.ack_sent_on or ""),
		"correlation_id": doc.ack_correlation_id,
	}
