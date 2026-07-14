import json
from datetime import date, datetime, time, timedelta

import frappe
import requests
from frappe import _
from frappe.utils import flt, add_days


def get_remote_site_details():
    settings = frappe.get_single("Lifelong Settings")

    if not settings.target_site_url:
        frappe.throw("Target site URL not configured")

    if not settings.target_site_user_api_key:
        frappe.throw("Target site API key not configured")

    if not settings.target_site_user_api_secret:
        frappe.throw("Target site API secret not configured")

    return (
        settings.target_site_url.rstrip("/"),
        settings.target_site_user_api_key,
        settings.get_password("target_site_user_api_secret"),
    )


def get_remote_headers():
    target_site_url, api_key, api_secret = get_remote_site_details()

    return (
        target_site_url,
        {
            "Authorization": f"token {api_key}:{api_secret}",
            "Content-Type": "application/json",
        },
    )


def get_remote_doc(doctype, name):
    target_site_url, headers = get_remote_headers()

    url = f"{target_site_url}/api/resource/{doctype}/{name}"

    response = requests.get(
        url,
        headers=headers,
        timeout=30,
    )

    response.raise_for_status()

    return response.json().get("data")


def update_remote_doc(doctype, name, data):
    target_site_url, headers = get_remote_headers()

    url = f"{target_site_url}/api/resource/{doctype}/{name}"

    response = requests.put(
        url,
        headers=headers,
        json=data,
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


def create_remote_doc(doctype, data):
    target_site_url, headers = get_remote_headers()

    url = f"{target_site_url}/api/resource/{doctype}"

    response = requests.post(
        url,
        headers=headers,
        json=data,
        timeout=30,
    )

    response.raise_for_status()

    return response.json()

@frappe.whitelist()
def get_workflow_data(shipment):

    shipment_doc = get_remote_doc(
        "Shipment",
        shipment
    )

    if not shipment_doc:
        frappe.throw(
            f"Shipment {shipment} not found"
        )


    go_comet_details = shipment_doc.get(
        "custom_go_comet_details",
        []
    )


    if not go_comet_details:
        frappe.msgprint(
            _("Go Comet Details missing")
        )
        return


    enquiry_id = go_comet_details[0].get(
        "enquiry_id"
    )


    if not enquiry_id:
        frappe.msgprint(
            _("Enquiry ID missing")
        )
        return


    token = frappe.db.get_single_value(
        "Go Comet Settings",
        "token"
    )

    client_group_id = frappe.db.get_single_value(
        "Go Comet Settings",
        "client_group_id"
    )


    url = (
        f"https://workflow.gocomet.com/"
        f"api/v1/integration/workflow/"
        f"{enquiry_id}"
        f"?token={token}"
        f"&client_group_unique_id={client_group_id}"
    )


    try:

        response = requests.get(
            url,
            timeout=30
        )

        response.raise_for_status()

        data = response.json()


        if data:

            create_logs(
                str(data),
                shipment
            )


            go_comet_details_update(
                data.get("milestones", []),
                shipment
            )


            freight_forwarder = ""
            cha = ""


            for milestone in data.get("milestones", []):

                for checklist in milestone.get(
                    "checklists",
                    []
                ):

                    stakeholders = checklist.get(
                        "responsible_stakeholder",
                        []
                    )


                    companies = checklist.get(
                        "responsible_companies",
                        []
                    )


                    for stakeholder in stakeholders:

                        if (
                            stakeholder.get("name") == "FF"
                            and companies
                        ):
                            freight_forwarder = (
                                companies[0].get("name")
                            )


                        if (
                            stakeholder.get("name") == "CHA"
                            and companies
                        ):
                            cha = (
                                companies[0].get("name")
                            )


            get_charges(
                freight_forwarder,
                cha,
                shipment
            )


        return data


    except requests.exceptions.RequestException as e:

        frappe.msgprint(
            f"API request failed: {str(e)}"
        )

    except Exception:

        frappe.log_error(
            frappe.get_traceback(),
            "GoComet Workflow Error"
        )


def get_charges(freight_forwarder, cha, shipment):
    """
    Update CHA and Freight Forwarder in remote Shipment
    """

    update_data = {}

    # Update CHA
    if cha:

        expense_accounts = frappe.get_all(
            "Go Comet Vendor Type Expense Account Mapping",
            filters={
                "vendor_type": "CHA"
            },
            fields=[
                "expense_account"
            ],
        )

        if (
            expense_accounts
            and expense_accounts[0].get("expense_account")
        ):
            update_data["custom_cha"] = cha


    # Update Freight Forwarder
    if freight_forwarder:

        expense_accounts = frappe.get_all(
            "Go Comet Vendor Type Expense Account Mapping",
            filters={
                "vendor_type": "Freight Forwarder"
            },
            fields=[
                "expense_account"
            ],
        )

        if (
            expense_accounts
            and expense_accounts[0].get("expense_account")
        ):
            update_data["custom_freight_forward"] = freight_forwarder


    # Update remote Shipment using REST API
    if update_data:

        target_site_url, api_key, api_secret = get_url_details()

        url = (
            f"{target_site_url}/api/resource/"
            f"Shipment/{shipment}"
        )

        headers = {
            "Authorization": f"token {api_key}:{api_secret}",
            "Content-Type": "application/json",
        }


        response = requests.put(
            url,
            headers=headers,
            json=update_data,
            timeout=30
        )


        if response.status_code != 200:
            frappe.log_error(
                response.text,
                "Remote Shipment Update Failed"
            )

            frappe.throw(
                "Failed to update Shipment on target site"
            )


        frappe.log_error(
            json.dumps(update_data),
            "Remote Shipment Charge Update"
        )


def update_gocomet_details_in_ship():

    token = frappe.db.get_single_value(
        "Go Comet Settings",
        "token"
    )

    client_group_id = frappe.db.get_single_value(
        "Go Comet Settings",
        "client_group_id"
    )


    no_of_days = frappe.db.get_single_value(
        "Go Comet Settings",
        "no_of_days"
    )


    start_date = date.today() - timedelta(
        days=int(no_of_days)
    )

    start_datetime = datetime.combine(
        start_date,
        time.min
    )

    start_datetime_str = start_datetime.strftime(
        "%Y-%m-%d %H:%M:%S"
    )


    # Get remote site details
    target_site_url, api_key, api_secret = get_url_details()

    headers = {
        "Authorization": f"token {api_key}:{api_secret}",
        "Content-Type": "application/json"
    }


    # Fetch Go Comet Details from remote site
    url = f"{target_site_url}/api/resource/Go Comet Details"


    params = {
        "fields": json.dumps(
            [
                "name",
                "parent",
                "enquiry_id"
            ]
        ),

        "filters": json.dumps(
            [
                [
                    "enquiry_id",
                    "!=",
                    ""
                ],
                [
                    "creation",
                    ">=",
                    start_datetime_str
                ]
            ]
        ),

        "limit_page_length": 0
    }


    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=30
    )


    response.raise_for_status()


    shipments = response.json().get(
        "data",
        []
    )


    for shipment_data in shipments:

        enquiry_id = shipment_data.get(
            "enquiry_id"
        )

        shipment = shipment_data.get(
            "parent"
        )


        if not enquiry_id or not shipment:
            continue


        workflow_url = (
            "https://workflow.gocomet.com/"
            f"api/v1/integration/workflow/"
            f"{enquiry_id}"
            f"?token={token}"
            f"&client_group_unique_id={client_group_id}"
        )


        try:

            workflow_response = requests.get(
                workflow_url,
                timeout=30
            )

            workflow_response.raise_for_status()


            data = workflow_response.json()


            if data:

                create_logs(
                    str(data),
                    shipment
                )


                go_comet_details(
                    data.get("milestones", []),
                    shipment
                )


                freight_forwarder = ""
                cha = ""


                for milestone in data.get(
                    "milestones",
                    []
                ):

                    for checklist in milestone.get(
                        "checklists",
                        []
                    ):


                        stakeholders = checklist.get(
                            "responsible_stakeholder",
                            []
                        )

                        companies = checklist.get(
                            "responsible_companies",
                            []
                        )


                        for stake in stakeholders:

                            if (
                                stake.get("name") == "FF"
                                and companies
                            ):

                                freight_forwarder = (
                                    companies[0].get("name")
                                )


                            if (
                                stake.get("name") == "CHA"
                                and companies
                            ):

                                cha = (
                                    companies[0].get("name")
                                )


                # Updates remote Shipment
                get_charges(
                    freight_forwarder,
                    cha,
                    shipment
                )


        except requests.exceptions.RequestException as e:

            frappe.log_error(
                str(e),
                "GoComet Workflow API Error"
            )


        except Exception:

            frappe.log_error(
                frappe.get_traceback(),
                "GoComet Shipment Update Error"
            )


def create_logs(response, shipment_id):
	doc = frappe.get_doc(
		{"doctype": "Gocomet Logs", "shipment_id": shipment_id, "logs": response, "update_shipment": 1}
	)
	doc.insert()




def go_comet_details(milestones, shipment):
	"""Process GoComet shipment milestones to update shipment details,
	including transit status, pre-sailing data, and provisional charges."""
	for milestone in milestones:
		# Handle "In Transit" milestone — update shipment tracking or status
		if milestone.get("id") == "In Transit":
			process_in_transit_milestone(milestone, shipment)
		# Handle "Pre Sailing" milestone — update shipment before vessel departure
		elif milestone.get("id") == "Pre Sailing":
			process_pre_sailing_milestone(milestone, shipment)
		# Handle "Provisional Invoice Charges" milestone — add LCV details
		if milestone.get("id") == "Provisional Invoice Charges":
			provisional_charges(milestone, shipment)


def process_in_transit_milestone(milestone, shipment):

    shipment_doc = get_remote_doc(
        "Shipment",
        shipment
    )

    ship_items = shipment_doc.get(
        "shipment_item",
        []
    )

    go_comet_details = [
        row for row in shipment_doc.get(
            "custom_go_comet_details",
            []
        )
        if row.get("mode") in ["fcl", "lcl", "air"]
    ]


    for checklist in milestone.get("checklists", []):

        if checklist.get("form_list"):

            for section in checklist["form_list"]:

                for row in section:

                    for item in row:

                        item_id = item.get("id")
                        value = item.get("value")


                        # Shipping Line
                        if item_id == "carrier_line_ocean":

                            update_remote_doc(
                                "Shipment",
                                shipment,
                                {
                                    "custom_shipping_line": value
                                }
                            )


                        # Container Number
                        if item_id == "tracking_number_ocean" and value:

                            for ship_item in ship_items:

                                update_remote_doc(
                                    "Shipment Item",
                                    ship_item["name"],
                                    {
                                        "container_no": value
                                    }
                                )


                        # BL Date
                        if (
                            item_id == "bl_date_lifelong__1"
                            and value
                        ):

                            raw_date = str(value).strip()

                            bl_date = None

                            for fmt in (
                                "%d-%b-%Y",
                                "%d/%m/%Y"
                            ):

                                try:

                                    bl_date = datetime.strptime(
                                        raw_date,
                                        fmt
                                    ).date().isoformat()

                                    break

                                except ValueError:
                                    continue


                            if bl_date:

                                update_remote_doc(
                                    "Shipment",
                                    shipment,
                                    {
                                        "custom_bl_date": bl_date
                                    }
                                )

                            else:

                                frappe.log_error(
                                    f"Invalid date format: {raw_date}",
                                    "BL Date Parsing Error"
                                )


                        # GoComet CBM update
                        if (
                            go_comet_details
                            and "cbm_lifelong" in str(item_id)
                            and value
                        ):

                            update_remote_doc(
                                "Go Comet Details",
                                go_comet_details[0]["name"],
                                {
                                    "gocomet_cbm": value
                                }
                            )


                        # Container number alternative field
                        if (
                            item_id
                            == "container_numbers__please_mention_all_container_numbers__"
                            and value
                        ):

                            for ship_item in ship_items:

                                update_remote_doc(
                                    "Shipment Item",
                                    ship_item["name"],
                                    {
                                        "container_no": value
                                    }
                                )


        # ETA / ATA / ATD checklist
        if checklist.get("id") == 6:

            for section in checklist.get(
                "form_list",
                []
            ):

                for row in section:

                    for item in row:

                        item_id = item.get("id")
                        value = item.get("value")


                        field_map = {
                            "eta": "eta_date",
                            "ata": "ata_date",
                            "atd": "atd_date"
                        }


                        if item_id in field_map:

                            date_value = None


                            if value:

                                date_value = datetime.strptime(
                                    str(value),
                                    "%d/%m/%Y %H:%M"
                                ).date().isoformat()


                            update_remote_doc(
                                "Shipment",
                                shipment,
                                {
                                    field_map[item_id]: date_value
                                }
                            )


            # If this function also uses local Shipment,
            # convert set_ata_atd_eta_date() separately
            set_ata_atd_eta_date(shipment)



def set_ata_atd_eta_date(shipment_id):

    shipment = get_remote_doc(
        "Shipment",
        shipment_id
    )

    dates = frappe._dict({
        "ata_date": shipment.get("ata_date"),
        "atd_date": shipment.get("atd_date"),
        "eta_date": shipment.get("eta_date"),
    })


    set_warehouse_arrival_time(
        shipment_id,
        dates
    )


def set_warehouse_arrival_time(shipment_id, dates):

    # ETA WH = if ATA=null, ETA+3, ATA+3

    if dates.eta_date and not dates.ata_date:

        expected_time = add_days(
            dates.eta_date,
            3
        )

    elif dates.ata_date:

        expected_time = add_days(
            dates.ata_date,
            3
        )

    else:

        expected_time = None


    update_remote_doc(
        "Shipment",
        shipment_id,
        {
            "expected_time_of_arrival_in_wh_": expected_time
        }
    )


def process_pre_sailing_milestone(milestone, shipment):

    for checklist in milestone.get("checklists", []):

        if checklist.get("id") == 3 and checklist.get("form_list"):

            for section in checklist["form_list"]:

                for row in section:

                    for item in row:

                        item_id = item.get("id")
                        value = item.get("value")


                        if item_id == "bl_number_lifelong_":

                            update_remote_doc(
                                "Shipment",
                                shipment,
                                {
                                    "bl_no": value
                                }
                            )


                        elif item_id == "bl_date_lifelong_":

                            if value:

                                bl_date = datetime.strptime(
                                    value,
                                    "%d/%m/%Y"
                                ).strftime(
                                    "%Y-%m-%d"
                                )


                                update_remote_doc(
                                    "Shipment",
                                    shipment,
                                    {
                                        "custom_bl_date": bl_date
                                    }
                                )


def add_lcv_details(
    provisional_charges_ff,
    provisional_charges_cha,
    shipment
):

    shipment_doc = get_remote_doc(
        "Shipment",
        shipment
    )


    existing_lcv = shipment_doc.get(
        "lcv_details",
        []
    )


    descriptions = [
        row.get("description")
        for row in existing_lcv
        if row.get("description")
    ]


    # Freight Forwarder Charges
    if (
        provisional_charges_ff
        and "Provisional charges FF" not in descriptions
    ):

        vendor_mapping = frappe.get_all(
            "Go Comet Vendor Type Expense Account Mapping",
            filters={
                "vendor_type": "Freight Forwarder"
            },
            fields=[
                "expense_account"
            ],
        )


        if vendor_mapping:

            create_remote_doc(
                "LCV Details",
                {
                    "parent": shipment,
                    "parenttype": "Shipment",
                    "parentfield": "lcv_details",
                    "expense_account": vendor_mapping[0]["expense_account"],
                    "amount": provisional_charges_ff,
                    "description": "Provisional charges FF"
                }
            )


    # CHA Charges
    if (
        provisional_charges_cha
        and "Provisional charges CHA" not in descriptions
    ):

        vendor_mapping_cha = frappe.get_all(
            "Go Comet Vendor Type Expense Account Mapping",
            filters={
                "vendor_type": "CHA"
            },
            fields=[
                "expense_account"
            ],
        )


        if vendor_mapping_cha:

            create_remote_doc(
                "LCV Details",
                {
                    "parent": shipment,
                    "parenttype": "Shipment",
                    "parentfield": "lcv_details",
                    "expense_account": vendor_mapping_cha[0]["expense_account"],
                    "amount": provisional_charges_cha,
                    "description": "Provisional charges CHA"
                }
            )

def provisional_charges(milestone, shipment):
	"""Extract and total provisional charges (FF & CHA) from milestone checklists,
	then add them as LCV Details to the given Shipment."""
	for checklist in milestone.get("checklists", []):
		provisional_charges_ff = 0
		provisional_charges_cha = 0
		# Sum all values for Freight Forwarder (FF) provisional charges
		if "Provisional Charges FF" in checklist.get("name"):
			for sec in checklist["form_list"]:
				for ff in sec:
					for i in ff:
						if i.get("value"):
							provisional_charges_ff = provisional_charges_ff + flt(i.get("value"))
		# Sum all values for CHA provisional charges
		if "Provisional Charges CHA" in checklist.get("name"):
			for sect in checklist["form_list"]:
				for cha in sect:
					for i in cha:
						if i.get("value"):
							provisional_charges_cha = provisional_charges_cha + flt(i.get("value"))
		# If any provisional charges exist, add them to the Shipment's LCV details
		if provisional_charges_ff or provisional_charges_cha:

			add_lcv_details(provisional_charges_ff, provisional_charges_cha, shipment)