"""Endpoints Flipkart calls (egress notifications and ASN callbacks).

Contract (Flipkart "Onboarding for Egress Document Notifications"):
- POST, application/json, Authorization: Bearer <token from auth.token>
- 2xx within 30 s, body {"delivery_status": "SUCCESS", "uuid": "..."}
- errors: 4xx (client) / 5xx (server, Flipkart retries) with
  {"error_response": {"error_code": "...", "error_message": "..."}}
- never 2xx unless the document is stored.
"""

import hashlib
import json
import time

import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils import add_to_date, getdate, now_datetime

from lifelong_integrations.lifelong_integrations.api.flipkart_api.auth import get_auth_error_response
from lifelong_integrations.lifelong_integrations.api.flipkart_api.utils import (
	INTERNAL_ERROR,
	VALIDATION_FAILED,
	create_api_log,
	error_response,
	find_value,
	get_settings,
	new_request_id,
	safe_request_headers,
	success_response,
)

PO_NOTIFICATION_TYPES = ("PO_CREATE", "PO_EDIT")
# A notification larger than this is refused (413) and its body is not stored
MAX_BODY_BYTES = 5 * 1024 * 1024
# per source IP, for each webhook
WEBHOOK_RATE_LIMIT = 1200
WEBHOOK_RATE_WINDOW = 60


class NotificationError(Exception):
	def __init__(self, status, error_code, message):
		super().__init__(message)
		self.status = status
		self.error_code = error_code
		self.message = message


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=WEBHOOK_RATE_LIMIT, seconds=WEBHOOK_RATE_WINDOW)
def po_notification():
	"""Webhook endpoint registered with Flipkart for PO_CREATE and PO_EDIT."""
	return _handle("Flipkart PO Notification", _process_po_notification)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=WEBHOOK_RATE_LIMIT, seconds=WEBHOOK_RATE_WINDOW)
def consignment_schedule_callback():
	"""Callback endpoint for the Consignment Schedule response (ASN step 2)."""
	return _handle("Flipkart Consignment Schedule Callback", _process_schedule_callback)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=WEBHOOK_RATE_LIMIT, seconds=WEBHOOK_RATE_WINDOW)
def document_ack_callback():
	"""Callback endpoint for the ASN / document acknowledgement (ASN step 4)."""
	return _handle("Flipkart Document Ack Callback", _process_document_callback)


def _handle(api, processor):
	frappe.local.flags.disable_traceback = True
	started = time.monotonic()
	delivery_uuid = new_request_id()
	notification_type = _notification_type_header()
	raw_body = frappe.request.get_data(as_text=True) if frappe.request else ""
	reference = None

	def log(status, status_code, response, traceback=None, store_body=True):
		create_api_log(
			api=api,
			direction="Inbound",
			status=status,
			status_code=status_code,
			endpoint=frappe.request.path if frappe.request else None,
			# a request that is not authenticated (or too large) can't make the log grow by its body
			payload=raw_body if store_body else f"(body not stored: {len(raw_body.encode())} bytes)",
			response=response,
			reference=reference,
			request_id=frappe.get_request_header("X-Request-Id") or delivery_uuid,
			notification_type=notification_type,
			request_headers=safe_request_headers(),
			duration_ms=int((time.monotonic() - started) * 1000),
			traceback=traceback,
		)

	auth_error = get_auth_error_response()
	if auth_error is not None:
		log("Failed", auth_error.status_code, auth_error.get_data(as_text=True), store_body=False)
		return auth_error

	if len(raw_body.encode()) > MAX_BODY_BYTES:
		response = error_response(413, VALIDATION_FAILED, f"Request body is larger than {MAX_BODY_BYTES} bytes")
		log("Failed", 413, response.get_data(as_text=True), store_body=False)
		return response

	try:
		try:
			body = json.loads(raw_body or "null")
		except ValueError:
			raise NotificationError(400, VALIDATION_FAILED, "Request body is not valid JSON")
		if not isinstance(body, dict):
			raise NotificationError(400, VALIDATION_FAILED, "Request body must be a JSON object")

		reference = processor(body, notification_type, delivery_uuid)
		response = success_response(delivery_uuid)
		log("Success", 200, response.get_data(as_text=True))
		frappe.db.commit()
		return response

	except NotificationError as e:
		frappe.db.rollback()
		response = error_response(e.status, e.error_code, e.message)
		log("Failed", e.status, response.get_data(as_text=True))
		return response

	except Exception:
		frappe.db.rollback()
		response = error_response(500, INTERNAL_ERROR, "The document could not be stored, please retry")
		log("Failed", 500, response.get_data(as_text=True), traceback=frappe.get_traceback())
		return response

	finally:
		frappe.local.message_log = []


def _notification_type_header():
	value = (
		frappe.get_request_header("NOTIFICATION-TYPE")
		or frappe.get_request_header("X-Notification-Type")
		or ""
	)
	return value.strip().upper()


# ---------------------------------------------------------------------------
# PO_CREATE / PO_EDIT
# ---------------------------------------------------------------------------


def _process_po_notification(body, notification_type, delivery_uuid):
	if notification_type and notification_type not in PO_NOTIFICATION_TYPES:
		raise NotificationError(
			400, VALIDATION_FAILED, f"Unsupported notification type '{notification_type}'"
		)

	purchase_orders = body.get("purchaseOrders")
	if not isinstance(purchase_orders, list) or not purchase_orders:
		raise NotificationError(400, VALIDATION_FAILED, "Missing required field 'purchaseOrders'.")

	# Validate the whole notification first: it is stored all-or-nothing.
	for index, po in enumerate(purchase_orders):
		_validate_po(po, index)

	settings = get_settings()
	created = []
	for po in purchase_orders:
		po_number = po["purchaseOrderNumber"].strip()
		# Without the header, a PO already on file is treated as an edit.
		event_type = notification_type or (
			"PO_EDIT" if frappe.db.exists("Flipkart PO Data", {"po_number": po_number}) else "PO_CREATE"
		)
		payload_hash = _payload_hash(po)
		dedupe_key = f"{event_type}:{po_number}:{payload_hash}"
		if frappe.db.exists("Flipkart PO Data", {"dedupe_key": dedupe_key}):
			continue  # Flipkart re-delivered the same document

		doc = frappe.new_doc("Flipkart PO Data")
		doc.update(
			{
				"po_number": po_number,
				"event_type": event_type,
				"status": "Initiated",
				"order_date": _date_or_none(po.get("orderDate")),
				"expiry_date": _date_or_none(po.get("expiryDate")),
				"ship_from_id": _get(po, "seller", "shipFrom", "id"),
				"ship_to_id": _get(po, "buyer", "shipTo", "id"),
				"ship_to_name": _get(po, "buyer", "shipTo", "name"),
				"line_count": len(po.get("itemDetails") or []),
				"total_qty": sum(
					float(_get(item, "quantity", "orderedQuantity", "amount") or 0)
					for item in po.get("itemDetails") or []
				),
				"grand_total": float(_get(po, "orderTotals", "grandTotalAmount") or 0),
				"delivery_uuid": delivery_uuid,
				"payload_hash": payload_hash,
				"dedupe_key": dedupe_key,
				"purchase_order": json.dumps(po, indent=4),
			}
		)
		if event_type == "PO_CREATE":
			doc.ack_status = "Pending"
			doc.ack_due_by = _ack_due_by(settings, doc.ship_to_id)
		else:
			doc.ack_status = "Not Required"  # Flipkart: no PO_ACK for edits
		doc.flags.ignore_permissions = True
		try:
			doc.insert(ignore_permissions=True)
		except frappe.UniqueValidationError:
			continue  # a concurrent delivery of the same document won the race
		created.append(doc.name)

	frappe.db.commit()

	if created and settings.auto_push_to_erp:
		frappe.enqueue(
			"lifelong_integrations.lifelong_integrations.api.flipkart_api.po._push_pending_pos",
			queue="short",
			job_id="flipkart_push_pending_pos",
			deduplicate=True,
		)

	return ", ".join(po["purchaseOrderNumber"] for po in purchase_orders)[:140]


def _validate_po(po, index):
	if not isinstance(po, dict):
		raise NotificationError(400, VALIDATION_FAILED, f"purchaseOrders[{index}] must be an object.")

	required = {
		"purchaseOrderNumber": po.get("purchaseOrderNumber"),
		"orderDate": po.get("orderDate"),
		"seller.shipFrom.id": _get(po, "seller", "shipFrom", "id"),
		"buyer.shipTo.id": _get(po, "buyer", "shipTo", "id"),
	}
	for field, value in required.items():
		if value in (None, ""):
			raise NotificationError(
				400, VALIDATION_FAILED, f"Missing required field 'purchaseOrders[{index}].{field}'."
			)

	items = po.get("itemDetails")
	if not isinstance(items, list) or not items:
		raise NotificationError(
			400, VALIDATION_FAILED, f"Missing required field 'purchaseOrders[{index}].itemDetails'."
		)
	for line, item in enumerate(items):
		if not _get(item, "productIdentifier", "buyerProductIdentifier", "articleCode"):
			raise NotificationError(
				400,
				VALIDATION_FAILED,
				f"Missing required field 'purchaseOrders[{index}].itemDetails[{line}]"
				".productIdentifier.buyerProductIdentifier.articleCode'.",
			)
		if _get(item, "quantity", "orderedQuantity", "amount") in (None, ""):
			raise NotificationError(
				400,
				VALIDATION_FAILED,
				f"Missing required field 'purchaseOrders[{index}].itemDetails[{line}]"
				".quantity.orderedQuantity.amount'.",
			)

	try:
		getdate(po["orderDate"])
	except Exception:
		raise NotificationError(
			400, VALIDATION_FAILED, f"'purchaseOrders[{index}].orderDate' must be YYYY-MM-DD."
		)


def _ack_due_by(settings, ship_to_id):
	hyperlocal_ids = {
		line.strip() for line in (settings.hyperlocal_ship_to_ids or "").splitlines() if line.strip()
	}
	if ship_to_id and ship_to_id in hyperlocal_ids:
		hours = settings.hyperlocal_ack_window_hours or 24
	else:
		hours = settings.ack_window_hours or 168
	return add_to_date(now_datetime(), hours=hours)


def _payload_hash(payload):
	normalised = json.dumps(payload, sort_keys=True, separators=(",", ":"))
	return hashlib.sha256(normalised.encode()).hexdigest()


def _date_or_none(value):
	try:
		return getdate(value) if value else None
	except Exception:
		return None


def _get(data, *path):
	for key in path:
		if not isinstance(data, dict):
			return None
		data = data.get(key)
	return data


# ---------------------------------------------------------------------------
# ASN callbacks
# ---------------------------------------------------------------------------

# Flipkart has not published the callback payloads yet, so the fields are
# looked up by every name the ASN contract uses for them.
REQUEST_ID_KEYS = ("requestId", "request_id", "xRequestId", "clientRequestId")
CONSIGNMENT_ID_KEYS = ("forwardConsignmentId", "forward_consignment_id", "consignmentId", "consignment_id")
STATUS_KEYS = ("status", "validationStatus", "documentStatus", "result", "state")
MESSAGE_KEYS = ("message", "description", "errorMessage", "error_message", "reason", "remarks")


def _process_schedule_callback(body, notification_type, delivery_uuid):
	consignment = _find_consignment(body)
	forward_id = find_value(body, CONSIGNMENT_ID_KEYS)
	status = str(find_value(body, STATUS_KEYS) or "").upper()
	failed = any(word in status for word in ("FAIL", "REJECT", "ERROR", "INVALID"))

	consignment.schedule_callback = json.dumps(body, indent=4)
	if forward_id:
		consignment.forward_consignment_id = forward_id
	if failed or not forward_id:
		consignment.status = "Schedule Failed"
		consignment.message = str(
			find_value(body, MESSAGE_KEYS) or status or "No forwardConsignmentId in callback"
		)
	else:
		consignment.status = "Scheduled"
		consignment.message = f"Scheduled: {forward_id}"
	consignment.erp_synced = 0
	consignment.save(ignore_permissions=True)
	_enqueue_erp_sync(consignment.name)
	return consignment.shipment


def _process_document_callback(body, notification_type, delivery_uuid):
	consignment = _find_consignment(body)
	status = str(find_value(body, STATUS_KEYS) or "").upper()
	failed = any(word in status for word in ("FAIL", "REJECT", "ERROR", "INVALID"))

	consignment.document_callback = json.dumps(body, indent=4)
	consignment.status = "Rejected" if failed else "Accepted"
	consignment.message = str(find_value(body, MESSAGE_KEYS) or status or consignment.status)
	consignment.erp_synced = 0
	consignment.save(ignore_permissions=True)
	_enqueue_erp_sync(consignment.name)
	return consignment.shipment


def _find_consignment(body):
	request_id = find_value(body, REQUEST_ID_KEYS) or frappe.get_request_header("X-Request-Id")
	forward_id = find_value(body, CONSIGNMENT_ID_KEYS)

	name = None
	if request_id:
		name = frappe.db.get_value(
			"Flipkart Consignment",
			{"schedule_request_id": request_id},
			"name",
		) or frappe.db.get_value("Flipkart Consignment", {"dispatch_request_id": request_id}, "name")
	if not name and forward_id:
		name = frappe.db.get_value("Flipkart Consignment", {"forward_consignment_id": forward_id}, "name")
	if not name:
		# Unknown consignment: a 4xx stops Flipkart from retrying something we can never match.
		raise NotificationError(
			400, VALIDATION_FAILED, "No consignment found for the given requestId / forwardConsignmentId."
		)
	return frappe.get_doc("Flipkart Consignment", name, for_update=True)


def _enqueue_erp_sync(consignment_name):
	frappe.enqueue(
		"lifelong_integrations.lifelong_integrations.api.flipkart_api.asn.push_consignment_status",
		queue="short",
		consignment_name=consignment_name,
		enqueue_after_commit=True,
	)
