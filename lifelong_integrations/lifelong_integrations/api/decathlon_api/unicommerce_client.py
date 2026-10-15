# Copyright (c) 2026 8848 Digital LLP. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use
# of this file, via any medium, is strictly prohibited without prior
# written permission from 8848 Digital LLP.

"""UniCommerce login, sale order push and Decathlon Logs for the Decathlon integration."""

import json

import frappe
import requests
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from lifelong_integrations.lifelong_integrations.api.decathlon_api.order_payload import \
    build_unicommerce_payload

REQUEST_TIMEOUT = 30
UNICOMMERCE_SETTINGS = "Lifelong Unicommerce Settings"
DUPLICATE_SALE_ORDER_ERROR = "DUPLICATE_SALE_ORDER"

# Decathlon Logs > Log Type
LOG_GET_ORDERS = "Decathlon - Get Orders"
LOG_CREATE_SALE_ORDER = "UniCommerce - Create Sale Order"
LOG_LOGIN = "UniCommerce - Login"


def push_order_to_unicommerce(order, order_id, mapping, channel, connection):
	"""
	Send one Decathlon order to UniCommerce and write one log with the
	payload, the response and the outcome.

	Parameters:
	        order (dict, required): One order from the Decathlon orders API.
	        order_id (str, required): Decathlon order ID, for logs and results.
	        mapping (dict, required): {unicommerce_field: decathlon_field}.
	        channel (str, required): UniCommerce channel code.
	        connection (dict, required): From get_unicommerce_connection();
	                updated in place if the token is renewed.

	Returns:
	        dict: {"order_id", "status", "error"} plus "http_status" when
	        UniCommerce answered. status is Success, Skipped (already in
	        UniCommerce) or Failed.
	"""
	url = connection["url"]
	payload = None

	try:
		payload = build_unicommerce_payload(
			order, mapping, channel, connection["facility_code"]
		)
		response = __unicommerce_post(connection, payload)
	except Exception as exc:
		create_decathlon_log(
			title=f"Order {order_id}: not sent to UniCommerce",
			log_type=LOG_CREATE_SALE_ORDER,
			status="Failed",
			order_id=order_id,
			request_url=url,
			payload=payload if payload is not None else order,
			message=(
				"Could not send the order to UniCommerce."
				if payload is not None
				else "Could not build the UniCommerce payload from the Decathlon order (Payload shows the Decathlon order)."
			),
			error_message=str(exc),
			traceback=frappe.get_traceback(),
		)
		return {"order_id": order_id, "status": "Failed", "error": str(exc)}

	response_data = parse_json(response)

	if not isinstance(response_data, dict):
		error = f"HTTP {response.status_code}: UniCommerce returned a response that is not valid JSON."
		create_decathlon_log(
			title=f"Order {order_id}: UniCommerce error",
			log_type=LOG_CREATE_SALE_ORDER,
			status="Failed",
			order_id=order_id,
			http_status=response.status_code,
			request_url=url,
			payload=payload,
			response=response.text,
			message="UniCommerce did not create the sale order.",
			error_message=error,
		)
		return {"order_id": order_id, "status": "Failed", "error": error}

	if response_data.get("successful"):
		status = "Success"
		title = f"Order {order_id}: created in UniCommerce"
		message = "Sale order created in UniCommerce."
		error = None
	elif __is_duplicate_sale_order(response_data):
		status = "Skipped"
		title = f"Order {order_id}: already in UniCommerce"
		message = "UniCommerce already has this sale order (sent on an earlier run). Nothing was changed."
		error = None
	else:
		status = "Failed"
		title = f"Order {order_id}: UniCommerce rejected the order"
		message = "UniCommerce did not create the sale order."
		error = __get_unicommerce_error(response_data)

	create_decathlon_log(
		title=title,
		log_type=LOG_CREATE_SALE_ORDER,
		status=status,
		order_id=order_id,
		http_status=response.status_code,
		request_url=url,
		payload=payload,
		response=response_data,
		message=message,
		error_message=error,
	)

	return {
		"order_id": order_id,
		"status": status,
		"http_status": response.status_code,
		"error": error,
	}


def get_unicommerce_connection():
	"""
	Load Lifelong Unicommerce Settings and a valid access token once, for
	pushing a whole batch of orders.

	Returns:
	        dict: {"settings", "url", "facility_code", "access_token"}; passed to
	        push_order_to_unicommerce for every order.
	"""
	settings = __get_unicommerce_settings()

	return {
		"settings": settings,
		"url": f"https://{settings.unicommerce_site}/services/rest/v1/oms/saleOrder/create",
		"facility_code": settings.facility_code,
		"access_token": __get_access_token(settings),
	}


def create_decathlon_log(
	title,
	log_type,
	status,
	order_id=None,
	payload=None,
	response=None,
	http_status=None,
	request_url=None,
	message=None,
	error_message=None,
	traceback=None,
):
	"""
	Create a Decathlon Logs entry and commit it straight away, so the log is
	kept even if the request fails and rolls back afterwards.

	Parameters:
	        title (str, required): Short summary shown in the list.
	        log_type (str, required): One of the LOG_* constants.
	        status (str, required): Success, Failed or Skipped.
	        order_id (str, optional): Decathlon order ID.
	        payload (dict | list | str, optional): What was sent.
	        response (dict | list | str, optional): What came back.
	        http_status (int, optional): HTTP status code.
	        request_url (str, optional): URL called (never with secrets).
	        message (str, optional): Readable description of what happened.
	        error_message (str, optional): The error, if any.
	        traceback (str, optional): Python traceback, if any.

	Returns:
	        None
	"""
	frappe.get_doc(
		{
			"doctype": "Decathlon Logs",
			"title": title,
			"log_type": log_type,
			"status": status,
			"decathlon_order_id": order_id,
			"http_status": http_status,
			"request_url": request_url,
			"message": message,
			"error_message": error_message,
			"payload": __to_log_text(payload),
			"response": __to_log_text(response),
			"traceback": traceback,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()


def parse_json(response):
	"""
	Read an HTTP response body as JSON without raising.

	Parameters:
	        response (requests.Response, required): The HTTP response.

	Returns:
	        dict | list | None: The parsed body, or None if it isn't valid JSON.
	"""
	try:
		return response.json()
	except ValueError:
		return None


def __get_unicommerce_settings():
	"""
	Load Lifelong Unicommerce Settings and stop with a clear error if a field
	the integration needs is empty.

	Returns:
	        Document: The Lifelong Unicommerce Settings document.
	"""
	settings = frappe.get_doc(UNICOMMERCE_SETTINGS)

	missing = [
		label
		for fieldname, label in (
			("unicommerce_site", "UniCommerce Site"),
			("client_id", "Client ID"),
			("facility_code", "Facility Code"),
			("username", "Username"),
		)
		if not settings.get(fieldname)
	]
	if not settings.get_password("password", raise_exception=False):
		missing.append("Password")

	if missing:
		frappe.throw(_("Fill {0} in {1}.").format(", ".join(missing), UNICOMMERCE_SETTINGS))

	return settings


def __get_access_token(settings):
	"""
	Return the saved access token if it hasn't expired yet; otherwise log in
	again and return the new one.

	Parameters:
	        settings (Document, required): Lifelong Unicommerce Settings.

	Returns:
	        str: A valid access token.
	"""
	access_token = settings.get_password("access_token", raise_exception=False)

	if (
		access_token
		and settings.expires_on
		and now_datetime() < get_datetime(settings.expires_on)
	):
		return access_token

	return __login_to_unicommerce(settings)


def __login_to_unicommerce(settings):
	"""
	Log in to UniCommerce with the username and password from Lifelong
	Unicommerce Settings (grant_type=password), and save the new access
	token and its expiry there.

	Parameters:
	        settings (Document, required): Lifelong Unicommerce Settings.

	Returns:
	        str: The new access token.
	"""
	token_url = f"https://{settings.unicommerce_site}/oauth/token"

	try:
		response = requests.get(
			token_url,
			params={
				"grant_type": "password",
				"client_id": settings.client_id,
				"username": settings.username,
				"password": settings.get_password("password"),
			},
			timeout=REQUEST_TIMEOUT,
		)
	except requests.exceptions.RequestException as exc:
		# Log the exception type only: its text can include the URL,
		# which carries the password as a query parameter.
		create_decathlon_log(
			title="UniCommerce login failed: could not connect",
			log_type=LOG_LOGIN,
			status="Failed",
			request_url=token_url,
			message="Could not connect to UniCommerce to log in.",
			error_message=type(exc).__name__,
		)
		frappe.throw(_("Could not connect to UniCommerce to log in. See Decathlon Logs."))

	token_data = parse_json(response) or {}
	access_token = token_data.get("access_token")

	if not response.ok or not access_token:
		create_decathlon_log(
			title="UniCommerce login failed",
			log_type=LOG_LOGIN,
			status="Failed",
			http_status=response.status_code,
			request_url=token_url,
			response=response.text,
			message=(
				f"Could not log in to UniCommerce with the username and password in "
				f"{UNICOMMERCE_SETTINGS}."
			),
			error_message=token_data.get("error_description")
			or token_data.get("error")
			or f"HTTP {response.status_code}",
		)
		frappe.throw(
			_(
				"Could not log in to UniCommerce. Check the username and password in {0} "
				"and see Decathlon Logs."
			).format(UNICOMMERCE_SETTINGS)
		)

	# Renew a minute early so a token never expires mid-batch.
	expires_in = max(cint(token_data.get("expires_in")) - 60, 0)
	settings.access_token = access_token
	settings.expires_on = add_to_date(now_datetime(), seconds=expires_in)
	settings.flags.ignore_permissions = True
	settings.save()
	frappe.db.commit()

	create_decathlon_log(
		title="UniCommerce login successful",
		log_type=LOG_LOGIN,
		status="Success",
		http_status=response.status_code,
		request_url=token_url,
		message=f"New access token saved in {UNICOMMERCE_SETTINGS}; valid until {settings.expires_on}.",
	)

	return access_token


def __unicommerce_post(connection, payload, retry=True):
	"""
	POST a sale order to UniCommerce. On a 401, log in again once and retry;
	`connection` is updated in place so the rest of the batch uses the new token.

	Parameters:
	        connection (dict, required): From get_unicommerce_connection().
	        payload (dict, required): The sale order payload.
	        retry (bool, optional): Whether a 401 may trigger one re-login. Default True.

	Returns:
	        requests.Response: UniCommerce's response.
	"""
	headers = {
		"Content-Type": "application/json",
		"Authorization": f"Bearer {connection['access_token']}",
		"Facility": connection["facility_code"],
	}

	response = requests.post(
		connection["url"],
		headers=headers,
		json=payload,
		timeout=REQUEST_TIMEOUT,
	)

	if response.status_code == 401 and retry:
		connection["access_token"] = __login_to_unicommerce(connection["settings"])
		return __unicommerce_post(connection, payload, retry=False)

	return response


def __is_duplicate_sale_order(response_data):
	"""
	Check whether UniCommerce rejected the sale order only because an order
	with the same code already exists.

	Parameters:
	        response_data (dict, required): UniCommerce's JSON response.

	Returns:
	        bool: True if every error is DUPLICATE_SALE_ORDER.
	"""
	errors = response_data.get("errors") or []
	return bool(errors) and all(
		error.get("message") == DUPLICATE_SALE_ORDER_ERROR for error in errors
	)


def __get_unicommerce_error(response_data):
	"""
	Turn UniCommerce's error list into readable text.

	Parameters:
	        response_data (dict, required): UniCommerce's JSON response.

	Returns:
	        str: One error description per line, or a fallback message.
	"""
	messages = [
		error.get("description") or error.get("message")
		for error in (response_data.get("errors") or [])
		if error
	]
	messages = [message for message in messages if message]
	return (
		"\n".join(messages) or response_data.get("message") or "No error details returned."
	)


def __to_log_text(value):
	"""
	Format a value for a Decathlon Logs text field.

	Parameters:
	        value (dict | list | str | None, optional): Value to store.

	Returns:
	        str | None: Indented JSON for dict/list, text for anything else,
	        None for None.
	"""
	if value is None:
		return None
	if isinstance(value, (dict, list)):
		return json.dumps(value, indent=2, default=str)
	return str(value)
