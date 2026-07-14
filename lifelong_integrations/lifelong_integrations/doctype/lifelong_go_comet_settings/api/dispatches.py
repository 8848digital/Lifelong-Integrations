import frappe



import json
import requests
import frappe
from frappe.utils import add_to_date, now_datetime, flt
from lifelong_integrations.lifelong_integrations.doctype.lifelong_gocomet_settings.api.get_workflow_data import (
	create_logs,
	get_charges,
	go_comet_details,
)


def create_gocomet_log(
    api=None, method=None, status=None, logs=None, exception=None, shipment_id=None
):
    traceback = frappe.get_traceback(with_context=True)

    log = frappe.new_doc("Gocomet Logs")

    if isinstance(logs, dict):
        logs = json.dumps(logs, indent=4)

    log.update(
        {
            "api": api,
            "method": json.dumps(method, indent=4) if method else "",
            "logs": logs,
            "traceback": str(exception) + "\n\n" + str(traceback)
            if exception
            else "",
            "shipment_id": shipment_id,
            "status": status,
        }
    )

    log.flags.ignore_permissions = True
    log.insert(ignore_permissions=True)


def get_url_details():
    settings = frappe.get_doc("Go Comet Settings")

    return (
        settings.target_site_url.rstrip("/"),
        settings.target_site_user_api_key,
        settings.get_password("target_site_user_api_secret"),
    )


def get_shipments_data():
    """
    Fetch Shipment/Go Comet Details from another site.
    """

    dispatch_days = frappe.db.get_single_value(
        "Go Comet Settings", "dispatch_days"
    )

    if not dispatch_days:
        return []

    from_datetime = add_to_date(
        now_datetime(),
        days=-int(flt(dispatch_days)),
    )

    target_site_url, api_key, api_secret = get_url_details()

    url = f"{target_site_url}/api/method/your_app.api.get_shipments"

    headers = {
        "Authorization": f"token {api_key}:{api_secret}"
    }

    params = {
        "from_datetime": str(from_datetime)
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=60,
        )

        response.raise_for_status()

        return response.json().get("message", [])

    except Exception as e:
        create_gocomet_log(
            api=url,
            method=params,
            status="Failed",
            exception=e,
        )
        return []


def fetch_shipments_from_go_comet_to_update_lcv():
    shipments = get_shipments_data()

    if not shipments:
        return

    for row in shipments:

        shipment = row["parent"]
        enquiry_id = row["enquiry_id"]

        token = frappe.db.get_single_value(
            "Go Comet Settings", "token"
        )

        client_group_id = frappe.db.get_single_value(
            "Go Comet Settings", "client_group_id"
        )

        url = (
            f"https://workflow.gocomet.com/api/v1/integration/workflow/"
            f"{enquiry_id}?token={token}"
            f"&client_group_unique_id={client_group_id}"
        )

        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()

            data = response.json()

            if not data:
                continue

            create_logs(str(data), shipment)

            go_comet_details(
                data.get("milestones", []),
                shipment,
            )

            freight_forwarder = ""
            cha = ""

            for milestone in data.get("milestones", []):

                for checklist in milestone.get("checklists", []):

                    for stakeholder in checklist.get(
                        "responsible_stakeholder", []
                    ):

                        company = ""

                        if checklist.get("responsible_companies"):
                            company = checklist["responsible_companies"][0].get(
                                "name"
                            )

                        if stakeholder.get("name") == "FF":
                            freight_forwarder = company

                        elif stakeholder.get("name") == "CHA":
                            cha = company

            get_charges(
                freight_forwarder,
                cha,
                shipment,
            )

        except Exception as e:
            create_gocomet_log(
                api=url,
                shipment_id=shipment,
                status="Failed",
                exception=e,
            )