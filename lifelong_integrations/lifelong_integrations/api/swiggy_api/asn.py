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
			log.status = "Error"
			log.response = resp.text
			log.traceback = f"Non-JSON response, status {resp.status_code}"
			log.insert(ignore_permissions=True)
			frappe.db.commit()
			return {"error": f"Swiggy returned a non-JSON response (HTTP {resp.status_code})"}

		log.response = frappe.as_json(data)

		if resp.status_code != 200:
			log.status = "Error"
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
		log.status = "Error"
		log.response = getattr(e.response, "text", "")
		log.traceback = frappe.get_traceback()
		log.insert(ignore_permissions=True)
		frappe.db.commit()
		return {"error": str(e)}
