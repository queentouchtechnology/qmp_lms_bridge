"""
Bench-independent tests for qmp_lms_bridge.native_roles — production-
readiness audit, found via live multi-tenant verification (see that
module's own docstring for the full story: a real signup + real Manager
attempting to create a real LMS Course was rejected by native Frappe
DocPerm, because nothing had ever granted the underlying native role a
QTT Product Access grant implies).

Run manually from the qmp_lms_bridge repo root:

    python -m unittest qmp_lms_bridge.tests.test_native_roles -v
"""

import sys
import types
import unittest
from unittest import mock


def _install_fake_frappe(existing_roles=None):
	fake_frappe = types.ModuleType("frappe")
	fake_frappe.db = types.SimpleNamespace(get_value=mock.Mock(return_value="user@example.com"))
	fake_frappe.get_roles = mock.Mock(return_value=existing_roles or [])
	fake_user_doc = mock.Mock()
	fake_frappe.get_doc = mock.Mock(return_value=fake_user_doc)
	sys.modules["frappe"] = fake_frappe
	return fake_frappe, fake_user_doc


def _fresh_native_roles_module():
	sys.modules.pop("qmp_lms_bridge.native_roles", None)
	sys.modules.pop("qmp_lms_bridge", None)
	import importlib

	return importlib.import_module("qmp_lms_bridge.native_roles")


class SyncNativeRolesOnAccessChangeTest(unittest.TestCase):
	def test_manager_grants_moderator_course_creator_and_batch_evaluator(self):
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=[])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QMP_LMS", status="active", product_role="Manager", membership="membership-1")

		native_roles.sync_native_roles_on_access_change(doc)

		user_doc.add_roles.assert_called_once()
		granted = set(user_doc.add_roles.call_args[0])
		self.assertEqual(granted, {"Moderator", "Course Creator", "Batch Evaluator"})

	def test_instructor_grants_moderator_and_course_creator_only(self):
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=[])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QMP_LMS", status="active", product_role="Instructor", membership="membership-1")

		native_roles.sync_native_roles_on_access_change(doc)

		granted = set(user_doc.add_roles.call_args[0])
		self.assertEqual(granted, {"Moderator", "Course Creator"})

	def test_staff_grants_moderator_only(self):
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=[])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QMP_LMS", status="active", product_role="Staff", membership="membership-1")

		native_roles.sync_native_roles_on_access_change(doc)

		granted = set(user_doc.add_roles.call_args[0])
		self.assertEqual(granted, {"Moderator"})

	def test_student_grants_nothing(self):
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=[])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QMP_LMS", status="active", product_role="Student", membership="membership-1")

		native_roles.sync_native_roles_on_access_change(doc)

		user_doc.add_roles.assert_not_called()

	def test_already_held_roles_are_not_re_granted(self):
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=["Moderator", "Course Creator", "Batch Evaluator"])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QMP_LMS", status="active", product_role="Manager", membership="membership-1")

		native_roles.sync_native_roles_on_access_change(doc)

		user_doc.add_roles.assert_not_called()

	def test_only_missing_roles_are_granted(self):
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=["Moderator"])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QMP_LMS", status="active", product_role="Manager", membership="membership-1")

		native_roles.sync_native_roles_on_access_change(doc)

		granted = set(user_doc.add_roles.call_args[0])
		self.assertEqual(granted, {"Course Creator", "Batch Evaluator"})

	def test_other_product_is_a_no_op(self):
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=[])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QTT_HRMS", status="active", product_role="Manager", membership="membership-1")

		native_roles.sync_native_roles_on_access_change(doc)

		fake_frappe.get_doc.assert_not_called()
		user_doc.add_roles.assert_not_called()

	def test_inactive_access_is_a_no_op(self):
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=[])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QMP_LMS", status="suspended", product_role="Manager", membership="membership-1")

		native_roles.sync_native_roles_on_access_change(doc)

		fake_frappe.get_doc.assert_not_called()
		user_doc.add_roles.assert_not_called()

	def test_resolves_user_via_the_membership_link(self):
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=[])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QMP_LMS", status="active", product_role="Staff", membership="membership-42")

		native_roles.sync_native_roles_on_access_change(doc)

		fake_frappe.db.get_value.assert_called_once_with("QTT Tenant Membership", "membership-42", "user")
		fake_frappe.get_doc.assert_called_once_with("User", "user@example.com")


if __name__ == "__main__":
	unittest.main()
