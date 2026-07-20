import frappe
import requests


@frappe.whitelist()
def submit_swiggy_asn(invoice_payload):
	payload = frappe.parse_json(invoice_payload)

	settings = frappe.get_single("Swiggy Settings")

	base_url = settings.api_base_url
	url = base_url.rstrip("/") + "/api/v1/edi/invoice/submit"
	token = settings.client_secret

	log = frappe.new_doc("Swiggy API Log")
	log.api = "Submit Swiggy ASN"
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
			frappe.db.commit()
			return {"error": f"Swiggy returned a non-JSON response (HTTP {resp.status_code})"}

		log.response = frappe.as_json(data)

		if resp.status_code != 200:
			log.status = "Failed"
			log.traceback = data.get("message", "")
			log.insert(ignore_permissions=True)
			frappe.db.commit()
			return {"error": data.get("message", "Swiggy ASN submission failed")}

		log.status = "Success"
		log.insert(ignore_permissions=True)
		frappe.db.commit()
		return {"ackId": data.get("ackId")}

	except requests.exceptions.RequestException as e:
		log.status_code = str(getattr(e.response, "status_code", 0))
		log.status = "Failed"
		log.response = getattr(e.response, "text", "")
		log.traceback = frappe.get_traceback()
		log.insert(ignore_permissions=True)
		frappe.db.commit()
		return {"error": str(e)}


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

	lookback_days = _get_remote_setting(base_url, headers, "asn_lookback_days", 7)

	try:
		resp = requests.post(
			f"{base_url}/api/method/swiggy_integration.api.swiggy_asn.sync_pending_asn",
			json={"lookback_days": lookback_days},
			headers=headers,
			timeout=60,
		)
		if not resp.ok:
			frappe.log_error(resp.text, "Swiggy ASN scheduler trigger failed")
	except requests.exceptions.RequestException:
		frappe.log_error(frappe.get_traceback(), "Swiggy ASN scheduler trigger failed")


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
