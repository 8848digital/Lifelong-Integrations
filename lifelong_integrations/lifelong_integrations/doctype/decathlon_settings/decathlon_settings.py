# Copyright (c) 2026, 8848 Digital LLP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, getdate, today


class DecathlonSettings(Document):
	def validate(self):
		validate_order_period(self)


def validate_order_period(settings):
	"""Allow exactly one way of choosing which orders to fetch: either
	No. of Days to get orders, or Start Date and End Date."""
	has_days = cint(settings.no_of_days_to_get_orders) > 0
	has_dates = bool(settings.start_date or settings.end_date)

	if has_days and has_dates:
		frappe.throw(
			_(
				"Fill either No. of Days to get orders, or Start Date and End Date, not both. "
				"Clear No. of Days to get orders to use Start Date and End Date, or clear "
				"Start Date and End Date to use No. of Days to get orders."
			),
			title=_("Orders to Fetch"),
		)

	if not has_days and not has_dates:
		frappe.throw(
			_(
				"Fill either No. of Days to get orders, or Start Date and End Date, "
				"to choose which Decathlon orders to fetch."
			),
			title=_("Orders to Fetch"),
		)

	if has_dates:
		if not (settings.start_date and settings.end_date):
			frappe.throw(
				_(
					"Fill both Start Date and End Date, or clear them and use No. of Days to get orders."
				),
				title=_("Orders to Fetch"),
			)

		if getdate(settings.start_date) > getdate(settings.end_date):
			frappe.throw(_("Start Date cannot be after End Date."), title=_("Orders to Fetch"))


def get_order_period(settings):
	"""Return (start_date, end_date) for fetching Decathlon orders.

	With No. of Days to get orders = N, the period runs from N days before
	today until today. Otherwise the Start Date and End Date from Decathlon
	Settings are used.
	"""
	validate_order_period(settings)

	days = cint(settings.no_of_days_to_get_orders)
	if days > 0:
		return getdate(add_days(today(), -days)), getdate(today())

	return getdate(settings.start_date), getdate(settings.end_date)
