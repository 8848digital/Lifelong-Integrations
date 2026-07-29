import copy
import json

import frappe
import requests

from lifelong_integrations.lifelong_integrations.api.live_site_api import \
    live_site_connection
from lifelong_integrations.lifelong_integrations.doctype.freshdesk_api_log.freshdesk_api_log import \
    freshdesk_log
from lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.freshdesk_settings import \
    get_merged_freshdesk_settings

LIVE_MODULE = "freshdesk_integration.freshdesk_integration.doctype.freshdesk_integration.utility_functions.update_category"


def get_category_list():
	"""Fetch the category -> sub-category -> model dict from live site."""
	base_url, headers = live_site_connection()
	url = f"{base_url}/api/method/{LIVE_MODULE}.get_category_list_api"
	resp = requests.get(url, headers=headers, timeout=60)
	resp.raise_for_status()
	return resp.json().get("message") or {}


def remove_modified_choices(category_list, fd_choices, result):
	"""Mark existing Freshdesk choices no longer present in the ERP category list as deleted, appending them to result."""
	for level1 in fd_choices:
		if level1.get("value") not in category_list:
			found = False
			for r1 in result:
				if r1.get("value") == level1.get("value"):
					r1["deleted"] = True
					r1["choices"] = []
					found = True
			if not found:
				level1["deleted"] = True
				level1["choices"] = []
				result.append(level1)
			continue
		if level1.get("choices"):
			for level2 in level1["choices"]:
				if level2.get("value") not in category_list[level1["value"]]:
					found = False
					for r1 in result:
						if r1.get("value") == level1.get("value"):
							if r1.get("choices"):
								for r2 in r1["choices"]:
									if r2.get("value") == level2.get("value"):
										r2["deleted"] = True
										r2["choices"] = []
										found = True
							if not found:
								new_l2_choice = copy.copy(level2)
								new_l2_choice["deleted"] = True
								new_l2_choice["choices"] = []
								r1["choices"].append(new_l2_choice)
								found = True
					if not found:
						new_l1_choice = copy.copy(level1)
						new_l2_choice = copy.copy(level2)
						new_l2_choice["deleted"] = True
						new_l2_choice["choices"] = []

						new_l1_choice["choices"] = [new_l2_choice]
						result.append(new_l1_choice)
					continue
				if level2.get("choices"):
					for level3 in level2["choices"]:
						if level3.get("value") not in category_list[level1["value"]][level2["value"]]:
							found = False
							for r1 in result:
								if r1.get("value") == level1.get("value"):
									if r1.get("choices"):
										for r2 in r1["choices"]:
											if r2.get("value") == level2.get("value"):
												if r2.get("choices"):
													for r3 in r2["choices"]:
														if r3.get("value") == level3.get("value"):
															r3["deleted"] = True
															r3["choices"] = []
															found = True
													if not found:
														new_l3_choice = copy.copy(level3)
														new_l3_choice["deleted"] = True
														new_l3_choice["choices"] = []
														r2["choices"].append(new_l3_choice)
														found = True
							if not found:
								new_l1_choice = copy.copy(level1)
								new_l2_choice = copy.copy(level2)
								new_l3_choice = copy.copy(level3)
								new_l3_choice["deleted"] = True
								new_l3_choice["choices"] = []
								new_l2_choice["choices"] = [new_l3_choice]
								new_l1_choice["choices"] = [new_l2_choice]
								result.append(new_l1_choice)
	return result


def get_category_list_in_freshdesk_format(choices):
	"""Merge the ERP category/sub-category/model list into the existing Freshdesk ticket field choices (3-level nested dropdown), preserving unchanged entries and marking removed/modified ones."""
	category_list = get_category_list()
	result = []
	level1_value_wise_choices = {}
	for row1 in choices:
		row = copy.copy(row1)
		if row.get("value"):
			del row["choices"]
			level1_value_wise_choices.setdefault(row["value"], row)
	level2_value_wise_choices = {}
	for level1_row in choices:
		if level1_row.get("choices"):
			for row1 in level1_row["choices"]:
				row = copy.copy(row1)
				del row["choices"]
				level2_value_wise_choices.setdefault(
					f"""{level1_row["value"]}-{row["value"]}""", row
				)
	level3_value_wise_choices = {}
	for level1_row in choices:
		if level1_row.get("choices"):
			for level2_row in level1_row["choices"]:
				if level2_row.get("choices"):
					for row1 in level2_row["choices"]:
						row = copy.copy(row1)
						del row["choices"]
						level3_value_wise_choices.setdefault(
							f"""{level1_row["value"]}-{level2_row["value"]}""", {}
						)
						level3_value_wise_choices[f"""{level1_row["value"]}-{level2_row["value"]}"""][
							row1["value"]
						] = row1

	level1_pos = 1
	for category in category_list:
		choice = {}
		level1_modified = False
		if level1_value_wise_choices.get(category):
			choice = copy.copy(level1_value_wise_choices[category])
			choice["choices"] = []
		else:
			level1_modified = True
			choice = {
				"label": category,
				"value": category,
			}
			choice["choices"] = []
		choice["position"] = level1_pos
		level1_pos += 1
		level2_pos = 1
		for sub_category in category_list[category]:
			level2_modified = False
			if level2_value_wise_choices.get(f"""{category}-{sub_category}"""):
				choice["choices"].append(
					level2_value_wise_choices[f"""{category}-{sub_category}"""]
				)
				level2_choice = choice["choices"][-1]
				level2_choice["choices"] = []
			else:
				level2_modified = True
				choice["choices"].append(
					{
						"label": sub_category,
						"value": sub_category,
					}
				)
				level2_choice = choice["choices"][-1]
				level2_choice["choices"] = []
			level2_choice["position"] = level2_pos
			level2_pos += 1
			level3_pos = 1
			level3_modified = False
			for modal in category_list[category][sub_category]:

				if level3_value_wise_choices.get(
					f"""{category}-{sub_category}"""
				) and level3_value_wise_choices.get(
					f"""{category}-{sub_category}"""
				).get(
					modal
				):
					level2_choice["choices"].append(
						level3_value_wise_choices[f"""{category}-{sub_category}"""][modal]
					)
				else:
					level3_modified = True
					level2_choice["choices"].append(
						{
							"label": modal,
							"value": modal,
						}
					)
				level2_choice["choices"][-1]["position"] = level3_pos
				level3_pos += 1
			if level1_modified or level2_modified or level3_modified:
				if choice not in result:
					result.append(choice)

	result = remove_modified_choices(
		category_list=category_list, fd_choices=choices, result=result
	)
	return result


def update_category_list_in_freshdesk(freshdesk=None):
	"""Sync the ERP Category/Sub Category/Model list into the configured Freshdesk ticket field(s) as dropdown choices."""
	# Update ERP Category/ERP Sub Category/ERP Model
	if not freshdesk:
		freshdesk = get_merged_freshdesk_settings()
	if not freshdesk.get("enable") or not freshdesk.get("update_category"):
		return
	headers = {"Content-Type": "application/json"}
	field_id = freshdesk.get("erp_category_field_id") or ""
	if field_id:
		field_id = list(map(lambda x: x.strip(), field_id.split(",")))
	for id in field_id:
		if not id:
			continue
		try:
			endpoint = f"""{freshdesk.get("host")}/api/v2/admin/ticket_fields/{id}"""
			res = requests.get(endpoint, headers=headers, auth=(freshdesk.get("api_key"), "X"))
			if res.content and res.status_code in range(200, 300):
				field_data = res.json()
				freshdesk_log(
					response=res, api="Get Ticket Field", message=field_data, endpoint=endpoint
				)
				choices = field_data.get("choices")
				result = get_category_list_in_freshdesk_format(choices)
				result = {"choices": result}
				put_res = requests.put(
					endpoint,
					headers=headers,
					auth=(freshdesk.get("api_key"), "X"),
					data=json.dumps(result),
				)
				freshdesk_log(
					response=put_res,
					api="Update Category Choices",
					endpoint=endpoint,
					request_data=result,
				)
			else:
				freshdesk_log(response=res, api="Get Ticket Field", endpoint=endpoint)
		except Exception:
			freshdesk_log(api="Update Category Choices")
