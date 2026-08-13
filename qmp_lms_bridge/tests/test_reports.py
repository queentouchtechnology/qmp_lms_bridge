"""
Bench-independent tests for qmp_lms_bridge.reports — production-readiness
audit, P4. Same fake-module technique as test_roles.py: `frappe` and the
specific qtt_platform functions reports.py calls (product.guards.
require_product_role, tenant.context.resolve_active_tenant, errors.ok/
fail) are faked directly — the real qtt_platform package isn't importable
from this repo's own test run in this dev environment (see test_roles.py's
own docstring for the same constraint).

Run manually from the qmp_lms_bridge repo root:

    python -m unittest qmp_lms_bridge.tests.test_reports -v
"""

import sys
import types
import unittest
from unittest import mock


class _FrappeDict(dict):
	def __getattr__(self, name):
		try:
			return self[name]
		except KeyError:
			return None


def _install_fake_modules():
	class _PermissionError(Exception):
		pass

	fake_frappe = types.ModuleType("frappe")
	fake_frappe.PermissionError = _PermissionError
	fake_frappe.whitelist = lambda *a, **k: (lambda fn: fn)
	fake_frappe.db = types.SimpleNamespace(sql=mock.Mock(return_value=[]))
	sys.modules["frappe"] = fake_frappe

	fake_qtt_platform = types.ModuleType("qtt_platform")
	fake_errors = types.ModuleType("qtt_platform.errors")
	fake_errors.ok = lambda data=None: {"success": True, "data": data or {}}
	fake_errors.fail = lambda code, message: {"success": False, "error": {"code": code, "message": message}}
	fake_product = types.ModuleType("qtt_platform.product")
	fake_product_guards = types.ModuleType("qtt_platform.product.guards")
	fake_product_guards.require_product_role = mock.Mock()
	fake_tenant = types.ModuleType("qtt_platform.tenant")
	fake_tenant_context = types.ModuleType("qtt_platform.tenant.context")
	fake_tenant_context.resolve_active_tenant = mock.Mock(return_value="tenant-1")

	sys.modules["qtt_platform"] = fake_qtt_platform
	sys.modules["qtt_platform.errors"] = fake_errors
	sys.modules["qtt_platform.product"] = fake_product
	sys.modules["qtt_platform.product.guards"] = fake_product_guards
	sys.modules["qtt_platform.tenant"] = fake_tenant
	sys.modules["qtt_platform.tenant.context"] = fake_tenant_context

	return fake_frappe, fake_product_guards, fake_tenant_context


def _fresh_reports_module():
	sys.modules.pop("qmp_lms_bridge.reports", None)
	sys.modules.pop("qmp_lms_bridge", None)
	import importlib

	return importlib.import_module("qmp_lms_bridge.reports")


class GetReportTest(unittest.TestCase):
	def setUp(self):
		self.fake_frappe, self.fake_guards, self.fake_context = _install_fake_modules()
		self.reports = _fresh_reports_module()

	def test_no_active_tenant_rejected(self):
		# `reports.py` does `from qtt_platform.tenant.context import
		# resolve_active_tenant` — that binds the name into reports.py's
		# OWN module namespace at import time, so overriding it later
		# means patching `self.reports.resolve_active_tenant` directly,
		# not the fake module's attribute (which reports.py never looks
		# at again after import).
		with mock.patch.object(self.reports, "resolve_active_tenant", return_value=None):
			result = self.reports.get_report("course_engagement")
		self.assertFalse(result["success"])
		self.assertEqual(result["error"]["code"], "TENANT_ACCESS_DENIED")

	def test_non_instructor_role_rejected(self):
		with mock.patch.object(
			self.reports, "require_product_role", side_effect=self.fake_frappe.PermissionError("nope")
		):
			result = self.reports.get_report("course_engagement")
		self.assertFalse(result["success"])
		self.assertEqual(result["error"]["code"], "ROLE_PERMISSION_DENIED")

	def test_unknown_report_key_rejected(self):
		result = self.reports.get_report("not_a_real_report")
		self.assertFalse(result["success"])
		self.assertEqual(result["error"]["code"], "REPORT_NOT_FOUND")

	def test_all_six_reports_are_registered_and_callable(self):
		self.fake_frappe.db.sql = mock.Mock(return_value=[])
		for key in (
			"course_engagement",
			"quiz_performance",
			"batch_enrollment",
			"instructor_activity",
			"certificate_issuance",
			"student_progress",
		):
			result = self.reports.get_report(key)
			self.assertTrue(result["success"], f"{key}: {result}")
			self.assertIn("summary", result["data"])
			self.assertIn("rows", result["data"])

	def test_course_engagement_scopes_by_tenant(self):
		self.fake_frappe.db.sql = mock.Mock(return_value=[])
		self.reports.get_report("course_engagement")
		sql_text, params = self.fake_frappe.db.sql.call_args[0]
		self.assertIn("LMS Course", sql_text)
		self.assertIn("LMS Enrollment", sql_text)
		self.assertIn("tenant-1", params)

	def test_quiz_performance_computes_overall_pass_rate(self):
		self.fake_frappe.db.sql = mock.Mock(
			return_value=[
				_FrappeDict(quiz="q1", quiz_title="Quiz 1", submission_count=8, avg_percentage=75.0,
				            pass_count=6, fail_count=2),
				_FrappeDict(quiz="q2", quiz_title="Quiz 2", submission_count=2, avg_percentage=50.0,
				            pass_count=1, fail_count=1),
			]
		)
		result = self.reports.get_report("quiz_performance")
		summary = result["data"]["summary"]
		self.assertEqual(summary["total_submissions"], 10)
		self.assertEqual(summary["overall_pass_rate"], 70.0)

	def test_batch_enrollment_is_not_an_attendance_report(self):
		# Regression guard: "attendance" was corrected to "enrollment"
		# because LMS Batch Enrollment has no attendance/present field —
		# this pins the actual query target so a future edit can't
		# silently reintroduce a fabricated attendance concept.
		self.fake_frappe.db.sql = mock.Mock(return_value=[])
		self.reports.get_report("batch_enrollment")
		sql_text, _params = self.fake_frappe.db.sql.call_args[0]
		self.assertIn("LMS Batch Enrollment", sql_text)
		self.assertNotIn("attendance", sql_text.lower())

	def test_instructor_activity_merges_course_and_quiz_counts_by_owner(self):
		call_count = 0

		def _sql(*args, **kwargs):
			nonlocal call_count
			call_count += 1
			if call_count == 1:
				return [_FrappeDict(owner="alice@example.com", course_count=3)]
			return [_FrappeDict(owner="alice@example.com", quiz_count=5)]

		self.fake_frappe.db.sql = mock.Mock(side_effect=_sql)
		result = self.reports.get_report("instructor_activity")
		self.assertEqual(len(result["data"]["rows"]), 1)
		self.assertEqual(result["data"]["rows"][0]["course_count"], 3)
		self.assertEqual(result["data"]["rows"][0]["quiz_count"], 5)

	def test_student_progress_counts_completed_at_100_percent(self):
		self.fake_frappe.db.sql = mock.Mock(
			return_value=[
				_FrappeDict(member="a@example.com", member_name="A", course="c1", course_title="C1",
				            progress=100, current_lesson=None),
				_FrappeDict(member="b@example.com", member_name="B", course="c1", course_title="C1",
				            progress=40, current_lesson="lesson-1"),
			]
		)
		result = self.reports.get_report("student_progress")
		self.assertEqual(result["data"]["summary"]["enrollment_count"], 2)
		self.assertEqual(result["data"]["summary"]["completed_count"], 1)


if __name__ == "__main__":
	unittest.main()
