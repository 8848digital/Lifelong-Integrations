import json
import frappe
import requests
from frappe import _




@frappe.whitelist()
def update_po_details_scheduler():
    target_site_url, api_key, api_secret = get_url_details()

    headers = {
        "Authorization": f"token {api_key}:{api_secret}"
    }

    # Get Go Comet Details
    url = f"{target_site_url}/api/resource/Go Comet Details"

    params = {
        "fields": json.dumps(["parent"]),
        "filters": json.dumps([
            ["creation", ">", "2025-05-22 00:00:00"],
            ["enquiry_id", "!=", ""],
            ["docstatus", "!=", 2]
        ]),
        "limit_page_length": 0
    }

    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()

    ship_details = response.json().get("data", [])

    for row in ship_details:
        shipment_url = f"{target_site_url}/api/resource/Shipment/{row['parent']}"

        shipment_response = requests.get(
            shipment_url,
            headers=headers
        )

        if shipment_response.status_code != 200:
            continue

        shipment = shipment_response.json().get("data", {})

        if not shipment.get("ata_date"):
            update_po_details(row["parent"])





@frappe.whitelist()
def update_po_details(ship):

    token = frappe.db.get_value(
        "Go Comet Settings",
        "Go Comet Settings",
        "token"
    )

    client_group_unique_id = frappe.db.get_value(
        "Go Comet Settings",
        "Go Comet Settings",
        "client_group_id"
    )

    target_site_url, api_key, api_secret = get_url_details()

    headers = {
        "Authorization": f"token {api_key}:{api_secret}"
    }


    # Get Shipment from remote site
    shipment_url = f"{target_site_url}/api/resource/Shipment/{ship}"

    shipment_response = requests.get(
        shipment_url,
        headers=headers
    )

    if shipment_response.status_code != 200:
        frappe.throw(f"Shipment {ship} not found on target site")

    shipment = shipment_response.json().get("data")


    if not shipment:
        frappe.msgprint(_("Shipment not found"))
        return


    # Child table data from Shipment response
    purchase_orders = shipment.get(
        "custom_shipment_po_wise",
        []
    )

    enquiry_details = shipment.get(
        "custom_go_comet_details",
        []
    )

    shipment_purchase_orders = shipment.get(
        "shipment_purchase_order",
        []
    )


    if not purchase_orders or not enquiry_details:
        frappe.msgprint(
            _("Missing required Shipment details.")
        )
        return


    enquiry_id = enquiry_details[0].get("enquiry_id")

    if not enquiry_id:
        frappe.msgprint(
            _("Enquiry ID is missing in Go Comet Details.")
        )
        return


    created_by = enquiry_details[0].get(
        "created_by",
        ""
    )


    undo_gocomet_milestone(
        token,
        enquiry_id,
        client_group_unique_id
    )


    url = (
        "https://workflow.gocomet.com/"
        "api/v1/integration/workflow/field-update"
    )


    params = {
        "token": token,
        "key": enquiry_id,
        "client_group_unique_id": client_group_unique_id
    }


    # Purchase order numbers
    po_lst = [
        row.get("purchase_order")
        for row in purchase_orders
        if row.get("purchase_order")
    ]

    po_data = ", ".join(po_lst)


    # Item categories
    category_list = []

    for row in shipment_purchase_orders:

        item_code = row.get("item_code")

        if item_code:

            item_url = (
                f"{target_site_url}/api/resource/"
                f"Item/{item_code}"
            )

            item_response = requests.get(
                item_url,
                headers=headers
            )

            if item_response.status_code == 200:

                item = item_response.json().get("data", {})

                item_category = item.get(
                    "items_category"
                )

                if (
                    item_category
                    and item_category not in category_list
                ):
                    category_list.append(item_category)


    category_data = ", ".join(category_list)


    qc_date_lifelong_ = ""

    shipment_inspection_date = shipment.get(
        "shipment_inspection_date"
    )


    if shipment_inspection_date:

        from frappe.utils import get_datetime

        qc_date_lifelong_ = get_datetime(
            shipment_inspection_date
        ).strftime("%d/%m/%Y")


    payload = {
        "fields_and_values": {

            "po_number_lifelong_": po_data,

            "qc_date_lifelong_": qc_date_lifelong_,

            "product_category_lifelong_": category_data,

            "shipment_of": created_by

        }
    }


    frappe.log_error(
        str(params),
        "GoComet URL Params"
    )

    frappe.log_error(
        json.dumps(payload),
        "GoComet Payload"
    )


    try:

        response = requests.put(
            url,
            headers={
                "Content-Type": "application/json"
            },
            params=params,
            json=payload,
            timeout=30
        )


        response.raise_for_status()


        frappe.msgprint(
            _(f"Successfully updated GoComet details: {response.text}")
        )


    except requests.exceptions.HTTPError:

        frappe.log_error(
            response.text,
            "GoComet Update Failed"
        )

        frappe.throw(
            _("GoComet update failed.")
        )


    except requests.exceptions.RequestException as e:

        frappe.log_error(
            str(e),
            "GoComet Request Error"
        )

        frappe.throw(
            _("Error communicating with GoComet.")
        )


def undo_gocomet_milestone(token, enquiry_id, client_group_unique_id):
	try:
		url = "https://workflow.gocomet.com/api/v1/integration/workflow/perform-action"
		params = {
			"token": token,
			"key": enquiry_id,
			"client_group_unique_id": client_group_unique_id,
			"milestone_id": "Pre Sailing",
			"checklist_id": 1,
			"action_type": "undo",
		}

		response = requests.put(url, data=params)
		if response:
			frappe.log_error("response_of_undo_changes", str(response.text))
			frappe.msgprint(_(f"Successfully updated GoComet details: {response.text}"))
		else:
			frappe.throw(_(f"Failed to update GoComet: {response.status_code} - {response.text}"))

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "GoComet API Error")
		frappe.throw(_("An error occurred while communicating with GoComet."))
