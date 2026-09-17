// Copyright (c) 2026, 8848 Digital LLP and contributors
// For license information, please see license.txt

frappe.ui.form.on("Swiggy PO Data", {
	refresh(frm) {
		// Show "Create Quotation" only for Initiated POs that haven't been synced yet.
		if (frm.doc.status === "Initiated" && !frm.doc.__islocal) {
			frm.add_custom_button(
				__("Create Quotation"),
				function () {
					frappe.confirm(
						`Create a Quotation on the Finance site for PO <b>${frm.doc.name}</b>?`,
						function () {
							frappe.call({
								method: "lifelong_integrations.lifelong_integrations.api.swiggy_api.quotation.create_swiggy_quotations",
								args: { po_name: frm.doc.name },
								freeze: true,
								freeze_message: __("Creating Quotation on Finance site…"),
								callback: function (r) {
									if (!r.exc && r.message) {
										let msg = r.message;
										if (msg.success) {
											frappe.show_alert(
												{
													message: __("Quotation created successfully."),
													indicator: "green",
												},
												6
											);
										} else if (msg.failed) {
											frappe.show_alert(
												{
													message: __(
														"Quotation creation failed — check Swiggy API Log for details."
													),
													indicator: "red",
												},
												6
											);
										}
										frm.reload_doc();
									}
								},
							});
						}
					);
				},
				__("Actions")
			);
		}
	},
});
