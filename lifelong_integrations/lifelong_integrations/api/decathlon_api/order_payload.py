# Copyright (c) 2026 8848 Digital LLP. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use
# of this file, via any medium, is strictly prohibited without prior
# written permission from 8848 Digital LLP.

"""Field mapping and UniCommerce sale order payload building for Decathlon orders."""

import uuid

import frappe
from frappe import _
from frappe.utils import cint, flt
from india_compliance.gst_india.constants import STATE_PINCODE_MAPPING


def build_unicommerce_payload(order, mapping=None, channel=None, facility_code=None):
	"""
	Build a UniCommerce sale order payload from one Decathlon order, using
	the Decathlon Field Mapping for every field that comes from Decathlon.

	Parameters:
	        order (dict, required): One order from the Decathlon orders API.
	        mapping (dict, optional): {unicommerce_field: decathlon_field};
	                loaded from Field Mapping when not given.
	        channel (str, optional): UniCommerce channel code; read from
	                Field Mapping when not given (raises if not set there).
	        facility_code (str, optional): UniCommerce facility; read from
	                Lifelong Unicommerce Settings when not given.

	Returns:
	        dict: {"saleOrder": {...}} ready to POST to UniCommerce.
	"""
	if mapping is None:
		mapping = get_field_mapping()

	if not channel:
		channel = get_mapping_channel()

	if not facility_code:
		# Imported here: unicommerce_client imports this module, so a
		# top-level import would be circular.
		from lifelong_integrations.lifelong_integrations.api.decathlon_api.unicommerce_client import \
		    UNICOMMERCE_SETTINGS

		facility_code = frappe.db.get_single_value(UNICOMMERCE_SETTINGS, "facility_code")

	order_code = __get_mapped_value(order, "code", mapping)

	customer_data = order.get("customer") or {}

	billing_address = customer_data.get("billing_address") or {}
	shipping_address = customer_data.get("shipping_address") or {}

	customer_name = __get_mapped_value(billing_address, "customerName", mapping)
	customer_code = __get_mapped_value(customer_data, "customerCode", mapping)
	email = __get_mapped_value(order, "notificationEmail", mapping)

	phone = (
		__get_mapped_value(shipping_address, "notificationMobile", mapping)
		or __get_mapped_value(billing_address, "notificationMobile", mapping)
		or ""
	)

	billing_address_id = __generate_address_id()
	shipping_address_id = __generate_address_id()

	order_lines = order.get("order_lines") or []

	addresses = [
		__build_address(
			billing_address_id,
			billing_address,
			customer_name,
			phone,
			email,
			mapping,
		),
		__build_address(
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
			"displayOrderCode": __get_mapped_value(order, "displayOrderCode", mapping),
			"displayOrderDateTime": __get_mapped_value(order, "displayOrderDateTime", mapping),
			"channelProcessingTime": __get_mapped_value(order, "channelProcessingTime", mapping),
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
			"saleOrderItems": __build_sale_order_items(
				order_code, order_lines, mapping, facility_code
			),
			"customFieldValues": [],
			"currencyCode": __get_mapped_value(order, "currencyCode", mapping, default="INR"),
			"taxExempted": True,
			"cformProvided": False,
			"fulfillmentTat": "",
			"verificationRequired": False,
			"priority": 0,
			"totalDiscount": __get_mapped_value(order, "totalDiscount", mapping, default=0),
			"totalCashOnDeliveryCharges": 0,
			"totalGiftWrapCharges": 0,
			"totalStoreCredit": 0,
			"totalPrepaidAmount": __get_mapped_value(
				order, "totalPrepaidAmount", mapping, default=0
			),
			"useVerifiedListings": False,
		}
	}


def get_field_mapping(integration_name="Decathlon"):
	"""
	Load the UniCommerce <-> Decathlon field mapping from the Field Mapping
	doctype. Rows with a blank UniCommerce or Decathlon field name are ignored.

	Parameters:
	        integration_name (str, optional): Field Mapping integration. Default "Decathlon".

	Returns:
	        dict: {unicommerce_field_name: decathlon_field_name}; empty if no
	        Field Mapping exists for the integration.
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


def get_channel(integration_name="Decathlon"):
	"""
	Read the UniCommerce channel set on the Field Mapping record.

	Parameters:
	        integration_name (str, optional): Field Mapping integration. Default "Decathlon".

	Returns:
	        str | None: The channel code, or None if it is not set.
	"""
	return frappe.db.get_value(
		"Field Mapping", {"integration": integration_name}, "channel"
	)


def get_mapping_channel(integration_name="Decathlon"):
	"""
	Read the UniCommerce channel set on the Field Mapping record, and stop
	with an error if it is missing (it is required to push orders).

	Parameters:
	        integration_name (str, optional): Field Mapping integration. Default "Decathlon".

	Returns:
	        str: The channel code.
	"""
	channel = get_channel(integration_name)

	if not channel:
		frappe.throw(
			_("Channel is not set in Field Mapping for integration {0}.").format(
				integration_name
			)
		)

	return channel


def __build_address(address_id, address, customer_name, phone, email, mapping):
	"""
	Build one UniCommerce address from a Decathlon address, using the
	field mapping.

	Parameters:
	        address_id (str, required): Reference ID used by billingAddress/shippingAddress.
	        address (dict, required): Decathlon billing or shipping address.
	        customer_name (str, required): Name shown on the address.
	        phone (str, required): Contact phone ("" if none).
	        email (str, required): Contact email ("" if none).
	        mapping (dict, required): {unicommerce_field: decathlon_field}.

	Returns:
	        dict: The UniCommerce address.
	"""
	return {
		"id": address_id,
		"name": customer_name,
		"addressLine1": __get_mapped_value(address, "addressLine1", mapping),
		"addressLine2": __get_mapped_value(address, "addressLine2", mapping),
		"latitude": "",
		"longitude": "",
		"city": __get_mapped_value(address, "city", mapping),
		"state": __get_address_state(address, mapping),
		"country": "India",
		"pincode": __get_mapped_value(address, "pincode", mapping),
		"phone": phone,
		"email": email,
	}


def __build_sale_order_items(order_code, order_lines, mapping, facility_code):
	"""
	Build UniCommerce sale order items, one item per unit. UniCommerce needs
	a unique `code` on every item and treats each item as a single unit, so
	a Decathlon line with quantity N becomes N items.

	Parameters:
	        order_code (str, required): Order code, used for fallback item codes.
	        order_lines (list, required): Decathlon order lines.
	        mapping (dict, required): {unicommerce_field: decathlon_field}.
	        facility_code (str, required): UniCommerce facility for every item.

	Returns:
	        list[dict]: The UniCommerce sale order items.
	"""
	items = []

	for line_idx, line in enumerate(order_lines, start=1):
		items.extend(__build_line_items(line, line_idx, order_code, mapping, facility_code))

	return items


def __build_line_items(line, line_idx, order_code, mapping, facility_code):
	"""
	Build the UniCommerce items for one Decathlon order line, one per unit.
	The item code comes from the `itemCode` mapping row, then Decathlon's
	order_line_id, then "<order code>-<line no>" (`code` is not used here
	because that mapping row is the order ID). Line prices are line totals,
	so they are split per unit.

	Parameters:
	        line (dict, required): One Decathlon order line.
	        line_idx (int, required): 1-based position of the line in the order.
	        order_code (str, required): Order code, used for the fallback item code.
	        mapping (dict, required): {unicommerce_field: decathlon_field}.
	        facility_code (str, required): UniCommerce facility for every item.

	Returns:
	        list[dict]: One item per unit; codes get "-1", "-2", … when quantity > 1.
	"""
	line_code = (
		__get_mapped_value(line, "itemCode", mapping)
		or line.get("order_line_id")
		or f"{order_code}-{line_idx}"
	)
	quantity = cint(__get_mapped_value(line, "quantity", mapping, default=1)) or 1
	total_price = (
		flt(__get_mapped_value(line, "totalPrice", mapping, default=0)) / quantity
	)
	selling_price = (
		flt(__get_mapped_value(line, "sellingPrice", mapping, default=0)) / quantity
	)

	return [
		{
			"code": line_code if quantity == 1 else f"{line_code}-{unit}",
			"itemSku": __get_mapped_value(line, "itemSku", mapping),
			"shippingMethodCode": "STD",
			"packetNumber": 1,
			"giftWrap": False,
			"giftMessage": "",
			"facilityCode": facility_code,
			"totalPrice": total_price,
			"sellingPrice": selling_price,
			"storeCredit": "0",
			"giftWrapCharges": "0",
		}
		for unit in range(1, quantity + 1)
	]


def __get_address_state(address, mapping):
	"""
	Return the state for a Decathlon address: the state Decathlon sent, or
	the state derived from the pincode when that is null or empty.

	Parameters:
	        address (dict, required): Decathlon billing or shipping address.
	        mapping (dict, required): {unicommerce_field: decathlon_field}.

	Returns:
	        str: The state name, or "" if it cannot be found.
	"""
	return __get_mapped_value(address, "state", mapping) or __get_state_from_pincode(
		__get_mapped_value(address, "pincode", mapping)
	)


def __get_state_from_pincode(pincode):
	"""
	Return the state for an Indian pincode from India Compliance's
	STATE_PINCODE_MAPPING, matched on the first 3 digits. The first
	matching state wins (same logic as the UniCommerce customer sync).

	Parameters:
	        pincode (str | int, optional): The 6-digit pincode.

	Returns:
	        str: The state name, or "" if the pincode is invalid or matches nothing.
	"""
	pincode = str(pincode or "").strip()
	if len(pincode) != 6 or not pincode.isdigit():
		return ""

	first_three = cint(pincode[:3])

	for state, ranges in STATE_PINCODE_MAPPING.items():
		if __is_in_pincode_ranges(first_three, ranges):
			return state

	return ""


def __is_in_pincode_ranges(first_three, ranges):
	"""
	Check whether a pincode prefix falls in a STATE_PINCODE_MAPPING entry.

	Parameters:
	        first_three (int, required): First 3 digits of the pincode.
	        ranges (tuple, required): One range, e.g. (180, 194), or a tuple of
	                ranges, e.g. ((140, 140), (160, 160)).

	Returns:
	        bool: True if the prefix is inside any of the ranges.
	"""
	# (180, 194) -> ((180, 194),); tuples of ranges pass through.
	if isinstance(ranges[0], int):
		ranges = (ranges,)

	return any(low <= first_three <= high for low, high in ranges)


def __get_mapped_value(source, unicommerce_field, mapping, default=""):
	"""
	Read a value from a Decathlon dict using the Decathlon field name mapped
	to `unicommerce_field`, falling back to `unicommerce_field` itself when
	there is no mapping row. Missing keys, null and "" all give `default`,
	so a field Decathlon sends as null doesn't slip through as None.

	Parameters:
	        source (dict, optional): Decathlon order, line, customer or address.
	        unicommerce_field (str, required): The UniCommerce field name.
	        mapping (dict, required): {unicommerce_field: decathlon_field}.
	        default (any, optional): Value when nothing is found. Default "".

	Returns:
	        any: The Decathlon value, or `default`.
	"""
	if not source:
		return default

	decathlon_field = mapping.get(unicommerce_field, unicommerce_field)
	value = source.get(decathlon_field)
	return default if value in (None, "") else value


def __generate_address_id():
	"""
	Generate a unique address reference ID, so IDs never repeat across orders.

	Returns:
	        str: e.g. "ADDR_1A2B3C4D".
	"""
	return f"ADDR_{uuid.uuid4().hex[:8].upper()}"
