"""
Reproduces Frappe's real module-discovery/import logic against this repo's
actual files on disk — no mocking, no bench. This exercises the exact
sequence that crashed with `ModuleNotFoundError:
No module named 'qmp_lms_bridge.qmp_lms_bridge'` during `install-app`:

  1. frappe.get_module_list(app) reads `<app>/modules.txt` line by line
     (frappe/__init__.py:get_module_list).
  2. Each line is passed through frappe.scrub() — lowercase, spaces/hyphens
     -> underscores (frappe/__init__.py:scrub). "QMP LMS Bridge" becomes
     "qmp_lms_bridge".
  3. frappe/model/sync.py's sync_for(), called from install_app() via
     add_module_defs()/sync_for(), does exactly:
         frappe.get_module(app_name + "." + module_name)
     i.e. frappe.get_module("qmp_lms_bridge.qmp_lms_bridge") — and
     frappe.get_module() is a thin wrapper over
     importlib.import_module(). It then reads .__file__ off the result.

Every step above was confirmed by reading the real Frappe 15
(version-15 branch) source before writing this fix — not guessed. This
test performs the same three steps directly against this repo's own
modules.txt and package layout, so it fails the same way `install-app`
did if the module folder is ever deleted or renamed again, without
needing a Frappe bench to catch it.

Run manually from the repo root:

    python -m unittest qmp_lms_bridge.tests.test_module_structure -v
"""

import importlib
import os
import unittest


def _scrub(txt: str) -> str:
	"""Exact copy of frappe.scrub() (frappe/__init__.py) — reimplemented
	here rather than imported, since `frappe` isn't installable outside a
	bench and this test must run with plain Python."""
	return txt.replace(" ", "_").replace("-", "_").lower()


def _read_modules_txt(path: str) -> list[str]:
	"""Exact copy of frappe.get_file_items()'s behavior as used by
	get_module_list(): non-empty, non-comment lines, stripped."""
	with open(path, encoding="utf-8") as f:
		return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]


class ModuleDiscoveryStructureTest(unittest.TestCase):
	def setUp(self):
		self.app_root = os.path.dirname(  # .../qmp_lms_bridge (repo root)
			os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		)
		self.package_root = os.path.join(self.app_root, "qmp_lms_bridge")  # the app's own package
		self.modules_txt = os.path.join(self.package_root, "modules.txt")

	def test_modules_txt_exists(self):
		self.assertTrue(
			os.path.isfile(self.modules_txt), f"modules.txt missing at {self.modules_txt}"
		)

	def test_every_declared_module_has_an_importable_package_folder(self):
		modules = _read_modules_txt(self.modules_txt)
		self.assertTrue(modules, "modules.txt declared no modules")

		for module_name in modules:
			scrubbed = _scrub(module_name)
			dotted_path = f"qmp_lms_bridge.{scrubbed}"

			# Reproduces frappe/model/sync.py:105 exactly:
			#   folder = os.path.dirname(frappe.get_module(app_name + "." + module_name).__file__)
			try:
				imported = importlib.import_module(dotted_path)
			except ModuleNotFoundError as exc:
				self.fail(
					f"modules.txt declares '{module_name}' (scrubbed: '{scrubbed}'), "
					f"but {dotted_path} is not importable — this is exactly the "
					f"install-app crash. Missing folder: "
					f"qmp_lms_bridge/{scrubbed}/__init__.py. Original error: {exc}"
				)

			self.assertIsNotNone(imported.__file__)
			folder = os.path.dirname(imported.__file__)
			self.assertTrue(os.path.isdir(folder))


if __name__ == "__main__":
	unittest.main()
