"""OAuth2 (client credentials) for Flipkart -> Gateway calls.

Flipkart fetches a token from `token`, then sends it as `Authorization: Bearer <token>`
on every notification and callback. Tokens are signed JWTs (HS256, keyed on the
inbound client secret), so they survive restarts and need no storage.

Frappe rejects any request with a two-part Authorization header unless it maps
to a user, so `authenticate_flipkart_request` (an `auth_hooks` entry) verifies
the token for the three Flipkart webhook URLs only (exact path) and sets the
session user to the Integration User of Flipkart Settings. A bad token is not
rejected here: it is flagged, and the webhook answers with Flipkart's error
envelope instead of Frappe's. Any other URL, and a missing Integration User,
never get a user from this hook (never Administrator).
"""

import hmac
import ipaddress
import time
import uuid
from functools import wraps

import frappe
import jwt
from frappe import _

from lifelong_integrations.lifelong_integrations.api.flipkart_api.utils import (
	FORBIDDEN,
	UNAUTHORIZED,
	error_response,
	get_settings,
	json_response,
)

FLIPKART_INBOUND_PREFIX = "lifelong_integrations.lifelong_integrations.api.flipkart_api.webhook."
FLIPKART_WEBHOOKS = ("po_notification", "consignment_schedule_callback", "document_ack_callback")
# Only these exact paths get the hook's user: the module name anywhere else in a URL (e.g. as a document
# name in /api/resource/<Single>/<name>) must not authenticate the request.
FLIPKART_WEBHOOK_PATHS = frozenset(f"/api/method/{FLIPKART_INBOUND_PREFIX}{method}" for method in FLIPKART_WEBHOOKS)
TOKEN_ISSUER = "lifelong-integrations-gateway"
MAX_TOKEN_TTL = 3600
# clock difference allowed between the token's iat and this server
TOKEN_CLOCK_SKEW = 60


# per source IP: Flipkart fetches a token about once an hour
TOKEN_RATE_LIMIT = 30
TOKEN_RATE_WINDOW = 60
# a proxy on this server is always trusted to report the caller's IP; others only when listed in Flipkart Settings
LOOPBACK_NETWORKS = (ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("::1/128"))


def rate_limit_by_client_ip(limit, seconds):
	"""Like frappe.rate_limiter.rate_limit, but counted per `get_client_ip`: Frappe's own key is the first
	X-Forwarded-For entry, which the caller chooses, so a new value per request escaped the limit."""

	def decorator(fn):
		@wraps(fn)
		def wrapper(*args, **kwargs):
			if getattr(frappe.local, "request", None):
				ip = get_client_ip(get_settings()) or "unknown"
				key = frappe.cache.make_key(f"rl:{fn.__module__}.{fn.__name__}:{ip}")
				if not frappe.cache.get(key):
					frappe.cache.setex(key, seconds, 0)
				if frappe.cache.incrby(key, 1) > limit:
					frappe.throw(
						_("You hit the rate limit because of too many requests. Please try after sometime."),
						frappe.RateLimitExceededError,
					)
			return fn(*args, **kwargs)

		return wrapper

	return decorator


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit_by_client_ip(limit=TOKEN_RATE_LIMIT, seconds=TOKEN_RATE_WINDOW)
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
	if not request or not is_flipkart_webhook_path(request.path):
		return

	settings = get_settings()
	frappe.local.flags.flipkart_auth_error = None

	if not is_ip_allowed(settings):
		frappe.local.flags.flipkart_auth_error = (403, FORBIDDEN, "Source IP is not allowed")
	else:
		error = _verify_bearer(settings)
		if error:
			frappe.local.flags.flipkart_auth_error = (401, UNAUTHORIZED, error)

	# Set the user either way, otherwise Frappe raises its own 401 before the webhook can reply in Flipkart's
	# format; the webhook refuses the request when the flag is set (only the webhook runs on these paths).
	# No Integration User: no user is set and Frappe refuses the request.
	integration_user = get_integration_user(settings)
	if integration_user:
		frappe.set_user(integration_user)
	else:
		frappe.local.flags.flipkart_auth_error = (401, UNAUTHORIZED, "Flipkart integration is not configured")


def is_flipkart_webhook_path(path):
	return (path or "").rstrip("/") in FLIPKART_WEBHOOK_PATHS


def get_integration_user(settings):
	"""Flipkart Settings' Integration User, if usable: enabled and not Administrator / Guest."""
	user = settings.get("integration_user")
	if not user or user in ("Administrator", "Guest"):
		return None
	if not frappe.db.get_value("User", user, "enabled"):
		return None
	return user


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
	# Only tokens as `token` issues them: at most MAX_TOKEN_TTL long and not issued in the future
	try:
		issued_at, expires_at = int(claims["iat"]), int(claims["exp"])
	except (TypeError, ValueError):
		return "Invalid token"
	if issued_at > time.time() + TOKEN_CLOCK_SKEW or expires_at - issued_at > MAX_TOKEN_TTL:
		return "Invalid token"
	frappe.local.flags.flipkart_auth_checked = True
	return None


def is_ip_allowed(settings):
	allowlist = _networks(settings.inbound_ip_allowlist)
	if not allowlist:
		return True
	ip = get_client_ip(settings)
	return ip is not None and _in_networks(ip, allowlist)


def get_client_ip(settings):
	"""The caller's IP: the connecting address, or, when that is a trusted proxy, the last X-Forwarded-For
	entry no trusted proxy added. Entries further left are written by the caller and are never used
	(frappe.local.request_ip is the leftmost one). None when an address read is not a valid IP."""
	request = getattr(frappe.local, "request", None)
	peer = _parse_ip(getattr(request, "remote_addr", None))
	if peer is None:
		return None
	trusted = [*LOOPBACK_NETWORKS, *_networks(settings.get("trusted_proxies"))]
	if not _in_networks(peer, trusted):
		return peer
	forwarded = ",".join(request.headers.getlist("X-Forwarded-For"))
	for entry in reversed([part.strip() for part in forwarded.split(",") if part.strip()]):
		ip = _parse_ip(entry)
		if ip is None or not _in_networks(ip, trusted):
			return ip
	return peer


def _parse_ip(value):
	try:
		return ipaddress.ip_address((value or "").strip())
	except ValueError:
		return None


def _networks(text):
	networks = []
	for line in (text or "").splitlines():
		try:
			if line.strip():
				networks.append(ipaddress.ip_network(line.strip(), strict=False))
		except ValueError:
			continue
	return networks


def _in_networks(ip, networks):
	return any(ip.version == network.version and ip in network for network in networks)


def _oauth_error(status, error, description):
	return json_response({"error": error, "error_description": description}, status)
