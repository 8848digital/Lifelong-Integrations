# Copyright (c) 2024, Shankar and contributors
# For license information, please see license.txt


from frappe import whitelist

from lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.utility_functions.schedulers import (
    create_contact_scheduler, get_tickets_scheduler,
    update_category_list_choice_scheduler, update_spare_item_choice_scheduler,
    update_ticket_scheduler)


@whitelist()
def get_tickets():
	return get_tickets_scheduler()


@whitelist()
def update_tickets():
	return update_ticket_scheduler()


@whitelist()
def create_contacts():
	return create_contact_scheduler()


@whitelist()
def update_spare_list_in_ticket_field():
	return update_spare_item_choice_scheduler()


@whitelist()
def update_category_list_in_freshdesk():
	return update_category_list_choice_scheduler()
