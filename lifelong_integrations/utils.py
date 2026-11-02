import frappe


def hide_error_traceback():
	"""before_request: stack traces in error responses only for a System Manager signed in on the desk.

	Runs before API keys and Bearer tokens are checked, so those requests count as Guest here: callers of
	the APIs (Flipkart and other integrations) never get a traceback, whatever System Settings > Allow
	Error Traceback says. The full traceback is still saved in the Error Log."""
	if "System Manager" not in frappe.get_roles():
		frappe.local.flags.disable_traceback = True
