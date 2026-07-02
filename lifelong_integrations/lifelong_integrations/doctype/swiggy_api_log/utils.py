import json

import frappe
import requests


def create_swiggy_api_log(
	response=None,
	request_data=None,
	status_code=None,
	api=None,
	endpoint=None,
):
	# Note: If this function is called inside a Except statement,
	# then run frappe.db.rollback()[**If Needed**] before calling this function.
	# This function will execute frappe.db.commit()
	if response is None:
		response = frappe.response or {}
	if not endpoint and frappe.form_dict and frappe.form_dict.cmd:
		endpoint = frappe.form_dict.cmd
	if not request_data and frappe.form_dict:
		request_data = frappe.form_dict
	if type(response) == requests.models.Response:
		if not status_code:
			status_code = response.status_code
		try:
			response = response.json()
		except requests.exceptions.JSONDecodeError:
			response = {}
	if isinstance(response, dict) and response.get("status_code"):
		status_code = response.get("status_code")
	traceback = frappe.get_traceback(with_context=True)
	new_log = frappe.new_doc("Swiggy API Log")
	new_log.status = "Success" if status_code in range(200, 300) else "Failed"
	new_log.api = api
	new_log.status_code = status_code
	new_log.endpoint = endpoint
	new_log.payload = json.dumps(request_data or {}, indent=4)
	new_log.response = json.dumps(response, indent=4)
	new_log.traceback = str(traceback)
	new_log.flags.ignore_links = True
	new_log.flags.ignore_permissions = True
	new_log.insert(ignore_permissions=True, ignore_links=True)
	frappe.db.commit()
	frappe.local.flags.swiggy_log_id = new_log.name
	return new_log.name
