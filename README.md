# QMP LMS Bridge

Registers **QMP LMS** as the first product on the **QTT SaaS Platform**
(`qtt_platform`). This is Phase 10 of that project's implementation order
— see `qtt_platform`'s own README for the full six-phase architecture
history this completes.

## Why a third app, instead of putting this in `lms` or `qtt_platform`

Two hard constraints, both established throughout this whole project,
collide without a bridge app:

1. **`lms` is upstream, vendor-maintained code.** Every phase of this
   project has refused to edit a single file inside it — an upstream
   `lms` update does a hard checkout of that repository, and anything
   placed inside it becomes indistinguishable from LMS's own tracked
   files at the next merge.
2. **`qtt_platform` must stay product-agnostic.** It's a hard rule
   throughout that codebase (see its own `hooks.py`): it never learns
   what a Course, a Batch, or an Instructor role means. Putting LMS's
   product registration, usage-counting logic, or cross-tenant validation
   there would break that boundary permanently — the next product (a
   future HRMS) would inherit LMS's own assumptions.

So the registration/bridging code — the part that genuinely needs to know
about *both* `lms`'s real doctypes and `qtt_platform`'s registration
APIs — lives in its own small app. `qtt_platform` never imports anything
from here. This app imports from `qtt_platform` (never edits it) and
reads/writes Custom Fields on `lms`'s doctypes via Frappe's own Custom
Field mechanism (never edits `lms`'s source).

## What this app does

| Piece | File |
|---|---|
| `tenant` Custom Field on the 12 anchor/denormalized LMS doctypes | `fixtures/custom_field.json` |
| Registers `QMP_LMS` as a `QTT Product`, its role catalog (Instructor/Manager/Staff/Student), and all 16 of its doctypes (12 tenant-scoped + 4 hook-only) | `install.py`, called from `after_install`/`after_migrate` |
| Usage resolvers (`max_students`, `max_instructors`, ...) | `usage.py`, registered via `hooks.py`'s `usage_resolvers` |
| Cross-tenant reference validation (Quiz→Course/Lesson, Enrollment→Course, ...) | `validators.py`, registered via `hooks.py`'s `doc_events` |
| `permission_query_conditions` for the 4 hook-only doctypes (Course Chapter, LMS Batch Timetable, LMS Timetable Legend, Discussion Topic) | `permissions.py` |
| `has_permission` for those same 4 doctypes | **Not written here** — `qtt_platform.permissions.handlers.has_permission` is fully generic and registered directly; see below |
| The 3 SaaS plans (Starter/Professional/Enterprise) and their entitlement limits | `plans.py`, called from `after_install`/`after_migrate` right after product registration |
| Role-based feature enforcement (which QMP_LMS product role may create/edit/delete which doctype) for all 16 registered doctypes | `roles.py`, registered via `hooks.py`'s `doc_events` (`validate` + `on_trash`) |

## SaaS lifecycle Phase G — role-based feature enforcement

`roles.py::_ROLE_MATRIX` maps each of the 16 doctypes this app
registers to which product role(s) may `write` (create or edit) and
`delete` it — a deliberate, documented interpretation of "Manager: LMS
administration / Instructor: teaching+course+batch operations / Staff:
staff-level operations / Student: learning-only" onto real doctypes,
since neither LMS nor the SaaS lifecycle brief publishes an
operation-by-operation table to consult. Full reasoning for every row is
in `roles.py`'s own module docstring — summary:

| Role | Can write | Can delete |
|---|---|---|
| Manager | everything (all 16) | everything (all 16) |
| Instructor | Course Chapter, Course Lesson, LMS Quiz, LMS Live Class, LMS Assignment, Discussion Topic | nothing |
| Staff | LMS Enrollment, LMS Batch Enrollment, LMS Certificate, LMS Batch Timetable, LMS Timetable Legend | LMS Enrollment, LMS Batch Enrollment |
| Student | Discussion Topic only | nothing |

Registered as `validate` (covers both create and edit — this matrix
makes no create-vs-edit distinction) and `on_trash` `doc_events` for all
16 doctypes; the 7 that already had a cross-tenant `validate` handler
(Phase 10) now run BOTH via `doc_events`' list-of-handlers form — Frappe
calls every handler in the list, so `roles.py`'s check is additive to
`validators.py`'s existing one, never a replacement.

**This is a SECOND, additional layer on top of LMS's own native
Frappe-Role DocPerm** (e.g. "Course Creator"), never a replacement — a
`validate()` hook only runs for a caller LMS's own permission system
already let through, so this can only narrow access further (reject a
user who lacks the right QMP_LMS product role even if their global
Frappe Role would otherwise allow the write), never widen it. No LMS
source file was touched to add this.

**Mechanism vs. data split**: the actual capability this relies on —
resolving which tenant a brand-new, not-yet-saved document belongs to
(needed because `validate()` fires before a new document is committed,
so the existing `resolve_tenant_for_doc()`'s database-lookup-by-name
approach doesn't work for it) — is generic and lives in `qtt_platform`
(`document_security.resolve_tenant_for_new_doc()`, new this phase);
`require_product_role()` (existing, unmodified) is what actually gates
the role. Only the role MATRIX itself — which is 100% QMP_LMS business
policy — lives in this app.

**System Manager bypass**: same precedent already established by
`qtt_platform.permissions.handlers.guard_tenant_change_before_save` — a
session holding the System Manager Frappe Role skips this check
entirely, so trusted administrative operations (bench console, install
scripts, a future scheduled job) are never blocked by a product-role
check that assumes an ordinary tenant member is acting.

**Update (production-readiness audit)**: student self-enrollment is now
implemented — `roles.py`'s `_ROLE_MATRIX` grants `Student` write on both
`LMS Enrollment` and `LMS Batch Enrollment`. This was resolved by reading
the real `frappe/lms` source (`develop` branch, both doctypes' own JSON):
`LMS Enrollment` grants the native `LMS Student` role `create=1, write=1,
if_owner=1`; `LMS Batch Enrollment` grants `create=1, if_owner=1` (no
edit after creation). Both doctypes' own controllers already enforce
eligibility (`disable_self_learning`/`allow_self_enrollment`,
`validate_owner()` forcing `owner == member`) — none of that is
reimplemented here, this module only adds the tenant/product-role check
on top. See `roles.py`'s own module docstring for the full reasoning,
including why granting "write" for `Student` on Batch Enrollment is safe
even though the real DocPerm is create-only (Frappe's native permission
check still runs first and independently blocks the edit).

## SaaS lifecycle Phase B — plan catalog

`plans.py::seed_plans()` create-or-updates exactly 3 `QTT Plan` rows
under `QMP_LMS`, each with 6 `QTT Plan Feature` child rows, on every
`after_install`/`after_migrate` — the same idempotent, re-apply-on-every-
migrate pattern `install.py::register_lms_product()` already established
for the product row itself:

| Plan | `plan_code` | Price | `max_students` | `max_batch_students` | `max_instructors` | `max_courses` | `max_batches` | `max_live_classes` |
|---|---|---|---|---|---|---|---|---|
| QMP LMS Starter | `STARTER` | ₹99/mo | 25 | 25 | 2 | 5 | 2 | 2 |
| QMP LMS Professional | `PROFESSIONAL` | ₹299/mo | 100 | 100 | 10 | 25 | 10 | 10 |
| QMP LMS Enterprise | `ENTERPRISE` | ₹799/mo | 500 | 500 | 50 | 100 | 50 | 50 |

All three: `billing_period=monthly`, `trial_days=7`, `is_public=1`.

**Why this lives here and not as a `qtt_platform` patch**: a Frappe
patch (`patches/v0_*`) runs at most once per site, tracked in `Patch
Log`. At the moment `qtt_platform`'s own `migrate` first runs, `QMP_LMS`
does not exist yet — `qmp_lms_bridge` installs afterward, per its own
`before_install` dependency check (see below). A patch would check for
the product, find nothing, no-op, and — because Frappe patches don't
retry — never run again. `after_install`/`after_migrate` hooks, by
contrast, run every time, which is what makes them the right place for
data that must track what's actually deployed. This also matches the
SaaS lifecycle brief's own architecture rule: the plan catalog and its
entitlement limits are QMP_LMS business data, not generic platform
infrastructure, so it belongs in this app, never in `qtt_platform`.

**No hardcoded plan checks anywhere** — `feature_key` values
(`max_students`, `max_batch_students`, `max_instructors`, `max_courses`,
`max_batches`, `max_live_classes`) match `usage.py`'s registered usage
resolvers exactly, so every limit above is enforced through
`qtt_platform.entitlement.engine.check_limit()` /
`qtt_platform.api.saas.get_plans()`, the same generic engine every other
phase already uses — nothing in this file, or anywhere else, branches on
`if plan_code == "STARTER"`.

Re-running `bench migrate` after editing `PLAN_CATALOG` in `plans.py`
updates the existing plan rows in place (price/limit changes take
effect immediately for every tenant reading `get_entitlements()`);
it never creates a duplicate plan for the same `plan_code`.

## Why `qtt_platform` is not in `required_apps`

`hooks.py` lists `required_apps = ["lms"]` only — `qtt_platform` is a real,
hard dependency (this whole app is meaningless without it) but is
deliberately **not** declared through `required_apps`. This was a real
production bug, found and fixed after the first install attempt on a real
bench, not a theoretical concern:

**What happened**: `bench --site app.quizmasterplus.in install-app
qmp_lms_bridge` failed with `frappe.exceptions.InvalidRemoteException`,
even though `qtt_platform` was genuinely already installed on that site.

**Root cause**, traced against the real Frappe 15 installer source
(`frappe/installer.py`, `version-15` branch) before writing the fix —
not guessed: `install_app()` computes `frappe.get_installed_apps()` (the
site's real, DB-tracked install state) but then does **not** use it to
resolve `required_apps` — instead, for every entry in `required_apps`, it
calls `parse_app_name(app)`, which checks membership in
`frappe.get_all_apps()`. That function reads `sites/apps.txt` (bench-wide)
plus the site's own `apps.txt` — flat files populated by `bench get-app`,
**not** the database. `qtt_platform` is a private app with no public git
remote; if it was ever placed into `apps/` without going through `bench
get-app` (e.g. copied in directly, then `pip install -e`), it's genuinely
installed on the site but still missing from `sites/apps.txt`. When
`parse_app_name` can't find it there, it falls through to
`fetch_details_from_tag()` → `find_org()`, which HEAD-requests
`https://api.github.com/repos/frappe/qtt_platform` and
`.../erpnext/qtt_platform` — both 404 (it's published under neither org)
— and raises `InvalidRemoteException`. This happens **before**
`qmp_lms_bridge`'s own `before_install` hooks even run, so nothing in this
app's own code could intercept it while `qtt_platform` stayed in
`required_apps`. There is no `required_apps` syntax for "this one is
local-only, never remote-resolve it" — that's a hard constraint of how the
installer works, not a bug in `qtt_platform` or in this app's earlier
`hooks.py`.

**The fix**: `qtt_platform` was removed from `required_apps` entirely.
Instead, `install.py`'s `check_dependencies()` runs as a real
`before_install` hook and checks `frappe.get_installed_apps()` directly —
the same DB-backed source `install_app()` itself trusts as ground truth,
just consulted at the right point in the flow. If `qtt_platform` really
isn't installed, this raises a clear `frappe.throw()` with the exact
install command to run first; if it is installed (regardless of whether
it's ever listed in `sites/apps.txt`), installation proceeds normally.
`lms` stays in `required_apps` unchanged — it's a real, publicly gettable
app, so `parse_app_name` resolves it without ever reaching the remote
fallback.

**Also worth doing, separately, on the bench itself** (optional — not
required for `qmp_lms_bridge` to install correctly, since the code no
longer depends on it): add `qtt_platform` as a line in the bench-wide
`sites/apps.txt` so other bench tooling that does consult that file
(`bench get-app`, `bench build --app qtt_platform`, etc.) recognizes it
too. That's bench/environment hygiene, not part of this app's fix.

## The parent-walk extension this phase made to `qtt_platform` itself

Phase 3 of `qtt_platform` deliberately left `resolve_tenant_for_doc()`
implementing only the direct-`tenant`-field case, with an explicit note
that the parent-walk case (for hook-only doctypes) would be added "when
the first such doctype is actually registered" rather than guessed at in
advance. That's now — but the actual extension lives in `qtt_platform`
itself (`document_security.py`), not here, because the *mechanism* (walk
to a registered parent field, or a registered polymorphic
reference_doctype/reference_docname pair, recursively) is generic
infrastructure any future product can use. Only the *data* — which
doctype maps to which parent field — is LMS-specific, and that data is
declared in this app's own `hooks.py` (`tenant_parent_links` /
`tenant_dynamic_parent_links`), read by `qtt_platform` via the same
`frappe.get_hooks()` aggregation pattern already used for
`usage_resolvers`.

`has_permission` for the 4 hook-only doctypes needed **zero new code** as
a result — `qtt_platform.permissions.handlers.has_permission` (built in
Phase 7, unregistered until now for lack of a real target) works
correctly the moment the parent-link registries exist. Only
`permission_query_conditions` needed real, doctype-specific SQL here,
since that hook's shape is inherently not genericizable (see the
hardening review section 2/17 and `permissions.py`'s own docstring).

## Module layout: why `qmp_lms_bridge/qmp_lms_bridge/qmp_lms_bridge/` exists and is empty

After the `required_apps` fix above, installation failed a second time
with `ModuleNotFoundError: No module named 'qmp_lms_bridge.qmp_lms_bridge'`.
Traced against the real Frappe 15 source (`version-15` branch) before
fixing, not guessed:

- `modules.txt` (this app's, one line: `QMP LMS Bridge`) is read by
  `frappe.get_module_list()` and passed through `frappe.scrub()`
  (lowercase, spaces → underscores) — `"QMP LMS Bridge"` becomes
  `"qmp_lms_bridge"`, stored in `frappe.local.app_modules["qmp_lms_bridge"]`.
- During `install-app`, `frappe/model/sync.py`'s `sync_for()` does, for
  every scrubbed module name: `frappe.get_module(app_name + "." +
  module_name)` — i.e. `frappe.get_module("qmp_lms_bridge.qmp_lms_bridge")`.
  `frappe.get_module()` is a thin wrapper over
  `importlib.import_module()`.
- This is standard, unavoidable Frappe app structure, the same shape
  `bench new-app` generates for every app: `<repo>/<app>/modules.txt`
  declares a module name, and `<repo>/<app>/<scrubbed_module_name>/`
  must exist as a real importable package (at minimum an empty
  `__init__.py`) — Frappe imports it to build the search path for that
  module's doctypes/pages/reports, even when there are none.

**What was actually wrong**: this app's Phase 10 build originally
scaffolded a `qmp_lms_bridge/qmp_lms_bridge/doctype/` folder (copying the
pattern from `qtt_platform`, which does define its own doctypes), then
that whole folder — including the required `__init__.py` — was deleted
once it became clear this app defines zero doctypes of its own, since it
only carries Custom Field fixtures. Deleting the *whole* folder instead
of just the incorrect `doctype/` subfolder inside it left `modules.txt`
pointing at a module folder that no longer existed. `python -m py_compile`
never catches this class of bug — it checks syntax file-by-file and has
no notion of "this dotted import path must resolve" the way Frappe's
installer does.

**The fix**: restored `qmp_lms_bridge/qmp_lms_bridge/qmp_lms_bridge/`
with a single empty `__init__.py` — deliberately empty, since this app
still defines no doctypes/pages/reports of its own; Frappe's module sync
(`get_doc_files()`) just finds no `doctype/`/`page/`/`report/`
subfolders under it and moves on, which is safe and expected for a
fixtures-and-hooks-only app.

## Fixture naming: why every Custom Field fixture needs an explicit `name`

After the module-layout fix above, installation failed a third time with
`KeyError: 'name'` while importing `fixtures/custom_field.json`. Traced
against real Frappe 15 source before fixing, not guessed:

- Fixture sync runs `frappe.utils.fixtures.sync_fixtures()` ->
  `frappe.core.doctype.data_import.data_import.import_doc()` ->
  `frappe.modules.import_file.import_file_by_path()`. The very first
  thing that function does with each record in the JSON list is
  `frappe.db.get_value(doc["doctype"], doc["name"], "modified")` — a
  plain dict access, called *before* `frappe.get_doc()` or `.insert()`
  ever run.
- A DocType's own `autoname()` (for Custom Field:
  `self.name = self.dt + "-" + self.fieldname`, in
  `frappe/custom/doctype/custom_field/custom_field.py`) only fires
  during `.insert()` — too late to satisfy the line above. Every fixture
  record must ship an explicit `name` that already matches what that
  autoname would produce.

**The fix**: every one of the 12 records in `fixtures/custom_field.json`
now carries `"name": "<dt>-tenant"` (e.g. `"LMS Course-tenant"`,
`"LMS Batch Enrollment-tenant"`) — Custom Field's real, documented
autoname convention (`<dt>-<fieldname>`), read from Frappe's own source,
not invented. All 12 intended doctypes/fields are unchanged; only the
`name` key was added.

**Idempotency**: `import_doc()` does `if frappe.db.exists(doc.doctype,
doc.name): delete_old_doc(doc, ...)` before `doc.insert()` — every
fixture sync deletes and re-creates the row with that exact name. Since
`<dt>-<fieldname>` never changes for these fields, repeated
`install-app`/`migrate` runs always target the same 12 rows — safe to
re-run any number of times.

**On requirement to re-validate the 12 doctypes/`insert_after` positions
against live LMS metadata**: attempted this — `GET
/api/resource/DocType/<name>` against `app.quizmasterplus.in` requires an
authenticated System Manager session (confirmed live: an unauthenticated
request returns `403 PermissionError`, "Guest does not have doctype
access"), and no site credentials were available in the session that
built this fix. The 12 doctype names and `insert_after` values are
therefore **unchanged from the existing confidence grading already
documented below** — not newly re-verified. Nothing here should be
treated as freshly confirmed just because this fix pass touched the
file; only the `name` keys are new.

## Confidence notes — read before deploying

This implementation pass was done from this project's own accumulated
knowledge of the LMS schema (extensive live verification across earlier
phases of the broader project), not fresh live queries against the
backend in this specific pass. Two honest distinctions:

- **Verified live, this project, with high confidence**: `LMS Quiz.course`,
  `LMS Quiz.lesson`, `Course Lesson.chapter`, `Discussion Topic`'s
  `reference_doctype`/`reference_docname` shape, and the existence of the
  five anchor doctypes (`LMS Course`, `LMS Batch`, `LMS Zoom Settings`,
  `Course Evaluator`, `LMS Category`) with their key fields.
- **Carried forward from earlier work, not freshly re-verified this
  pass**: exact field names on `LMS Enrollment` (`course`),
  `LMS Batch Enrollment` (`batch`), `LMS Certificate` (`course`),
  `LMS Live Class` (`batch`), `LMS Assignment` (`course`), and
  `LMS Timetable Legend`'s polymorphic shape (assumed to match
  `Discussion Topic`'s `reference_doctype`/`reference_docname` pattern,
  based on an earlier Flutter-side discovery that it requires a
  `reference_doctype` value).

**Before installing on a real site**: confirm every field name above
against the live DocType metadata (the same
`GET /api/resource/DocType/<name>` pattern used throughout this whole
project). A wrong field name fails safe here — `require_same_tenant_reference`
and the parent-link resolvers both treat a missing/None field as "nothing
to check" rather than crashing or silently allowing a violation — but a
wrong name means that specific cross-tenant guard isn't actually
protecting anything yet, which should be caught and fixed before this
matters for real data.

The `insert_after` values in `fixtures/custom_field.json` are best-effort
form-layout placement, cosmetic only — a wrong value places the new field
in a slightly different spot on the Desk form, nothing more.

## Deployment

```bash
# from the bench directory — lms and qtt_platform must already be installed
bench get-app qmp_lms_bridge /path/to/this/qmp_lms_bridge
bench --site app.quizmasterplus.in install-app qmp_lms_bridge
bench --site app.quizmasterplus.in migrate
```

`install-app` first runs `before_install` (`check_dependencies()` —
confirms `qtt_platform` is really installed on this site, and fails with
a clear message and the exact fix command if it isn't), then triggers
`after_install` (registers the product). `migrate` syncs the Custom Field
fixtures and re-runs registration (idempotent). Confirm all 12 Custom
Fields exist and `QTT Product/QMP_LMS` resolves before treating this as
live — and re-run the full `qtt_platform` security test suite (see its
own README) against real two-tenant LMS data before this governs
production access.

**Updating an existing bench that already hit the `InvalidRemoteException`
bug** (i.e. `qmp_lms_bridge` is cloned into `apps/` but `install-app`
never completed):

```bash
cd apps/qmp_lms_bridge
git pull origin main
bench --site app.quizmasterplus.in install-app qmp_lms_bridge
bench --site app.quizmasterplus.in migrate
```

No manual `hooks.py` edits on the server, no `sites/apps.txt` edits, no
manual folder creation, no manual `custom_field.json` edits required —
every fix ships in this repository (see "Why `qtt_platform` is not in
`required_apps`", "Module layout", and "Fixture naming" above) and takes
effect the moment you pull it.

## Tests

- `qmp_lms_bridge/tests/test_install.py` — bench-independent, verifies
  `check_dependencies()`'s actual logic by injecting fake `frappe` /
  `qtt_platform` modules; runs with plain Python, no bench needed:
  `python -m unittest qmp_lms_bridge.tests.test_install -v`. Actually run
  while building that fix.
- `qmp_lms_bridge/tests/test_module_structure.py` — bench-independent,
  reproduces Frappe's exact `modules.txt` → `scrub()` →
  `frappe.get_module(app + "." + module)` sequence (frappe/__init__.py +
  frappe/model/sync.py, read from source, not guessed) against this
  repo's real files — fails the same way `install-app` did if the module
  folder is ever deleted again: `python -m unittest
  qmp_lms_bridge.tests.test_module_structure -v`. Actually run while
  building that fix.
- `qmp_lms_bridge/tests/test_fixtures.py` — bench-independent: a generic
  guard that every record in every `fixtures/*.json` file has a `name`
  key (catches the exact `KeyError: 'name'` class of bug for any future
  fixture, not just this one), plus Custom-Field-specific checks (exactly
  12 records, one per intended LMS doctype, `name` matches Frappe's real
  `<dt>-<fieldname>` autoname convention, names unique):
  `python -m unittest qmp_lms_bridge.tests.test_fixtures -v`. Actually
  run while building that fix.
- `qmp_lms_bridge/tests/test_install_integration.py` — a real
  `FrappeTestCase` integration test for a live bench: `bench --site
  <test-site> run-tests --app qmp_lms_bridge --module
  qmp_lms_bridge.tests.test_install_integration`. Not executed during
  development (no bench access) — run it on your own bench to confirm
  end-to-end.
- `qmp_lms_bridge/tests/test_plans.py` — bench-independent: pins the
  exact price/limit figures in `PLAN_CATALOG` against the SaaS lifecycle
  brief (catches a pricing/entitlement typo, not just a code bug), plus
  `seed_plans()`'s create-vs-update branching (no-op when `QMP_LMS`
  doesn't exist yet, creates exactly 3 plans with 6 feature rows each
  when none exist, updates in place rather than duplicating when they
  already do): `python -m unittest qmp_lms_bridge.tests.test_plans -v`.
  Actually run while building Phase B — 9/9 pass.

**On a real bench**, additionally confirm: `bench --site <site>
console` → `frappe.get_all("QTT Plan", filters={"product": "QMP_LMS"},
fields=["plan_code", "base_price", "trial_days"])` returns all 3 with
the correct prices; `qtt_platform.entitlement.engine.get_entitlements(<a
Starter tenant>, "QMP_LMS")["max_students"] == 25`; editing a limit in
`PLAN_CATALOG` and re-running `bench migrate` updates the existing plan
row (same `name`) rather than creating a fourth one.

- `qmp_lms_bridge/tests/test_roles.py` — bench-independent (SaaS
  lifecycle Phase G): pins the entire `_ROLE_MATRIX` against the
  documented policy (Manager sees every doctype in both write and
  delete; Instructor/Staff appear in `write` but never `delete` except
  Staff on the two enrollment doctypes; Student appears only on
  `Discussion Topic`; all 16 registered doctypes are covered, no more,
  no less), plus `enforce_role_on_write`/`enforce_role_on_delete`'s own
  logic (calls `require_product_role` with exactly the matrix's roles
  for a governed doctype, no-ops for an ungoverned one, the System
  Manager bypass, raises when tenant can't be resolved rather than
  failing open): `python -m unittest qmp_lms_bridge.tests.test_roles -v`.
  Actually run while building Phase G — 15/15 pass. Fakes
  `qtt_platform.document_security`/`qtt_platform.product.guards`
  directly (same technique as `test_install.py`'s `qtt_platform.product.
  registry` fake) rather than importing the real qtt_platform package,
  since it isn't on this dev environment's Python path outside a real
  bench.

**On a real bench**, additionally confirm: a user with only QMP_LMS
`Instructor` product access, attempting to create an `LMS Course`
directly (e.g. via the Desk, if their Frappe Role happens to also
include `Course Creator`) → rejected with a `PermissionError` from
`require_product_role`, even though LMS's own DocPerm would otherwise
have allowed it; the same Instructor creating a `Course Lesson` within a
course they have access to → succeeds; a `Student` attempting to create
a `Discussion Topic` → succeeds; a `Student` attempting to create an
`LMS Enrollment` (self-enrollment) → rejected, consistent with the
documented known limitation above (there is no path that currently
allows it, by design, pending live confirmation of the real
self-enrollment mechanism).
