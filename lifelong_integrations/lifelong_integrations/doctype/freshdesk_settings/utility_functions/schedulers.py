import frappe

from lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.freshdesk_settings import \
    get_merged_freshdesk_settings
from lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.utility_functions import \
    create_contact
from lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.utility_functions.get_ticket import \
    get_tickets
from lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.utility_functions.update_category import \
    update_category_list_in_freshdesk
from lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.utility_functions.update_spare import \
    update_spare_list_in_ticket_field
from lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.utility_functions.update_ticket import \
    update_tickets


def get_tickets_scheduler():
	"""Scheduled job entry point to fetch new/updated Freshdesk tickets, unless the scheduler is disabled."""
	freshdesk = get_merged_freshdesk_settings()
	if freshdesk.disable_scheduler:
		return
	get_tickets(freshdesk, from_scheduler=True)


def create_contact_scheduler():
	"""Scheduled job entry point to sync B2C Customer Data records to Freshdesk contacts, unless the scheduler is disabled."""
	freshdesk = get_merged_freshdesk_settings()
	if freshdesk.disable_scheduler:
		return
	create_contact()


def update_ticket_scheduler():
	"""Scheduled job entry point to push ERP transaction updates back to Freshdesk tickets, unless the scheduler is disabled."""
	freshdesk = get_merged_freshdesk_settings()
	if freshdesk.disable_scheduler:
		return
	update_tickets()


def update_spare_item_choice_scheduler():
	"""Scheduled job entry point to sync the ERP spare/item list into Freshdesk ticket field choices, unless the scheduler is disabled."""
	freshdesk = get_merged_freshdesk_settings()
	if freshdesk.disable_scheduler:
		return
	update_spare_list_in_ticket_field()


def update_category_list_choice_scheduler():
	"""Scheduled job entry point to sync the ERP category/sub-category/model list into Freshdesk, unless the scheduler is disabled."""
	freshdesk = get_merged_freshdesk_settings()
	if freshdesk.disable_scheduler:
		return
	update_category_list_in_freshdesk()
