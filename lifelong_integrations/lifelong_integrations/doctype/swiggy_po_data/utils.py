import json

import frappe
from frappe import _


def create_swiggy_po_data():
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

	po_code = frappe.form_dict.purchase_order.get("purchase_order", {}).get("id")

	po_data = frappe.new_doc("Swiggy PO Data")
	po_data.update(
		{
			"po_code": po_code,
			"event_type": "New PO",
			"purchase_order": json.dumps(frappe.form_dict.purchase_order, indent=4),
		}
	)
	po_data.insert(ignore_mandatory=True, ignore_permissions=True)
	frappe.response.update(
		{
			"status": "Success",
			"status_message": "Purchase Order created Successfully",
			"status_code": 200,
			"http_status_code": 200,
		}
	)
	frappe.db.commit()