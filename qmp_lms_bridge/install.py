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

import frappe

from qtt_platform.product.registry import register_product, register_product_doctype

PRODUCT_KEY = "QMP_LMS"

#: Real name of the platform app this bridge depends on. Not expressed via
#: hooks.py's `required_apps` — see check_dependencies() below for why.
_PLATFORM_APP = "qtt_platform"


def check_dependencies():
	"""before_install hook: fail clearly if qtt_platform isn't installed
	on this site yet, without going through required_apps.

	Traced against the real Frappe 15 installer source
	(frappe/installer.py, version-15 branch) before writing this fix:

	  install_app(name) does, in this exact order:
	    1. installed_apps = frappe.get_installed_apps()          # DB-backed,
	       correct site-truth — but not used for the next step.
	    2. for app in app_hooks.required_apps:
	           required_app = parse_app_name(app)                # <-- crashes
	           install_app(required_app)
	    3. (only now) `if not force and name in installed_apps: return`

	parse_app_name() checks `name in frappe.get_all_apps()`, which reads
	ONLY `sites/apps.txt` (bench-wide) plus the site's own apps.txt — a
	flat file list of apps fetched via `bench get-app`, NOT the DB-tracked
	install state `get_installed_apps()` already computed one line above.
	`qtt_platform` is a private app with no public git remote, so if it
	was ever added to `apps/` without going through `bench get-app` (e.g.
	copied in directly + `pip install -e`), it's never added to
	sites/apps.txt even though it's genuinely installed on the site. When
	that happens, parse_app_name() falls through to
	fetch_details_from_tag() -> find_org(), which HEAD-requests
	https://api.github.com/repos/frappe/qtt_platform and
	.../erpnext/qtt_platform, gets 404 on both (it's private, published
	under neither org), and raises frappe.exceptions.InvalidRemoteException
	— before qmp_lms_bridge's own before_install hooks even run, so
	nothing in THIS app's hooks.py can intercept that failure. There is no
	required_apps flag or syntax for "local-only, never remote-resolve
	this one" in the installer — this is a hard constraint of how
	required_apps works, not a bug in qtt_platform or in this app's
	earlier hooks.py.

	The fix: don't ask the installer to resolve `qtt_platform` via
	required_apps at all. Check the real, DB-backed installed-apps list
	ourselves, in a before_install hook (runs after the required_apps
	loop above, so it never touches the broken code path) — this is the
	same frappe.get_installed_apps() the installer itself trusts as
	ground truth for "is this actually installed on this site."
	"""
	if _PLATFORM_APP not in frappe.get_installed_apps():
		frappe.throw(
			"qmp_lms_bridge requires the '{platform}' app to be installed on "
			"this site first.\n\nInstall it, then retry:\n\n"
			"  bench --site {site} install-app {platform}\n"
			"  bench --site {site} install-app qmp_lms_bridge".format(
				platform=_PLATFORM_APP, site=frappe.local.site
			),
			title="Missing dependency: {0}".format(_PLATFORM_APP),
		)

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
