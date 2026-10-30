# Copyright (c) 2026, 8848 Digital LLP and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.query_builder import Interval
from frappe.query_builder.functions import Now


class FlipkartAPILog(Document):
	@staticmethod
	def clear_old_logs(days=90):
		"""Log Settings: Flipkart API Logs older than `days` are deleted (hooks default_log_clearing_doctypes)."""
		table = frappe.qb.DocType("Flipkart API Log")
		frappe.db.delete(table, filters=(table.modified < (Now() - Interval(days=days))))
