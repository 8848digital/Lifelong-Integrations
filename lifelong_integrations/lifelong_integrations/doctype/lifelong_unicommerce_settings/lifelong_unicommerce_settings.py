# Copyright (c) 2026, 8848 Digital LLP and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class LifelongUnicommerceSettings(Document):
	def validate(self):
		# Strip a pasted "https://" and trailing "/" so the site can be
		# used directly in URLs.
		if self.unicommerce_site:
			site = self.unicommerce_site.strip()
			for prefix in ("https://", "http://"):
				if site.startswith(prefix):
					site = site[len(prefix) :]
			self.unicommerce_site = site.rstrip("/")
