// Copyright (c) 2026, 8848 Digital LLP and contributors
// For license information, please see license.txt

frappe.ui.form.on("Decathlon Logs", {
	refresh(frm) {
		const colors = { Success: "green", Failed: "red", Skipped: "orange" };
		if (frm.doc.status) {
			frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");
		}
	},
});
