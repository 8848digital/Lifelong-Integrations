# Copyright (c) 2026, 8848 Digital LLP and contributors
# For license information, please see license.txt

import frappe
import requests
from frappe import _
from frappe.model.document import Document
from frappe.utils.password import get_decrypted_password

from lifelong_integrations.lifelong_integrations.api.live_site_api import \
    live_site_connection


class FreshDeskSettings(Document):
	def validate(self):
		self.validate_host()
		self.set_schedulers()

	def validate_host(self):
		if self.host:
			self.host = self.host.strip()
			if self.host[-1] == "/":
				self.host = self.host[0:-1]

	def set_schedulers(self):
		scheduler_fields = {
			"get_tickets_scheduler_interval": "lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.utility_functions.schedulers.get_tickets_scheduler",
			"create_contact_scheduler_interval": "lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.utility_functions.schedulers.create_contact_scheduler",
			"update_ticket_scheduler_interval": "lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.utility_functions.schedulers.update_ticket_scheduler",
			"get_custom_object_scheduler_interval": "lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.utility_functions.schedulers.get_custom_object_scheduler",
			"update_spare_item_choice_scheduler_interval": "lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.utility_functions.schedulers.update_spare_item_choice_scheduler",
			"update_category_list_choice_scheduler_interval": "lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.utility_functions.schedulers.update_category_list_choice_scheduler",
		}
		for field in scheduler_fields:
			if self.get(field):
				cron = generate_cron(self.get(field))
				if cron:
					scheduler = frappe.db.get_value(
						"Scheduled Job Type",
						{"method": scheduler_fields[field]},
						["name", "cron_format"],
						as_dict=1,
					)
					if scheduler and scheduler.name and scheduler.cron_format != cron:
						frappe.db.set_value("Scheduled Job Type", scheduler, "cron_format", cron)
			else:
				# - Reset cron format from Hooks
				scheduler_events = frappe.get_hooks("scheduler_events")["cron"]
				found = False
				for c in scheduler_events:
					for method in scheduler_events[c]:
						if method == scheduler_fields[field]:
							scheduler = frappe.db.get_value(
								"Scheduled Job Type",
								{"method": scheduler_fields[field]},
								["name", "cron_format"],
								as_dict=1,
							)
							if scheduler and scheduler.name and scheduler.cron_format != c:
								frappe.db.set_value("Scheduled Job Type", scheduler, "cron_format", c)
							break
					if found:
						break


def generate_cron(interval_minutes):
	"""
	Generate a cron expression based on an interval in minutes.

	Args:
	        interval_minutes (int): Interval in minutes.

	Returns:
	        str: Cron expression.
	"""
	cron_expression = None
	if interval_minutes > 1440:
		frappe.throw(_("Interval Time Should be Less than 1440 mins(24hrs)"))
	if interval_minutes == 1440:
		# Run every day
		cron_expression = "0 0 * * *"
	elif interval_minutes < 60:
		# Run every `interval_minutes` minutes
		cron_expression = f"*/{interval_minutes} * * * *"
	elif interval_minutes % 60 == 0:
		# Run every `N` hours
		hours = interval_minutes // 60
		cron_expression = f"0 */{hours} * * *"
	else:
		# Combination of minutes and hours
		hours = interval_minutes // 60
		minutes = interval_minutes % 60
		cron_expression = f"{minutes} */{hours} * * *"

	return cron_expression


@frappe.whitelist()
def get_freshdesk_credentials():
	"""Gateway site's own FreshDesk Settings - host, api_key, scheduler config."""
	doc = frappe.get_single("FreshDesk Settings")
	doc.api_key = get_decrypted_password(
		"FreshDesk Settings", "FreshDesk Settings", "api_key", raise_exception=False
	)
	return doc


def get_live_site_freshdesk_settings():
	"""Fetch FreshDesk Settings doc from the live site (business-mapping fields + child tables)."""
	base_url, headers = live_site_connection()
	url = f"{base_url}/api/method/frappe.client.get"
	params = {"doctype": "FreshDesk Integration", "name": "FreshDesk Integration"}

	response = requests.get(url, headers=headers, params=params, timeout=30)
	response.raise_for_status()
	live_settings = response.json().get("message") or {}

	return live_settings


def get_merged_freshdesk_settings():
	"""Merge gateway-site scheduler/API settings with live-site business settings."""
	gateway_settings = get_freshdesk_credentials()
	live_settings = get_live_site_freshdesk_settings()

	merged = frappe._dict(gateway_settings.as_dict())
	merged.update(live_settings)

	return merged
