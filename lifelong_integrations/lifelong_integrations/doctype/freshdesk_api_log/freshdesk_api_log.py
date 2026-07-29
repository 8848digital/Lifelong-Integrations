# Copyright (c) 2026, 8848 Digital LLP and contributors
# For license information, please see license.txt


import json

import frappe
import requests
from frappe.model.document import Document
from frappe.query_builder import Interval
from frappe.query_builder.functions import Now


class FreshDeskAPILog(Document):
	@staticmethod
	def clear_old_logs(days=180):
		table = frappe.qb.DocType("FreshDesk API Log")
		frappe.db.delete(table, filters=(table.modified < (Now() - Interval(days=days))))


def freshdesk_log(
	response=None,
	doc=None,
	request_data=None,
	status_code=None,
	api=None,
	message=None,
	endpoint=None,
	ticket_id=None,
):
	# Note: If this function is called inside a Except statement,
	# then run frappe.db.rollback()[**If Needed**] before calling this function.
	# This function will execute frappe.db.commit()
	if response is None:
		response = {}
	if type(response) == requests.models.Response:
		if not status_code:
			status_code = response.status_code
		try:
			response = response.json()
		except requests.exceptions.JSONDecodeError:
			response = {}
	if isinstance(response, dict) and response.get("require_login"):
		status_code = 401
	exception = frappe.get_traceback()
	new_log = frappe.new_doc("FreshDesk API Log")
	new_log.status = (
		"Success"
		if status_code in range(200, 300)
		and (
			(isinstance(response, dict) and not response.get("exc_type"))
			or isinstance(response, list)
		)
		else "Failure"
	)
	new_log.message = json.dumps(message or response, indent=4)
	new_log.doc_type = doc.doctype if doc else None
	new_log.doc_name = doc.name if doc else None
	new_log.traceback = str(exception)
	new_log.request_data = json.dumps(request_data or {}, indent=4)
	new_log.endpoint = endpoint
	new_log.api = api
	new_log.status_code = status_code
	new_log.ticket_id = ticket_id
	new_log.flags.ignore_links = True
	new_log.flags.ignore_permissions = True
	new_log.insert(ignore_permissions=True, ignore_links=True)
	frappe.db.commit()
	return new_log.name
