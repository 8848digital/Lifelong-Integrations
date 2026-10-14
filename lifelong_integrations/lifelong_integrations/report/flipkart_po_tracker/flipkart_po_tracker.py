# Copyright (c) 2026, 8848 Digital LLP and contributors
# For license information, please see license.txt

"""Flipkart POs received, ERP sync and PO_ACK status.

Covers what Flipkart asks for during UAT and the pilot: PO count, PO IDs,
warehouse (ship-to), VSID (ship-from) and total FSN quantity per period,
plus POs at risk of going dormant (no ACK before the due time).
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{
			"label": _("PO Data"),
			"fieldname": "name",
			"fieldtype": "Link",
			"options": "Flipkart PO Data",
			"width": 150,
		},
		{"label": _("PO Number"), "fieldname": "po_number", "fieldtype": "Data", "width": 140},
		{"label": _("Event"), "fieldname": "event_type", "fieldtype": "Data", "width": 90},
		{"label": _("Received On"), "fieldname": "creation", "fieldtype": "Datetime", "width": 150},
		{"label": _("Order Date"), "fieldname": "order_date", "fieldtype": "Date", "width": 100},
		{"label": _("VSID (Ship From)"), "fieldname": "ship_from_id", "fieldtype": "Data", "width": 120},
		{"label": _("Flipkart Warehouse"), "fieldname": "ship_to_id", "fieldtype": "Data", "width": 120},
		{"label": _("Warehouse Name"), "fieldname": "ship_to_name", "fieldtype": "Data", "width": 150},
		{"label": _("Lines"), "fieldname": "line_count", "fieldtype": "Int", "width": 60},
		{"label": _("FSN Qty"), "fieldname": "total_qty", "fieldtype": "Float", "width": 90},
		{"label": _("Grand Total"), "fieldname": "grand_total", "fieldtype": "Float", "width": 110},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
		{"label": _("Quotation"), "fieldname": "sync_doc", "fieldtype": "Data", "width": 130},
		{"label": _("ACK Status"), "fieldname": "ack_status", "fieldtype": "Data", "width": 95},
		{"label": _("ACK Due By"), "fieldname": "ack_due_by", "fieldtype": "Datetime", "width": 150},
		{"label": _("ACK Overdue"), "fieldname": "ack_overdue", "fieldtype": "Check", "width": 90},
	]


def get_data(filters):
	conditions = {
		"creation": [
			"between",
			[
				getdate(filters.from_date or add_days(nowdate(), -7)),
				add_days(getdate(filters.to_date or nowdate()), 1),
			],
		]
	}
	for field in ("event_type", "status", "ship_from_id", "ship_to_id", "ack_status"):
		if filters.get(field):
			conditions[field] = filters.get(field)

	rows = frappe.get_all(
		"Flipkart PO Data",
		filters=conditions,
		fields=[
			"name",
			"po_number",
			"event_type",
			"creation",
			"order_date",
			"ship_from_id",
			"ship_to_id",
			"ship_to_name",
			"line_count",
			"total_qty",
			"grand_total",
			"status",
			"sync_doc",
			"ack_status",
			"ack_due_by",
		],
		order_by="creation asc",
	)

	now = now_datetime()
	data = []
	for row in rows:
		row.ack_overdue = int(
			row.ack_status in ("Pending", "Failed") and bool(row.ack_due_by) and row.ack_due_by < now
		)
		if filters.get("only_ack_overdue") and not row.ack_overdue:
			continue
		data.append(row)
	return data
