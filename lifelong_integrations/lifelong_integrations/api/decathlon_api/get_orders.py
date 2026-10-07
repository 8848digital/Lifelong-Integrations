import json
import uuid

import frappe
import requests
from frappe import _
from frappe.utils import cint, flt, get_datetime
from india_compliance.gst_india.constants import STATE_PINCODE_MAPPING

from lifelong_integrations.lifelong_integrations.api.live_site_api import \
    live_site_connection

REQUEST_TIMEOUT = 30
FACILITY_CODE = "stglifelong"
UNICOMMERCE_SETTINGS = "Unicommerce Settings"
DUPLICATE_SALE_ORDER_ERROR = "DUPLICATE_SALE_ORDER"


def is_duplicate_sale_order(response_data):
	"""True if UniCommerce rejected the sale order only because an order
	with the same code already exists."""
	errors = response_data.get("errors") or []
	return bool(errors) and all(
		error.get("message") == DUPLICATE_SALE_ORDER_ERROR for error in errors
	)


def create_decathlon_log(title, response=None, message=None):
	"""Create a Decathlon integration log.
	Supports API responses and error messages.
	"""
	log_data = {
		"doctype": "Decathlon Logs",
		"title": title,
	}

	if response is not None:
		log_data["response"] = (
			json.dumps(response, indent=2)
			if isinstance(response, (dict, list))
			else str(response)
		)

	if message:
		log_data["message"] = message

	frappe.get_doc(log_data).insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# UniCommerce authentication (Unicommerce Settings is on the live site)
# ---------------------------------------------------------------------------


def call_live_site(method, params):
	"""Call a whitelisted Frappe method on the live site and return its
	`message`. The live site URL and API key/secret come from Lifelong
	Settings, via the shared live_site_connection() helper."""
	base_url, headers = live_site_connection()

	response = requests.get(
		f"{base_url}/api/method/{method}",
		headers=headers,
		params=params,
		timeout=REQUEST_TIMEOUT,
	)

	if not response.ok:
		create_decathlon_log(
			"Live Site API Request Failed",
			response=response.text,
			message=f"HTTP {response.status_code} from {method}",
		)
		response.raise_for_status()

	return (response.json() or {}).get("message")


def get_live_unicommerce_credentials():
	"""Read the UniCommerce site, client ID and access token from
	Unicommerce Settings on the live site, using Frappe's core client API.
	(frappe.client.get_password needs the API user to be a System Manager.)
	"""
	values = (
		call_live_site(
			"frappe.client.get_value",
			{
				"doctype": UNICOMMERCE_SETTINGS,
				"fieldname": json.dumps(["unicommerce_site", "client_id"]),
			},
		)
		or {}
	)

	credentials = {
		"unicommerce_site": values.get("unicommerce_site"),
		"client_id": values.get("client_id"),
	}

	credentials["access_token"] = call_live_site(
		"frappe.client.get_password",
		{
			"doctype": UNICOMMERCE_SETTINGS,
			"name": UNICOMMERCE_SETTINGS,
			"fieldname": "access_token",
		},
	)

	if not credentials["unicommerce_site"] or not credentials["access_token"]:
		frappe.throw(_("Could not read Unicommerce Settings from the live site."))

	return credentials


def login_to_unicommerce(credentials):
	"""Get a new UniCommerce access token by logging in with the username
	and password from Unicommerce Settings on the live site
	(grant_type=password) -- the same way ecommerce_integrations renews
	its token. The new token is only used in memory for this run;
	nothing is saved to Unicommerce Settings.
	"""
	username = (
		call_live_site(
			"frappe.client.get_value",
			{"doctype": UNICOMMERCE_SETTINGS, "fieldname": "username"},
		)
		or {}
	).get("username")
	password = call_live_site(
		"frappe.client.get_password",
		{
			"doctype": UNICOMMERCE_SETTINGS,
			"name": UNICOMMERCE_SETTINGS,
			"fieldname": "password",
		},
	)

	if not username or not password:
		frappe.throw(
			_("Username/password are not set in Unicommerce Settings on the live site.")
		)

	response = requests.get(
		f"https://{credentials['unicommerce_site']}/oauth/token",
		params={
			"grant_type": "password",
			"client_id": credentials["client_id"],
			"username": username,
			"password": password,
		},
		timeout=REQUEST_TIMEOUT,
	)

	# Not raise_for_status(): its error message would include the URL,
	# which carries the password as a query parameter.
	token_data = response.json() if response.ok else {}

	if not token_data.get("access_token"):
		create_decathlon_log(
			"UniCommerce Login Failed",
			response=response.text,
			message=f"HTTP {response.status_code} from /oauth/token (grant_type=password)",
		)
		frappe.throw(
			_(
				"Could not log in to UniCommerce. Check Decathlon Logs ('UniCommerce Login Failed')."
			)
		)

	credentials["access_token"] = token_data["access_token"]

	create_decathlon_log(
		"UniCommerce Token Renewed",
		message="New access token obtained with username/password after a 401 response",
	)


def renew_access_token(credentials):
	"""Called after a 401. First re-reads the token from the live site,
	since the live site may already have renewed it; only if it is still
	the same expired token, logs in again with username/password.
	"""
	stale_token = credentials["access_token"]
	credentials.update(get_live_unicommerce_credentials())

	if credentials["access_token"] == stale_token:
		login_to_unicommerce(credentials)


def unicommerce_post(credentials, url, payload, retry=True):
	"""POST a payload to UniCommerce.
	On a 401, renews the access token once and retries. `credentials`
	is updated in place, so the rest of the batch uses the new token.
	"""
	headers = {
		"Content-Type": "application/json",
		"Authorization": f"Bearer {credentials['access_token']}",
		"Facility": FACILITY_CODE,
	}

	response = requests.post(
		url,
		headers=headers,
		json=payload,
		timeout=REQUEST_TIMEOUT,
	)

	if response.status_code == 401 and retry:
		renew_access_token(credentials)
		return unicommerce_post(credentials, url, payload, retry=False)

	return response


# ---------------------------------------------------------------------------
# Field mapping helpers
# ---------------------------------------------------------------------------


def get_field_mapping(integration_name="Decathlon"):
	"""Load the UniCommerce <-> Decathlon field mapping from the
	Field Mapping doctype for the given integration.
	Returns a dict of {unicommerce_field_name: decathlon_field_name}.
	Rows with a blank UniCommerce or Decathlon field name are ignored.
	"""
	field_mapping_name = frappe.get_value(
		"Field Mapping", {"integration": integration_name}, "name"
	)

	if not field_mapping_name:
		return {}

	doc = frappe.get_doc("Field Mapping", field_mapping_name)

	return {
		row.unicommerce_field_name: row.decathlon_field_name
		for row in doc.get("decathlon_field_mapping", [])
		if row.unicommerce_field_name and row.decathlon_field_name
	}


def get_mapping_channel(integration_name="Decathlon"):
	"""Return the UniCommerce channel set on the Field Mapping record for
	the given integration. Raises an error if it is not set."""
	channel = frappe.db.get_value(
		"Field Mapping", {"integration": integration_name}, "channel"
	)

	if not channel:
		frappe.throw(
			_("Channel is not set in Field Mapping for integration {0}.").format(
				integration_name
			)
		)

	return channel


def get_mapped_value(source, unicommerce_field, mapping, default=""):
	"""Fetch a value out of `source` using the Decathlon field name
	configured for `unicommerce_field`. Falls back to `unicommerce_field`
	itself when no mapping row exists for it.

	Missing keys, null values and empty strings all return `default`,
	so a Decathlon field sent as null doesn't slip through as None.
	"""
	if not source:
		return default

	decathlon_field = mapping.get(unicommerce_field, unicommerce_field)
	value = source.get(decathlon_field)
	return default if value in (None, "") else value


# ---------------------------------------------------------------------------
# Payload building
# ---------------------------------------------------------------------------


def generate_address_id():
	"""Generate a unique address reference ID.
	Uses UUID to avoid duplicate IDs across orders.
	"""
	return f"ADDR_{uuid.uuid4().hex[:8].upper()}"


def get_state_from_pincode(pincode):
	"""Return the state for an Indian pincode from India Compliance's
	STATE_PINCODE_MAPPING, matched on the first 3 digits. Returns the
	first matching state (same logic as the UniCommerce customer sync),
	or "" if the pincode is invalid or matches nothing.
	"""
	pincode = str(pincode or "").strip()
	if len(pincode) != 6 or not pincode.isdigit():
		return ""

	first_three = cint(pincode[:3])

	for state, ranges in STATE_PINCODE_MAPPING.items():
		# (180, 194) -> ((180, 194),); tuples of ranges pass through.
		if isinstance(ranges[0], int):
			ranges = (ranges,)

		for low, high in ranges:
			if low <= first_three <= high:
				return state

	return ""


def get_address_state(address, mapping):
	"""Return the state for a Decathlon address.
	Uses the state Decathlon sent; when that is null or empty, derives
	it from the pincode.
	"""
	return get_mapped_value(address, "state", mapping) or get_state_from_pincode(
		get_mapped_value(address, "pincode", mapping)
	)


def build_address(address_id, address, customer_name, phone, email, mapping):
	"""Build an address payload for UniCommerce.
	Maps the Decathlon address structure to UniCommerce using
	the configured field mapping.
	"""
	return {
		"id": address_id,
		"name": customer_name,
		"addressLine1": get_mapped_value(address, "addressLine1", mapping),
		"addressLine2": get_mapped_value(address, "addressLine2", mapping),
		"latitude": "",
		"longitude": "",
		"city": get_mapped_value(address, "city", mapping),
		"state": get_address_state(address, mapping),
		"country": "India",
		"pincode": get_mapped_value(address, "pincode", mapping),
		"phone": phone,
		"email": email,
	}


def build_sale_order_items(order_code, order_lines, mapping):
	"""Build UniCommerce sale order items, one item per unit.

	UniCommerce needs a unique `code` on every item, and each item is a
	single unit, so a Decathlon line with quantity N becomes N items.
	The item code comes from the `itemCode` mapping row, falling back
	to Decathlon's order_line_id, then to "<order code>-<line no>".
	(`code` is not used here because that mapping row is the order ID.)

	Decathlon line prices are line totals, so they are split per unit.
	"""
	items = []

	for line_idx, line in enumerate(order_lines, start=1):
		line_code = (
			get_mapped_value(line, "itemCode", mapping)
			or line.get("order_line_id")
			or f"{order_code}-{line_idx}"
		)
		quantity = cint(get_mapped_value(line, "quantity", mapping, default=1)) or 1
		total_price = flt(get_mapped_value(line, "totalPrice", mapping, default=0)) / quantity
		selling_price = (
			flt(get_mapped_value(line, "sellingPrice", mapping, default=0)) / quantity
		)

		for unit in range(1, quantity + 1):
			items.append(
				{
					"code": line_code if quantity == 1 else f"{line_code}-{unit}",
					"itemSku": get_mapped_value(line, "itemSku", mapping),
					"shippingMethodCode": "STD",
					"packetNumber": 1,
					"giftWrap": False,
					"giftMessage": "",
					"facilityCode": FACILITY_CODE,
					"totalPrice": total_price,
					"sellingPrice": selling_price,
					"storeCredit": "0",
					"giftWrapCharges": "0",
				}
			)

	return items


def build_unicommerce_payload(order, mapping=None, channel=None):
	"""Build a UniCommerce sale order payload.
	Safely maps customer, address, and item information using
	the configured Decathlon <-> ERP field mapping.
	"""
	if mapping is None:
		mapping = get_field_mapping()

	if not channel:
		channel = get_mapping_channel()

	order_code = get_mapped_value(order, "code", mapping)

	customer_data = order.get("customer") or {}

	billing_address = customer_data.get("billing_address") or {}
	shipping_address = customer_data.get("shipping_address") or {}

	customer_name = get_mapped_value(billing_address, "customerName", mapping)
	customer_code = get_mapped_value(customer_data, "customerCode", mapping)
	email = get_mapped_value(order, "notificationEmail", mapping)

	phone = (
		get_mapped_value(shipping_address, "notificationMobile", mapping)
		or get_mapped_value(billing_address, "notificationMobile", mapping)
		or ""
	)

	billing_address_id = generate_address_id()
	shipping_address_id = generate_address_id()

	order_lines = order.get("order_lines") or []

	addresses = [
		build_address(
			billing_address_id,
			billing_address,
			customer_name,
			phone,
			email,
			mapping,
		),
		build_address(
			shipping_address_id,
			shipping_address,
			customer_name,
			phone,
			email,
			mapping,
		),
	]

	return {
		"saleOrder": {
			"code": order_code,
			"displayOrderCode": get_mapped_value(order, "displayOrderCode", mapping),
			"displayOrderDateTime": get_mapped_value(order, "displayOrderDateTime", mapping),
			"channelProcessingTime": get_mapped_value(order, "channelProcessingTime", mapping),
			"customerCode": customer_code,
			"customerName": customer_name,
			"customerGSTIN": "",
			"channel": channel,
			"notificationEmail": email,
			"notificationMobile": phone,
			"cashOnDelivery": False,
			"paymentInstrument": "CASH",
			"additionalInfo": "",
			"thirdPartyShipping": False,
			"shippingProviders": [],
			"saleOrderItemCombinations": [],
			"addresses": addresses,
			"billingAddress": {"referenceId": billing_address_id},
			"shippingAddress": {"referenceId": shipping_address_id},
			"saleOrderItems": build_sale_order_items(order_code, order_lines, mapping),
			"customFieldValues": [],
			"currencyCode": get_mapped_value(order, "currencyCode", mapping, default="INR"),
			"taxExempted": True,
			"cformProvided": False,
			"fulfillmentTat": "",
			"verificationRequired": False,
			"priority": 0,
			"totalDiscount": get_mapped_value(order, "totalDiscount", mapping, default=0),
			"totalCashOnDeliveryCharges": 0,
			"totalGiftWrapCharges": 0,
			"totalStoreCredit": 0,
			"totalPrepaidAmount": get_mapped_value(
				order, "totalPrepaidAmount", mapping, default=0
			),
			"useVerifiedListings": False,
		}
	}


# ---------------------------------------------------------------------------
# Whitelisted endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_orders():
	"""Fetch orders from Decathlon and send them to UniCommerce.
	Returns the fetched orders and processing results.
	"""
	settings = frappe.get_doc("Decathlon Settings", "Decathlon Settings")

	start_date = get_datetime(settings.start_date).strftime("%Y-%m-%dT%H:%M:%SZ")

	end_date = get_datetime(settings.end_date).strftime("%Y-%m-%dT%H:%M:%SZ")

	url = f"https://{settings.url}/api/orders"

	params = {
		"only_null_channel": "false",
		"start_date": start_date,
		"end_date": end_date,
		"customer_debited": "true",
		"payment_workflow": "PAY_ON_ACCEPTANCE",
	}

	headers = {"Authorization": settings.token}

	try:
		response = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)

		response.raise_for_status()

		data = response.json()

		create_decathlon_log("Decathlon Response", response=data)

		unicommerce_result = create_unicommerce_order(data)

		return {
			"success": True,
			"orders": data.get("orders", []),
			"order_ids": [
				order.get("order_id") for order in data.get("orders", []) if order.get("order_id")
			],
			"unicommerce": unicommerce_result,
		}

	except requests.exceptions.RequestException as exc:
		create_decathlon_log("Decathlon Get Orders Error", message=frappe.get_traceback())

		frappe.throw(f"Failed to fetch Decathlon orders: {str(exc)}")

	except ValueError:
		create_decathlon_log("Decathlon Invalid Response", message=frappe.get_traceback())

		frappe.throw("Decathlon returned an invalid JSON response.")


@frappe.whitelist()
def create_unicommerce_order(data):
	"""Create Decathlon orders in UniCommerce.
	Processes every order individually and returns results.
	A 401 on any order renews the access token once; the new token
	is then reused for the remaining orders.
	"""
	if isinstance(data, str):
		try:
			data = json.loads(data)
		except json.JSONDecodeError:
			frappe.throw("Invalid JSON data provided.")

	if not isinstance(data, dict):
		frappe.throw("Order data must be a dictionary or JSON object.")

	# Unicommerce Settings lives on the live site; read the site and
	# tokens from there once for the whole batch.
	credentials = get_live_unicommerce_credentials()

	url = (
		f"https://{credentials['unicommerce_site']}" "/services/rest/v1/oms/saleOrder/create"
	)

	mapping = get_field_mapping()
	channel = get_mapping_channel()

	results = []

	for order in data.get("orders", []):
		order_id = order.get("order_id")

		try:
			payload = build_unicommerce_payload(order, mapping, channel)

			create_decathlon_log("UniCommerce Order Payload", response=payload)

			response = unicommerce_post(credentials, url, payload)

			# Raise error for HTTP 4xx / 5xx (including a 401 that
			# persisted after the token refresh).
			response.raise_for_status()

			try:
				response_data = response.json()

			except ValueError:
				create_decathlon_log("UniCommerce Invalid Response", message=response.text)

				results.append(
					{
						"order_id": order_id,
						"success": False,
						"error": "Invalid JSON response",
						"response": response.text,
					}
				)

				continue

			create_decathlon_log("UniCommerce Order Response", response=response_data)

			successful = response_data.get("successful", False)

			# The order was already created in UniCommerce on an earlier
			# run (same Decathlon order fetched again) -- not a failure.
			already_exists = not successful and is_duplicate_sale_order(response_data)

			if already_exists:
				create_decathlon_log(
					"UniCommerce Order Already Exists",
					response=response_data,
					message=f"Order {order_id} already exists in UniCommerce; skipped.",
				)
			elif not successful:
				create_decathlon_log("UniCommerce Order Creation Failed", response=response_data)

			results.append(
				{
					"order_id": order_id,
					"success": successful or already_exists,
					"already_exists": already_exists,
					"http_status": response.status_code,
					"response": response_data,
				}
			)

		except requests.exceptions.RequestException as exc:
			create_decathlon_log("UniCommerce API Request Error", message=frappe.get_traceback())

			results.append(
				{
					"order_id": order_id,
					"success": False,
					"error": str(exc),
				}
			)

		except Exception:
			create_decathlon_log(
				"UniCommerce Order Processing Error", message=frappe.get_traceback()
			)

			results.append(
				{
					"order_id": order_id,
					"success": False,
					"error": "Unexpected error while processing order",
				}
			)

	return {
		"success": True,
		"total_orders": len(results),
		"results": results,
	}
