"""
Registers QMP LMS as a QTT Product — called from after_install and
after_migrate (hooks.py), so the registration always matches what's
actually deployed, the same idempotent register-on-every-migrate pattern
qtt_platform.product.registry.register_product() was built for in Phase 2.

This is the ONE file in this whole app that imports qtt_platform's
registration functions and calls them with LMS-specific data — exactly
the boundary the product-agnostic architecture describes: qtt_platform
never imports anything from here; this app imports from qtt_platform.
"""

from qtt_platform.product.registry import register_product, register_product_doctype

PRODUCT_KEY = "QMP_LMS"

#: The 12 anchor/denormalized LMS doctypes carrying the `tenant` Custom
#: Field (see fixtures/custom_field.json) — every one of them belongs to
#: this product, full stop, registered here so
#: qtt_platform.document_security.require_document_tenant_and_product can
#: resolve "this LMS Course belongs to QMP_LMS" without a product field on
#: every row.
_ANCHOR_AND_DENORMALIZED_DOCTYPES = (
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
)

#: The 3 hook-only doctypes — no direct tenant field, resolved via the
#: parent-walk registries (hooks.py's tenant_parent_links /
#: tenant_dynamic_parent_links). Still registered to the product, since
#: product ownership (§3 of the platform docs) and tenant-field presence
#: are two independent questions — has_permission for these still needs
#: to know they belong to QMP_LMS.
_HOOK_ONLY_DOCTYPES = (
	"Course Chapter",
	"LMS Batch Timetable",
	"LMS Timetable Legend",
	"Discussion Topic",
)

_ROLES = [
	{"role_key": "Instructor", "role_name": "Instructor"},
	{"role_key": "Manager", "role_name": "Manager"},
	{"role_key": "Staff", "role_name": "Staff"},
	{"role_key": "Student", "role_name": "Student"},
]


def register_lms_product():
	register_product(
		PRODUCT_KEY,
		display_name="QMP LMS",
		app_name="lms",
		description="Quiz Master Plus — the learning management product built on Frappe LMS.",
		roles=_ROLES,
	)

	for doctype in _ANCHOR_AND_DENORMALIZED_DOCTYPES:
		register_product_doctype(PRODUCT_KEY, doctype, is_tenant_scoped=True)

	for doctype in _HOOK_ONLY_DOCTYPES:
		register_product_doctype(PRODUCT_KEY, doctype, is_tenant_scoped=True)
