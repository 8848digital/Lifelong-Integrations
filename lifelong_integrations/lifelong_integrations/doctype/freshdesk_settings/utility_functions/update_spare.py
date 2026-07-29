import copy
import json

import frappe
import requests

from lifelong_integrations.lifelong_integrations.api.live_site_api import \
    remote_get_list
from lifelong_integrations.lifelong_integrations.doctype.freshdesk_api_log.freshdesk_api_log import \
    freshdesk_log
from lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.freshdesk_settings import \
    get_merged_freshdesk_settings


def get_spare_list():
	"""Return a mapping of each Spare to its list of Spare Items, fetched from live site."""
	spare_items = remote_get_list("Spare Item", fields=["spare_item", "parent as spare"])

	spare_list = {}
	for row in spare_items:
		if not row.get("spare") or not row.get("spare_item"):
			continue
		spare_list.setdefault(row["spare"], [])
		spare_list[row["spare"]].append(row["spare_item"])

	return spare_list


def get_spare_list_in_freshdesk_format(choices):
	"""Merge the ERP spare/item list into the existing Freshdesk ticket field choices (3-level nested dropdown), preserving unchanged entries and flagging modified ones."""
	spare_list = get_spare_list()
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

	for spare in spare_list:
		choice = {}
		level1_modified = False
		level1_pos = 1
		if level1_value_wise_choices.get(spare):
			choice = copy.copy(level1_value_wise_choices[spare])
			choice["choices"] = []
		else:
			level1_modified = True
			choice = {
				"label": spare,
				"value": spare,
			}
			choice["choices"] = []
		choice["position"] = level1_pos
		level1_pos += 1
		for item in spare_list[spare]:
			level2_pos = 1
			level2_modified = False
			if level2_value_wise_choices.get(f"""{spare}-{item}"""):
				choice["choices"].append(level2_value_wise_choices[f"""{spare}-{item}"""])
				level2_choice = choice["choices"][-1]
				level2_choice["choices"] = []
			else:
				level2_modified = True
				choice["choices"].append(
					{
						"label": item,
						"value": item,
					}
				)
				level2_choice = choice["choices"][-1]
				level2_choice["choices"] = []
			level2_choice["position"] = level2_pos
			level2_pos += 1
			level3_modified = False
			for i in range(1, 11):
				if level3_value_wise_choices.get(
					f"""{spare}-{item}"""
				) and level3_value_wise_choices.get(f"""{spare}-{item}""").get(str(i)):
					level2_choice["choices"].append(
						level3_value_wise_choices[f"""{spare}-{item}"""][str(i)]
					)
				else:
					level3_modified = True
					level2_choice["choices"].append(
						{
							"label": str(i),
							"position": i,
							"value": str(i),
						}
					)
			if level1_modified or level2_modified or level3_modified:
				if choice not in result:
					result.append(choice)
	return result


def update_spare_list_in_ticket_field(freshdesk=None):
	"""Sync the ERP spare/item list into the configured Freshdesk ticket field(s) as dropdown choices."""
	if not freshdesk:
		freshdesk = get_merged_freshdesk_settings()
	if not freshdesk.get("enable") or not freshdesk.get("update_spare_items"):
		return
	headers = {"Content-Type": "application/json"}
	fields_id = freshdesk.get("spare_fields_id") or ""
	if fields_id:
		fields_id = list(map(lambda x: x.strip(), fields_id.split(",")))
	for id in fields_id:
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
				result = get_spare_list_in_freshdesk_format(choices)
				result = {"choices": result}
				put_res = requests.put(
					endpoint,
					headers=headers,
					auth=(freshdesk.get("api_key"), "X"),
					data=json.dumps(result),
				)
				freshdesk_log(
					response=put_res,
					api="Update Spare Choices",
					endpoint=endpoint,
					request_data=result,
				)
			else:
				freshdesk_log(response=res, api="Get Ticket Field", endpoint=endpoint)
		except Exception:
			freshdesk_log(api="Update Spare Choices")
