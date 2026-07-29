import json
import urllib.parse
from datetime import datetime, timedelta

import frappe
import requests

from lifelong_integrations.lifelong_integrations.api.live_site_api import (
    remote_exists, remote_get_doc, remote_get_list, remote_get_meta,
    remote_insert_doc, remote_save_doc)
from lifelong_integrations.lifelong_integrations.doctype.freshdesk_api_log.freshdesk_api_log import \
    freshdesk_log
from lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.freshdesk_settings import \
    get_merged_freshdesk_settings


def get_freshdesk_contact_linked_with_b2c_contact_data(freshdesk, b2c_contact):
	"""Search Freshdesk contacts by the B2C contact's email/phone/mobile and return matching contact IDs."""
	headers = {"Content-Type": "application/json"}
	freshdesk_contacts = []
	if b2c_contact.get("b2c_cx_emailid"):
		r = requests.get(
			freshdesk.get("host")
			+ f"""/api/v2/search/contacts?query="email:'{b2c_contact.get("b2c_cx_emailid")}'" """,
			headers=headers,
			auth=(freshdesk.get("api_key"), "X"),
		)
		if r.content and r.status_code in range(200, 300):
			r_json = r.json()
			if r_json.get("results") and len(r_json.get("results")):
				freshdesk_contacts.extend([a["id"] for a in r_json.get("results")])
	if b2c_contact.get("b2c_cx_phnumber"):
		r = requests.get(
			freshdesk.get("host")
			+ f"""/api/v2/search/contacts?query="mobile:'{urllib.parse.quote_plus(b2c_contact.get("b2c_cx_phnumber"))}'" """,
			headers=headers,
			auth=(freshdesk.get("api_key"), "X"),
		)
		if r.content and r.status_code in range(200, 300):
			r_json = r.json()
			if r_json.get("results") and len(r_json.get("results")):
				freshdesk_contacts.extend([a["id"] for a in r_json.get("results")])
	if b2c_contact.get("b2c_cx_emailid"):
		r = requests.get(
			freshdesk.get("host")
			+ f"""/api/v2/search/contacts?query="phone:'{urllib.parse.quote_plus(b2c_contact.get("b2c_cx_phnumber"))}'" """,
			headers=headers,
			auth=(freshdesk.get("api_key"), "X"),
		)
		if r.content and r.status_code in range(200, 300):
			r_json = r.json()
			if r_json.get("results") and len(r_json.get("results")):
				freshdesk_contacts.extend([a["id"] for a in r_json.get("results")])
	return list(set(freshdesk_contacts))


def get_b2c_customer_product_info(mobile):
	"""Build a human-readable summary of a B2C customer's product/order details for the given mobile number, via live site."""
	customer_data = remote_get_list(
		"B2C Customer Data", filters={"b2c_cx_phnumber": mobile}, fields=["*"]
	)
	product_info = ""
	meta_fields = remote_get_meta("B2C Customer Data")
	for row in customer_data:
		keys = [
			"b2c_order_id",
			"b2c_category",
			"b2c_title",
			"b2c_edd",
			"b2c_sr",
			"b2c_awb_num",
			"b2c_brand_name",
			"b2c_sku_num",
			"b2c_qty",
			"b2c_order_date",
			"b2c_order_status",
			"b2c_channel",
			"extended_warranty",
			"item_cost",
		]
		for key in keys:
			if row.get(key):
				field = meta_fields.get(key) or {}
				fieldtype = field.get("fieldtype")
				label = field.get("label") or key
				if fieldtype == "Date":
					product_info += f"""{label}: {frappe.utils.formatdate(row[key])} \n"""
				elif fieldtype == "Datetime":
					product_info += f"""{label}: {frappe.utils.format_datetime(row[key])} \n"""
				else:
					product_info += f"""{label}: {row[key]} \n"""
		product_info += "\n\n"
	return product_info


def create_new_contact(freshdesk, contact):
	"""Create a new contact in Freshdesk from a B2C Customer Data record and return the resulting Freshdesk contact ID."""
	fd_contact_id = None
	headers = {"Content-Type": "application/json"}
	field_map = {
		"cf_state": "b2c_state",
		"cf_pincode": "b2c_postal_code",
		"cf_city": "b2c_city",
		"cf_order_id": "b2c_order_id",
		"cf_b2c_category": "b2c_category",
		"cf_title": "b2c_title",
		"cf_estimated_delivery_date": "b2c_edd",
		"cf_service_request_no": "b2c_sr",
		"cf_awb_number": "b2c_awb_num",
		"cf_brand_b2c": "b2c_brand_name",
		"cf_model_no_sku": "b2c_sku_num",
		"cf_quantity_b2c": "b2c_qty",
		"cf_order_date": "b2c_order_date",
		"cf_status": "b2c_order_status",
		"cf_channel": "b2c_channel",
		"cf_is_extended_warranty_available": "extended_warranty",
	}
	endpoint = freshdesk.get("host") + "/contacts.json"
	userinfo = {}
	try:
		product_info = get_b2c_customer_product_info(contact.get("b2c_cx_phnumber"))
		userinfo = {
			"user": {
				"name": contact.get("b2c_cx_name"),
				"email": contact.get("b2c_cx_emailid"),
				"customer_id": contact.get("name"),
				"mobile": contact.get("b2c_cx_phnumber"),
				"address": contact.get("b2c_cx_address"),
				"company_id": freshdesk.get("company_id"),
				"custom_field": {
					**{row: str(contact.get(field_map[row]) or "") for row in field_map},
					"cf_product_description": product_info,
				},
			}
		}
		resp = requests.post(
			endpoint,
			headers=headers,
			auth=(freshdesk.get("api_key"), "X"),
			data=json.dumps(userinfo),
		)
		if resp.status_code == 200:
			resp_json = {}
			if resp.content:
				resp_json = resp.json()
				if resp_json.get("user") and resp_json["user"].get("id"):
					fd_contact_id = resp_json["user"].get("id")
			freshdesk_log(
				response=resp,
				endpoint=endpoint,
				message=resp_json,
				request_data=userinfo,
				doc=contact,
				api="Create Contact",
			)
		else:
			freshdesk_log(
				response=resp,
				endpoint=endpoint,
				request_data=userinfo,
				doc=contact,
				api="Create Contact",
			)
	except Exception:
		freshdesk_log(
			api="Create Contact", endpoint=endpoint, request_data=userinfo, doc=contact
		)
	return fd_contact_id


def get_org_contact_id_for_contact(freshdesk, contact_id):
	"""Fetch a Freshdesk contact by ID and return its linked organization contact ID."""
	headers = {"Content-Type": "application/json"}
	r = requests.get(
		freshdesk.get("host") + f"""/api/v2/contacts/{contact_id}""",
		headers=headers,
		auth=(freshdesk.get("api_key"), "X"),
	)
	if r.content and r.status_code in range(200, 300):
		r_json = r.json()
		return r_json.get("org_contact_id")


def update_freshdesk_contact_details(child, resp_json):
	"""Update a FreshDesk Contact Details child row (on live site, via API) with custom object info and save it."""
	data = resp_json.get("data") or {}
	child.update(
		{
			"org_contact_id": data.get("customer_data"),
			"custom_object_id": resp_json.get("display_id"),
			"custom_object_version": resp_json.get("version"),
		}
	)
	remote_save_doc(child)


def create_contact():
	"""Sync recently modified B2C Customer Data records to Freshdesk, creating/linking contacts and syncing their custom object records."""
	freshdesk = get_merged_freshdesk_settings()
	if not freshdesk.get("enable") or not freshdesk.get("upload_contacts"):
		return
	filter_date = None
	today = datetime.today().date()
	if freshdesk.get("sync_contact_before_days"):
		filter_date = today - timedelta(days=freshdesk.get("sync_contact_before_days"))
	if not filter_date:
		frappe.throw(
			"<b>Sync B2C Customer Created Before Days</b> is Mandatory in FreshDesk Integration"
		)
	b2c_customer_data = remote_get_list(
		"B2C Customer Data", filters={"modified": [">=", str(filter_date)]}, fields=["*"]
	)
	headers = {"Content-Type": "application/json"}
	field_map = {
		"data": "name",
		"postal_code_b2c": "b2c_postal_code",
		"item_cost": "item_cost",
		"customer_phone_number": "b2c_cx_phnumber",
		"awb_number": "b2c_awb_num",
		"channel": "b2c_channel",
		"service_request_no": "b2c_sr",
		"brand_b2c": "b2c_brand_name",
		"title": "b2c_title",
		"estimated_delivery_date": "b2c_edd",
		"customer_email_id": "b2c_cx_emailid",
		"b2c_category": "b2c_category",
		"order_date": "b2c_order_date",
		"city_b2c": "b2c_city",
		"quantity_b2c": "b2c_qty",
		"is_extended_warranty_available": "extended_warranty",
		"customer_name": "b2c_cx_name",
		"state": "b2c_state",
		"customer_purchase_details": None,
		"order_id": "b2c_order_id",
		"model_no_sku": "b2c_sku_num",
		"status": "b2c_order_status",
	}
	for cust in b2c_customer_data:
		userinfo = {}
		freshdesk_contacts = get_freshdesk_contact_linked_with_b2c_contact_data(
			freshdesk=freshdesk, b2c_contact=cust
		)
		if not freshdesk_contacts:
			freshdesk_contacts = create_new_contact(freshdesk=freshdesk, contact=cust)
			if freshdesk_contacts:
				freshdesk_contacts = [freshdesk_contacts]
		endpoint = None
		if not freshdesk_contacts:
			continue
		try:
			for fc in freshdesk_contacts:
				endpoint = freshdesk.get("host") + "/api/v2/custom_objects/schemas/4093367/records"
				existing_name = remote_exists(
					"FreshDesk Contact Details",
					{"freshdesk_contact_id": fc, "parent": cust.get("name")},
				)
				if existing_name:
					child = remote_get_doc("FreshDesk Contact Details", existing_name)
					## - Update Existing Contact
					if not child.get("org_contact_id"):
						child["org_contact_id"] = get_org_contact_id_for_contact(
							freshdesk=freshdesk, contact_id=fc
						)
					endpoint += f"/{child.get('custom_object_id')}"
					userinfo = {
						"display_id": child.get("custom_object_id"),
						"data": {
							**{
								row: (str(cust.get(field_map[row])) if cust.get(field_map[row]) else None)
								for row in field_map
							},
							"customer_data": child.get("org_contact_id"),
						},
						"version": child.get("custom_object_version"),
					}
					float_fields = [
						"item_cost",
						"customer_phone_number",
						"quantity_b2c",
						"customer_data",
						"postal_code_b2c",
					]
					for field in float_fields:
						if userinfo["data"].get(field):
							userinfo["data"][field] = int(userinfo["data"][field] or 0)
						else:
							userinfo["data"][field] = None
					resp = requests.put(
						endpoint,
						headers=headers,
						auth=(freshdesk.get("api_key"), "X"),
						data=json.dumps(userinfo),
					)
					if resp.status_code in range(200, 300):
						resp_json = {}
						if resp.content:
							resp_json = resp.json()
							if resp_json.get("display_id"):
								update_freshdesk_contact_details(child, resp_json)
						freshdesk_log(
							response=resp,
							endpoint=endpoint,
							message=resp_json,
							request_data=userinfo,
							doc=cust,
							api="Update Contact Custom Object",
						)
					else:
						freshdesk_log(
							response=resp,
							endpoint=endpoint,
							request_data=userinfo,
							doc=cust,
							api="Update Contact Custom Object",
						)
				else:
					## - Create New Contact
					max_idx = remote_get_list(
						"FreshDesk Contact Details",
						filters={"parent": cust.get("name")},
						fields=["idx"],
					)
					next_idx = (max([r.get("idx") or 0 for r in max_idx], default=0)) + 1
					child = {
						"doctype": "FreshDesk Contact Details",
						"parent": cust.get("name"),
						"parenttype": "B2C Customer Data",
						"parentfield": "freshdesk_contact_details",
						"idx": next_idx,
						"freshdesk_contact_id": fc,
					}
					child["org_contact_id"] = get_org_contact_id_for_contact(
						freshdesk=freshdesk, contact_id=fc
					)
					userinfo = {
						"data": {
							**{
								row: (str(cust.get(field_map[row])) if cust.get(field_map[row]) else None)
								for row in field_map
								if cust.get(field_map[row])
							},
							"customer_data": child.get("org_contact_id"),
						},
					}
					float_fields = [
						"item_cost",
						"customer_phone_number",
						"quantity_b2c",
						"customer_data",
						"postal_code_b2c",
					]
					for field in float_fields:
						if userinfo["data"].get(field):
							userinfo["data"][field] = int(userinfo["data"][field] or 0)
						else:
							userinfo["data"][field] = None
					resp = requests.post(
						endpoint,
						headers=headers,
						auth=(freshdesk.get("api_key"), "X"),
						data=json.dumps(userinfo),
					)
					if resp.status_code in range(200, 300):
						resp_json = {}
						if resp.content:
							resp_json = resp.json()
							if resp_json.get("display_id"):
								child = remote_insert_doc(child)
								update_freshdesk_contact_details(child, resp_json)
						freshdesk_log(
							response=resp,
							endpoint=endpoint,
							message=resp_json,
							request_data=userinfo,
							doc=cust,
							api="Create Contact Custom Object",
						)
					else:
						freshdesk_log(
							response=resp,
							endpoint=endpoint,
							request_data=userinfo,
							doc=cust,
							api="Create Contact Custom Object",
						)
		except Exception:
			freshdesk_log(
				api="Create/Update Contact Custom Object",
				endpoint=endpoint,
				request_data=userinfo,
				doc=cust,
			)
