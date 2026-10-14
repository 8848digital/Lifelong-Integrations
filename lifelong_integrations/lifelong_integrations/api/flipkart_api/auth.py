"""OAuth2 (client credentials) for Flipkart -> Gateway calls.

Flipkart fetches a token from `token`, then sends it as `Authorization: Bearer <token>`
on every notification and callback. Tokens are signed JWTs (HS256, keyed on the
inbound client secret), so they survive restarts and need no storage.

Frappe rejects any request with a two-part Authorization header unless it maps
to a user, so `authenticate_flipkart_request` (an `auth_hooks` entry) verifies
the token for the Flipkart endpoints only and sets the session user. A bad token
is not rejected here: it is flagged, and the endpoint answers with Flipkart's
error envelope instead of Frappe's.
"""

import hmac
import ipaddress
import time
import uuid

import frappe
import jwt

from lifelong_integrations.lifelong_integrations.api.flipkart_api.utils import (
	FORBIDDEN,
	UNAUTHORIZED,
	error_response,
	get_settings,
	json_response,
)

FLIPKART_INBOUND_PREFIX = "lifelong_integrations.lifelong_integrations.api.flipkart_api.webhook."
TOKEN_ISSUER = "lifelong-integrations-gateway"
MAX_TOKEN_TTL = 3600


@frappe.whitelist(allow_guest=True, methods=["POST"])
def token():
	"""Token endpoint shared with Flipkart as `token_uri`."""
	frappe.local.flags.disable_traceback = True
	settings = get_settings()

	if not settings.enabled:
		return _oauth_error(503, "temporarily_unavailable", "Flipkart integration is disabled")
	if not is_ip_allowed(settings):
		return _oauth_error(403, "access_denied", "Source IP is not allowed")

	params = frappe.local.form_dict
	if params.get("grant_type") != "client_credentials":
		return _oauth_error(400, "unsupported_grant_type", "grant_type must be client_credentials")

	expected_id = settings.inbound_client_id or ""
	expected_secret = settings.get_password("inbound_client_secret", raise_exception=False) or ""
	client_id = params.get("client_id") or ""
	client_secret = params.get("client_secret") or ""
	if not (
		expected_id
		and expected_secret
		and hmac.compare_digest(client_id, expected_id)
		and hmac.compare_digest(client_secret, expected_secret)
	):
		return _oauth_error(401, "invalid_client", "Client authentication failed")

	scope = settings.inbound_scope or "flipkart.retail.notifications"
	requested = (params.get("scope") or "").split()
	if requested and not set(requested).issubset(set(scope.split())):
		return _oauth_error(400, "invalid_scope", "Requested scope is not allowed")

	ttl = min(int(settings.token_ttl_seconds or MAX_TOKEN_TTL), MAX_TOKEN_TTL)
	created_at = int(time.time())
	expires_at = created_at + ttl
	access_token = jwt.encode(
		{
			"iss": TOKEN_ISSUER,
			"sub": expected_id,
			"scope": scope,
			"iat": created_at,
			"exp": expires_at,
			"jti": str(uuid.uuid4()),
		},
		expected_secret,
		algorithm="HS256",
	)
	return json_response(
		{
			"access_token": access_token,
			"token_type": "Bearer",
			"expires_in": ttl,
			"created_at": created_at,
			"expires_at": expires_at,
			"scope": scope,
		}
	)


def authenticate_flipkart_request():
	"""auth_hooks entry: verify Flipkart's Bearer token on the Flipkart endpoints only."""
	request = getattr(frappe.local, "request", None)
	if not request or FLIPKART_INBOUND_PREFIX not in (request.path or ""):
		return

	settings = get_settings()
	frappe.local.flags.flipkart_auth_error = None

	if not is_ip_allowed(settings):
		frappe.local.flags.flipkart_auth_error = (403, FORBIDDEN, "Source IP is not allowed")
	else:
		error = _verify_bearer(settings)
		if error:
			frappe.local.flags.flipkart_auth_error = (401, UNAUTHORIZED, error)

	# Set the user either way, otherwise Frappe raises its own 401 before the
	# endpoint can reply in Flipkart's format. The endpoint refuses the request
	# when the flag is set.
	frappe.set_user(settings.integration_user or "Administrator")


def get_auth_error_response():
	error = frappe.local.flags.get("flipkart_auth_error")
	if error is None and not frappe.local.flags.get("flipkart_auth_checked"):
		# The hook did not run (e.g. no Authorization header was sent at all).
		settings = get_settings()
		if not is_ip_allowed(settings):
			error = (403, FORBIDDEN, "Source IP is not allowed")
		else:
			message = _verify_bearer(settings)
			error = (401, UNAUTHORIZED, message) if message else None
	if error:
		return error_response(*error)
	return None


def _verify_bearer(settings):
	header = frappe.get_request_header("Authorization") or ""
	parts = header.split(" ")
	if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
		return "Missing Bearer token"

	secret = settings.get_password("inbound_client_secret", raise_exception=False)
	if not (settings.enabled and settings.inbound_client_id and secret):
		return "Flipkart integration is not configured"

	try:
		claims = jwt.decode(
			parts[1],
			secret,
			algorithms=["HS256"],
			issuer=TOKEN_ISSUER,
			options={"require": ["exp", "iat", "sub"]},
		)
	except jwt.ExpiredSignatureError:
		return "Token has expired"
	except jwt.PyJWTError:
		return "Invalid token"

	if claims.get("sub") != settings.inbound_client_id:
		return "Invalid token"
	frappe.local.flags.flipkart_auth_checked = True
	return None


def is_ip_allowed(settings):
	allowlist = [line.strip() for line in (settings.inbound_ip_allowlist or "").splitlines() if line.strip()]
	if not allowlist:
		return True
	try:
		ip = ipaddress.ip_address(frappe.local.request_ip or "")
	except ValueError:
		return False
	for entry in allowlist:
		try:
			if ip in ipaddress.ip_network(entry, strict=False):
				return True
		except ValueError:
			continue
	return False


def _oauth_error(status, error, description):
	return json_response({"error": error, "error_description": description}, status)
