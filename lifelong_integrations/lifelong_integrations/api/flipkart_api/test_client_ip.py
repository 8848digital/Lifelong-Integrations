# Copyright (c) 2026, 8848 Digital LLP and Contributors
# See license.txt

"""The caller's IP for the allowlist and rate limits (VAPT GW-01) and tracebacks only for desk
System Managers (VAPT GW-02). Settings are in memory; nothing is saved."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from werkzeug.test import EnvironBuilder

from lifelong_integrations import utils as site_utils
from lifelong_integrations.lifelong_integrations.api.flipkart_api import auth

FLIPKART = "103.4.255.70"
ATTACKER = "198.51.100.7"


def settings(**values):
	base = dict(inbound_ip_allowlist="103.4.255.64/26", trusted_proxies="")
	base.update(values)
	return frappe._dict(base)


class RequestCase(FrappeTestCase):
	def setUp(self):
		self.saved_request = getattr(frappe.local, "request", None)

	def tearDown(self):
		frappe.local.request = self.saved_request

	def request(self, peer, forwarded=None):
		headers = [
			("X-Forwarded-For", value)
			for value in ([forwarded] if isinstance(forwarded, str) else forwarded or [])
		]
		frappe.local.request = EnvironBuilder(
			path="/api/method/x", method="POST", headers=headers, environ_base={"REMOTE_ADDR": peer}
		).get_request()


class TestClientIP(RequestCase):
	def client_ip(self, peer, forwarded=None, **values):
		self.request(peer, forwarded)
		ip = auth.get_client_ip(settings(**values))
		return ip and str(ip)

	def test_direct_caller_ignores_the_header(self):
		self.assertEqual(self.client_ip(ATTACKER, FLIPKART), ATTACKER)

	def test_behind_local_nginx(self):
		# nginx appends the address it saw; whatever the caller sent stays on the left
		self.assertEqual(self.client_ip("127.0.0.1", FLIPKART), FLIPKART)
		self.assertEqual(self.client_ip("127.0.0.1", f"{FLIPKART}, {ATTACKER}"), ATTACKER)
		self.assertEqual(self.client_ip("::1", ATTACKER), ATTACKER)

	def test_load_balancer_listed_in_settings(self):
		lb = "10.0.0.5"
		self.assertEqual(
			self.client_ip("127.0.0.1", f"{FLIPKART}, {ATTACKER}, {lb}", trusted_proxies="10.0.0.0/24"),
			ATTACKER,
		)
		self.assertEqual(
			self.client_ip("127.0.0.1", f"{ATTACKER}, {lb}", trusted_proxies="10.0.0.0/24"), ATTACKER
		)
		# not listed: the load balancer itself is the caller
		self.assertEqual(self.client_ip("127.0.0.1", f"{FLIPKART}, {lb}"), lb)
		self.assertEqual(self.client_ip(lb, FLIPKART, trusted_proxies="10.0.0.0/24\nnot-a-network"), FLIPKART)

	def test_repeated_headers_are_one_list(self):
		self.assertEqual(self.client_ip("127.0.0.1", [FLIPKART, ATTACKER]), ATTACKER)

	def test_no_header_behind_a_proxy(self):
		self.assertEqual(self.client_ip("127.0.0.1"), "127.0.0.1")

	def test_bad_values_fail_closed(self):
		self.assertIsNone(self.client_ip("127.0.0.1", "garbage"))
		self.assertIsNone(self.client_ip("127.0.0.1", f"{FLIPKART}:443"))


class TestAllowlist(RequestCase):
	def allowed(self, peer, forwarded=None, **values):
		self.request(peer, forwarded)
		return auth.is_ip_allowed(settings(**values))

	def test_spoofed_header_refused(self):
		self.assertFalse(self.allowed(ATTACKER, FLIPKART))
		self.assertFalse(self.allowed("127.0.0.1", f"{FLIPKART}, {ATTACKER}"))
		self.assertFalse(self.allowed("127.0.0.1", "garbage"))

	def test_flipkart_allowed(self):
		self.assertTrue(self.allowed(FLIPKART))
		self.assertTrue(self.allowed("127.0.0.1", FLIPKART))

	def test_no_allowlist_allows_all(self):
		self.assertTrue(self.allowed(ATTACKER, inbound_ip_allowlist=""))

	def test_ipv6_caller_against_ipv4_list(self):
		self.assertFalse(self.allowed("2001:db8::1"))


class TestRateLimit(RequestCase):
	def test_counted_per_real_caller_not_per_header(self):
		calls = []
		limited = auth.rate_limit_by_client_ip(limit=3, seconds=60)(lambda: calls.append(1))
		key = frappe.cache.make_key(f"rl:{limited.__module__}.<lambda>:{ATTACKER}")
		frappe.cache.delete(key)
		try:
			with patch.object(auth, "get_settings", return_value=settings()):
				for n in range(3):
					self.request("127.0.0.1", f"10.9.9.{n}, {ATTACKER}")  # a new forged value each time
					limited()
				self.request("127.0.0.1", f"10.9.9.99, {ATTACKER}")
				with self.assertRaises(frappe.RateLimitExceededError):
					limited()
				self.assertEqual(len(calls), 3)
				# another caller has its own count
				self.request("127.0.0.1", FLIPKART)
				limited()
				self.assertEqual(len(calls), 4)
		finally:
			frappe.cache.delete(key)
			frappe.cache.delete(frappe.cache.make_key(f"rl:{limited.__module__}.<lambda>:{FLIPKART}"))


class TestErrorTraceback(FrappeTestCase):
	def tearDown(self):
		frappe.local.flags.disable_traceback = None
		frappe.set_user("Administrator")

	def run_hook(self, user):
		frappe.local.flags.disable_traceback = None
		frappe.set_user(user)
		site_utils.hide_error_traceback()
		return bool(frappe.local.flags.disable_traceback)

	def test_guest_gets_no_traceback(self):
		self.assertTrue(self.run_hook("Guest"))

	def test_system_manager_keeps_it(self):
		self.assertFalse(self.run_hook("Administrator"))

	def test_hook_registered(self):
		self.assertIn("lifelong_integrations.utils.hide_error_traceback", frappe.get_hooks("before_request"))
