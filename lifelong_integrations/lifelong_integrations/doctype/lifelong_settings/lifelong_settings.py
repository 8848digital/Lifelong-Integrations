# Copyright (c) 2026, 8848 Digital LLP and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from lifelong_integrations.utils import validate_https_url


class LifelongSettings(Document):
	def validate(self):
		validate_https_url(self.target_site_url, self.meta.get_label("target_site_url"))
