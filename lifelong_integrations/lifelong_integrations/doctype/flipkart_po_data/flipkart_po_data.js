// Copyright (c) 2026, 8848 Digital LLP and contributors
// For license information, please see license.txt

const FLIPKART_PO_API = "lifelong_integrations.lifelong_integrations.api.flipkart_api.po";

frappe.ui.form.on("Flipkart PO Data", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.status === "Initiated") {
			frm.add_custom_button(
				__("Push to ERP"),
				() =>
					frappe.call({
						method: `${FLIPKART_PO_API}.push_pending_pos`,
						args: { po_data_name: frm.doc.name },
						freeze: true,
						callback: () => frm.reload_doc(),
					}),
				__("Actions")
			);
		}

		if (frm.doc.status === "Failed") {
			frm.add_custom_button(
				__("Retry"),
				() =>
					frappe.call({
						method: `${FLIPKART_PO_API}.retry_po`,
						args: { po_data_name: frm.doc.name },
						freeze: true,
						callback: () => frm.reload_doc(),
					}),
				__("Actions")
			);
		}

		if (frm.doc.event_type === "PO_CREATE" && frm.doc.ack_status !== "Sent") {
			frm.add_custom_button(
				__("Send PO ACK"),
				() =>
					frappe.confirm(__("Acknowledge PO {0} to Flipkart as accepted?", [frm.doc.po_number]), () =>
						frappe.call({
							method: `${FLIPKART_PO_API}.send_po_ack`,
							args: { po_number: frm.doc.po_number },
							freeze: true,
							callback: () => frm.reload_doc(),
						})
					),
				__("Actions")
			);
		}
	},
});
