import json

import frappe
import requests


def __get_zepto_po_events():
	frappe.enqueue(fetch_zepto_po_events, queue="long", timeout=600)

	frappe.logger().info("Zepto PO sync enqueued")


def fetch_zepto_po_events():
	"""
	- Fetches PO events from Zepto API using Lifelong Zepto Settings
	- Sends data to Live using Lifelong Settings target URL
	"""
	try:
		# Get Zepto credentials from Lifelong Zepto Settings
		zepto_settings = frappe.get_single("Lifelong Zepto Settings")

		if not zepto_settings.enabled:
			frappe.throw("Zepto Integration is disabled in settings")

		# Get config from Lifelong Settings
		lifelong_settings = frappe.get_single("Lifelong Settings")

		if not lifelong_settings.target_site_url:
			frappe.throw("Live Live Sitease URL not configured in Lifelong Settings")

		if not lifelong_settings.target_site_user_api_key:
			frappe.throw("Live Site API Key not configured in Lifelong Settings")

		if not lifelong_settings.target_site_user_api_secret:
			frappe.throw("Live Site API Secret  not configured in Lifelong Settings")

		# Zepto API endpoint
		zepto_url = f"{zepto_settings.api_base_url}/api/v1/external/po/events"

		zepto_headers = {
			"X-Client-ID": zepto_settings.client_id,
			"X-Client-Secret": zepto_settings.get_password("client_secret"),
			"Content-Type": "application/json",
		}

		# Live site endpoint where data will be created
		target_site_url = lifelong_settings.target_site_url
		target_site_user_api_key = lifelong_settings.target_site_user_api_key
		target_site_user_api_secret = lifelong_settings.get_password(
			"target_site_user_api_secret"
		)

		page = 1

		while True:
			params = {
				"days": zepto_settings.days,
				"pageSize": zepto_settings.page_size,
				"pageNumber": page,
				"includeLineItemDetails": True,
				"includeAllPoEvents": True,
			}

			resp_json = make_zepto_request(zepto_url, headers=zepto_headers, params=params)

			data = resp_json.get("data") or {}
			purchase_orders = data.get("purchaseOrders") or []

			for po in purchase_orders:
				# Send to Live Site for data creation
				send_po_to_live_site(
					po, target_site_url, target_site_user_api_key, target_site_user_api_secret
				)

			if not data.get("hasNext"):
				break

			page += 1

	except Exception as e:
		log_zepto_error(
			api_name="PO Events",
			error_message=str(e),
			request_url=zepto_url if "zepto_url" in locals() else None,
			request_params={"page": page} if "page" in locals() else None,
			response_body=str(resp_json) if "resp_json" in locals() else None,
		)
		frappe.log_error(frappe.get_traceback(), f"Zepto PO Fetch Error: {str(e)}")


def make_zepto_request(url, headers=None, params=None, method="GET"):
	"""Make request to Zepto API from Site A"""
	try:
		response = requests.request(method=method, url=url, headers=headers, params=params)

		response.raise_for_status()

		try:
			return response.json()
		except Exception:
			log_zepto_error(
				api_name="PO Events",
				status_code=response.status_code,
				error_message="Invalid JSON response",
				request_url=url,
				request_params=params,
				response_body=response.text,
			)
			frappe.throw("Invalid response from Zepto API")

	except requests.exceptions.RequestException as e:
		log_zepto_error(
			api_name="PO Events",
			status_code=getattr(e.response, "status_code", None),
			error_message=str(e),
			request_url=url,
			request_params=params,
			response_body=getattr(e.response, "text", None),
		)
		raise


def po_exists(po_code, target_site_url, api_key, api_secret):
	"""
	Check if PO code already exists in Live Site
	Returns True if exists, False otherwise
	Avoids sending duplicate data
	"""
	try:
		url = f"{target_site_url}/api/method/frappe.client.get_list"

		headers = {
			"Authorization": f"token {api_key}:{api_secret}",
			"Content-Type": "application/json",
		}

		params = {
			"doctype": "Zepto PO Data",
			"filters": [["po_code", "=", po_code]],
			"fields": ["name"],
			"limit_page_length": 1,
		}

		response = requests.get(url, headers=headers, params=params, timeout=10)

		response.raise_for_status()
		result = response.json()

		# If message has results, PO exists
		if result.get("message") and len(result.get("message", [])) > 0:
			return True

		return False

	except Exception as e:
		# If check fails, log warning but don't fail the sync
		# Better to attempt send than skip due to check error
		frappe.logger().warning(
			f"Could not check if PO {po_code} exists in Live Site: {str(e)}"
		)
		return False


def send_po_to_live_site(po, target_site_url, api_key, api_secret):
	"""
	Send PO data to Live Site for creation
	Live Site will handle Zepto PO Data creation
	"""
	try:
		po_code = po.get("code")

		if not po_code:
			frappe.log_error("Missing PO Code", "Zepto PO Creation")
			return

		# Check if PO already exists
		if po_exists(po_code, target_site_url, api_key, api_secret):
			frappe.logger().info(f"PO {po_code} already exists, skipping")
			return

		# Prepare payload
		payload = {
			"po_code": po_code,
			"event_type": po.get("eventType"),
			"vendor_code": po.get("vendorCode"),
			"status": "Initiated",
			"po_data": json.dumps(po, indent=2),
		}

		# Call API to create Zepto PO Data
		url = f"{target_site_url}/api/resource/Zepto%20PO%20Data"

		headers = {
			"Authorization": f"token {api_key}:{api_secret}",
			"Content-Type": "application/json",
		}

		response = requests.post(url, headers=headers, json=payload, timeout=30)

		response.raise_for_status()

		frappe.logger().info(f"PO {po_code} sent to live site successfully")

	except requests.exceptions.RequestException as e:
		error_msg = f"Failed to send PO {po.get('code')} to live site: {str(e)}"
		log_zepto_error(
			api_name="PO Creation (Live Site)",
			status_code=getattr(e.response, "status_code", None),
			error_message=error_msg,
			request_url=f"{target_site_url}/api/resource/Zepto%20PO%20Data",
			request_params=payload,
			response_body=getattr(e.response, "text", None),
		)
		frappe.log_error(frappe.get_traceback(), error_msg)

	except Exception as e:
		error_msg = f"Failed to create Zepto PO Data for PO {po.get('code')}: {str(e)}"
		frappe.log_error(frappe.get_traceback(), error_msg)
		log_zepto_error(api_name="PO Creation (Live Site)", error_message=error_msg)


def log_zepto_error(
	api_name,
	status_code=None,
	error_message=None,
	request_url=None,
	request_params=None,
	response_body=None,
):
	"""Log errors in Site A (Logging site)"""
	try:
		doc = frappe.new_doc("Zepto Error Log")
		doc.api_name = api_name
		doc.status_code = str(status_code) if status_code else None
		doc.error_message = error_message
		doc.request_url = request_url
		doc.request_params = json.dumps(request_params, indent=2) if request_params else None
		doc.response_body = response_body
		doc.timestamp = frappe.utils.now()

		doc.insert(ignore_permissions=True)
		frappe.db.commit()

	except Exception:
		frappe.log_error(frappe.get_traceback(), "Failed to log Zepto API error")
