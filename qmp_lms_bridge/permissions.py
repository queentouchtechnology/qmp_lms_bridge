"""
permission_query_conditions for the 4 hook-only LMS doctypes — the piece
the hardening review section 2/17 said couldn't be built generically
(a raw SQL WHERE-clause fragment necessarily names real tables/columns).
Now that real doctypes exist, here they are.

has_permission for these same 4 doctypes does NOT need a per-doctype
function here — qtt_platform.permissions.handlers.has_permission is fully
generic once qtt_platform.document_security.resolve_tenant_for_doc can
resolve the doctype (which it now can, via the tenant_parent_links /
tenant_dynamic_parent_links registries this app populates in hooks.py).
Register that same function directly against all 4 doctypes in hooks.py's
has_permission dict — see that file.
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
