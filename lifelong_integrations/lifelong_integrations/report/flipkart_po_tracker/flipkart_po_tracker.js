// Copyright (c) 2026, 8848 Digital LLP and contributors
// For license information, please see license.txt

frappe.query_reports["Flipkart PO Tracker"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("Received From"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -7),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("Received To"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{ fieldname: "event_type", label: __("Event"), fieldtype: "Select", options: "\nPO_CREATE\nPO_EDIT" },
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "\nInitiated\nCreated\nEdit Applied\nEdit Review\nFailed\nCancelled",
		},
		{ fieldname: "ship_from_id", label: __("VSID (Ship From)"), fieldtype: "Data" },
		{ fieldname: "ship_to_id", label: __("Flipkart Warehouse"), fieldtype: "Data" },
		{
			fieldname: "ack_status",
			label: __("ACK Status"),
			fieldtype: "Select",
			options: "\nPending\nSent\nFailed\nNot Required",
		},
		{ fieldname: "only_ack_overdue", label: __("Only ACK Overdue"), fieldtype: "Check" },
	],
};
