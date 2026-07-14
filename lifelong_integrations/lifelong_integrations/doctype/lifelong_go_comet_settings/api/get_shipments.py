from datetime import datetime

import frappe
import requests
from frappe.utils import add_to_date, flt, now_datetime

from lifelong_integrations.lifelong_integrations.doctype.lifelong_gocomet_settings.api.get_workflow_data import (
	create_logs,
	get_charges,
	go_comet_details,
)


def get_url_details():
	""" Get target site details """"
	target_site_url = frappe.db.get_single_value(
		"Go Comet Settings", "target_site_url"
	)

	api_key = frappe.db.get_single_value(
		"Go Comet Settings", "target_site_user_api_key"
	)

	api_secret = frappe.db.get_single_value(
		"Go Comet Settings", "target_site_user_api_secret"
	)

	api_secret = frappe.get_doc(
		"Go Comet Settings"
	).get_password("target_site_user_api_secret")

	return target_site_url.rstrip("/"), api_key, api_secret



def target_get(doctype, params=None, name=None):

	target_site_url, api_key, api_secret = get_url_details()

	if name:
		url = f"{target_site_url}/api/resource/{doctype}/{name}"
	else:
		url = f"{target_site_url}/api/resource/{doctype}"


	headers = {
		"Authorization": f"token {api_key}:{api_secret}",
		"Content-Type": "application/json"
	}


	response = requests.get(
		url,
		headers=headers,
		params=params
	)

	response.raise_for_status()

	return response.json()



def get_shipments_data():
	"""
	Get Go Comet Details from target site
	"""

	no_of_days = frappe.db.get_single_value(
		"Go Comet Settings",
		"dispatch_days"
	)

	if not no_of_days:
		return []


	total_days = -1 * int(flt(no_of_days))

	from_datetime = add_to_date(
		now_datetime(),
		days=total_days
	)


	params = {

		"fields": frappe.as_json([
			"parent",
			"enquiry_id"
		]),

		"filters": frappe.as_json([
			[
				"enquiry_id",
				"!=",
				""
			],
			[
				"parenttype",
				"=",
				"Shipment"
			],
			[
				"creation",
				">=",
				from_datetime
			]
		]),

		"limit_page_length":0
	}


	response = target_get(
		"Go Comet Details",
		params
	)


	return response.get("data",[])




def update_shipments():

	"""
	Update shipment from GoComet workflow API
	"""

	shipments = get_shipments_data()


	if not shipments:
		return


	frappe.get_doc(
		{
			"doctype":"Gocomet Logs",
			"logs":frappe.as_json(shipments),
			"update_shipment":1
		}
	).insert(ignore_permissions=True)



	token = frappe.db.get_single_value(
		"Go Comet Settings",
		"token"
	)

	client_group_id = frappe.db.get_single_value(
		"Go Comet Settings",
		"client_group_id"
	)



	for ship in shipments:


		shipment = ship.get("parent")

		enquiry_id = ship.get("enquiry_id")


		if not enquiry_id:
			continue



		url = (
			f"https://workflow.gocomet.com/api/v1/integration/workflow/"
			f"{enquiry_id}"
			f"?token={token}"
			f"&client_group_unique_id={client_group_id}"
		)


		try:

			response = requests.get(url)

			response.raise_for_status()

			data = response.json()



			if data:


				create_logs(
					str(data),
					shipment
				)


				go_comet_details(
					data.get("milestones",[]),
					shipment
				)



				# stakeholders update
				freight_forwarder = ""
				cha = ""


				for milestone in data.get("milestones",[]):

					for checklist in milestone.get(
						"checklists",
						[]
					):

						for stakeholder in checklist.get(
							"responsible_stakeholder",
							[]
						):

							companies = checklist.get(
								"responsible_companies",
								[]
							)


							if companies:

								if stakeholder.get("name")=="FF":

									freight_forwarder = (
										companies[0].get("name")
									)


								if stakeholder.get("name")=="CHA":

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

			frappe.log_error(
				str(e),
				"GoComet API Error"
			)

			frappe.msgprint(
				f"API request failed: {str(e)}"
			)