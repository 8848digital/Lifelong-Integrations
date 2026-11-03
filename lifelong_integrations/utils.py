import ipaddress
from urllib.parse import urlparse

import frappe
from frappe import _

FLIPKART_API_PREFIX = "/api/method/lifelong_integrations.lifelong_integrations.api.flipkart_api."
# security headers on every response (VAPT FG-04); the Flipkart API answers only JSON, so it gets the strictest
COMMON_HEADERS = {
	"X-Content-Type-Options": "nosniff",
	"X-Frame-Options": "SAMEORIGIN",
	"Referrer-Policy": "strict-origin-when-cross-origin",
	"Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
	"Cross-Origin-Opener-Policy": "same-origin",
	"Cross-Origin-Resource-Policy": "same-site",
}
# Desk runs inline scripts, so its policy limits framing, plugins and <base> only
DESK_CSP = "frame-ancestors 'self'; object-src 'none'; base-uri 'self'"
API_CSP = "default-src 'none'; frame-ancestors 'none'"
HSTS = "max-age=31536000; includeSubDomains"


def hide_error_traceback():
	"""before_request: stack traces in error responses only for a System Manager signed in on the desk.

	Runs before API keys and Bearer tokens are checked, so those requests count as Guest here: callers of
	the APIs (Flipkart and other integrations) never get a traceback, whatever System Settings > Allow
	Error Traceback says. The full traceback is still saved in the Error Log."""
	if "System Manager" not in frappe.get_roles():
		frappe.local.flags.disable_traceback = True


def add_security_headers(response=None, request=None):
	"""after_request: browser security headers; a header the response already has is kept."""
	if response is None:
		return
	headers = response.headers
	for name, value in COMMON_HEADERS.items():
		headers.setdefault(name, value)
	if request is not None and (request.path or "").startswith(FLIPKART_API_PREFIX):
		headers["Content-Security-Policy"] = API_CSP
		headers["Cross-Origin-Embedder-Policy"] = "require-corp"
	else:
		headers.setdefault("Content-Security-Policy", DESK_CSP)
	if request is not None and (
		request.scheme == "https" or (request.headers.get("X-Forwarded-Proto") or "").lower() == "https"
	):
		headers.setdefault("Strict-Transport-Security", HSTS)


def validate_https_url(url, label):
	"""VAPT FG-06: integration URLs carry secrets, so they must be https://; plain http is allowed only for
	this machine (localhost, *.localhost, a loopback IP) for local testing."""
	if not url:
		return
	parsed = urlparse(url.strip())
	host = (parsed.hostname or "").lower()
	if parsed.scheme == "https" and host:
		return
	if parsed.scheme == "http" and (host == "localhost" or host.endswith(".localhost") or _is_loopback(host)):
		return
	frappe.throw(_("{0} must be an https:// URL").format(label))


def _is_loopback(host):
	try:
		return ipaddress.ip_address(host).is_loopback
	except ValueError:
		return False
