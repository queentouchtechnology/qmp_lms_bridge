"""
Student creation — a Manager/Instructor-only whitelisted method, NOT a
raw `/api/resource/User` REST create. Verified live 2026-08-16: the
stock `User` doctype's own DocPerm requires System Manager-tier native
access, which no QMP_LMS native role grants — correctly, per
native_roles.py's own docstring on why LMS content roles (Moderator/
Course Creator/Batch Evaluator) are deliberately narrow and never
touch User itself. A real Manager/Instructor product role is a
different, already-verified authorization decision, so this follows
the same "product role check replaces DocPerm, insert with
ignore_permissions=True" pattern
qtt_platform.user_provisioning.create_user already uses for
self-service signup — the caller's product role is the real gate, not
the User doctype's own native permissions.

Deliberately does not set `tenant` on the new User — `tenant` isn't a
field on the stock User doctype at all (see the DioClient tenant-
stamping interceptor's own doc comment on qzmaster for the doctypes
that do carry one); a student's real tenant relationship lives on
QTT Tenant Membership/QTT Product Access, created separately once
they're invited/enrolled, matching how every other account on this
platform gets its tenant relationship.
"""

import frappe
from frappe import _

from qtt_platform.product.guards import require_product_role
from qtt_platform.tenant.context import resolve_active_tenant

PRODUCT_KEY = "QMP_LMS"
_ALLOWED_ROLES = ("Manager", "Instructor")


@frappe.whitelist()
def create_student(email: str, first_name: str, last_name: str = "") -> dict:
	tenant = resolve_active_tenant()
	if not tenant:
		frappe.throw(_("No active tenant."), frappe.PermissionError)
	require_product_role(tenant, PRODUCT_KEY, list(_ALLOWED_ROLES))

	email = (email or "").strip().lower()
	first_name = (first_name or "").strip()
	if not email or "@" not in email:
		frappe.throw(_("Enter a valid email address."), frappe.ValidationError)
	if not first_name:
		frappe.throw(_("First name is required."), frappe.ValidationError)
	if frappe.db.exists("User", email):
		frappe.throw(_("A user with this email already exists."), frappe.ValidationError)

	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": first_name,
			"last_name": (last_name or "").strip(),
			"user_type": "Website User",
			"send_welcome_email": 0,
		}
	)
	# `lms` app's own after_insert hook is what actually grants "LMS
	# Student" for a new Website User — unaffected by ignore_permissions,
	# which only bypasses the permission CHECK, not doc_events hooks.
	user.insert(ignore_permissions=True)

	return {"name": user.name, "email": user.email, "full_name": user.full_name or first_name}
