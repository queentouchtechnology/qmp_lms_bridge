"""
Bench-independent tests for qmp_lms_bridge.permissions — never tested
before this pass. The 12 direct-tenant-field query-condition functions
are a critical fix found via live testing (Part E-F multi-tenant
isolation verification): see permissions.py's own module docstring for
the real production data that confirmed the leak.

Run manually from the qmp_lms_bridge repo root:

    python -m unittest qmp_lms_bridge.tests.test_permissions -v
"""

import sys
import types
import unittest
from unittest import mock


def _install_fake_frappe(active_tenant="tenant-1"):
	fake_frappe = types.ModuleType("frappe")
	fake_frappe.db = types.SimpleNamespace(escape=lambda v: f"'{v}'")
	sys.modules["frappe"] = fake_frappe

	fake_qtt_platform = types.ModuleType("qtt_platform")
	fake_tenant = types.ModuleType("qtt_platform.tenant")
	fake_tenant_context = types.ModuleType("qtt_platform.tenant.context")
	fake_tenant_context.resolve_active_tenant = mock.Mock(return_value=active_tenant)
	sys.modules["qtt_platform"] = fake_qtt_platform
	sys.modules["qtt_platform.tenant"] = fake_tenant
	sys.modules["qtt_platform.tenant.context"] = fake_tenant_context

	return fake_frappe, fake_tenant_context


def _fresh_permissions_module():
	sys.modules.pop("qmp_lms_bridge.permissions", None)
	sys.modules.pop("qmp_lms_bridge", None)
	import importlib

	return importlib.import_module("qmp_lms_bridge.permissions")


class DirectTenantFieldQueryConditionsTest(unittest.TestCase):
	"""Regression coverage for the critical cross-tenant leak: these 12
	doctypes (LMS Course, LMS Quiz, Course Lesson, ...) had NO
	permission_query_conditions at all — any list query returned every
	tenant's rows, confirmed live (ABC School's own list included XYZ
	College's course/quiz)."""

	def test_scopes_by_the_active_tenant(self):
		_install_fake_frappe(active_tenant="tenant-1")
		permissions = _fresh_permissions_module()
		result = permissions.lms_course_query_conditions()
		self.assertEqual(result, "`tabLMS Course`.tenant = 'tenant-1'")

	def test_denies_everything_when_no_active_tenant(self):
		_install_fake_frappe(active_tenant=None)
		permissions = _fresh_permissions_module()
		result = permissions.lms_quiz_query_conditions()
		self.assertEqual(result, "1=0")

	def test_all_twelve_functions_reference_their_own_table(self):
		_install_fake_frappe(active_tenant="tenant-1")
		permissions = _fresh_permissions_module()
		expectations = {
			"lms_course_query_conditions": "LMS Course",
			"lms_batch_query_conditions": "LMS Batch",
			"lms_zoom_settings_query_conditions": "LMS Zoom Settings",
			"course_evaluator_query_conditions": "Course Evaluator",
			"lms_category_query_conditions": "LMS Category",
			"course_lesson_query_conditions": "Course Lesson",
			"lms_quiz_query_conditions": "LMS Quiz",
			"lms_enrollment_query_conditions": "LMS Enrollment",
			"lms_batch_enrollment_query_conditions": "LMS Batch Enrollment",
			"lms_certificate_query_conditions": "LMS Certificate",
			"lms_live_class_query_conditions": "LMS Live Class",
			"lms_assignment_query_conditions": "LMS Assignment",
		}
		for fn_name, doctype in expectations.items():
			with self.subTest(fn_name):
				result = getattr(permissions, fn_name)()
				self.assertEqual(result, f"`tab{doctype}`.tenant = 'tenant-1'")

	def test_different_users_resolve_different_tenants(self):
		_install_fake_frappe(active_tenant="tenant-1")
		permissions = _fresh_permissions_module()
		with mock.patch.object(permissions, "resolve_active_tenant", return_value="tenant-2") as resolve_mock:
			result = permissions.lms_course_query_conditions(user="someone@example.com")
		self.assertEqual(result, "`tabLMS Course`.tenant = 'tenant-2'")
		resolve_mock.assert_called_once_with(user="someone@example.com")


if __name__ == "__main__":
	unittest.main()
