import json
import time
import uuid

import frappe
import requests
from werkzeug.wrappers import Response

SETTINGS = "Flipkart Settings"
OUTBOUND_TOKEN_CACHE_KEY = "flipkart_retail_api_access_token"

# Flipkart retries 4xx/5xx differently, so every inbound error carries a stable code.
VALIDATION_FAILED = "VALIDATION_FAILED"
UNAUTHORIZED = "UNAUTHORIZED"
FORBIDDEN = "FORBIDDEN"
INTERNAL_ERROR = "INTERNAL_ERROR"

RETRYABLE_STATUS = (429, 500, 502, 503, 504)


def get_settings():
	return frappe.get_cached_doc(SETTINGS)


def json_response(body, status=200):
	"""Raw JSON response: Flipkart expects its own envelope, not Frappe's {"message": ...}."""
	response = Response(json.dumps(body), status=status, mimetype="application/json")
	response.headers["Cache-Control"] = "no-store"
	return response


def success_response(delivery_uuid):
	return json_response({"delivery_status": "SUCCESS", "uuid": delivery_uuid}, 200)


def error_response(status, error_code, error_message):
	return json_response(
		{"error_response": {"error_code": error_code, "error_message": error_message}}, status
	)


def new_request_id():
	return str(uuid.uuid4())


def as_text(value):
	if value is None:
		return ""
	if isinstance(value, str):
		return value
	return json.dumps(value, indent=4, default=str)


def create_api_log(
	api,
	direction,
	status,
	status_code=None,
	endpoint=None,
	payload=None,
	response=None,
	reference=None,
	request_id=None,
	message_id=None,
	notification_type=None,
	request_headers=None,
	duration_ms=None,
	traceback=None,
	commit=True,
):
	log = frappe.new_doc("Flipkart API Log")
	log.update(
		{
			"api": api,
			"direction": direction,
			"status": status,
			"status_code": str(status_code or ""),
			"endpoint": endpoint or "",
			"payload": as_text(payload),
			"response": as_text(response),
			"reference": reference,
			"request_id": request_id,
			"message_id": message_id,
			"notification_type": notification_type,
			"request_headers": as_text(request_headers),
			"duration_ms": duration_ms,
			"traceback": traceback or "",
		}
	)
	log.flags.ignore_permissions = True
	log.insert(ignore_permissions=True)
	if commit:
		frappe.db.commit()
	return log.name


def safe_request_headers():
	"""Inbound headers for the log, with the bearer token masked."""
	headers = dict(frappe.request.headers) if frappe.request else {}
	if headers.get("Authorization"):
		headers["Authorization"] = headers["Authorization"].split(" ")[0] + " ***"
	return headers


# ---------------------------------------------------------------------------
# Outbound: Gateway -> Flipkart Retail API
# ---------------------------------------------------------------------------


def get_api_base_url(settings=None):
	settings = settings or get_settings()
	url = (
		settings.production_api_base_url
		if settings.environment == "Production"
		else settings.uat_api_base_url
	)
	if not url:
		frappe.throw(f"Flipkart {settings.environment} API Base URL is not set in Flipkart Settings")
	return url.rstrip("/")


def get_token_url(settings=None):
	settings = settings or get_settings()
	url = settings.production_token_url if settings.environment == "Production" else settings.uat_token_url
	if not url:
		frappe.throw(f"Flipkart {settings.environment} Token URL is not set in Flipkart Settings")
	return url


def get_access_token(force_refresh=False):
	"""Client-credentials token from Flipkart, cached until shortly before it expires."""
	settings = get_settings()
	cache_key = f"{OUTBOUND_TOKEN_CACHE_KEY}:{settings.environment}"
	if not force_refresh:
		# expires=True: don't let a cached miss in frappe.local hide a freshly fetched token
		token = frappe.cache.get_value(cache_key, expires=True)
		if token:
			return token

	if not (settings.client_id and settings.target_client_id):
		frappe.throw("Flipkart Client ID and Target Client ID are required in Flipkart Settings")

	token_url = get_token_url(settings)
	started = time.monotonic()
	resp = requests.post(
		token_url,
		data={
			"client_id": settings.client_id,
			"client_secret": settings.get_password("client_secret"),
			"grant_type": "client_credentials",
			"target_client_id": settings.target_client_id,
		},
		headers={"Content-Type": "application/x-www-form-urlencoded"},
		timeout=20,
	)
	duration_ms = int((time.monotonic() - started) * 1000)

	try:
		body = resp.json()
	except ValueError:
		body = {"raw": resp.text[:2000]}

	if not resp.ok or not body.get("access_token"):
		create_api_log(
			api="Flipkart Token",
			direction="Outbound",
			status="Failed",
			status_code=resp.status_code,
			endpoint=token_url,
			response=body,
			duration_ms=duration_ms,
		)
		frappe.throw(f"Could not get a Flipkart access token (HTTP {resp.status_code})")

	expires_in = int(body.get("expires_in") or 3600)
	# Refresh two minutes early so a token never expires mid-request.
	frappe.cache.set_value(cache_key, body["access_token"], expires_in_sec=max(expires_in - 120, 60))
	return body["access_token"]


def call_flipkart(api, path, payload, reference=None, request_id=None, extra_headers=None, max_attempts=3):
	"""POST to the Flipkart Retail API with token refresh, retry and logging.

	The same X-Request-Id is reused on every retry so Flipkart can de-duplicate.
	Returns a dict: ok, status_code, body, request_id, message_id, error.
	"""
	url = get_api_base_url() + path
	request_id = request_id or new_request_id()
	token_refreshed = False
	attempt = 0
	resp = None
	body = None
	error = None
	started = time.monotonic()

	while attempt < max_attempts:
		attempt += 1
		headers = {
			"Authorization": f"Bearer {get_access_token(force_refresh=token_refreshed)}",
			"Content-Type": "application/json",
			"X-Request-Id": request_id,
		}
		headers.update(extra_headers or {})
		error = None
		try:
			resp = requests.post(url, json=payload, headers=headers, timeout=30)
		except requests.exceptions.RequestException as e:
			resp = None
			error = str(e)
		else:
			if resp.status_code == 401 and not token_refreshed:
				token_refreshed = True
				attempt -= 1  # a token refresh is not a delivery attempt
				continue
			if resp.status_code not in RETRYABLE_STATUS:
				break

		if attempt < max_attempts:
			time.sleep(2 ** (attempt - 1))

	duration_ms = int((time.monotonic() - started) * 1000)
	status_code = resp.status_code if resp is not None else 0
	if resp is not None:
		try:
			body = resp.json()
		except ValueError:
			body = {"raw": resp.text[:5000]}
	ok = resp is not None and 200 <= status_code < 300
	if not ok and not error:
		error = extract_error_message(body) or f"Flipkart returned HTTP {status_code}"

	message_id = None
	if isinstance(body, dict):
		message_id = body.get("messageId") or body.get("correlationId")

	create_api_log(
		api=api,
		direction="Outbound",
		status="Success" if ok else "Failed",
		status_code=status_code,
		endpoint=url,
		payload=payload,
		response=body if body is not None else {"error": error},
		reference=reference,
		request_id=request_id,
		message_id=message_id,
		request_headers={k: v for k, v in (extra_headers or {}).items()},
		duration_ms=duration_ms,
		traceback=error if not ok else None,
	)

	return frappe._dict(
		ok=ok,
		status_code=status_code,
		body=body,
		request_id=request_id,
		message_id=message_id,
		error=error,
	)


def extract_error_message(body):
	if not isinstance(body, dict):
		return None
	if isinstance(body.get("error_response"), dict):
		return body["error_response"].get("error_message")
	return body.get("description") or body.get("message") or body.get("error")


# ---------------------------------------------------------------------------
# Gateway -> ERP (live site)
# ---------------------------------------------------------------------------


def erp_connection():
	from lifelong_integrations.lifelong_integrations.api.live_site_api import live_site_connection

	return live_site_connection()


def call_erp(method, payload, timeout=120):
	"""POST to a whitelisted method on the ERP site; returns (http_status, message)."""
	base_url, headers = erp_connection()
	resp = requests.post(
		f"{base_url}/api/method/{method}",
		data=json.dumps(payload, default=str),
		headers=headers,
		timeout=timeout,
	)
	try:
		message = resp.json().get("message")
	except ValueError:
		message = None
	return resp.status_code, message, resp


def find_value(data, keys):
	"""First value for any of `keys`, searching nested dicts/lists depth-first."""
	if isinstance(data, dict):
		for key in keys:
			if data.get(key) not in (None, ""):
				return data[key]
		for value in data.values():
			found = find_value(value, keys)
			if found not in (None, ""):
				return found
	elif isinstance(data, list):
		for value in data:
			found = find_value(value, keys)
			if found not in (None, ""):
				return found
	return None
