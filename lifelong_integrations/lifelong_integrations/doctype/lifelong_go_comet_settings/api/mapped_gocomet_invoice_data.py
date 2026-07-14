import datetime
import json
import re
from urllib.parse import urlparse

import frappe
import requests
from frappe import _
from frappe.utils import add_to_date, flt, formatdate, getdate, today
from frappe.utils.file_manager import save_file



from lifelong_integrations.lifelong_integrations.doctype.lifelong_go_comet_settings.api.get_tracking_data import get_url_details


def create_po(
	total_amount,
	shipment,
	supplier,
	items_list,
	freight_doc_url,
	bl_doc_url,
	invoice_info,
	proforma_invoice,
	supplier_address,
	url_list,
):
	target_site_url, api_key, api_secret = get_url_details()

	headers = {
		"Authorization": f"token {api_key}:{api_secret}",
		"Content-Type": "application/json",
	}

	# Download documents on this site if required
	attachment = download_and_save_pdf(freight_doc_url) or freight_doc_url

	documents = []
	for u in url_list:
		doc_url = download_and_save_pdf(u) or u
		documents.append({"document": doc_url})

	items = []
	for item in items_list:
		items.append(
			{
				"item_code": item["item"],
				"qty": item["qty"],
				"rate": item["rate"],
				"amount": item["amount"],
				"schedule_date": today(),
				"shipment": shipment,
				"custom_shipment_id": shipment,
			}
		)

	doc = {
		"doctype": "Purchase Order",
		"supplier": supplier,
		"location": frappe.db.get_single_value("Go Comet Settings", "location"),
		"proforma_invoice": proforma_invoice,
		"supplier_address": supplier_address,
		"attchment": attachment,
		"proforma_date": str(getdate(invoice_info[0]["invoice_date"])),
		"etd": today(),
		"boe_number": shipment,
		"custom_gocomet_po": 1,
		"items": items,
		"custom_gocomet_docs": documents,
	}

	url = f"{target_site_url}/api/resource/Purchase Order"

	response = requests.post(
		url,
		headers=headers,
		json=doc,
		timeout=120,
	)

	response.raise_for_status()

	po_name = response.json()["data"]["name"]

	# Submit PO if required
	if frappe.db.get_single_value("Go Comet Settings", "po_status") == "Submit":
		requests.post(
			f"{target_site_url}/api/method/frappe.client.submit",
			headers=headers,
			json={
				"doctype": "Purchase Order",
				"name": po_name,
			},
			timeout=120,
		)

	frappe.msgprint(_("Purchase Order {0} created on target site").format(po_name))

	return po_name




def download_and_save_pdf(url):
	"""Download a PDF from URL and save it as a private File.
	Supports both .pdf filenames and /PDF style URLs."""

	try:
		headers = {
			"User-Agent": "Mozilla/5.0"
		}

		# Download file from URL
		response = requests.get(url, headers=headers, timeout=30)
		response.raise_for_status()

		# Validate content type
		content_type = response.headers.get("Content-Type", "")

		if "pdf" not in content_type.lower():
			frappe.log_error(
				title="Invalid PDF Response",
				message=f"URL did not return PDF\nURL: {url}"
			)
			return None

		# Validate PDF binary signature
		if not response.content.startswith(b"%PDF"):
			frappe.log_error(
				title="Corrupted PDF",
				message=f"Downloaded file is corrupted\nURL: {url}"
			)
			return None

		# Remove query params and trailing slash
		path = urlparse(url).path.strip("/")

		# Get last part of URL
		last_part = path.rsplit("/", 1)[-1]

		# Handle URLs ending with .pdf / .PDF
		if re.search(r"\.pdf$", last_part, re.IGNORECASE):
			file_name = re.sub(
				r"\.pdf$",
				".pdf",
				last_part,
				flags=re.IGNORECASE
			)

		else:
			parts = path.split("/")

			# Handle URLs ending with /PDF
			if last_part.lower() == "pdf" and len(parts) >= 2:
				file_name = f"{parts[-2]}.pdf"
			else:
				file_name = "downloaded_file.pdf"

		# Save file in ERPNext private files
		file_doc = save_file(
			fname=file_name,
			content=response.content,
			dt=None,
			dn=None,
			is_private=1,
		)

		frappe.db.commit()

		return file_doc.file_url

	except Exception:
		# Log failed URL and continue
		frappe.log_error(
			title="PDF Download Failed",
			message=frappe.get_traceback() + f"\n\nURL: {url}"
		)

		return None



