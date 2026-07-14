import frappe

from lifelong_integrations.lifelong_integrations.api.zepto_settings import \
    _get_zepto_config
from lifelong_integrations.lifelong_integrations.doctype.lifelong_zepto_settings.zepto_intergration.process_pending_asn_shipments import \
    process_shipment_invoices


@frappe.whitelist()
def get_zepto_config():
	return _get_zepto_config()


@frappe.whitelist()
def trigger_process_shipment_invoices(shipment):
	process_shipment_invoices(shipment)
	return {"status": "ok"}
