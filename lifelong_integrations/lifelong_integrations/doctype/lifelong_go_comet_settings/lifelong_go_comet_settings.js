// Copyright (c) 2025, 8848 Digital LLP and contributors
// For license information, please see license.txt

frappe.ui.form.on("Lifelong Go Comet Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Generate Token"), () => {
			generate_token(frm.doc);
		});
		// frm.add_custom_button(__("Create Gocomet Shipment"), () => {
		// 	create_go_comet_shipment(frm.doc);
		// });
		frm.add_custom_button(__("Fetch Tracking Data"), () => {
			fetch_live_tracking_data(frm.doc);
		});
		// frm.add_custom_button(__("Create PO"), () => {
		// 	create_po(frm.doc);
		// });
		// Custom button to redirect on Go comet logs
		frm.add_custom_button(__("View Logs"), () => {
			frappe.set_route("List", "Gocomet Logs");
		});
	},
});

function generate_token(doc) {
	frappe.call({
		method: "lifelong_integrations.lifelong_integrations.doctype.lifelong_go_comet_settings.api.generate_token.get_token",
		args: {},
		callback: function (r) {
			if (r.message) {
				console.log(r.message);
			}
		},
	});
}
function create_go_comet_shipment(doc) {
	frappe.call({
		method: "lifelong_integrations.lifelong_integrations.doctype.lifelong_go_comet_settings.api.go_comet_shipment.gocomet_shipment",
		args: {},
		callback: function (r) {
			if (r.message) {
				console.log(r.message);
			}
		},
	});
}
function fetch_live_tracking_data(doc) {
	frappe.call({
		method: "lifelong_integrations.lifelong_integrations.doctype.lifelong_go_comet_settings.api.get_tracking_data.fetch_live_tracking_data",
		args: {},
		callback: function (r) {
			if (r.message) {
				console.log(r.message);
			}
		},
	});
}

function create_po(doc) {
	frappe.call({
		method: "lifelong_integrations.lifelong_integrations.doctype.lifelong_go_comet_settings.api.create_po.get_po_from_gocomet",
		args: {},
		callback: function (r) {
			if (r.message) {
				console.log(r.message);
			}
		},
	});
}
