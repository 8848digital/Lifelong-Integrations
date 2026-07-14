import frappe

from lifelong_integrations.lifelong_integrations.doctype.lifelong_zepto_settings.zepto_intergration.create_zepto_quotation import \
    __create_zepto_quotations
from lifelong_integrations.lifelong_integrations.doctype.lifelong_zepto_settings.zepto_intergration.get_zepto_po_events import \
    __get_zepto_po_events
from lifelong_integrations.lifelong_integrations.doctype.lifelong_zepto_settings.zepto_intergration.process_pending_asn_shipments import \
    __process_pending_asn_shipments


@frappe.whitelist()
def get_zepto_po_events():
	return __get_zepto_po_events()


@frappe.whitelist()
def create_zepto_quotations():
	return __create_zepto_quotations()


def process_pending_asn_shipments():
	return __process_pending_asn_shipments()
