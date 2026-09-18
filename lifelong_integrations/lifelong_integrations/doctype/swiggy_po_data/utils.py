import hashlib
import json

import frappe
from frappe import _


def _payload_hash(payload_dict):
	"""Return a stable MD5 hex digest of a JSON payload dict for comparison."""
	normalised = json.dumps(payload_dict, sort_keys=True, separators=(",", ":"))
	return hashlib.md5(normalised.encode()).hexdigest()


def create_swiggy_po_data():
	"""
	Receive a Swiggy purchase_order payload and persist it as a Swiggy PO Data record.

	Deduplication rules applied when an existing record already exists for the
	same PO Code:

	- **Identical payload** (same hash as the latest existing record) → skip
	  silently; return Success so Swiggy does not retry.
	- **Changed payload** (any field updated by Swiggy) → create a new record
	  with status ``Updated PO`` and event_type ``Updated PO`` so the ops team
	  can review and re-process if needed.
	- **No prior record** → create normally with status ``Initiated``.
	"""
	if "purchase_order" not in frappe.form_dict:
		frappe.response.update(
			{
				"status": "Failed",
				"status_message": "Missing required key: purchase_order",
				"status_code": 400,
				"http_status_code": 400,
			}
		)
		frappe.throw(_("Missing required key: purchase_order"))
		return

	if isinstance(frappe.form_dict.purchase_order, str):
		try:
			frappe.form_dict.purchase_order = json.loads(frappe.form_dict.purchase_order)
		except Exception as e:
			frappe.response.update(
				{
					"status": "Failed",
					"status_message": "purchase_order should be a Valid JSON",
					"status_code": 400,
					"http_status_code": 400,
				}
			)
			raise e

	po_code = frappe.form_dict.purchase_order.get("id")
	vendor_code = frappe.form_dict.purchase_order.get("selling_party", {}).get("id")
	incoming_payload_str = json.dumps(frappe.form_dict.purchase_order, indent=4)
	incoming_hash = _payload_hash(frappe.form_dict.purchase_order)

	# Check for an existing record with the same PO Code (pick the latest one).
	existing_name = frappe.db.get_value(
		"Swiggy PO Data",
		{"po_code": po_code},
		"name",
		order_by="creation desc",
	)

	if existing_name:
		existing_payload_raw = frappe.db.get_value(
			"Swiggy PO Data", existing_name, "purchase_order"
		)
		try:
			existing_payload = (
				json.loads(existing_payload_raw)
				if isinstance(existing_payload_raw, str)
				else existing_payload_raw
			)
			existing_hash = _payload_hash(existing_payload)
		except Exception:
			existing_hash = None

		if existing_hash == incoming_hash:
			# Exact duplicate — acknowledge without creating a new record.
			frappe.response.update(
				{
					"status": "Success",
					"status_message": "Duplicate PO received — no new record created",
					"status_code": 200,
					"http_status_code": 200,
				}
			)
			return

		# Payload has changed — create a new record marked as Updated PO.
		status = "Updated PO"
		event_type = "Updated PO"
	else:
		# First time we see this PO Code.
		status = "Initiated"
		event_type = "New PO"

	po_data = frappe.new_doc("Swiggy PO Data")
	po_data.update(
		{
			"po_code": po_code,
			"vendor_code": vendor_code,
			"status": status,
			"event_type": event_type,
			"purchase_order": incoming_payload_str,
		}
	)
	po_data.insert(ignore_mandatory=True, ignore_permissions=True)
	frappe.response.update(
		{
			"status": "Success",
			"status_message": f"Purchase Order {event_type} Successfully",
			"status_code": 200,
			"http_status_code": 200,
		}
	)
	frappe.db.commit()
