// Copyright (c) 2026, 8848 Digital LLP and contributors
// For license information, please see license.txt

frappe.ui.form.on("FreshDesk Settings", {
	refresh: function (frm) {
		frm.set_intro(
			`
			Click <a href='https://developers.freshdesk.com/api/#filter_tickets' target='_blank'>Here</a> to view the Supported Ticket Fields in Filters
			<br>
			Supported FreshDesk fields types for <b style="color:var(--dt-text-color)">Filtering Custom Fields</b>:
			<ul>
				<li>Single line text</li>
				<li>Number</li>
				<li>Checkbox</li>
				<li>Dropdown</li>
			</ul>
			Use the below End Point to Configure WebHook to Check Stock Availability:
			<br>
			<code>{{HOST}}/api/method/lifelong_integrations.api.freshdesk_api.ticket_webhook.check_stock_availability</code>
			<br>
			args:
			<ul>
				<li><code>ticket - Ticket ID</code></li>
				<li><code>check_inventory - True/False</code></li>
			</ul>
			`,
			"red"
		);
		frm.add_custom_button(
			"Get Tickets",
			() => {
				frappe.call({
					method: "lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.api.get_tickets",
					freeze: true,
				});
			},
			"API's"
		);
		frm.add_custom_button(
			"Post Contacts",
			() => {
				frappe.call({
					method: "lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.api.create_contacts",
					freeze: true,
				});
			},
			"API's"
		);
		frm.add_custom_button(
			"Update Tickets",
			() => {
				frappe.call({
					method: "lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.api.update_tickets",
					freeze: true,
				});
			},
			"API's"
		);
		frm.add_custom_button(
			"Update Spare List",
			() => {
				frappe.call({
					method: "lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.api.update_spare_list_in_ticket_field",
					freeze: true,
				});
			},
			"API's"
		);
		frm.add_custom_button(
			"Update Category List",
			() => {
				frappe.call({
					method: "lifelong_integrations.lifelong_integrations.doctype.freshdesk_settings.api.update_category_list_in_freshdesk",
					freeze: true,
				});
			},
			"API's"
		);

		frm.add_custom_button(
			"API Logs",
			() => {
				window.open("/app/freshdesk-api-log/view/list");
			},
			"View"
		);
	},
});
