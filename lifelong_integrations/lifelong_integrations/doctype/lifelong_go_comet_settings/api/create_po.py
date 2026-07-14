import datetime
import json
import re

import frappe
import requests
from frappe import _
from frappe.utils import add_to_date, flt, formatdate, getdate
from frappe.utils.file_manager import save_file

from go_comet.gocomet.customizations.purchase_order.api.mapped_gocomet_invoice_data import (
	create_po,
)


@frappe.whitelist()
def get_po_from_gocomet():

	# Get stored API token from Go Comet Settings
	token = frappe.db.get_value("Go Comet Settings", "Go Comet Settings", "token")

	# Get invoice start date or use today's date if not set
	invoice_start_date = frappe.db.get_value(
		"Go Comet Settings", "Go Comet Settings", "invoice_start_date"
	)
	date_str = invoice_start_date if invoice_start_date else frappe.utils.nowdate()

	today_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
	start_date = today_obj.strftime("%d/%m/%Y")
	get_invoice_from_gocomet(token, start_date)


@frappe.whitelist()
def create_po_from_gocomet_by_scheduler():

	# Get stored API token from Go Comet Settings
	token = frappe.db.get_single_value("Go Comet Settings", "token")

	# Get invoice start date or use today's date if not set
	invoice_start_date = frappe.db.get_single_value("Go Comet Settings", "invoice_start_date")
	no_of_days_for_invoice_sync = frappe.db.get_single_value(
		"Go Comet Settings", "no_of_days_for_invoice_sync"
	)
	today = datetime.date.today()
	start_date_obj = today - datetime.timedelta(days=no_of_days_for_invoice_sync)

	start_date = start_date_obj.strftime("%d/%m/%Y")

	get_invoice_from_gocomet(token, start_date)


def get_invoice_page(token, start_date, page):
	"""Fetch a single page from GoComet API."""

	url = f"https://invoice.gocomet.com/api/v1/client/integrations/invoices?page={page}&size=30&token={token}&final_approved_at_start_date={start_date}"

	response = requests.get(url)
	data = response.json()

	# Log each page once
	frappe.get_doc(
		{"doctype": "Gocomet Logs", "logs": json.dumps(data), "api": f"Invoices response page {page}"}
	).insert()

	return data


def get_invoice_from_gocomet(token, start_date):
	"""Fetch ALL pages automatically, log them & create PO."""

	# 1️⃣ Fetch first page to detect total pages
	first_page = get_invoice_page(token, start_date, page=1)

	if not first_page or "invoice_page" not in first_page:
		return

	total_pages = first_page["invoice_page"].get("total_pages")

	# Process page 1
	create_purchase_order(first_page)
	if total_pages:
		# 2️⃣ Loop remaining pages
		for page in range(total_pages):
			result = get_invoice_page(token, start_date, page)
			create_purchase_order(result)


def create_purchase_order(res):
	"""Create Purchase Orders in ERPNext from GoComet invoice data and map vendors/items using configuration mappings."""

	# Extract invoices from the GoComet API response
	invoices = res["invoice_page"]["invoices"]
	for i in invoices:
		shipment = i["name"]
		if i["dispatch_data"]:
			vendor = i["dispatch_data"]["dispatch_details"]["vendor_group"]["name"]
			vendors = frappe.get_all(
				"Gocomet Supplier Mapping",
				filters={"gocomet_supplier": vendor},
				fields=["supplier", "supplier_address"],
			)
			if vendors:
				quote_charges = i["dispatch_data"]["quote_charges"]

				# # Extract freight charge documents
				if i["documents"]:
					from datetime import datetime

					invoice_info = []
					docs = i["documents"]["freight_charges_invoices"]
					# other_docs = i["documents"]["other_documents"]
					other_docs = i.get("documents", {}).get("other_documents", [])
					freight_docs = i.get("documents", {}).get("freight_charges_invoices", [])

					for doc in freight_docs:
						details = doc.get("details", {})
						for invoice_number, invoice_data in details.items():
							detail_info = invoice_data.get("details", {})
							if detail_info:

								invoice_date_str = detail_info.get("invoice_date", "").strip()
								invoice_date_str = invoice_date_str.split()[0]  # remove time if present

								invoice_date = invoice_date_str.split()[0]

								invoice_info.append(
									{"invoice_number": detail_info.get("invoice_number"), "invoice_date": invoice_date}
								)
					url_list = []
					if other_docs:
						for r in other_docs:
							if r["url"]:
								url_list.append(r["url"])

					for d in docs:
						items_list = []
						stamp_duty_item_list = []
						freight_doc_url = ""
						bl_doc_url = ""
						supplier = vendors[0]["supplier"]
						total_amount = 0
						stamp_duty_amount = 0
						proforma_invoice = ""
						if d["url"]:
							freight_doc_url = d["url"]
						name = d["name"].replace(".pdf", "")
						# Parse freight invoice details
						if "details" in d:
							if d["details"]:
								proforma_invoice = list(d["details"].keys())[0]
								gocomet_name = list(d["details"].keys())[0]
								# if gocomet_name == name:
								freight_items = list(d["details"].values())[0]
								if freight_items:
									for item in freight_items["items"]:
										if item["item"] == "STAMP DUTY":
											freig_items = frappe.get_all(
												"Gocomet Item Mapping", filters={"gocomet_item": item["item"]}, fields=["item"]
											)
											if freig_items:
												dict = {}
												dict["item"] = freig_items[0]["item"]
												dict["qty"] = 1
												dict["rate"] = item["total_price"]
												dict["amount"] = item["total_price"]
												stamp_duty_amount = stamp_duty_amount + flt(item["total_price"])
												stamp_duty_item_list.append(dict)
										else:

											freig_items = frappe.get_all(
												"Gocomet Item Mapping", filters={"gocomet_item": item["item"]}, fields=["item"]
											)
											if freig_items:
												dict = {}
												dict["item"] = freig_items[0]["item"]
												dict["qty"] = 1
												dict["rate"] = item["total_price"]
												dict["amount"] = item["total_price"]
												total_amount = total_amount + flt(item["total_price"])
												items_list.append(dict)
											else:
												frappe.throw(_("Item {0} not mapped in Go comet settings").format(item["item"]))
						doc = frappe.get_doc(
							{
								"doctype": "Gocomet Logs",
								"logs": str(items_list),  # convert dict → JSON string
								"api": "Invoices items listresponse",
							}
						)

						doc.insert()
						doc1 = frappe.get_doc(
							{
								"doctype": "Gocomet Logs",
								"logs": str(stamp_duty_item_list),  # convert dict → JSON string
								"api": "Invoices non gst items list response",
							}
						)
						doc1.insert()
						if total_amount:
							# Create Purchase Order if it doesn’t already exist for the shipment
							# po_exist = frappe.get_all(
							# 	"Purchase Order Item",
							# 	filters={"docstatus": ("!=", 2), "shipment": shipment},
							# 	fields=["name"],
							# )
							# if not po_exist:
							po_exist = frappe.get_all(
								"Purchase Order",
								filters={"proforma_invoice": proforma_invoice, "docstatus": ("!=", 2)},
								fields=["name"],
							)

							if not po_exist:
								create_po(
									total_amount,
									shipment,
									supplier,
									items_list,
									freight_doc_url,
									bl_doc_url,
									invoice_info,
									proforma_invoice,
									vendors[0]["supplier_address"],
									url_list,
								)
						if stamp_duty_item_list:
							non_gst_po_exist = frappe.get_all(
								"Purchase Order",
								filters={"proforma_invoice": proforma_invoice, "docstatus": ("!=", 2)},
								fields=["name"],
							)
							if not non_gst_po_exist:
								create_po(
									stamp_duty_amount,
									shipment,
									supplier,
									stamp_duty_item_list,
									freight_doc_url,
									bl_doc_url,
									invoice_info,
									proforma_invoice,
									vendors[0]["supplier_address"],
									url_list,
								)

			else:
				# Throw error if vendor not mapped in settings
				frappe.throw(_("Vendor {0} not mapped in Go comet settings").format(vendor))
