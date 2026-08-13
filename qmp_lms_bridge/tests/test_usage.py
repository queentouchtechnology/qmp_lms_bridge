"""
Bench-independent test for qmp_lms_bridge.usage.count_ai_credits_used() —
production-readiness audit. The other usage resolvers in that module are
plain one-line frappe.db.count() wrappers (no dedicated tests exist for
those, by established precedent in this app); this one does real SQL
(SUM with a sign flip), which is worth pinning down.

Run manually from the qmp_lms_bridge repo root:

    python -m unittest qmp_lms_bridge.tests.test_usage -v
"""

import sys
import types
import unittest
from unittest import mock


def _install_fake_frappe(sql_result):
	fake_frappe = types.ModuleType("frappe")
	fake_frappe.db = types.SimpleNamespace(sql=mock.Mock(return_value=[[sql_result]]))
	sys.modules["frappe"] = fake_frappe
	return fake_frappe


class CountAiCreditsUsedTest(unittest.TestCase):
	def setUp(self):
		sys.modules.pop("qmp_lms_bridge.usage", None)
		sys.modules.pop("qmp_lms_bridge", None)

	def test_returns_the_summed_consumption_as_a_positive_int(self):
		# QTT AI Credit Ledger stores consumption as a NEGATIVE amount
		# (see that doctype's own description) — the resolver flips the
		# sign so "used" reads as a positive number, matching every other
		# usage resolver's own positive-count convention.
		_install_fake_frappe(sql_result=35.0)
		usage = __import__("qmp_lms_bridge.usage", fromlist=["count_ai_credits_used"])
		self.assertEqual(usage.count_ai_credits_used("tenant-1"), 35)

	def test_no_usage_yet_returns_zero(self):
		_install_fake_frappe(sql_result=None)
		usage = __import__("qmp_lms_bridge.usage", fromlist=["count_ai_credits_used"])
		self.assertEqual(usage.count_ai_credits_used("tenant-1"), 0)

	def test_query_scopes_by_tenant_and_qmp_lms_and_consumption_only(self):
		fake_frappe = _install_fake_frappe(sql_result=0)
		usage = __import__("qmp_lms_bridge.usage", fromlist=["count_ai_credits_used"])
		usage.count_ai_credits_used("tenant-1")
		sql_text, params = fake_frappe.db.sql.call_args[0]
		self.assertIn("QTT AI Credit Ledger", sql_text)
		self.assertIn("QMP_LMS", sql_text)
		self.assertIn("consumption", sql_text)
		self.assertEqual(params, ("tenant-1",))


if __name__ == "__main__":
	unittest.main()
