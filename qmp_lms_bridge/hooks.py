from . import __version__ as app_version

app_name = "qmp_lms_bridge"
app_title = "QMP LMS Bridge"
app_publisher = "Queen Touch Technology"
app_description = (
	"Registers QMP LMS as a product on the QTT SaaS Platform. The only app "
	"in this system allowed to know about both `lms` (vendor code, never "
	"edited) and `qtt_platform` (which stays fully product-agnostic and "
	"never imports anything from here) — see this app's own README for the "
	"architectural reason a third app is needed instead of putting this "
	"logic in either of the other two."
)
app_email = "queentouchtech@gmail.com"
app_license = "Proprietary"

# `qtt_platform` is deliberately NOT listed here — see install.py's
# check_dependencies() docstring and the README's "Why qtt_platform is not
# in required_apps" section for the exact Frappe installer behavior (traced
# against real frappe/frappe source, not guessed) that makes required_apps
# unusable for a private app with no public git remote. `lms` stays here —
# it resolves fine, since it's a real, publicly gettable app.
required_apps = ["lms"]

# Custom Field fixtures — the `tenant` Link field on the 12 anchor/
# denormalized LMS doctypes. Applied by `bench migrate` directly from
# fixtures/custom_field.json; no Python code needed for this part.
fixtures = ["Custom Field"]


def _check_dependencies():
	from qmp_lms_bridge.install import check_dependencies

	check_dependencies()


def _register_lms_product():
	from qmp_lms_bridge.install import register_lms_product

	register_lms_product()


# The real "qtt_platform must already be installed" guard — runs before
# schema sync starts, using frappe.get_installed_apps() (the site's actual
# DB-tracked install state), not required_apps (which only trusts the
# bench-wide sites/apps.txt file and cannot see a real install that never
# went through `bench get-app`).
before_install = "qmp_lms_bridge.hooks._check_dependencies"

# Registers/re-registers QMP_LMS as a QTT Product on every install and
# every migrate — idempotent (qtt_platform.product.registry.register_product
# is an upsert), so the registration always matches what's actually
# deployed, the same reasoning as any other hooks.py-driven registration
# in this system.
after_install = "qmp_lms_bridge.hooks._register_lms_product"
after_migrate = "qmp_lms_bridge.hooks._register_lms_product"

# --------------------------------------------------------------------------
# Usage resolvers — read by qtt_platform.usage.registry.get_usage(), keyed
# "PRODUCT_KEY::feature_key". See qmp_lms_bridge/usage.py for the actual
# counting functions.
# --------------------------------------------------------------------------
usage_resolvers = {
	"QMP_LMS::max_students": "qmp_lms_bridge.usage.count_students",
	"QMP_LMS::max_batch_students": "qmp_lms_bridge.usage.count_batch_students",
	"QMP_LMS::max_instructors": "qmp_lms_bridge.usage.count_instructors",
	"QMP_LMS::max_courses": "qmp_lms_bridge.usage.count_courses",
	"QMP_LMS::max_batches": "qmp_lms_bridge.usage.count_batches",
	"QMP_LMS::max_live_classes": "qmp_lms_bridge.usage.count_live_classes",
}

# --------------------------------------------------------------------------
# Tenant parent-link registries — read by
# qtt_platform.document_security.resolve_tenant_for_doc() so the 4
# hook-only doctypes (no direct `tenant` field) resolve correctly. See
# that function's own docstring for the static-vs-dynamic distinction.
# --------------------------------------------------------------------------
tenant_parent_links = {
	"Course Chapter": ("course", "LMS Course"),
	"LMS Batch Timetable": ("batch", "LMS Batch"),
}
tenant_dynamic_parent_links = {
	# CONFIDENCE NOTE: LMS Timetable Legend's polymorphic
	# reference_doctype/reference_docname shape is carried forward from
	# this project's earlier Flutter work (TimetableLegendModel required
	# a `referenceDoctype` field, discovered live, defaulting to
	# 'LMS Batch') — not freshly re-verified in this implementation pass.
	# Discussion Topic's shape (reference_doctype/reference_docname) WAS
	# verified live earlier this project.
	"LMS Timetable Legend": ("reference_doctype", "reference_docname"),
	"Discussion Topic": ("reference_doctype", "reference_docname"),
}

# --------------------------------------------------------------------------
# has_permission — the SAME generic qtt_platform function for all 4
# hook-only doctypes; nothing LMS-specific needed once the parent-link
# registries above exist (see qmp_lms_bridge/permissions.py's own
# docstring for why permission_query_conditions, unlike has_permission,
# does need one function per doctype).
# --------------------------------------------------------------------------
has_permission = {
	"Course Chapter": "qtt_platform.permissions.handlers.has_permission",
	"LMS Batch Timetable": "qtt_platform.permissions.handlers.has_permission",
	"LMS Timetable Legend": "qtt_platform.permissions.handlers.has_permission",
	"Discussion Topic": "qtt_platform.permissions.handlers.has_permission",
}

permission_query_conditions = {
	"Course Chapter": "qmp_lms_bridge.permissions.course_chapter_query_conditions",
	"LMS Batch Timetable": "qmp_lms_bridge.permissions.lms_batch_timetable_query_conditions",
	"LMS Timetable Legend": "qmp_lms_bridge.permissions.lms_timetable_legend_query_conditions",
	"Discussion Topic": "qmp_lms_bridge.permissions.discussion_topic_query_conditions",
}

# --------------------------------------------------------------------------
# Cross-tenant reference validation (hardening review section 7) for the
# denormalized doctypes that reference another tenant-owned document. See
# qmp_lms_bridge/validators.py's own confidence note on which field names
# were freshly verified this project vs. carried forward from earlier work.
# --------------------------------------------------------------------------
doc_events = {
	"Course Lesson": {"validate": "qmp_lms_bridge.validators.course_lesson_validate"},
	"LMS Quiz": {"validate": "qmp_lms_bridge.validators.lms_quiz_validate"},
	"LMS Enrollment": {"validate": "qmp_lms_bridge.validators.lms_enrollment_validate"},
	"LMS Batch Enrollment": {"validate": "qmp_lms_bridge.validators.lms_batch_enrollment_validate"},
	"LMS Certificate": {"validate": "qmp_lms_bridge.validators.lms_certificate_validate"},
	"LMS Live Class": {"validate": "qmp_lms_bridge.validators.lms_live_class_validate"},
	"LMS Assignment": {"validate": "qmp_lms_bridge.validators.lms_assignment_validate"},
}
