import frappe
import requests


@frappe.whitelist()
def submit_swiggy_asn(invoice_payload):
	payload = frappe.parse_json(invoice_payload)

	settings = frappe.get_single("Swiggy Settings")

	base_url = settings.api_base_url
	url = base_url.rstrip("/") + "/api/v1/edi/invoice/submit"
	token = settings.client_secret

	invoice_number = (payload.get("invoice") or {}).get("invoice_number") or ""

	log = frappe.new_doc("Swiggy API Log")
	log.api = f"Submit Swiggy ASN | {invoice_number}".strip(" |")
	log.endpoint = url
	log.payload = frappe.as_json(payload)

	try:
		resp = requests.post(
			url,
			json=payload,
			headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
			timeout=30,
		)
		log.status_code = str(resp.status_code)

		try:
			data = resp.json()
		except ValueError:
			# Response wasn't valid JSON at all (HTML error page, empty
			# body, WAF block, etc). Log the raw text so we can actually
			# see what came back, instead of losing it to an unhandled
			# JSONDecodeError.
			log.status = "Failed"
			log.response = resp.text
			log.traceback = f"Non-JSON response, status {resp.status_code}"
			log.insert(ignore_permissions=True)
			return {
				"status_code": resp.status_code,
				"error": f"Swiggy returned a non-JSON response (HTTP {resp.status_code})",
			}

		log.response = frappe.as_json(data)

		# 409 means Swiggy already accepted this idempotency_id. The live site
		# treats it as an acknowledgement, so it is not logged as a failure.
		if resp.status_code == 409:
			log.status = "Success"
			log.traceback = data.get("message", "")
			log.insert(ignore_permissions=True)
			return {"status_code": 409, "ackId": data.get("ackId")}

		if resp.status_code != 200:
			log.status = "Failed"
			log.traceback = data.get("message", "")
			log.insert(ignore_permissions=True)
			return {
				"status_code": resp.status_code,
				"error": data.get("message", "Swiggy ASN submission failed"),
				"code": data.get("code"),
				"grpc_status": data.get("status"),
			}

		log.status = "Success"
		log.insert(ignore_permissions=True)
		return {"status_code": resp.status_code, "ackId": data.get("ackId")}

	except requests.exceptions.RequestException as e:
		status_code = getattr(e.response, "status_code", 0)
		log.status_code = str(status_code)
		log.status = "Failed"
		log.response = getattr(e.response, "text", "")
		log.traceback = frappe.get_traceback()
		log.insert(ignore_permissions=True)
		return {"status_code": status_code or None, "error": str(e)}


@frappe.whitelist()
def log_asn_error(api=None, payload=None, error=None, status_code=None, shipment=None):
	"""Record an ASN failure raised on the live site into Swiggy API Log here."""
	log = frappe.new_doc("Swiggy API Log")
	log.api = api or "Swiggy ASN"
	log.status = "Failed"
	log.status_code = str(status_code) if status_code else ""
	log.endpoint = f"Shipment: {shipment}" if shipment else ""
	log.payload = frappe.as_json(frappe.parse_json(payload) if payload else {})
	log.response = frappe.as_json({"error": error})
	log.traceback = str(error or "")
	log.insert(ignore_permissions=True)
	return log.name


def _get_live_site_connection():
	config = frappe.get_cached_doc("Lifelong Settings")
	base_url = config.target_site_url.rstrip("/")
	headers = {
		"Authorization": f"token {config.target_site_user_api_key}:{config.get_password('target_site_user_api_secret')}",
		"Content-Type": "application/json",
	}
	return base_url, headers


def _get_remote_setting(base_url, headers, fieldname, default=None):
	resp = requests.get(
		f"{base_url}/api/method/frappe.client.get_value",
		params={"doctype": "Swiggy Settings", "fieldname": fieldname},
		headers=headers,
		timeout=15,
	)
	if not resp.ok:
		return default
	return resp.json().get("message", {}).get(fieldname, default)


def trigger_swiggy_asn_sync():
	base_url, headers = _get_live_site_connection()

	interval = _get_remote_setting(base_url, headers, "asn_sync_interval_mins")
	if not _is_due("swiggy_asn_sync_last_run", interval):
		return

	lookback_days = _get_remote_setting(base_url, headers, "asn_lookback_days")
	if not lookback_days:
		return

	try:
		resp = requests.post(
			f"{base_url}/api/method/swiggy_integration.api.swiggy_asn.sync_pending_asn",
			json={"lookback_days": lookback_days},
			headers=headers,
			timeout=60,
		)
		if not resp.ok:
			log_asn_error(
				api="Swiggy ASN Scheduler",
				payload={"lookback_days": lookback_days},
				error=resp.text,
				status_code=resp.status_code,
			)
	except requests.exceptions.RequestException as e:
		log_asn_error(
			api="Swiggy ASN Scheduler",
			payload={"lookback_days": lookback_days},
			error=f"{e}\n\n{frappe.get_traceback()}",
		)


def _is_due(cache_key, interval_mins):
	if not interval_mins:
		return False
	last_run = frappe.cache().get_value(cache_key)
	now = frappe.utils.now_datetime()
	if (
		last_run
		and (now - frappe.utils.get_datetime(last_run)).total_seconds() < interval_mins * 60
	):
		return False
	frappe.cache().set_value(cache_key, now)
	return True
