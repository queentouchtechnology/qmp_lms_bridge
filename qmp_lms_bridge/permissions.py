"""
permission_query_conditions for every tenant-scoped LMS doctype this app
registers. Two shapes:

- The 4 hook-only doctypes (Course Chapter, LMS Batch Timetable,
  LMS Timetable Legend, Discussion Topic) — no direct `tenant` field,
  resolved via a parent-link join, one function each (unavoidable — a
  raw SQL WHERE-clause fragment necessarily names the real join path,
  which differs per doctype).
- The 12 doctypes WITH a direct `tenant` Custom Field (LMS Course,
  LMS Batch, LMS Zoom Settings, Course Evaluator, LMS Category,
  Course Lesson, LMS Quiz, LMS Enrollment, LMS Batch Enrollment,
  LMS Certificate, LMS Live Class, LMS Assignment) — genuinely generic
  (same `tenant` column name on every one), added in the
  production-readiness audit after live testing found these 12 had NO
  permission_query_conditions AND no has_permission registered at all:
  a real Tenant Owner could list AND directly open another tenant's
  LMS Course/LMS Quiz by name, confirmed against real production data
  (ABC School reading XYZ College's course/quiz). Only the 4 hook-only
  doctypes had ever been wired up; the other 12 relied solely on native
  Frappe DocPerm (Moderator/Course Creator/etc.), which has no concept
  of tenant at all.

has_permission for ALL 16 doctypes (both shapes) uses the exact same
generic qtt_platform.permissions.handlers.has_permission — it already
resolves tenant via document_security.resolve_tenant_for_doc(), which
tries a direct `tenant` field FIRST before falling back to the
parent-link registries, so no per-doctype has_permission function is
ever needed here. See hooks.py's has_permission dict.
"""

import frappe

from qtt_platform.tenant.context import resolve_active_tenant

#: The two reference types Discussion Topic / LMS Timetable Legend
#: actually point at in this product. If a third ever appears (unlikely —
#: these are LMS's own established polymorphic patterns), add it here.
_POLYMORPHIC_REFERENCE_TYPES = ("LMS Course", "LMS Batch")


def course_chapter_query_conditions(user=None):
	tenant = resolve_active_tenant(user=user)
	if not tenant:
		return "1=0"
	return f"""`tabCourse Chapter`.course in (
		select name from `tabLMS Course` where tenant = {frappe.db.escape(tenant)}
	)"""


def lms_batch_timetable_query_conditions(user=None):
	tenant = resolve_active_tenant(user=user)
	if not tenant:
		return "1=0"
	return f"""`tabLMS Batch Timetable`.batch in (
		select name from `tabLMS Batch` where tenant = {frappe.db.escape(tenant)}
	)"""


def _polymorphic_query_conditions(doctype: str, doctype_field: str, name_field: str, user=None) -> str:
	"""For a polymorphic reference (reference_doctype/reference_docname):
	one OR-clause per possible reference type, each matching BOTH the
	doctype field AND the name against that type's own tenant-scoped
	rows — not a flattened combined name list, which could theoretically
	mismatch a name that collides across two different reference types."""
	tenant = resolve_active_tenant(user=user)
	if not tenant:
		return "1=0"

	tenant_escaped = frappe.db.escape(tenant)
	clauses = []
	for ref_doctype in _POLYMORPHIC_REFERENCE_TYPES:
		clauses.append(
			f"""(`tab{doctype}`.{doctype_field} = {frappe.db.escape(ref_doctype)}
				and `tab{doctype}`.{name_field} in (
					select name from `tab{ref_doctype}` where tenant = {tenant_escaped}
				))"""
		)
	return "(" + " or ".join(clauses) + ")"


def discussion_topic_query_conditions(user=None):
	return _polymorphic_query_conditions("Discussion Topic", "reference_doctype", "reference_docname", user=user)


def lms_timetable_legend_query_conditions(user=None):
	return _polymorphic_query_conditions(
		"LMS Timetable Legend", "reference_doctype", "reference_docname", user=user
	)


# ---------------------------------------------------------------------------
# The 12 doctypes with a direct `tenant` Custom Field — see this module's
# own docstring for why these were missing entirely until the
# production-readiness audit caught it via live cross-tenant testing.
# ---------------------------------------------------------------------------


def _direct_tenant_query_conditions(doctype: str, user=None) -> str:
	tenant = resolve_active_tenant(user=user)
	if not tenant:
		return "1=0"
	return f"`tab{doctype}`.tenant = {frappe.db.escape(tenant)}"


def lms_course_query_conditions(user=None):
	return _direct_tenant_query_conditions("LMS Course", user=user)


def lms_batch_query_conditions(user=None):
	return _direct_tenant_query_conditions("LMS Batch", user=user)


def lms_zoom_settings_query_conditions(user=None):
	return _direct_tenant_query_conditions("LMS Zoom Settings", user=user)


def course_evaluator_query_conditions(user=None):
	return _direct_tenant_query_conditions("Course Evaluator", user=user)


def lms_category_query_conditions(user=None):
	return _direct_tenant_query_conditions("LMS Category", user=user)


def course_lesson_query_conditions(user=None):
	return _direct_tenant_query_conditions("Course Lesson", user=user)


def lms_quiz_query_conditions(user=None):
	return _direct_tenant_query_conditions("LMS Quiz", user=user)


def lms_enrollment_query_conditions(user=None):
	return _direct_tenant_query_conditions("LMS Enrollment", user=user)


def lms_batch_enrollment_query_conditions(user=None):
	return _direct_tenant_query_conditions("LMS Batch Enrollment", user=user)


def lms_certificate_query_conditions(user=None):
	return _direct_tenant_query_conditions("LMS Certificate", user=user)


def lms_live_class_query_conditions(user=None):
	return _direct_tenant_query_conditions("LMS Live Class", user=user)


def lms_assignment_query_conditions(user=None):
	return _direct_tenant_query_conditions("LMS Assignment", user=user)
