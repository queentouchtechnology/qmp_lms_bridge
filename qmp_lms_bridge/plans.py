"""
QMP_LMS's own SaaS plan catalog and per-plan entitlement limits (SaaS
customer lifecycle, Phase B).

Deliberately NOT in qtt_platform. QTT Plan / QTT Plan Feature are generic
platform doctypes any product may write rows into, but WHICH plans exist,
what they cost, and what their limits are is 100% QMP_LMS business data
— exactly what the SaaS lifecycle brief's own architecture rule (Part 50)
assigns to qmp_lms_bridge ("QMP_LMS entitlement catalog" is listed there
as this app's responsibility, not qtt_platform's).

Called from hooks.py's after_install/after_migrate, right after
register_lms_product() (QMP_LMS must exist as a QTT Product before a
QTT Plan can reference it) — every migrate re-applies this catalog, the
same create-or-update-idempotent pattern
qtt_platform.product.registry.register_product() already established for
the product row itself. This is also why plan-seeding could NOT live in
a qtt_platform patch (patches/v0_*): a Frappe patch runs at most once per
site, tracked in Patch Log, and at the time qtt_platform's own migrate
first runs, QMP_LMS does not exist yet (qmp_lms_bridge installs
afterward, per its own before_install dependency check) — a patch would
silently no-op forever. after_install/after_migrate hooks, by contrast,
run every time and are exactly the right place for data that must track
what's actually deployed.

feature_key values match qmp_lms_bridge/usage.py's registered usage
resolvers exactly (max_students, max_batch_students, max_instructors,
max_courses, max_batches, max_live_classes) — this is what makes these
real, server-enforced limits through
qtt_platform.entitlement.engine.check_limit(), not just descriptive
numbers on a pricing page.

No `plan_order` field exists on QTT Plan (and none is added here — see
the SaaS lifecycle brief's own instruction not to add fields beyond
Phase C's explicit list). The 1/2/3 ordering the brief asks for already
falls out of `base_price` ascending (99 < 299 < 799) — qtt_platform.
api.saas.get_plans() already sorts `order_by="base_price asc"`, so
Starter/Professional/Enterprise is the natural result without a new
field.
"""

import frappe

PRODUCT_KEY = "QMP_LMS"
TRIAL_DAYS = 7
BILLING_PERIOD = "monthly"

#: The three initial SaaS plans, in ascending price order. Explicitly
#: labelled in the SaaS lifecycle brief as "initial product catalog
#: values" — not assumed permanent; changing a price/limit here and
#: re-running migrate is the intended way to evolve the catalog, with no
#: change to any platform code.
PLAN_CATALOG = [
	{
		"plan_code": "STARTER",
		"display_name": "QMP LMS Starter",
		"base_price": 99,
		"features": {
			"max_students": 25,
			"max_batch_students": 25,
			"max_instructors": 2,
			"max_courses": 5,
			"max_batches": 2,
			"max_live_classes": 2,
		},
	},
	{
		"plan_code": "PROFESSIONAL",
		"display_name": "QMP LMS Professional",
		"base_price": 299,
		"features": {
			"max_students": 100,
			"max_batch_students": 100,
			"max_instructors": 10,
			"max_courses": 25,
			"max_batches": 10,
			"max_live_classes": 10,
		},
	},
	{
		"plan_code": "ENTERPRISE",
		"display_name": "QMP LMS Enterprise",
		"base_price": 799,
		"features": {
			"max_students": 500,
			"max_batch_students": 500,
			"max_instructors": 50,
			"max_courses": 100,
			"max_batches": 50,
			"max_live_classes": 50,
		},
	},
]


def seed_plans() -> None:
	if not frappe.db.exists("QTT Product", PRODUCT_KEY):
		# register_lms_product() must have already run in this same
		# after_install/after_migrate pass (see hooks.py's call order) —
		# if QMP_LMS genuinely doesn't exist yet, there's nothing to
		# attach a plan to. Not expected to actually happen given the
		# call order, but fails closed (no-op) rather than crashing the
		# whole migrate over a plan catalog.
		return
	for plan_data in PLAN_CATALOG:
		_upsert_plan(plan_data)


def _upsert_plan(plan_data: dict) -> None:
	existing_name = frappe.db.exists(
		"QTT Plan", {"product": PRODUCT_KEY, "plan_code": plan_data["plan_code"]}
	)
	if existing_name:
		plan = frappe.get_doc("QTT Plan", existing_name)
	else:
		plan = frappe.new_doc("QTT Plan")
		plan.product = PRODUCT_KEY
		plan.plan_code = plan_data["plan_code"]

	plan.display_name = plan_data["display_name"]
	plan.base_price = plan_data["base_price"]
	plan.billing_period = BILLING_PERIOD
	plan.trial_days = TRIAL_DAYS
	plan.is_public = 1

	plan.set("features", [])
	for feature_key, limit_value in plan_data["features"].items():
		plan.append("features", {"feature_key": feature_key, "limit_value": str(limit_value)})

	if existing_name:
		plan.save(ignore_permissions=True)
	else:
		plan.insert(ignore_permissions=True)
