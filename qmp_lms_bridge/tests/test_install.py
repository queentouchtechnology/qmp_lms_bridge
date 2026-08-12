"""
Bench-independent test for install.check_dependencies() — verifies the
dependency-check logic itself by injecting fake `frappe` / `qtt_platform`
modules before import, so this runs with plain `python -m unittest` and
needs no bench, no site, and no database. This is the test that was
actually executed while fixing the required_apps/InvalidRemoteException
bug (see install.py's check_dependencies() docstring for the full root
cause) — its real output is quoted in this fix's commit message.

Run manually:

    python -m unittest qmp_lms_bridge.tests.test_install -v

For a real integration test against a live bench (actually running
`bench --site <site> install-app qmp_lms_bridge` end to end), see
test_install_integration.py in this same directory — that one needs
`bench --site <test-site> run-tests --app qmp_lms_bridge` and has not
been executed anywhere in this project (no bench access during
development); it is provided for whoever next has bench access to run.
"""

import importlib
import sys
import types
import unittest
from unittest import mock


def _install_fake_modules(installed_apps):
	"""Puts minimal fake `frappe` and `qtt_platform.product.registry`
	modules into sys.modules so `qmp_lms_bridge.install` can be imported
	and exercised without a real Frappe bench."""

	class _ValidationError(Exception):
		pass

	def _throw(msg, title=None):
		raise _ValidationError(msg)

	fake_frappe = types.ModuleType("frappe")
	fake_frappe.local = types.SimpleNamespace(site="test-site")
	fake_frappe.get_installed_apps = mock.Mock(return_value=list(installed_apps))
	fake_frappe.throw = _throw
	fake_frappe.ValidationError = _ValidationError
	sys.modules["frappe"] = fake_frappe

	fake_qtt_platform = types.ModuleType("qtt_platform")
	fake_qtt_product = types.ModuleType("qtt_platform.product")
	fake_qtt_registry = types.ModuleType("qtt_platform.product.registry")
	fake_qtt_registry.register_product = mock.Mock()
	fake_qtt_registry.register_product_doctype = mock.Mock()
	sys.modules["qtt_platform"] = fake_qtt_platform
	sys.modules["qtt_platform.product"] = fake_qtt_product
	sys.modules["qtt_platform.product.registry"] = fake_qtt_registry

	return fake_frappe


class CheckDependenciesTest(unittest.TestCase):
	def setUp(self):
		sys.modules.pop("qmp_lms_bridge.install", None)
		sys.modules.pop("qmp_lms_bridge", None)

	def test_raises_clearly_when_qtt_platform_missing(self):
		# Reproduces the reported bench state: qtt_platform is genuinely
		# absent from the site's installed-apps list.
		fake_frappe = _install_fake_modules(installed_apps=["frappe", "lms"])
		install = importlib.import_module("qmp_lms_bridge.install")

		with self.assertRaises(fake_frappe.ValidationError) as ctx:
			install.check_dependencies()

		message = str(ctx.exception)
		self.assertIn("qtt_platform", message)
		self.assertIn("install-app qtt_platform", message)

	def test_passes_silently_when_qtt_platform_installed(self):
		# Reproduces the user's actual reported state: qtt_platform IS
		# installed on the site (frappe.get_installed_apps() has it),
		# regardless of whether it's listed in the bench-wide
		# sites/apps.txt file — that file is deliberately NOT consulted
		# by this check, which is the entire point of the fix.
		_install_fake_modules(installed_apps=["frappe", "lms", "qtt_platform"])
		install = importlib.import_module("qmp_lms_bridge.install")

		install.check_dependencies()  # must not raise


if __name__ == "__main__":
	unittest.main()
