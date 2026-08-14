"""
Bridges QTT Product Access (QMP_LMS) grants to the underlying native
Frappe Roles LMS's own DocPerm requires — production-readiness audit,
found via live multi-tenant verification (real signup, real Manager
attempting to create a real LMS Course): holding "Manager"/"Instructor"
in QTT Product Access grants NOTHING at the native Frappe permission
layer on its own, so LMS Course/Chapter/Lesson/Quiz/etc.'s own DocPerm
(System Manager / Course Creator / Moderator / Batch Evaluator —
verified live against the real DocPerm on all 16 registered doctypes,
not guessed) denied every create attempt regardless of QTT role, before
roles.py's own document-event layer ever got a chance to run (native
permission checks happen first — same ordering already established for
self-enrollment in roles.py's own docstring).

Native roles are strictly BROADER than the final effective permission —
roles.py's own document-event checks plus qtt_platform.document_security's
tenant/permission_query_conditions scoping are what narrow "Moderator can
write any LMS Course anywhere" down to "only within this user's own
active tenant, and only if their current QTT Product Access still says
so." Granting these native roles does not bypass or weaken that
narrowing; it's the other half of the architecture roles.py's own
docstring already promised ("ADDITIONAL layer... never a replacement for
[native DocPerm]") but never actually wired up.

Mapping (verified against the real DocPerm on all 16 registered
doctypes, 2026-08-14):
  Manager    -> Moderator, Course Creator, Batch Evaluator (LMS Batch's
                own DocPerm is the one doctype neither Moderator nor
                Course Creator alone covers).
  Instructor -> Moderator, Course Creator (LMS Live Class/LMS Assignment
                require Moderator specifically — Course Creator alone
                covers Chapter/Lesson/Quiz but not those two).
  Staff      -> Moderator (covers LMS Enrollment/LMS Batch Enrollment/
                LMS Certificate/LMS Batch Timetable/LMS Timetable
                Legend).
  Student    -> no additional native role — "LMS Student" is already
                granted by the `lms` app itself on account creation.

Deliberately grant-only, never auto-revoking. Recomputing "the full set
this user should hold" and stripping anything else would risk silently
removing a native role an admin granted directly for an unrelated
reason, or one this user still legitimately needs via a DIFFERENT
tenant's QMP_LMS access (native Frappe Roles are global, not per-tenant).
This is safe to leave asymmetric: a leftover native role on a user whose
QTT Product Access was later revoked/downgraded is harmless, because
roles.py's own enforce_role_on_write/enforce_role_on_delete always
re-checks the CURRENT QTT Product Access role independently — a native
role alone was never sufficient to write anything, only necessary.
"""

import frappe

PRODUCT_KEY = "QMP_LMS"

_NATIVE_ROLES_BY_PRODUCT_ROLE = {
	"Manager": ("Moderator", "Course Creator", "Batch Evaluator"),
	"Instructor": ("Moderator", "Course Creator"),
	"Staff": ("Moderator",),
	"Student": (),
}


def sync_native_roles_on_access_change(doc, method=None):
	"""doc_events hook — QTT Product Access after_insert/on_update. A
	no-op for every product other than QMP_LMS, and for an
	inactive/unrecognized product_role (nothing to grant)."""
	if doc.product != PRODUCT_KEY or doc.status != "active":
		return

	native_roles = _NATIVE_ROLES_BY_PRODUCT_ROLE.get(doc.product_role, ())
	if not native_roles:
		return

	user = frappe.db.get_value("QTT Tenant Membership", doc.membership, "user")
	if not user:
		return

	existing = set(frappe.get_roles(user))
	missing = [role for role in native_roles if role not in existing]
	if not missing:
		return

	# NOT User.add_roles() — it calls self.save() with no
	# ignore_permissions, so it 403s under any caller who lacks native
	# write access to User, which is every real Guest signup (this
	# function runs from an after_insert hook fired mid-signup, before
	# the new user is ever authenticated as anyone). Found live: a real,
	# unauthenticated signup() call failed outright because of this.
	# Appending the role rows directly and saving with
	# ignore_permissions=True is the correct bypass — this grant is a
	# system-level side effect of a QTT Product Access change, not
	# something the calling user's own permissions should gate.
	user_doc = frappe.get_doc("User", user)
	for role in missing:
		user_doc.append("roles", {"role": role})
	user_doc.save(ignore_permissions=True)
