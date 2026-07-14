import frappe
import requests


import frappe
import requests
import json
from datetime import datetime
from frappe.utils import add_to_date


@frappe.whitelist()
def fetch_live_tracking_data():
    gocomet_doc = frappe.get_doc("Go Comet Settings", "Go Comet Settings")

    days = gocomet_doc.no_of_days_for_tracking_api or 0
    yesterday = add_to_date(datetime.now(), days=-days, as_string=True)

    url = (
        f"https://tracking.gocomet.com/api/v1/integrations/live-tracking"
        f"?token={gocomet_doc.token}&start_date={yesterday}"
    )

    headers = {
        "Authorization": gocomet_doc.token,
        "Content-Type": "application/json"
    }

    response = requests.get(url, headers=headers)

    try:
        res = response.json()

        for tracking in res.get("updated_trackings", []):
            reference_no = tracking.get("reference_no")

            if not reference_no:
                continue

            create_logs(str(tracking), reference_no)

            # Get target site details
            target_site_url, api_key, api_secret = get_url_details()

            shipment_url = (
                f"{target_site_url}/api/resource/Shipment/{reference_no}"
            )

            api_headers = {
                "Authorization": f"token {api_key}:{api_secret}",
                "Content-Type": "application/json"
            }

            # Fetch particular shipment from target site
            shipment_response = requests.get(
                shipment_url,
                headers=api_headers
            )

            if shipment_response.status_code != 200:
                continue

            shipment = shipment_response.json().get("data")

            if not shipment:
                continue


            # Update Shipment Item fields
            for evt in tracking.get("events", []):

                vessel_details = evt.get("vessel_details", {})

                for item in shipment.get("shipment_item", []):

                    item_update = {}

                    if vessel_details.get("vessel_name"):
                        item_update["custom_vessel_name"] = (
                            vessel_details["vessel_name"]
                        )

                    if vessel_details.get("voyage_num"):
                        item_update["custom_voyage_number"] = (
                            vessel_details["voyage_num"]
                        )

                    if item_update:
                        item_url = (
                            f"{target_site_url}/api/resource/"
                            f"Shipment Item/{item['name']}"
                        )

                        requests.put(
                            item_url,
                            headers=api_headers,
                            json=item_update
                        )


                event_type = evt.get("event")
                actual_date_str = evt.get("actual_date")


                # Update ATD Port Date
                if event_type == "trans_shipment_arrival" and actual_date_str:

                    atd_port_date = datetime.strptime(
                        actual_date_str,
                        "%d/%m/%Y"
                    ).strftime("%Y-%m-%d")


                    requests.put(
                        shipment_url,
                        headers=api_headers,
                        json={
                            "custom_atd_port_date": atd_port_date
                        }
                    )


                # Update ATA Date
                if event_type == "arrival" and actual_date_str:

                    ata_date = datetime.strptime(
                        actual_date_str,
                        "%d/%m/%Y"
                    ).strftime("%Y-%m-%d")


                    requests.put(
                        shipment_url,
                        headers=api_headers,
                        json={
                            "custom_ata_date": ata_date
                        }
                    )


        return res

    except json.JSONDecodeError:
        frappe.msgprint("Failed to decode response from GoComet API.")
        return response.text



def get_url_details():
    lifelong_settings = frappe.get_single("Lifelong Settings")

    if not lifelong_settings.target_site_url:
        frappe.throw("Live Site URL not configured in Lifelong Settings")

    if not lifelong_settings.target_site_user_api_key:
        frappe.throw("Live Site API Key not configured in Lifelong Settings")

    if not lifelong_settings.target_site_user_api_secret:
        frappe.throw("Live Site API Secret not configured in Lifelong Settings")

    target_site_url = lifelong_settings.target_site_url.rstrip("/")
    api_key = lifelong_settings.target_site_user_api_key
    api_secret = lifelong_settings.get_password(
        "target_site_user_api_secret"
    )

    return target_site_url, api_key, api_secret

