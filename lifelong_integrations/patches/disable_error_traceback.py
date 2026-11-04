import frappe


def execute():
	"""VAPT GW-02: no stack traces in error responses on the gateway site. Errors that happen before any
	hook runs (e.g. a malformed JSON body) are only covered by this setting; the traceback is still saved
	in the Error Log."""
	frappe.db.set_single_value("System Settings", "allow_error_traceback", 0)
