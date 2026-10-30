import frappe


def execute():
	"""Flipkart Integration role (gateway Flipkart methods) and the Flipkart API Log retention."""
	if not frappe.db.exists("Role", "Flipkart Integration"):
		frappe.get_doc({"doctype": "Role", "role_name": "Flipkart Integration", "desk_access": 1}).insert(
			ignore_permissions=True
		)
	if frappe.db.exists("DocType", "Log Settings"):
		log_settings = frappe.get_doc("Log Settings")
		if not any(row.ref_doctype == "Flipkart API Log" for row in log_settings.logs_to_clear):
			log_settings.register_doctype("Flipkart API Log", 90)
			log_settings.save(ignore_permissions=True)
