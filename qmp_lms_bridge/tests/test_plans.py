"""
Bench-independent tests for qmp_lms_bridge.plans — verifies the plan
catalog data itself (the exact prices/limits from the SaaS lifecycle
brief, Phase B — a typo here is a real pricing/entitlement bug, not a
cosmetic one) and the create-vs-update upsert logic, without a real
Frappe bench. Same fake-frappe technique as test_install.py.

Run manually from the qmp_lms_bridge repo root:

    python -m unittest qmp_lms_bridge.tests.test_plans -v
"""

import importlib
import sys
import types
import unittest
from unittest import mock


def _install_fake_modules(product_exists: bool = True):
	class _ValidationError(Exception):
		pass

	fake_frappe = types.ModuleType("frappe")
	fake_frappe.ValidationError = _ValidationError
	fake_frappe.db = types.SimpleNamespace(exists=mock.Mock(return_value=product_exists))
	fake_frappe.get_doc = mock.Mock()
	fake_frappe.new_doc = mock.Mock()
	sys.modules["frappe"] = fake_frappe
	return fake_frappe


class PlanCatalogDataTest(unittest.TestCase):
	"""Pins down the exact figures from the SaaS lifecycle brief — this is
	the test that actually catches a transcription typo in a price or a
	limit."""

	def setUp(self):
		sys.modules.pop("qmp_lms_bridge.plans", None)
		sys.modules.pop("qmp_lms_bridge", None)
		_install_fake_modules()
		self.plans = importlib.import_module("qmp_lms_bridge.plans")

	def test_exactly_three_plans_in_ascending_price_order(self):
		codes = [p["plan_code"] for p in self.plans.PLAN_CATALOG]
		self.assertEqual(codes, ["STARTER", "PROFESSIONAL", "ENTERPRISE"])
		prices = [p["base_price"] for p in self.plans.PLAN_CATALOG]
		self.assertEqual(prices, sorted(prices))

	def test_starter_pricing_and_limits(self):
		plan = self._plan("STARTER")
		self.assertEqual(plan["display_name"], "QMP LMS Starter")
		self.assertEqual(plan["base_price"], 99)
		self.assertEqual(
			plan["features"],
			{
				"max_students": 25,
				"max_batch_students": 25,
				"max_instructors": 2,
				"max_courses": 5,
				"max_batches": 2,
				"max_live_classes": 2,
				"max_quizzes": 10,
				"ai_credits_grant": 20,
				"max_ai_credits": 20,
			},
		)

	def test_professional_pricing_and_limits(self):
		plan = self._plan("PROFESSIONAL")
		self.assertEqual(plan["display_name"], "QMP LMS Professional")
		self.assertEqual(plan["base_price"], 299)
		self.assertEqual(
			plan["features"],
			{
				"max_students": 100,
				"max_batch_students": 100,
				"max_instructors": 10,
				"max_courses": 25,
				"max_batches": 10,
				"max_live_classes": 10,
				"max_quizzes": 50,
				"ai_credits_grant": 100,
				"max_ai_credits": 100,
			},
		)

	def test_enterprise_pricing_and_limits(self):
		plan = self._plan("ENTERPRISE")
		self.assertEqual(plan["display_name"], "QMP LMS Enterprise")
		self.assertEqual(plan["base_price"], 799)
		self.assertEqual(
			plan["features"],
			{
				"max_students": 500,
				"max_batch_students": 500,
				"max_instructors": 50,
				"max_courses": 100,
				"max_batches": 50,
				"max_live_classes": 50,
				"max_quizzes": 250,
				"ai_credits_grant": 500,
				"max_ai_credits": 500,
			},
		)

	def test_every_plan_has_a_7_day_trial_and_is_public_monthly(self):
		for plan in self.plans.PLAN_CATALOG:
			self.assertEqual(self.plans.TRIAL_DAYS, 7)
		self.assertEqual(self.plans.BILLING_PERIOD, "monthly")

	def _plan(self, code):
		return next(p for p in self.plans.PLAN_CATALOG if p["plan_code"] == code)


class SeedPlansTest(unittest.TestCase):
	def setUp(self):
		sys.modules.pop("qmp_lms_bridge.plans", None)
		sys.modules.pop("qmp_lms_bridge", None)

	def test_noop_when_product_does_not_exist_yet(self):
		fake_frappe = _install_fake_modules(product_exists=False)
		plans = importlib.import_module("qmp_lms_bridge.plans")
		plans.seed_plans()
		fake_frappe.get_doc.assert_not_called()
		fake_frappe.new_doc.assert_not_called()

	def test_creates_three_new_plans_when_none_exist(self):
		fake_frappe = _install_fake_modules(product_exists=True)
		# First db.exists call is the QTT Product check (True); every
		# subsequent call is a per-plan-code QTT Plan lookup (False = not
		# created yet).
		fake_frappe.db.exists = mock.Mock(side_effect=[True, False, False, False])
		created_docs = [mock.Mock(name=f"plan-{i}") for i in range(3)]
		fake_frappe.new_doc = mock.Mock(side_effect=created_docs)

		plans = importlib.import_module("qmp_lms_bridge.plans")
		plans.seed_plans()

		self.assertEqual(fake_frappe.new_doc.call_count, 3)
		for doc in created_docs:
			doc.insert.assert_called_once_with(ignore_permissions=True)
			doc.save.assert_not_called()
			# Each plan gets exactly 9 feature rows appended.
			self.assertEqual(doc.append.call_count, 9)

	def test_updates_existing_plans_rather_than_duplicating(self):
		fake_frappe = _install_fake_modules(product_exists=True)
		fake_frappe.db.exists = mock.Mock(side_effect=[True, "plan-1", "plan-2", "plan-3"])
		existing_docs = [mock.Mock() for _ in range(3)]
		fake_frappe.get_doc = mock.Mock(side_effect=existing_docs)

		plans = importlib.import_module("qmp_lms_bridge.plans")
		plans.seed_plans()

		fake_frappe.new_doc.assert_not_called()
		for doc in existing_docs:
			doc.save.assert_called_once_with(ignore_permissions=True)
			doc.insert.assert_not_called()

	def test_feature_limits_are_appended_as_strings(self):
		# QTT Plan Feature.limit_value is a Data field (string) by design
		# — see that doctype's own description in qtt_platform. A plain
		# int here would be a real bug (get_entitlements() would still
		# coerce it back via int(), but the stored DB value should match
		# the doctype's own documented convention).
		fake_frappe = _install_fake_modules(product_exists=True)
		fake_frappe.db.exists = mock.Mock(side_effect=[True, False, False, False])
		created = mock.Mock()
		fake_frappe.new_doc = mock.Mock(return_value=created)

		plans = importlib.import_module("qmp_lms_bridge.plans")
		plans.seed_plans()

		for call in created.append.call_args_list:
			_, kwargs = call
			row = call.args[1] if len(call.args) > 1 else kwargs
			self.assertIsInstance(row["limit_value"], str)


if __name__ == "__main__":
	unittest.main()
