import frappe

from lifelong_integrations.lifelong_integrations.doctype.swiggy_api_log.utils import  create_swiggy_api_log
from lifelong_integrations.lifelong_integrations.doctype.swiggy_po_data.utils import  create_swiggy_po_data


@frappe.whitelist()
def store_po_data():
	frappe.local.flags.disable_traceback = True
	try:
		create_swiggy_po_data()
		create_swiggy_api_log(
			api="Create Swiggy PO Data",
		)
	except Exception:
		frappe.db.rollback()
		response = {
			"status": "Failed",
			"status_message": "Purchase Order creation Failed",
			"status_code": 500,
			"http_status_code": 500,
		}
		for key, val in response.items():
			if key not in frappe.response:
				frappe.response[key] = val
		create_swiggy_api_log(
			api="Create Swiggy PO Data",
		)
		frappe.local.message_log = []  # Avoind sending server message logs in response
	if frappe.local.flags.swiggy_log_id:
		frappe.response.log_id = frappe.local.flags.swiggy_log_id
