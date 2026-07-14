import json
import uuid

import frappe
import requests
from frappe.integrations.utils import create_request_log
from frappe.utils import add_days, flt, format_date, today

# HELPERS


def _get_headers(api_key, api_secret):
	"""Common auth headers for Live Site API calls"""
	return {
		"Authorization": f"token {api_key}:{api_secret}",
		"Content-Type": "application/json",
	}


def _get_live_site_config():
	"""
	Get all config.
	- Lifelong Settings: Live Site REST credentials
	- Lifelong Zepto Settings: enabled flag + Zepto external API credentials
	"""
	s = frappe.get_single("Lifelong Settings")

	if not s.target_site_url:
		frappe.throw("Live Site URL not configured in Lifelong Settings")
	if not s.target_site_user_api_key:
		frappe.throw("Live Site API Key not configured in Lifelong Settings")
	if not s.target_site_user_api_secret:
		frappe.throw("Live Site API Secret not configured in Lifelong Settings")

	z = frappe.get_single("Lifelong Zepto Settings")

	return frappe._dict(
		{
			"url": s.target_site_url.rstrip("/"),
			"api_key": s.target_site_user_api_key,
			"api_secret": s.get_password("target_site_user_api_secret"),
			"enabled": z.enabled,
			"api_base_url": (z.api_base_url or "").rstrip("/"),
			"client_id": z.client_id,
			"client_secret": z.get_password("client_secret"),
		}
	)


# LIVE SITE FETCH FUNCTIONS


def fetch_zepto_settings(config):
	"""
	Fetch only default_customer from Live Site Zepto Settings.
	days_filter, enabled etc. all come from Lifelong Zepto Settings.
	"""
	try:
		url = f"{config.url}/api/resource/Zepto%20Settings/Zepto%20Settings"
		response = requests.get(
			url, headers=_get_headers(config.api_key, config.api_secret), timeout=30
		)
		response.raise_for_status()
		data = response.json().get("data", {})
		return frappe._dict(
			{
				"default_customer": data.get("default_customer"),
			}
		)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(), "Failed to fetch Zepto Settings from Live Site"
		)
		return None


def fetch_shipments_pending_asn(
	config, default_customer, from_date, last_name, batch_size
):
	"""Fetch pending ASN shipments from Live Site via whitelisted SQL method"""
	try:
		url = (
			f"{config.url}/api/method/zepto_integration.api.shipment.get_pending_asn_shipments"
		)
		params = {
			"customer": default_customer,
			"from_date": str(from_date),
			"last_name": last_name,
			"limit": batch_size,
		}
		response = requests.get(
			url,
			headers=_get_headers(config.api_key, config.api_secret),
			params=params,
			timeout=30,
		)
		response.raise_for_status()
		return response.json().get("message", [])
	except Exception:
		frappe.log_error(
			frappe.get_traceback(), "Failed to fetch pending shipments from Live Site"
		)
		return []


def fetch_shipment_doc(config, shipment_name):
	"""Fetch full Shipment doc from Live Site"""
	try:
		url = f"{config.url}/api/resource/Shipment/{shipment_name}"
		response = requests.get(
			url, headers=_get_headers(config.api_key, config.api_secret), timeout=30
		)
		response.raise_for_status()
		return frappe._dict(response.json().get("data", {}))
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"Failed to fetch Shipment {shipment_name}")
		return None


def fetch_sales_invoices_for_delivery_note(config, delivery_note):
	"""Fetch submitted Sales Invoices linked to a Delivery Note from Live Site"""
	try:
		url = f"{config.url}/api/method/frappe.client.get_list"
		params = {
			"doctype": "Sales Invoice",
			"filters": json.dumps(
				[["delivery_note", "=", delivery_note], ["docstatus", "=", 1]]
			),
			"fields": json.dumps(["name"]),
		}
		response = requests.get(
			url,
			headers=_get_headers(config.api_key, config.api_secret),
			params=params,
			timeout=30,
		)
		response.raise_for_status()
		return [r.get("name") for r in response.json().get("message", [])]
	except Exception:
		frappe.log_error(
			frappe.get_traceback(), f"Failed to fetch invoices for DN {delivery_note}"
		)
		return []


def fetch_sales_invoice_doc(config, invoice_name):
	"""Fetch full Sales Invoice doc from Live Site"""
	try:
		url = f"{config.url}/api/resource/Sales%20Invoice/{invoice_name}"
		response = requests.get(
			url, headers=_get_headers(config.api_key, config.api_secret), timeout=30
		)
		response.raise_for_status()
		return frappe._dict(response.json().get("data", {}))
	except Exception:
		frappe.log_error(
			frappe.get_traceback(), f"Failed to fetch Sales Invoice {invoice_name}"
		)
		return None


def fetch_vendor_code(config, zepto_po_data_name):
	"""Fetch vendor_code from Zepto PO Data on Live Site"""
	try:
		url = f"{config.url}/api/resource/Zepto%20PO%20Data/{zepto_po_data_name}"
		response = requests.get(
			url, headers=_get_headers(config.api_key, config.api_secret), timeout=30
		)
		response.raise_for_status()
		return response.json().get("data", {}).get("vendor_code")
	except Exception:
		frappe.log_error(
			frappe.get_traceback(), f"Failed to fetch vendor code for {zepto_po_data_name}"
		)
		return None


def update_asn_on_live_site(config, shipment_name, invoice_name, asn_number):
	"""Call whitelisted method on Live Site to save ASN details"""
	try:
		url = f"{config.url}/api/method/zepto_integration.api.shipment.update_asn_on_shipment"
		data = {
			"shipment_name": shipment_name,
			"invoice_name": invoice_name,
			"asn_number": asn_number,
		}
		response = requests.post(
			url, headers=_get_headers(config.api_key, config.api_secret), json=data, timeout=30
		)
		response.raise_for_status()
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"Failed to update ASN on Live Site | Shipment: {shipment_name} | Invoice: {invoice_name}",
		)


def __process_pending_asn_shipments():
	try:
		config = _get_live_site_config()

		if not config.enabled:
			frappe.logger().info("Zepto ASN disabled in Lifelong Zepto Settings")
			return

		zepto_setting = fetch_zepto_settings(config)

		if not zepto_setting:
			frappe.log_error(
				title="ASN Cron Stopped", message="Could not fetch Zepto Settings from Live Site"
			)
			return

		default_customer = zepto_setting.get("default_customer")

		# days comes from Lifelong Zepto Settings
		days_filter = config.days or 0

		if days_filter == 0:
			frappe.log_error(
				title="ASN Cron Stopped - Invalid Days Filter",
				message="""
                Days Filter is set to 0.
                This may cause processing of all historical shipments.
                Please configure 'days' in Lifelong Zepto Settings.
                """,
			)
			return

		from_date = add_days(today(), -days_filter)
		batch_size = config.page_size or 20
		last_name = ""

		while True:
			shipments = fetch_shipments_pending_asn(
				config, default_customer, from_date, last_name, batch_size
			)

			if not shipments:
				break

			for row in shipments:
				shipment_name = row.get("name")
				try:
					job_id = f"asn_job_{shipment_name}"

					if not frappe.utils.background_jobs.is_job_enqueued(job_id):
						frappe.enqueue(
							"lifelong_integrations.zepto_intergration.process_shipment_invoices",
							queue="long",
							timeout=600,
							job_id=job_id,
							shipment_name=shipment_name,
						)
						frappe.logger().info(f"Enqueued ASN job for Shipment {shipment_name}")

				except Exception:
					frappe.log_error(
						frappe.get_traceback(), f"ASN Cron Error for Shipment {shipment_name}"
					)

			last_name = shipments[-1].get("name")

			if len(shipments) < batch_size:
				break

		frappe.logger().info("ASN Cron enqueue pass completed")

	except Exception:
		frappe.log_error(frappe.get_traceback(), "ASN Cron Fatal Error")


# BACKGROUND JOB - processes one shipment


def process_shipment_invoices(shipment_name):
	"""
	Background job.
	Re-fetches config fresh — don't pass config across job boundary.
	"""
	try:
		config = _get_live_site_config()

		if not config.enabled:
			frappe.logger().info("Zepto ASN disabled — skipping background job")
			return

		shipment_doc = fetch_shipment_doc(config, shipment_name)

		if not shipment_doc:
			frappe.log_error(
				title="ASN Failed - Shipment Not Found",
				message=f"Shipment {shipment_name} not found on Live Site",
			)
			return

		delivery_notes = shipment_doc.get("shipment_delivery_note", [])

		if not delivery_notes:
			frappe.log_error(
				title="ASN Failed - No Delivery Notes",
				message=f"Shipment {shipment_name} has no delivery notes",
			)
			return

		processed_invoices = {
			d.get("sales_invoice")
			for d in shipment_doc.get("custom_zepto_asn_details", [])
			if d.get("zepto_asn_status") == 1 and not d.get("custom_zepto_asn_cancelled")
		}

		found_invoice = False

		for dn_row in delivery_notes:
			delivery_note = dn_row.get("delivery_note")
			invoice_names = fetch_sales_invoices_for_delivery_note(config, delivery_note)

			if not invoice_names:
				continue

			found_invoice = True

			for invoice_name in invoice_names:
				if invoice_name in processed_invoices:
					continue

				inv_doc = fetch_sales_invoice_doc(config, invoice_name)
				if not inv_doc:
					continue

				send_to_zepto(config, shipment_name, inv_doc)

		if not found_invoice:
			frappe.log_error(
				title="ASN Failed - No Invoice Found",
				message=f"Shipment {shipment_name} has delivery notes but no submitted invoices",
			)

	except Exception:
		frappe.log_error(
			frappe.get_traceback(), f"ASN Job Fatal Error | Shipment: {shipment_name}"
		)


# SEND TO ZEPTO - Builds payload and POSTs to Zepto external API


def send_to_zepto(config, shipment_name, inv):
	"""
	Build ASN payload and POST to Zepto API.
	Zepto API credentials (client_id, client_secret, api_base_url) from
	config — not from Live Site.
	"""
	invoice_name = inv.get("name")

	url = f"{config.api_base_url}/api/v1/external/asn"

	zepto_headers = {
		"Content-Type": "application/json",
		"X-Client-ID": config.client_id,
		"X-Client-Secret": config.client_secret,
		"X-Idempotency-Key": str(uuid.uuid4()),
	}

	# Resolve vendor codes from Live Site
	vendor_codes = set()
	items = inv.get("items", [])

	for item in items:
		po_data_name = item.get("custom_zepto_po_data")
		if not po_data_name:
			frappe.log_error(
				title="ASN Failed - Missing PO Data",
				message=f"Invoice {invoice_name} | Item {item.get('item_code')} has no Zepto PO Data",
			)
			return

		vendor_code = fetch_vendor_code(config, po_data_name)
		if not vendor_code:
			frappe.log_error(
				title="ASN Failed - Missing Vendor Code",
				message=f"Zepto PO Data {po_data_name} has no vendor_code",
			)
			return

		vendor_codes.add(vendor_code)

	if not vendor_codes:
		frappe.log_error(
			title="ASN Failed - No Vendor Code",
			message=f"No vendor code found for Invoice {invoice_name}",
		)
		return

	if len(vendor_codes) > 1:
		frappe.log_error(
			title="ASN Failed - Multiple Vendor Codes",
			message=f"Invoice {invoice_name} has multiple vendor codes: {vendor_codes}",
		)
		return

	vendor_code = list(vendor_codes)[0]

	payload = {
		"purchaseOrderDetails": {
			"purchaseOrderNumber": inv.get("po_no"),
			"purchaseOrderDate": format_date(inv.get("po_date"), "yyyy-mm-dd"),
			"expiryDate": format_date(inv.get("po_date"), "yyyy-mm-dd"),
		},
		"invoiceDetails": {
			"invoiceNumber": invoice_name,
			"invoiceType": "SSI",
			"invoiceDate": format_date(inv.get("posting_date"), "yyyy-mm-dd"),
			"shippingDate": format_date(inv.get("lr_date"), "yyyy-mm-dd")
			if inv.get("lr_date")
			else "",
			"deliveryDate": format_date(inv.get("due_date"), "yyyy-mm-dd"),
			"dueDate": format_date(inv.get("due_date"), "yyyy-mm-dd"),
		},
		"invoiceTotals": {
			"currencyCode": inv.get("currency") or "INR",
			"discountDetails": {
				"totalDiscountAmount": flt(inv.get("discount_amount"), 2) or 0.0
			},
			"taxableAmount": flt(inv.get("net_total"), 2),
			"grandTotalAmount": flt(inv.get("grand_total"), 2),
		},
		"itemDetails": [],
		"seller": {"soldFrom": {"id": vendor_code}},
	}

	for idx, item in enumerate(items, start=1):
		cgst = flt(item.get("cgst_amount"), 2) or 0.0
		sgst = flt(item.get("sgst_amount"), 2) or 0.0
		igst = flt(item.get("igst_amount"), 2) or 0.0

		tax_details = []
		if cgst:
			tax_details.append(
				{
					"taxType": "GST",
					"rateType": "CGST",
					"currencyCode": "INR",
					"taxAmount": cgst,
					"taxRate": flt(item.get("cgst_rate") or 0),
				}
			)
		if sgst:
			tax_details.append(
				{
					"taxType": "GST",
					"rateType": "SGST",
					"currencyCode": "INR",
					"taxAmount": sgst,
					"taxRate": flt(item.get("sgst_rate") or 0),
				}
			)
		if igst:
			tax_details.append(
				{
					"taxType": "GST",
					"rateType": "IGST",
					"currencyCode": "INR",
					"taxAmount": igst,
					"taxRate": flt(item.get("igst_rate") or 0),
				}
			)

		payload["itemDetails"].append(
			{
				"itemSequenceNumber": idx,
				"productIdentifier": {
					"buyerProductIdentifier": {
						"skuCode": item.get("custom_sku_code"),
						"materialCode": item.get("custom_zepto_material_code"),
					},
					"sellerProductIdentifier": {
						"identifier": {
							"identifierType": "EAN",
							"identifierValue": item.get("barcode") or None,
						},
						"itemCode": item.get("item_code"),
						"itemName": item.get("item_name"),
					},
				},
				"quantity": {
					"invoicedQuantity": {"amount": int(item.get("qty", 0)), "unitOfMeasure": "EA"}
				},
				"mrp": flt(item.get("custom_zepto_mrp"), 2),
				"basePrice": flt(item.get("base_net_rate"), 2),
				"taxDetails": tax_details,
				"netAmount": flt(item.get("net_amount"), 2),
			}
		)

	frappe.logger().info(
		f"Zepto ASN Payload for {invoice_name}: {json.dumps(payload, indent=2)}"
	)

	# Log request
	integration_request = create_request_log(
		data=payload,
		service_name="Zepto ASN",
		request_headers=zepto_headers,
		is_remote_request=1,
		url=url,
	)

	try:
		response = requests.post(url, headers=zepto_headers, json=payload, timeout=20)

		try:
			res_data = response.json()
		except Exception:
			res_data = {}

		if 200 <= response.status_code < 300 and not res_data.get("errors"):
			asn_number = res_data.get("data", {}).get("asnNumber") or res_data.get("asnNumber")

			if not asn_number:
				frappe.log_error(
					title="ASN Missing in Success Response",
					message=f"Shipment: {shipment_name} | Invoice: {invoice_name} | Response: {response.text}",
				)
				integration_request.db_set(
					{
						"status": "Failed",
						"error": "ASN number missing in success response",
						"output": response.text,
					}
				)
				return

			# Write ASN back to Live Site
			update_asn_on_live_site(config, shipment_name, invoice_name, asn_number)

			integration_request.db_set({"status": "Completed", "output": response.text})

			frappe.logger().info(f"ASN {asn_number} created for Invoice {invoice_name}")

		else:
			frappe.log_error(
				title="ASN API Failed",
				message=f"Shipment: {shipment_name} | Invoice: {invoice_name} | "
				f"Status: {response.status_code} | Response: {response.text}",
			)
			integration_request.db_set(
				{
					"status": "Failed",
					"error": str(res_data.get("errors", response.text)),
					"output": response.text,
				}
			)

	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"ASN Connection Exception | Shipment: {shipment_name} | Invoice: {invoice_name}",
		)
		integration_request.db_set(
			{"status": "Failed", "error": frappe.get_traceback(), "output": ""}
		)
