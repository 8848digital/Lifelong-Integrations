import json

import frappe
import requests


def generate_swiggy_quotations():
	"""Scheduler entry point — pushes each PO to Live Site one at a time."""
	settings = frappe.get_cached_doc("Lifelong Settings")

	live_site_base = settings.target_site_url.rstrip("/")
	endpoint = f"{live_site_base}/api/method/swiggy_integration.api.quotation.create_quotation_from_swiggy_po"

	headers = {
		"Authorization": f"token {settings.target_site_user_api_key}:{settings.get_password('target_site_user_api_secret')}",
		"Content-Type": "application/json",
	}

	success_count = 0
	failure_count = 0

	po_list = frappe.get_all("Swiggy PO Data", filters={"status": "Initiated"})

	for po in po_list:
		swiggy_po_doc = frappe.get_doc("Swiggy PO Data", po.name)

		try:
			try:
				data = json.loads(swiggy_po_doc.purchase_order)
			except Exception:
				raise Exception("Invalid JSON in purchase_order")

			response = requests.post(
				endpoint, headers=headers, json={"po_data": data}, timeout=30
			)

			try:
				result = response.json().get("message", {})
			except Exception:
				result = {}

			if response.status_code == 200 and result.get("status") == "success":
				swiggy_po_doc.update(
					{
						"status": "Created",
						"sync_via": "Quotation",
						"sync_doc": result.get("quotation_name"),
						"error_message": None,
					}
				)
				success_count += 1

			else:
				raise Exception(
					result.get("error")
					or f"Live Site returned {response.status_code}: {response.text}"
				)

		except Exception as e:
			failure_count += 1
			frappe.log_error(
				frappe.get_traceback(), f"Swiggy Quotation Failed | PO: {swiggy_po_doc.name}"
			)
			swiggy_po_doc.error_message = str(e)

		finally:
			swiggy_po_doc.save(ignore_permissions=True)

	return {"success": success_count, "failed": failure_count}


@frappe.whitelist()
def get_pending_swiggy_pos():
	"""
	ENTRY POINT for Live Site's button. Returns all Initiated POs
	(name + raw po_data) so Live Site can process them locally.
	"""
	po_list = frappe.get_all(
		"Swiggy PO Data",
		filters={"status": "Initiated"},
		fields=["name", "purchase_order", "po_code"],
	)
	return po_list


@frappe.whitelist()
def update_po_status(po_name, status, sync_via=None, sync_doc=None, error_message=None):
	"""Called remotely by Live Site to update PO status after processing."""
	if not frappe.db.exists("Swiggy PO Data", po_name):
		frappe.throw(f"Swiggy PO Data {po_name} not found")

	doc = frappe.get_doc("Swiggy PO Data", po_name)
	doc.status = status
	if sync_via:
		doc.sync_via = sync_via
	if sync_doc:
		doc.sync_doc = sync_doc
	doc.error_message = error_message
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	return {"status": "updated"}


@frappe.whitelist()
def log_remote_error(title, message):
	"""Called remotely by Live Site to centralize error logs."""
	frappe.log_error(title=title, message=message)
	return {"status": "logged"}


@frappe.whitelist()
def reset_swiggy_po_by_quotation(quotation_name):
	"""
	Called remotely by Live Site when a Quotation is cancelled/deleted.
	Resets the matching Swiggy PO Data (matched via sync_doc) back to
	Initiated so it gets picked up again by the scheduler/button.
	"""
	po_name = frappe.db.get_value("Swiggy PO Data", {"sync_doc": quotation_name}, "name")

	if not po_name:
		frappe.log_error(
			f"No Swiggy PO Data found with sync_doc: {quotation_name}", "Swiggy PO Reset Failed"
		)
		return {"status": "not_found"}

	doc = frappe.get_doc("Swiggy PO Data", po_name)
	doc.status = "Initiated"
	doc.sync_via = None
	doc.sync_doc = None
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	return {"status": "reset", "po_name": po_name}
