import json
import requests
import frappe
from frappe.utils import flt
.customizations.shipment.doc_events.utility_functions import (
    containers_count,
    parcel_items
)



def create_gocomet_payload(shipment_name):
    gocomet_doc = frappe.get_doc("Go Comet Settings", "Go Comet Settings")

    # Get Shipment from target site
    target_site_url, api_key, api_secret = get_url_details()

    url = f"{target_site_url}/api/resource/Shipment/{shipment_name}"

    headers = {
        "Authorization": f"token {api_key}:{api_secret}",
        "Content-Type": "application/json",
    }

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    shipment = response.json()["data"]

    go_comet_details = shipment["custom_go_comet_details"][0]

    is_air = any(
        (item.get("container_type") or "").lower() == "air"
        for item in shipment.get("shipment_item", [])
    )

    is_lcl = go_comet_details.get("mode", "").lower() == "lcl"
    is_fcl = go_comet_details.get("mode", "").lower() == "fcl"

    containers = []

    if not is_air and not is_fcl and not is_lcl:
        for row in shipment.get("custom_go_comet_details", []):
            containers.append(
                {
                    "quantity": row.get("qty"),
                    "container_type": row.get("container_type"),
                    "weight": 1,
                    "volume": 1,
                }
            )

    packages = []
    total_quantity = {}

    if is_air or is_lcl:

        total_volume = sum(
            flt(p.get("length"))
            * flt(p.get("width"))
            * flt(p.get("height"))
            for p in shipment.get("shipment_parcel", [])
        )

        total_qty = sum(
            flt(po.get("qty"))
            for po in shipment.get("shipment_purchase_order", [])
        )

        total_quantity = {
            "volume": total_volume,
            "quantity": total_qty,
            "net_weight": 0,
            "volume_unit": "CBM",
            "weight_unit": "KG",
            "gross_weight": 1,
            "package_type": "Non-Stackable",
        }

    else:

        for pack in shipment.get("shipment_parcel", []):
            packages.append(
                {
                    "count": pack.get("count"),
                    "weight": 1,
                    "length": pack.get("length"),
                    "width": pack.get("width"),
                    "height": pack.get("height"),
                    "length_unit": "cm",
                    "weight_unit": "KG",
                    "package_type": "carton",
                }
            )

    consignees = {
        "shipper_group": "",
        "consignee_group": "",
        "customer_group": "",
    }

    po_name = ""
    if shipment.get("shipment_purchase_order"):
        po_name = shipment["shipment_purchase_order"][0].get("delivery_note")

    enquiry_data = {
        "name": shipment.get("name"),
        "mode": go_comet_details.get("mode"),
        "service": frappe.db.get_value(
            "Mode",
            go_comet_details.get("mode"),
            "service",
        ),
        "incoterm": frappe.db.get_value(
            "Incoterm",
            shipment.get("incoterm"),
            "custom_gocomet_code",
        ),
        "client_group_unique_id": gocomet_doc.client_group_id,
        "enquiry_type": "dispatch",
        "shipment_type": go_comet_details.get("enquiry_type"),
        "pol": {
            "name": frappe.db.get_value(
                "Purchase Order",
                po_name,
                "pof",
            )
        },
        "pod": {
            "name": shipment.get("custom_port_of_arrival_")
        },
        "origin": "origin address",
        "destination": "destination address",
        "cargo_type": {
            "hazardous": False,
            "envirotainer": False,
            "refrigerated": False,
        },
        "temperature": "",
        "weight_type": "total_shipment",
        "comments": "FCL Enquiry will be created",
        "destination_charges": {
            "cfs": False,
            "port": True,
            "customs": False,
        },
        "origin_charges": {
            "cfs": False,
            "port": True,
            "customs": False,
        },
        "shipment_of": go_comet_details.get("created_by"),
    }

    if is_air:
        enquiry_data["stuffing_location"] = "factory_stuff"
        enquiry_data["destuffing_location"] = "dock_destuff"
        enquiry_data["consignees"] = consignees
        enquiry_data["packages"] = packages

    elif is_lcl:
        enquiry_data["auction_type"] = "reverse_auction"
        enquiry_data["total_quantity"] = total_quantity
        enquiry_data["bid_close_time"] = "29/10/2021 17:00:00"
        enquiry_data["bid_open_time"] = "28/10/2021 17:00:00"
        enquiry_data["ready_date"] = "27/01/2020"

    else:
        enquiry_data["stuffing_location"] = "factory_stuff"
        enquiry_data["destuffing_location"] = "dock_destuff"
        enquiry_data["consignees"] = consignees
        enquiry_data["packages"] = packages

        if not is_fcl:
            enquiry_data["containers"] = containers

    payload = json.dumps(
        {
            "token": gocomet_doc.token,
            "enquiry": enquiry_data,
        }
    )

    frappe.log_error(payload, "GoComet Payload")

    return payload



@frappe.whitelist()
def gocomet_shipment(shipment_name):
	
	self = frappe.get_doc("Shipment",shipment_name)
	parcel_items(self)
	payload = create_gocomet_payload(shipment_name)
	create_gocomet_log(payload, shipment_name)
	return send_gocomet_request(payload, shipment_name)


@frappe.whitelist()
def gocomet_shipment_by_scheduler():
	ship = frappe.get_all(
		"Go Comet Details",
		filters={"docstatus": ("!=", 2), "mode": ("!=", ""), "enquiry_id": ("=", "")},
		fields=["parent"],
	)
	for i in ship:
		ata_date = frappe.db.get_value("Shipment", i["parent"], "ata_date")
		if not ata_date:
			payload = create_gocomet_payload(i["parent"])
			send_gocomet_request(payload, i["parent"])


def send_gocomet_request(payload, shipment_name):
	enq_id = ""
	gocomet_doc = frappe.get_doc("Go Comet Settings", "Go Comet Settings")
	base_url = gocomet_doc.gocomet_site.rstrip("/")
	url = f"https://{base_url}/api/v1/client/integrations/enquiries"

	headers = {"Content-Type": "application/json"}
	response = requests.post(url, headers=headers, data=payload)
	frappe.msgprint(str(response.text))
	try:
		response_data = response.json()
		enquiry_id = response_data.get("enquiry_id")

		if enquiry_id:
			enq_ids = frappe.get_all("Go Comet Details", filters={"parent": shipment_name}, fields=["name"])
			enq_id = enquiry_id
			for i in enq_ids:
				frappe.db.set_value("Go Comet Details", i["name"], "enquiry_id", enquiry_id)
		else:
			frappe.msgprint("Dispatch created, but no Enquiry ID returned.")
	except Exception as e:
		frappe.msgprint(f"Error parsing response: {str(e)}")
	return enq_id


def create_gocomet_log(payload, shipment_id):
	doc = frappe.get_doc({"doctype": "Gocomet Logs", "shipment_id": shipment_id, "method": payload})
	doc.insert()
