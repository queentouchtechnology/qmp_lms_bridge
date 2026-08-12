"""
Validates fixtures/custom_field.json without a bench — catches the exact
class of bug that crashed `install-app` with `KeyError: 'name'`.

Root cause, traced against real Frappe 15 source before fixing (not
guessed): fixture sync (frappe.utils.fixtures.sync_fixtures ->
frappe.core.doctype.data_import.data_import.import_doc ->
frappe.modules.import_file.import_file_by_path) reads
`frappe.db.get_value(doc["doctype"], doc["name"], "modified")` as the
FIRST thing it does with each fixture record — before frappe.get_doc()
or .insert() are ever called. A DocType's own `autoname()` method (e.g.
Custom Field's `self.name = self.dt + "-" + self.fieldname`, frappe/
custom/doctype/custom_field/custom_field.py) only runs during .insert(),
which is too late — fixture JSON files MUST carry an explicit, correct
`name` key already matching what that autoname would produce, or the
plain dict access above raises KeyError before any doc is ever built.

Idempotency note (fixture sync is safe to re-run): import_file_by_path's
import_doc() does `if frappe.db.exists(doc.doctype, doc.name):
delete_old_doc(doc, ...)` before `doc.insert()` — i.e. it deletes and
re-creates the SAME row by name on every run. This is only idempotent if
`name` is deterministic and stable across runs, which "<dt>-<fieldname>"
is by construction (dt/fieldname never change here).

Run manually from the repo root:

    python -m unittest qmp_lms_bridge.tests.test_fixtures -v
"""

import json
import os
import unittest

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../qmp_lms_bridge (package)
_FIXTURES_DIR = os.path.join(_APP_ROOT, "fixtures")

#: The 12 tenant-scoped LMS doctypes this app registers as QMP_LMS's own
#: (qmp_lms_bridge/install.py::_ANCHOR_AND_DENORMALIZED_DOCTYPES) — kept
#: as a second, independent list here so a fixture drifting out of sync
#: with install.py's registration list is caught, not just internal
#: self-consistency within the fixture file.
_EXPECTED_TENANT_FIELD_DOCTYPES = {
	"LMS Course",
	"LMS Batch",
	"LMS Zoom Settings",
	"Course Evaluator",
	"LMS Category",
	"Course Lesson",
	"LMS Quiz",
	"LMS Certificate",
	"LMS Enrollment",
	"LMS Batch Enrollment",
	"LMS Live Class",
	"LMS Assignment",
}


def _load(fname):
	with open(os.path.join(_FIXTURES_DIR, fname), encoding="utf-8") as f:
		return json.load(f)


class AllFixturesHaveNameTest(unittest.TestCase):
	"""Generic guard: every fixture record in every fixtures/*.json file
	must carry a `name` key, regardless of doctype — this is what
	import_file_by_path() unconditionally reads first, for any fixture
	doctype this app ever adds in future, not just Custom Field."""

	def test_every_fixture_record_has_a_name_key(self):
		self.assertTrue(os.path.isdir(_FIXTURES_DIR), f"missing fixtures dir: {_FIXTURES_DIR}")
		json_files = [f for f in os.listdir(_FIXTURES_DIR) if f.endswith(".json")]
		self.assertTrue(json_files, "no fixture JSON files found")

		for fname in json_files:
			records = _load(fname)
			self.assertIsInstance(records, list, f"{fname}: expected a JSON list")
			for i, record in enumerate(records):
				self.assertIn(
					"name",
					record,
					f"{fname}[{i}] ({record.get('doctype')}: {record.get('dt', record.get('label'))}) "
					f"has no 'name' key — this is exactly the KeyError: 'name' crash "
					f"import_file_by_path() raises during install-app/migrate.",
				)
				self.assertTrue(record["name"], f"{fname}[{i}] has an empty 'name'")


class CustomFieldFixtureTest(unittest.TestCase):
	def setUp(self):
		self.records = _load("custom_field.json")

	def test_count_matches_the_12_intended_lms_tenant_fields(self):
		self.assertEqual(len(self.records), 12)
		self.assertEqual({r["dt"] for r in self.records}, _EXPECTED_TENANT_FIELD_DOCTYPES)

	def test_every_record_is_well_formed(self):
		for r in self.records:
			self.assertEqual(r["doctype"], "Custom Field")
			self.assertEqual(r["fieldname"], "tenant")
			self.assertEqual(r["fieldtype"], "Link")
			self.assertEqual(r["options"], "QTT Tenant")
			self.assertTrue(r["insert_after"], f"{r['dt']}: insert_after must not be empty")

	def test_name_matches_frappe_custom_field_autoname_convention(self):
		# Reproduces Custom Field.autoname() exactly (frappe/custom/doctype/
		# custom_field/custom_field.py: self.name = self.dt + "-" + self.fieldname).
		for r in self.records:
			expected_name = f"{r['dt']}-{r['fieldname']}"
			self.assertEqual(
				r["name"],
				expected_name,
				f"{r['dt']}: fixture 'name' must match Custom Field's real autoname "
				f"convention '<dt>-<fieldname>' so re-imports target the same row.",
			)

	def test_names_are_unique(self):
		names = [r["name"] for r in self.records]
		self.assertEqual(len(names), len(set(names)), f"duplicate fixture names: {names}")


if __name__ == "__main__":
	unittest.main()
