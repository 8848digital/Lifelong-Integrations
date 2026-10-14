// Copyright (c) 2026, 8848 Digital LLP and contributors
// For license information, please see license.txt

const FLIPKART_API = "lifelong_integrations.lifelong_integrations.api.flipkart_api";
const FLIPKART_SETTINGS = "lifelong_integrations.lifelong_integrations.doctype.flipkart_settings.flipkart_settings";

frappe.ui.form.on("Flipkart Settings", {
	refresh(frm) {
		const base = `${window.location.origin}/api/method/${FLIPKART_API}`;
		const rows = [
			["Token URL (token_uri)", `${base}.auth.token`],
			["PO Webhook (PO_CREATE / PO_EDIT)", `${base}.webhook.po_notification`],
			["Consignment Schedule Callback", `${base}.webhook.consignment_schedule_callback`],
			["Document Acknowledgement Callback", `${base}.webhook.document_ack_callback`],
		];
		frm.get_field("endpoint_urls").$wrapper.html(`
			<p class="text-muted small">Share these with the Flipkart technical contact. They must be
			served over HTTPS on port 443 from a public domain name (separate for UAT and Production).</p>
			<table class="table table-bordered small">
				${rows.map(([label, url]) => `<tr><td>${label}</td><td><code>${url}</code></td></tr>`).join("")}
			</table>`);

		frm.add_custom_button(__("Generate Inbound Credentials"), () => {
			frappe.confirm(
				__("Generate a new Client ID and Secret for Flipkart? Tokens already issued stop working."),
				() =>
					frappe.call({
						method: `${FLIPKART_SETTINGS}.generate_inbound_credentials`,
						callback: () => frm.reload_doc(),
					})
			);
		});

		frm.add_custom_button(__("Test Flipkart Token"), () => {
			frappe.call({
				method: `${FLIPKART_SETTINGS}.test_outbound_token`,
				freeze: true,
				callback: (r) => {
					if (r.message && r.message.ok) {
						frappe.show_alert({ message: __("Flipkart token received"), indicator: "green" });
					}
				},
			});
		});

		frm.add_custom_button(__("Push Pending POs to ERP"), () => {
			frappe.call({
				method: `${FLIPKART_API}.po.push_pending_pos`,
				freeze: true,
				callback: (r) => {
					const m = r.message || {};
					frappe.msgprint(__("{0} pushed, {1} failed", [m.success || 0, m.failed || 0]));
				},
			});
		});
	},
});
