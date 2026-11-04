# Copyright (c) 2026, 8848 Digital LLP and Contributors
# See license.txt

"""VAPT Low findings: unreadable bodies answered as the endpoint would (FG-01), refused calls logged as a
sample (FG-02), security headers (FG-04), Integration User re-checked per request (FG-05) and https://
integration URLs (FG-06). Settings are in memory; nothing is committed."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Response

from lifelong_integrations import utils as site_utils
from lifelong_integrations.lifelong_integrations.api.flipkart_api import auth, webhook

PO_URL = "/api/method/" + auth.FLIPKART_INBOUND_PREFIX + "po_notification"


def request(path, body, content_type="application/json", headers=None, peer="127.0.0.1"):
	return EnvironBuilder(
		path=path,
		method="POST",
		data=body,
		content_type=content_type,
		headers=headers or {},
		environ_base={"REMOTE_ADDR": peer},
	).get_request()


def settings(**values):
	base = dict(enabled=1, inbound_ip_allowlist="", trusted_proxies="", integration_user="fk@example.com")
	base.update(values)
	return frappe._dict(base)


class TestUnparseableBody(FrappeTestCase):
	def answer(self, path, body, bearer_error=None, ip_allowed=True, status=500):
		response = Response('{"exc_type": "JSONDecodeError"}', status=status, mimetype="application/json")
		frappe.local.request = request(path, body)
		self.addCleanup(setattr, frappe.local, "request", None)
		with (
			patch.object(webhook, "get_settings", return_value=settings()),
			patch.object(webhook, "is_ip_allowed", return_value=ip_allowed),
			patch.object(webhook, "_verify_bearer", return_value=bearer_error),
			patch.object(webhook, "create_api_log") as log,
		):
			webhook.answer_unparseable_body(response, frappe.local.request)
		return response, log

	def test_no_token_gets_401(self):
		response, log = self.answer(PO_URL, '{"a": ', bearer_error="Missing Bearer token")
		self.assertEqual(response.status_code, 401)
		self.assertEqual(json.loads(response.get_data())["error_response"]["error_code"], "UNAUTHORIZED")
		log.assert_not_called()

	def test_source_not_allowed_gets_403(self):
		response, _ = self.answer(PO_URL, '{"a": ', ip_allowed=False)
		self.assertEqual(response.status_code, 403)

	def test_authenticated_gets_400_and_one_log_row_without_body(self):
		response, log = self.answer(PO_URL, "{not json")
		self.assertEqual(response.status_code, 400)
		self.assertEqual(json.loads(response.get_data())["error_response"]["error_code"], "VALIDATION_FAILED")
		self.assertEqual(response.headers["Cache-Control"], "no-store")
		self.assertNotIn("not json", log.call_args.kwargs["payload"])

	def test_deep_nesting_is_a_client_error(self):
		response, _ = self.answer(PO_URL, "[" * 100000 + "]" * 100000)
		self.assertEqual(response.status_code, 400)

	def test_token_endpoint_gets_oauth_error(self):
		response, _ = self.answer(auth.TOKEN_PATH, '{"a": ')
		self.assertEqual(response.status_code, 400)
		self.assertEqual(json.loads(response.get_data())["error"], "invalid_request")

	def test_left_alone(self):
		# a body that parses means a real server error: Flipkart must still get the 5xx and retry
		for path, body, status in (
			(PO_URL, '{"ok": 1}', 500),
			(PO_URL, '{"a": ', 200),
			("/api/method/frappe.auth.get_logged_user", '{"a": ', 500),
		):
			response, _ = self.answer(path, body, status=status)
			self.assertEqual(response.status_code, status, path)


class TestRefusedLogSample(FrappeTestCase):
	def test_one_row_per_address_and_minute(self):
		frappe.local.request = request(PO_URL, "{}", headers={"X-Forwarded-For": "198.51.100.77"})
		key = frappe.cache.make_key("flipkart-refused-log:Flipkart PO Notification:198.51.100.77")
		frappe.cache.delete(key)
		try:
			with patch.object(webhook, "get_settings", return_value=settings()):
				results = [webhook.first_refusal_in_window("Flipkart PO Notification") for _ in range(5)]
			self.assertEqual(results, [True, False, False, False, False])
		finally:
			frappe.cache.delete(key)
			frappe.local.request = None


class TestSecurityHeaders(FrappeTestCase):
	def headers(self, path, **request_headers):
		response = Response("x")
		site_utils.add_security_headers(response, request(path, "{}", headers=request_headers))
		return response.headers

	def test_flipkart_api(self):
		h = self.headers(PO_URL)
		self.assertEqual(h["Content-Security-Policy"], "default-src 'none'; frame-ancestors 'none'")
		self.assertEqual(h["Cross-Origin-Embedder-Policy"], "require-corp")
		for name in site_utils.COMMON_HEADERS:
			self.assertIn(name, h)
		self.assertNotIn("Strict-Transport-Security", h)

	def test_desk_keeps_inline_scripts_working(self):
		h = self.headers("/app/user")
		self.assertNotIn("script-src", h["Content-Security-Policy"])
		self.assertNotIn("Cross-Origin-Embedder-Policy", h)

	def test_hsts_only_over_https(self):
		self.assertIn("Strict-Transport-Security", self.headers("/app", **{"X-Forwarded-Proto": "https"}))

	def test_existing_header_kept(self):
		response = Response("x", headers={"X-Frame-Options": "DENY"})
		site_utils.add_security_headers(response, request("/app", "{}"))
		self.assertEqual(response.headers["X-Frame-Options"], "DENY")

	def test_hooks_registered(self):
		hooks = frappe.get_hooks("after_request")
		self.assertIn("lifelong_integrations.utils.add_security_headers", hooks)
		self.assertIn(
			"lifelong_integrations.lifelong_integrations.api.flipkart_api.webhook.answer_unparseable_body",
			hooks,
		)


class TestIntegrationUserPerRequest(FrappeTestCase):
	def test_system_manager_refused_on_request(self):
		with (
			patch.object(auth.frappe.db, "get_value", return_value=1),
			patch.object(auth.frappe, "get_roles", return_value=["System Manager"]),
			patch.object(auth.frappe, "log_error"),
		):
			self.assertIsNone(auth.get_integration_user(settings()))

	def test_plain_user_accepted(self):
		with (
			patch.object(auth.frappe.db, "get_value", return_value=1),
			patch.object(auth.frappe, "get_roles", return_value=["Guest", "All"]),
		):
			self.assertEqual(auth.get_integration_user(settings()), "fk@example.com")


class TestHttpsUrls(FrappeTestCase):
	def test_validator(self):
		for url in (
			"https://retail-edi.api.flipkart.net",
			"http://localhost:8000",
			"http://127.0.0.1",
			"http://dev.localhost:8000",
			"http://[::1]:8000",
			"",
			None,
		):
			site_utils.validate_https_url(url, "URL")
		for url in (
			"http://erp.example.com",
			"ftp://x",
			"https://",
			"erp.example.com",
			"http://127.0.0.1.evil.com",
		):
			with self.assertRaises(frappe.ValidationError, msg=url):
				site_utils.validate_https_url(url, "URL")

	def test_flipkart_settings_refuses_http(self):
		doc = frappe.copy_doc(frappe.get_doc("Flipkart Settings"))
		doc.uat_token_url = "http://authn.flipkart.net/v3/oauth/token"
		with self.assertRaises(frappe.ValidationError):
			doc.validate()

	def test_lifelong_settings_refuses_http(self):
		doc = frappe.copy_doc(frappe.get_doc("Lifelong Settings"))
		doc.target_site_url = "http://erp.example.com"
		with self.assertRaises(frappe.ValidationError):
			doc.validate()
		doc.target_site_url = "https://erp.example.com"
		doc.validate()
