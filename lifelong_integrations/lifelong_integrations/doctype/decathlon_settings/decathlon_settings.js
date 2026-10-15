// Copyright (c) 2026, 8848 Digital LLP and contributors
// For license information, please see license.txt

frappe.ui.form.on("Decathlon Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Get Orders"), function () {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save the settings before getting orders."));
				return;
			}
			frm.trigger("get_orders");
		}).addClass("btn-primary");
	},
	get_orders(frm) {
		frappe.call({
			method: "lifelong_integrations.lifelong_integrations.api.decathlon_api.get_orders.get_orders",
			args: {},
			freeze: true,
			freeze_message: __("Getting orders from Decathlon..."),
			callback: function (r) {
				if (r.message && r.message.summary) {
					frappe.msgprint({
						title: __("Decathlon Orders"),
						message: r.message.summary,
						indicator: r.message.push_skipped ? "orange" : "green",
					});
				}
			},
		});
	},
});
