"""
QMP_LMS role-based feature enforcement — SaaS lifecycle Phase G.
Deliberately lives here, not in qtt_platform: WHICH product role may
write or delete WHICH LMS doctype is 100% QMP_LMS business policy, the
same "product-specific rules belong in the bridge app" line already
drawn for the plan catalog (Phase B) and usage resolvers (Phase 10).

The MECHANISM this relies on — resolving which tenant a brand-new,
not-yet-saved document belongs to, and checking a tenant's Product
Access role for that product — is generic, product-agnostic
infrastructure and lives in qtt_platform
(document_security.resolve_tenant_for_new_doc, product.guards.
require_product_role), reused unmodified. This module supplies only the
DATA (the role matrix below) and the two generic doc_event handlers that
consult it.

This is an ADDITIONAL layer on top of LMS's own native Frappe-Role-based
DocPerm (e.g. "Course Creator"), never a replacement for it and never
requiring an LMS source change — a validate()/on_trash() hook only runs
for a caller LMS's own permission system has ALREADY let through, so
this can only narrow access further (a user without QMP_LMS Product
Access at all, or holding the wrong product_role for this specific
tenant, is rejected even if their global Frappe Role would otherwise
allow the write), never widen it.

ROLE MATRIX — a deliberate, documented interpretation of the SaaS
lifecycle brief's four conceptual categories onto this app's actual 16
registered doctypes (LMS publishes no equivalent matrix to consult, and
the brief itself gives categories, not an operation-by-operation table):

  Manager    — LMS administration: full write+delete on every doctype
               below. The only role that can create/edit/delete LMS
               Course, LMS Batch, LMS Zoom Settings, Course Evaluator,
               LMS Category, LMS Batch Timetable, LMS Timetable Legend
               at all.
  Instructor — teaching/course/batch operations: write (create/edit,
               never delete) on the content-authoring doctypes — Course
               Chapter, Course Lesson, LMS Quiz, LMS Live Class,
               LMS Assignment — plus Discussion Topic participation.
               Read-only everywhere else (LMS Course/Batch/Category/
               Zoom Settings/Evaluator itself, enrollment records,
               certificates, timetables) — an Instructor teaches within
               a Course/Batch a Manager already set up, not administers
               the tenant's LMS.
  Staff      — staff-level (operational/registration-support) tasks:
               write (create/edit) on LMS Enrollment, LMS Batch
               Enrollment, LMS Certificate, LMS Batch Timetable,
               LMS Timetable Legend — and, uniquely, delete on the two
               enrollment doctypes (un-enrolling someone is a routine
               support task). No content-authoring, no LMS Course/Batch/
               Category administration.
  Student    — learning-only: no write access anywhere in this matrix
               except Discussion Topic (asking/answering questions is
               participation, not administration). Deliberately does
               NOT include creating their own LMS Enrollment
               (self-enrollment) — this project has no freshly-verified
               evidence this session of exactly how/whether LMS's real
               self-enrollment flow works, and guessing a doctype shape
               for a real money/access-relevant action is exactly what
               this project avoids; flagged as a known limitation, not
               silently assumed.

Doctypes not listed below are outside this matrix entirely — their
existing tenant/cross-reference guards (Phase 7/10) are unaffected
either way, and no product-role check applies to them from this module.
"""

import frappe
from frappe import _

from qtt_platform.document_security import resolve_tenant_for_new_doc
from qtt_platform.product.guards import require_product_role

PRODUCT_KEY = "QMP_LMS"

_MANAGER_ONLY = ("Manager",)
_MANAGER_AND_INSTRUCTOR = ("Manager", "Instructor")
_MANAGER_AND_STAFF = ("Manager", "Staff")
_EVERYONE = ("Manager", "Instructor", "Staff", "Student")

_ROLE_MATRIX = {
	"LMS Course": {"write": _MANAGER_ONLY, "delete": _MANAGER_ONLY},
	"LMS Batch": {"write": _MANAGER_ONLY, "delete": _MANAGER_ONLY},
	"LMS Zoom Settings": {"write": _MANAGER_ONLY, "delete": _MANAGER_ONLY},
	"Course Evaluator": {"write": _MANAGER_ONLY, "delete": _MANAGER_ONLY},
	"LMS Category": {"write": _MANAGER_ONLY, "delete": _MANAGER_ONLY},
	"Course Chapter": {"write": _MANAGER_AND_INSTRUCTOR, "delete": _MANAGER_ONLY},
	"Course Lesson": {"write": _MANAGER_AND_INSTRUCTOR, "delete": _MANAGER_ONLY},
	"LMS Quiz": {"write": _MANAGER_AND_INSTRUCTOR, "delete": _MANAGER_ONLY},
	"LMS Live Class": {"write": _MANAGER_AND_INSTRUCTOR, "delete": _MANAGER_ONLY},
	"LMS Assignment": {"write": _MANAGER_AND_INSTRUCTOR, "delete": _MANAGER_ONLY},
	"LMS Certificate": {"write": _MANAGER_AND_STAFF, "delete": _MANAGER_ONLY},
	"LMS Enrollment": {"write": _MANAGER_AND_STAFF, "delete": _MANAGER_AND_STAFF},
	"LMS Batch Enrollment": {"write": _MANAGER_AND_STAFF, "delete": _MANAGER_AND_STAFF},
	"LMS Batch Timetable": {"write": _MANAGER_AND_STAFF, "delete": _MANAGER_ONLY},
	"LMS Timetable Legend": {"write": _MANAGER_AND_STAFF, "delete": _MANAGER_ONLY},
	"Discussion Topic": {"write": _EVERYONE, "delete": _MANAGER_ONLY},
}


def enforce_role_on_write(doc, method=None):
	"""Registered as a `validate` doc_event (SaaS lifecycle Phase G) —
	covers both create and edit, since QMP_LMS's role matrix makes no
	distinction between the two (a role that may create content may also
	edit it; nothing in this matrix is create-only or edit-only)."""
	_enforce(doc, "write")


def enforce_role_on_delete(doc, method=None):
	"""Registered as an `on_trash` doc_event."""
	_enforce(doc, "delete")


def _enforce(doc, action: str) -> None:
	allowed_roles = _ROLE_MATRIX.get(doc.doctype, {}).get(action)
	if not allowed_roles:
		return  # doctype not governed by this matrix at all

	# System Manager escape hatch — same precedent already established by
	# qtt_platform.permissions.handlers.guard_tenant_change_before_save:
	# trusted administrative/system operations (bench console, fixtures,
	# future scheduled jobs) must not be blocked by a product-role check
	# that assumes an ordinary tenant member is acting.
	if "System Manager" in frappe.get_roles():
		return

	tenant = resolve_tenant_for_new_doc(doc)
	if not tenant:
		frappe.throw(_("Cannot determine the tenant for this document."), frappe.PermissionError)

	require_product_role(tenant, PRODUCT_KEY, list(allowed_roles))
