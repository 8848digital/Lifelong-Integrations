import json

import frappe
import requests
from frappe.utils import getdate


def __create_zepto_quotations():
	frappe.enqueue(generate_zepto_quotations, queue="long", timeout=600)
	frappe.logger().info("Zepto quotation generation enqueued")


def generate_zepto_quotations():
	"""
	- Fetch Zepto Settings from Live Site
	- Fetch Zepto PO Data from Live Site
	- Process and create Quotations in Live Site
	"""
	try:

		# Get config from Lifelong Settings (this site)

		lifelong_settings = frappe.get_single("Lifelong Settings")

		if not lifelong_settings.target_site_url:
			frappe.throw("Live Site URL not configured in Lifelong Settings")

		if not lifelong_settings.target_site_user_api_key:
			frappe.throw("Live Site API Key not configured in Lifelong Settings")

		if not lifelong_settings.target_site_user_api_secret:
			frappe.throw("Live Site API Secret not configured in Lifelong Settings")

		target_site_url = lifelong_settings.target_site_url.rstrip("/")
		api_key = lifelong_settings.target_site_user_api_key
		api_secret = lifelong_settings.get_password("target_site_user_api_secret")

		# Fetch Zepto Settings from Live Site (not this site)

		zepto_setting = fetch_zepto_settings(target_site_url, api_key, api_secret)

		if not zepto_setting:
			frappe.throw("Could not fetch Zepto Settings from Live Site")

		success_count = 0
		failure_count = 0

		# STEP 1: Fetch Initiated POs from Live Site

		po_list = fetch_zepto_po_data(target_site_url, api_key, api_secret)

		if not po_list:
			frappe.logger().info("No Zepto PO Data to process from Live Site")
			return {"success": 0, "failed": 0}

		frappe.logger().info(f"Fetched {len(po_list)} POs from Live Site")

		# STEP 2: Process each PO and create Quotation in Live Site

		for po in po_list:
			po_name = po.get("name")

			try:
				po_data = fetch_single_po(target_site_url, api_key, api_secret, po_name)

				if not po_data:
					frappe.log_error(f"Could not fetch PO {po_name} from Live Site")
					failure_count += 1
					continue

				if po_data.get("event_type") != "CreatePO":
					continue

				try:
					po_json = json.loads(po_data.get("po_data", "{}"))
				except Exception:
					frappe.log_error(f"Invalid JSON for PO {po_name}")
					failure_count += 1
					continue

				quotation_name = process_po_and_create_quotation(
					po_data, po_json, zepto_setting, target_site_url, api_key, api_secret
				)

				if quotation_name:
					update_po_status(
						target_site_url,
						api_key,
						api_secret,
						po_name,
						{
							"status": "Created",
							"sync_via": "Quotation",
							"sync_doc": quotation_name,
							"error_message": None,
						},
					)
					success_count += 1
				else:
					failure_count += 1

			except Exception as e:
				frappe.log_error(
					frappe.get_traceback(), f"Failed to process PO {po_name}: {str(e)}"
				)
				failure_count += 1

				try:
					update_po_status(
						target_site_url,
						api_key,
						api_secret,
						po_name,
						{"status": "Failed", "error_message": str(e)},
					)
				except Exception:
					pass

		frappe.logger().info(
			f"Quotation generation complete | Success: {success_count} | Failed: {failure_count}"
		)
		return {"success": success_count, "failed": failure_count}

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), f"Quotation Generation Error: {str(e)}")
		return {"success": 0, "failed": 0}


# API FUNCTIONS - Fetch/Update Live Site data


def _get_headers(api_key, api_secret):
	"""Common auth headers"""
	return {
		"Authorization": f"token {api_key}:{api_secret}",
		"Content-Type": "application/json",
	}


def fetch_zepto_settings(site_url, api_key, api_secret):
	"""
	Fetch Zepto Settings doc from Live Site via API.
	Returns a frappe._dict with all required fields.
	"""
	try:
		url = f"{site_url}/api/resource/Zepto%20Settings/Zepto%20Settings"
		response = requests.get(url, headers=_get_headers(api_key, api_secret), timeout=30)
		response.raise_for_status()

		data = response.json().get("data", {})

		# Build a _dict that mirrors what frappe.get_cached_doc would return
		zepto_setting = frappe._dict(
			{
				"company": data.get("company"),
				"company_address": data.get("company_address"),
				"default_item": data.get("default_item"),
				"default_customer": data.get("default_customer"),
				"default_payment_terms_template": data.get("default_payment_terms_template"),
				"quotation_status": data.get("quotation_status"),
				# Child tables as list of _dicts
				"zepto_customer_mapping": [
					frappe._dict(row) for row in data.get("zepto_customer_mapping", [])
				],
				"zepto_linked_location": [
					frappe._dict(row) for row in data.get("zepto_linked_location", [])
				],
			}
		)

		return zepto_setting

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), f"Failed to fetch Zepto Settings: {str(e)}")
		return None


def fetch_zepto_po_data(site_url, api_key, api_secret):
	"""Fetch list of Initiated Zepto POs from Live Site"""
	try:
		url = f"{site_url}/api/method/frappe.client.get_list"
		params = {
			"doctype": "Zepto PO Data",
			"filters": json.dumps([["status", "=", "Initiated"]]),
			"fields": json.dumps(["name", "po_code"]),
		}
		response = requests.get(
			url, headers=_get_headers(api_key, api_secret), params=params, timeout=30
		)
		response.raise_for_status()
		return response.json().get("message", [])

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), f"Failed to fetch PO list: {str(e)}")
		return []


def fetch_single_po(site_url, api_key, api_secret, po_name):
	"""Fetch a single Zepto PO Data doc from Live Site"""
	try:
		url = f"{site_url}/api/resource/Zepto%20PO%20Data/{po_name}"
		response = requests.get(url, headers=_get_headers(api_key, api_secret), timeout=30)
		response.raise_for_status()
		return response.json().get("data")

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), f"Failed to fetch PO {po_name}: {str(e)}")
		return None


def create_quotation_in_live_site(site_url, api_key, api_secret, quotation_data):
	"""POST a new Quotation to Live Site"""
	try:
		url = f"{site_url}/api/resource/Quotation"
		response = requests.post(
			url, headers=_get_headers(api_key, api_secret), json=quotation_data, timeout=30
		)
		response.raise_for_status()

		quotation_name = response.json().get("data", {}).get("name")
		frappe.logger().info(f"Quotation created in Live Site: {quotation_name}")
		return quotation_name

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), f"Failed to create Quotation: {str(e)}")
		raise


def submit_quotation_in_live_site(site_url, api_key, api_secret, quotation_name):
	"""Submit a Quotation in Live Site"""
	try:
		url = f"{site_url}/api/method/frappe.client.submit"
		data = {"doctype": "Quotation", "name": quotation_name}
		response = requests.post(
			url, headers=_get_headers(api_key, api_secret), json=data, timeout=30
		)
		response.raise_for_status()

	except Exception as e:
		frappe.log_error(
			frappe.get_traceback(), f"Failed to submit Quotation {quotation_name}: {str(e)}"
		)


def quotation_exists_in_live_site(site_url, api_key, api_secret, po_code):
	"""Check if a Quotation already exists for this PO code in Live Site"""
	try:
		url = f"{site_url}/api/method/frappe.client.get_list"
		params = {
			"doctype": "Quotation",
			"filters": json.dumps([["po_no", "=", po_code], ["docstatus", "!=", 2]]),
			"fields": json.dumps(["name"]),
			"limit_page_length": 1,
		}
		response = requests.get(
			url, headers=_get_headers(api_key, api_secret), params=params, timeout=10
		)
		response.raise_for_status()
		return len(response.json().get("message", [])) > 0

	except Exception:
		return False


def update_po_status(site_url, api_key, api_secret, po_name, update_data):
	"""Update Zepto PO Data status in Live Site"""
	try:
		url = f"{site_url}/api/resource/Zepto%20PO%20Data/{po_name}"
		response = requests.put(
			url, headers=_get_headers(api_key, api_secret), json=update_data, timeout=30
		)
		response.raise_for_status()

	except Exception as e:
		frappe.log_error(
			frappe.get_traceback(), f"Failed to update PO {po_name} status: {str(e)}"
		)


# LOOKUP FUNCTIONS - Resolve data from Zepto Settings (fetched from Live Site


def get_item_code(item, zepto_setting, site_url, api_key, api_secret):
	"""Lookup item code from EAN barcode via Live Site"""
	try:
		ean = item.get("ean")

		url = f"{site_url}/api/method/frappe.client.get_list"
		params = {
			"doctype": "Item",
			"filters": json.dumps(
				[
					["Item Barcode", "barcode", "=", ean],
					["Item Barcode", "barcode_type", "=", "EAN"],
				]
			),
			"fields": json.dumps(["name"]),
			"limit_page_length": 1,
		}

		response = requests.get(
			url, headers=_get_headers(api_key, api_secret), params=params, timeout=10
		)
		response.raise_for_status()

		result = response.json().get("message", [])
		return result[0].get("name") if result else zepto_setting.default_item

	except Exception:
		frappe.log_error(frappe.get_traceback(), "Item Lookup Failed")
		return zepto_setting.default_item


def get_item_uom(item_code, site_url, api_key, api_secret):
	"""Fetch stock_uom for an item from Live Site"""
	try:
		url = f"{site_url}/api/resource/Item/{item_code}"
		response = requests.get(url, headers=_get_headers(api_key, api_secret), timeout=10)
		response.raise_for_status()
		return response.json().get("data", {}).get("stock_uom", "Nos")

	except Exception:
		frappe.log_error(frappe.get_traceback(), f"UOM Lookup Failed for {item_code}")
		return "Nos"


def get_location(vendor_code, zepto_setting):
	"""Lookup warehouse location from vendor code"""
	for row in zepto_setting.zepto_linked_location:
		if row.vendor_code == vendor_code:
			return row.location
	return None


def get_customer_details(store_code, zepto_setting):
	"""Lookup all customer-related fields from store code in a single pass"""
	details = frappe._dict(
		{
			"customer": None,
			"billing_address": None,
			"shipping_address": None,
			"contact_person_name": None,
			"contact_no": None,
		}
	)

	for row in zepto_setting.zepto_customer_mapping:
		if row.store_code == store_code:
			details.customer = row.customer
			details.billing_address = row.customer_billing_address
			details.shipping_address = row.customer_shipping_address
			details.contact_person_name = row.contact
			details.contact_no = row.contact_no
			break

	if not details.customer:
		details.customer = zepto_setting.default_customer

	return details


# PROCESSING - Build and dispatch Quotation


def process_po_and_create_quotation(
	po_data, po_json, zepto_setting, site_url, api_key, api_secret
):
	"""
	Build quotation payload from PO data and create it in Live Site.
	All lookups (item, customer, location) use zepto_setting fetched from Live Site.
	"""
	try:
		po_name = po_data.get("name")
		po_code = po_json.get("code") or po_data.get("po_code")

		if quotation_exists_in_live_site(site_url, api_key, api_secret, po_code):
			frappe.logger().warning(f"Quotation already exists for PO {po_code}, skipping")
			return None

		to_store_code = po_json.get("toStoreCode")
		vendor_code = po_json.get("vendorCode")
		po_items = po_json.get("poLineItems", [])

		if not po_items:
			frappe.throw(f"No items found in PO {po_code}")

		# Single-pass customer lookup
		customer_details = get_customer_details(to_store_code, zepto_setting)
		location = get_location(vendor_code, zepto_setting)

		quotation_data = {
			"quotation_to": "Customer",
			"party_name": customer_details.customer,
			"contact_person": customer_details.contact_person_name,
			"contact_person_name": customer_details.contact_person_name,
			"contact_no": customer_details.contact_no,
			"transaction_date": str(getdate(po_json.get("timestamp"))),
			"valid_till": str(getdate(po_json.get("expiryDate"))),
			"company": zepto_setting.company,
			"company_address": zepto_setting.company_address,
			"po_no": po_code,
			"po_date": str(getdate(po_json.get("timestamp"))),
			"payment_terms_template": zepto_setting.default_payment_terms_template,
			"taxes_and_charges": None,
			"taxes": [],
			"payment_schedule": [],
		}

		if customer_details.billing_address:
			quotation_data["customer_address"] = customer_details.billing_address

		if customer_details.shipping_address:
			quotation_data["shipping_address_name"] = customer_details.shipping_address

		if location:
			quotation_data["location"] = location

		# Build items
		items = []
		for idx, item in enumerate(po_items, start=1):
			try:
				item_code = get_item_code(item, zepto_setting, site_url, api_key, api_secret)
				stock_uom = get_item_uom(item_code, site_url, api_key, api_secret)

				items.append(
					{
						"item_code": item_code,
						"qty": item.get("quantity") or 0,
						"uom": stock_uom,
						"rate": item.get("taxExclusiveCost") or 0,
						"conversion_factor": 1.0,
						"custom_zepto_material_code": item.get("materialCode"),
						"custom_sku_code": item.get("skuCode"),
						"custom_zepto_po_code": po_code,
						"custom_zepto_mrp": item.get("mrp"),
						"custom_zepto_po_data": po_name,
						"custom_zepto_acknowledgement_status": 0,
					}
				)
			except Exception:
				frappe.log_error(
					frappe.get_traceback(), f"Item Append Failed | PO: {po_name} | Row: {idx}"
				)

		if not items:
			frappe.throw(f"No valid items to insert for PO {po_code}")

		quotation_data["items"] = items

		quotation_name = create_quotation_in_live_site(
			site_url, api_key, api_secret, quotation_data
		)

		if zepto_setting.quotation_status == "Submitted" and quotation_name:
			submit_quotation_in_live_site(site_url, api_key, api_secret, quotation_name)

		return quotation_name

	except Exception as e:
		frappe.log_error(
			frappe.get_traceback(), f"Error processing PO {po_data.get('name')}: {str(e)}"
		)
		raise
