// Copyright (c) 2026, 8848 Digital LLP and contributors
// For license information, please see license.txt

frappe.listview_settings["Decathlon Logs"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const colors = { Success: "green", Failed: "red", Skipped: "orange" };
		if (doc.status) {
			return [__(doc.status), colors[doc.status] || "gray", "status,=," + doc.status];
		}
	},
};
