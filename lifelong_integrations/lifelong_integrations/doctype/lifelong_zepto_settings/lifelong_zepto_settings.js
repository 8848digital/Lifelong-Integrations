// Copyright (c) 2026, 8848 Digital LLP and contributors
// For license information, please see license.txt

frappe.ui.form.on("Lifelong Zepto Settings", {
	refresh(frm) {
		frm.add_custom_button("Get Zepto PO", () => {
			frappe.call({
				method: "lifelong_integrations.lifelong_integrations.doctype.lifelong_zepto_settings.api.get_zepto_po_events",
				callback() {
					frappe.msgprint("PO Sync Started in Background");
				},
			});
		});

		frm.add_custom_button("Create Zepto Quotations", () => {
			frappe.call({
				method: "lifelong_integrations.lifelong_integrations.doctype.lifelong_zepto_settings.api.create_zepto_quotations",
				callback() {
					frappe.msgprint("Creating Zepto Quotations...");
				},
			});
		});
	},
});