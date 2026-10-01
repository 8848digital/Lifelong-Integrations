// Copyright (c) 2026, 8848 Digital LLP and contributors
// For license information, please see license.txt

frappe.ui.form.on("Decathlon Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Get Orders"), function () {
			frm.trigger("get_orders");
		}).addClass("btn-primary");
	},
	get_orders(frm) {
		frappe.call({
			method: "lifelong_integrations.lifelong_integrations.api.decathlon_api.get_orders.get_orders",
			args: {},
			freeze: true,
			callback: function (r) {
				// frm.reload_doc();
			},
		});
	},
});
