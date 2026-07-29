import frappe
import requests


def live_site_connection():
	config = frappe.get_cached_doc("Lifelong Settings")
	base_url = config.target_site_url.rstrip("/")
	headers = {
		"Authorization": f"token {config.target_site_user_api_key}:{config.get_password('target_site_user_api_secret')}",
		"Content-Type": "application/json",
	}
	return base_url, headers


def remote_get_list(doctype, filters=None, fields=None, limit_page_length=0):
	base_url, headers = live_site_connection()
	url = f"{base_url}/api/method/frappe.client.get_list"
	params = {
		"doctype": doctype,
		"filters": frappe.as_json(filters or {}),
		"fields": frappe.as_json(fields or ["name"]),
		"limit_page_length": limit_page_length,
	}
	resp = requests.get(url, headers=headers, params=params)
	resp.raise_for_status()
	return resp.json().get("message") or []


def remote_exists(doctype, filters):
	result = remote_get_list(
		doctype, filters=filters, fields=["name"], limit_page_length=1
	)
	return result[0]["name"] if result else None


def remote_get_doc(doctype, name=None):
	base_url, headers = live_site_connection()
	url = f"{base_url}/api/method/frappe.client.get"
	params = {"doctype": doctype}
	if name:
		params["name"] = name
	resp = requests.get(url, headers=headers, params=params)
	resp.raise_for_status()
	return resp.json().get("message") or {}


def remote_save_doc(doc):
	base_url, headers = live_site_connection()
	url = f"{base_url}/api/method/frappe.client.save"
	resp = requests.post(url, headers=headers, json={"doc": frappe.as_json(doc)})
	resp.raise_for_status()
	return resp.json().get("message") or {}


def remote_insert_doc(doc):
	base_url, headers = live_site_connection()
	url = f"{base_url}/api/method/frappe.client.insert"
	resp = requests.post(url, headers=headers, json={"doc": frappe.as_json(doc)})
	resp.raise_for_status()
	return resp.json().get("message") or {}


def remote_get_meta(doctype):
	"""Fetch DocType meta from live site so field labels/fieldtypes can still be resolved on gateway."""
	base_url, headers = live_site_connection()
	url = f"{base_url}/api/method/frappe.desk.form.load.getdoctype"
	resp = requests.get(url, headers=headers, params={"doctype": doctype})
	resp.raise_for_status()
	docs = resp.json().get("docs") or []
	for d in docs:
		if d.get("doctype") == "DocType" and d.get("name") == doctype:
			return {f["fieldname"]: f for f in d.get("fields", [])}
	return {}
