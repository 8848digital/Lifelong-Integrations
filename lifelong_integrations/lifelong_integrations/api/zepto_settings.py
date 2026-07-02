import frappe


def _get_zepto_config():
	config = frappe.get_single("Zepto Settings")
	return {
		"api_base_url": config.api_base_url,
		"client_id": config.client_id,
		"client_secret": config.get_password("client_secret"),
	}
