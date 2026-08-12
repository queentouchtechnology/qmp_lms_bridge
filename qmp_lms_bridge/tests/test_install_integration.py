"""
Real bench integration test for the qtt_platform dependency check —
requires an actual Frappe site with `frappe.tests.utils.FrappeTestCase`
available. NOT executed as part of this fix (no bench access during
development); provided for whoever next has bench access to run via:

    bench --site <test-site> run-tests --app qmp_lms_bridge \
        --module qmp_lms_bridge.tests.test_install_integration

See test_install.py in this same directory for the bench-independent
test that WAS actually executed while building this fix.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from qmp_lms_bridge.install import check_dependencies


class TestCheckDependenciesIntegration(FrappeTestCase):
	def test_raises_when_qtt_platform_not_installed(self):
		installed = frappe.get_installed_apps()
		if "qtt_platform" in installed:
			self.skipTest(
				"qtt_platform is installed on this test site — this test "
				"needs a site without it to exercise the failure path."
			)
		with self.assertRaises(frappe.ValidationError):
			check_dependencies()

	def test_passes_when_qtt_platform_installed(self):
		installed = frappe.get_installed_apps()
		if "qtt_platform" not in installed:
			self.skipTest("qtt_platform is not installed on this test site.")
		check_dependencies()  # must not raise
