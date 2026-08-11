import frappe
from frappe.model.document import Document
from frappe.query_builder import Interval
from frappe.query_builder.functions import Now


class DTDCErrorLog(Document):
	@staticmethod
	def clear_old_logs(days=180):
		table = frappe.qb.DocType("DTDC Error Log")
		frappe.db.delete(table, filters=(table.modified < (Now() - Interval(days=days))))
