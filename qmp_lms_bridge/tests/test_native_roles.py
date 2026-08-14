"""
Bench-independent tests for qmp_lms_bridge.native_roles — production-
readiness audit, found via live multi-tenant verification (see that
module's own docstring for the full story: a real signup + real Manager
attempting to create a real LMS Course was rejected by native Frappe
DocPerm, because nothing had ever granted the underlying native role a
QTT Product Access grant implies).

Regression note: sync_native_roles_on_access_change() originally called
User.add_roles(), which internally does self.save() with NO
ignore_permissions — this 403'd on every real, unauthenticated signup()
call (the after_insert hook fires mid-signup, before the new user is
ever an authenticated session). Found via a real HTTP signup attempt,
not a test. Fixed to append role rows directly and save with
ignore_permissions=True instead — these tests assert against that call
shape.

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


def _appended_roles(user_doc):
	return {call.args[1]["role"] for call in user_doc.append.call_args_list}


class SyncNativeRolesOnAccessChangeTest(unittest.TestCase):
	def test_manager_grants_moderator_course_creator_and_batch_evaluator(self):
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=[])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QMP_LMS", status="active", product_role="Manager", membership="membership-1")

		native_roles.sync_native_roles_on_access_change(doc)

		self.assertEqual(_appended_roles(user_doc), {"Moderator", "Course Creator", "Batch Evaluator"})
		user_doc.save.assert_called_once_with(ignore_permissions=True)

	def test_instructor_grants_moderator_and_course_creator_only(self):
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=[])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QMP_LMS", status="active", product_role="Instructor", membership="membership-1")

		native_roles.sync_native_roles_on_access_change(doc)

		self.assertEqual(_appended_roles(user_doc), {"Moderator", "Course Creator"})
		user_doc.save.assert_called_once_with(ignore_permissions=True)

	def test_staff_grants_moderator_only(self):
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=[])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QMP_LMS", status="active", product_role="Staff", membership="membership-1")

		native_roles.sync_native_roles_on_access_change(doc)

		self.assertEqual(_appended_roles(user_doc), {"Moderator"})
		user_doc.save.assert_called_once_with(ignore_permissions=True)

	def test_student_grants_nothing(self):
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=[])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QMP_LMS", status="active", product_role="Student", membership="membership-1")

		native_roles.sync_native_roles_on_access_change(doc)

		user_doc.append.assert_not_called()
		user_doc.save.assert_not_called()

	def test_already_held_roles_are_not_re_granted(self):
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=["Moderator", "Course Creator", "Batch Evaluator"])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QMP_LMS", status="active", product_role="Manager", membership="membership-1")

		native_roles.sync_native_roles_on_access_change(doc)

		user_doc.append.assert_not_called()
		user_doc.save.assert_not_called()

	def test_only_missing_roles_are_granted(self):
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=["Moderator"])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QMP_LMS", status="active", product_role="Manager", membership="membership-1")

		native_roles.sync_native_roles_on_access_change(doc)

		self.assertEqual(_appended_roles(user_doc), {"Course Creator", "Batch Evaluator"})
		user_doc.save.assert_called_once_with(ignore_permissions=True)

	def test_other_product_is_a_no_op(self):
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=[])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QTT_HRMS", status="active", product_role="Manager", membership="membership-1")

		native_roles.sync_native_roles_on_access_change(doc)

		fake_frappe.get_doc.assert_not_called()
		user_doc.save.assert_not_called()

	def test_inactive_access_is_a_no_op(self):
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=[])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QMP_LMS", status="suspended", product_role="Manager", membership="membership-1")

		native_roles.sync_native_roles_on_access_change(doc)

		fake_frappe.get_doc.assert_not_called()
		user_doc.save.assert_not_called()

	def test_resolves_user_via_the_membership_link(self):
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=[])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QMP_LMS", status="active", product_role="Staff", membership="membership-42")

		native_roles.sync_native_roles_on_access_change(doc)

		fake_frappe.db.get_value.assert_called_once_with("QTT Tenant Membership", "membership-42", "user")
		fake_frappe.get_doc.assert_called_once_with("User", "user@example.com")

	def test_does_not_use_add_roles(self):
		# The exact regression: add_roles() internally saves without
		# ignore_permissions and 403s under a real Guest signup context.
		fake_frappe, user_doc = _install_fake_frappe(existing_roles=[])
		native_roles = _fresh_native_roles_module()
		doc = mock.Mock(product="QMP_LMS", status="active", product_role="Manager", membership="membership-1")

		native_roles.sync_native_roles_on_access_change(doc)

		user_doc.add_roles.assert_not_called()


if __name__ == "__main__":
	unittest.main()
