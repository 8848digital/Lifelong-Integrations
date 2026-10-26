# Copyright (c) 2026, 8848 Digital LLP and contributors
# For license information, please see license.txt

import ipaddress
import secrets

import frappe
from frappe.model.document import Document

from lifelong_integrations.lifelong_integrations.api.flipkart_api.auth import MAX_TOKEN_TTL


class FlipkartSettings(Document):
	def validate(self):
		if self.token_ttl_seconds and not 60 <= self.token_ttl_seconds <= MAX_TOKEN_TTL:
			frappe.throw(f"Token Lifetime must be between 60 and {MAX_TOKEN_TTL} seconds (Flipkart limit)")
		for line in (self.inbound_ip_allowlist or "").splitlines():
			if line.strip():
				try:
					ipaddress.ip_network(line.strip(), strict=False)
				except ValueError:
					frappe.throw(f"Invalid IP address / CIDR in allowlist: {line.strip()}")


@frappe.whitelist()
def generate_inbound_credentials():
	"""New client id/secret to share with Flipkart. Rotating the secret invalidates issued tokens."""
	frappe.only_for("System Manager")
	settings = frappe.get_doc("Flipkart Settings")
	settings.inbound_client_id = f"flipkart-{secrets.token_hex(8)}"
	settings.inbound_client_secret = secrets.token_urlsafe(40)
	settings.save()
	return {"client_id": settings.inbound_client_id}


@frappe.whitelist()
def test_outbound_token():
	frappe.only_for("System Manager")
	from lifelong_integrations.lifelong_integrations.api.flipkart_api.utils import get_access_token

	token = get_access_token(force_refresh=True)
	return {"ok": bool(token)}
