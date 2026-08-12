"""
Bench-independent tests for qmp_lms_bridge.roles — SaaS lifecycle Phase G.
Same fake-module technique as test_install.py: `frappe` and the specific
qtt_platform functions roles.py calls (document_security.
resolve_tenant_for_new_doc, product.guards.require_product_role) are
faked directly, since the real qtt_platform package isn't importable
from this repo's own test run in this dev environment (a real bench puts
both apps on the same Python path; this local setup does not) — exactly
the same constraint test_install.py's own module docstring already
documents for qtt_platform.product.registry.

These tests verify roles.py's OWN logic — which doctype/action maps to
which allowed roles, the System Manager bypass, and that
require_product_role() is called with the right arguments — not
qtt_platform's guard implementations themselves, which have their own,
separate test suite in that project.

Run manually from the qmp_lms_bridge repo root:

    python -m unittest qmp_lms_bridge.tests.test_roles -v
"""

import importlib
import sys
import types
import unittest
from unittest import mock


def _install_fake_modules(*, roles=None, is_system_manager=False, tenant="tenant-1"):
	class _PermissionError(Exception):
		pass

	def _throw(msg, exc=None, **kwargs):
		raise (exc or Exception)(msg)

	fake_frappe = types.ModuleType("frappe")
	fake_frappe.PermissionError = _PermissionError
	fake_frappe.throw = _throw
	fake_frappe._ = lambda s: s
	fake_frappe.get_roles = mock.Mock(return_value=(["System Manager"] if is_system_manager else ["All"]))
	sys.modules["frappe"] = fake_frappe

	fake_qtt_platform = types.ModuleType("qtt_platform")
	fake_document_security = types.ModuleType("qtt_platform.document_security")
	fake_document_security.resolve_tenant_for_new_doc = mock.Mock(return_value=tenant)
	fake_product = types.ModuleType("qtt_platform.product")
	fake_product_guards = types.ModuleType("qtt_platform.product.guards")
	fake_product_guards.require_product_role = mock.Mock()
	sys.modules["qtt_platform"] = fake_qtt_platform
	sys.modules["qtt_platform.document_security"] = fake_document_security
	sys.modules["qtt_platform.product"] = fake_product
	sys.modules["qtt_platform.product.guards"] = fake_product_guards

	return fake_frappe, fake_document_security, fake_product_guards


def _fresh_roles_module(**fake_kwargs):
	sys.modules.pop("qmp_lms_bridge.roles", None)
	sys.modules.pop("qmp_lms_bridge", None)
	fake_frappe, fake_doc_sec, fake_guards = _install_fake_modules(**fake_kwargs)
	roles = importlib.import_module("qmp_lms_bridge.roles")
	return roles, fake_frappe, fake_doc_sec, fake_guards


class RoleMatrixDataTest(unittest.TestCase):
	def setUp(self):
		self.roles, *_ = _fresh_roles_module()

	def test_manager_only_administration_doctypes(self):
		for doctype in ("LMS Course", "LMS Batch", "LMS Zoom Settings", "Course Evaluator", "LMS Category"):
			with self.subTest(doctype=doctype):
				self.assertEqual(self.roles._ROLE_MATRIX[doctype]["write"], ("Manager",))
				self.assertEqual(self.roles._ROLE_MATRIX[doctype]["delete"], ("Manager",))

	def test_instructor_can_write_but_not_delete_teaching_content(self):
		for doctype in ("Course Chapter", "Course Lesson", "LMS Quiz", "LMS Live Class", "LMS Assignment"):
			with self.subTest(doctype=doctype):
				self.assertIn("Instructor", self.roles._ROLE_MATRIX[doctype]["write"])
				self.assertNotIn("Instructor", self.roles._ROLE_MATRIX[doctype]["delete"])

	def test_staff_can_write_and_delete_enrollments(self):
		for doctype in ("LMS Enrollment", "LMS Batch Enrollment"):
			with self.subTest(doctype=doctype):
				self.assertIn("Staff", self.roles._ROLE_MATRIX[doctype]["write"])
				self.assertIn("Staff", self.roles._ROLE_MATRIX[doctype]["delete"])

	def test_student_can_only_write_discussion_topic(self):
		doctypes_student_can_write = [dt for dt, ops in self.roles._ROLE_MATRIX.items() if "Student" in ops["write"]]
		self.assertEqual(doctypes_student_can_write, ["Discussion Topic"])

	def test_student_can_never_delete_anything(self):
		for doctype, ops in self.roles._ROLE_MATRIX.items():
			with self.subTest(doctype=doctype):
				self.assertNotIn("Student", ops["delete"])

	def test_manager_can_write_and_delete_every_matrix_doctype(self):
		for doctype, ops in self.roles._ROLE_MATRIX.items():
			with self.subTest(doctype=doctype):
				self.assertIn("Manager", ops["write"])
				self.assertIn("Manager", ops["delete"])

	def test_all_16_registered_doctypes_are_covered(self):
		expected = {
			"LMS Course", "LMS Batch", "LMS Zoom Settings", "Course Evaluator", "LMS Category",
			"Course Lesson", "LMS Quiz", "LMS Certificate", "LMS Enrollment", "LMS Batch Enrollment",
			"LMS Live Class", "LMS Assignment", "Course Chapter", "LMS Batch Timetable",
			"LMS Timetable Legend", "Discussion Topic",
		}
		self.assertEqual(set(self.roles._ROLE_MATRIX.keys()), expected)


class EnforceRoleOnWriteTest(unittest.TestCase):
	def test_calls_require_product_role_with_matrix_roles_for_governed_doctype(self):
		roles, _, doc_sec, guards = _fresh_roles_module(tenant="tenant-1")
		doc = mock.Mock(doctype="Course Lesson")

		roles.enforce_role_on_write(doc)

		doc_sec.resolve_tenant_for_new_doc.assert_called_once_with(doc)
		guards.require_product_role.assert_called_once_with("tenant-1", "QMP_LMS", ["Manager", "Instructor"])

	def test_noop_for_a_doctype_outside_the_matrix(self):
		roles, _, doc_sec, guards = _fresh_roles_module()
		doc = mock.Mock(doctype="Some Unrelated Doctype")

		roles.enforce_role_on_write(doc)

		doc_sec.resolve_tenant_for_new_doc.assert_not_called()
		guards.require_product_role.assert_not_called()

	def test_system_manager_bypasses_the_check_entirely(self):
		roles, _, doc_sec, guards = _fresh_roles_module(is_system_manager=True)
		doc = mock.Mock(doctype="LMS Course")

		roles.enforce_role_on_write(doc)

		doc_sec.resolve_tenant_for_new_doc.assert_not_called()
		guards.require_product_role.assert_not_called()

	def test_raises_when_tenant_cannot_be_resolved(self):
		roles, fake_frappe, doc_sec, guards = _fresh_roles_module(tenant=None)
		doc = mock.Mock(doctype="LMS Course")

		with self.assertRaises(Exception):
			roles.enforce_role_on_write(doc)

		guards.require_product_role.assert_not_called()

	def test_student_allowed_to_write_discussion_topic(self):
		roles, _, doc_sec, guards = _fresh_roles_module(tenant="tenant-1")
		doc = mock.Mock(doctype="Discussion Topic")

		roles.enforce_role_on_write(doc)

		guards.require_product_role.assert_called_once_with(
			"tenant-1", "QMP_LMS", ["Manager", "Instructor", "Staff", "Student"]
		)


class EnforceRoleOnDeleteTest(unittest.TestCase):
	def test_manager_only_doctype_delete_check(self):
		roles, _, doc_sec, guards = _fresh_roles_module(tenant="tenant-1")
		doc = mock.Mock(doctype="LMS Course")

		roles.enforce_role_on_delete(doc)

		guards.require_product_role.assert_called_once_with("tenant-1", "QMP_LMS", ["Manager"])

	def test_staff_included_for_enrollment_delete(self):
		roles, _, doc_sec, guards = _fresh_roles_module(tenant="tenant-1")
		doc = mock.Mock(doctype="LMS Enrollment")

		roles.enforce_role_on_delete(doc)

		guards.require_product_role.assert_called_once_with("tenant-1", "QMP_LMS", ["Manager", "Staff"])

	def test_instructor_not_included_for_course_lesson_delete(self):
		roles, _, doc_sec, guards = _fresh_roles_module(tenant="tenant-1")
		doc = mock.Mock(doctype="Course Lesson")

		roles.enforce_role_on_delete(doc)

		guards.require_product_role.assert_called_once_with("tenant-1", "QMP_LMS", ["Manager"])


if __name__ == "__main__":
	unittest.main()
