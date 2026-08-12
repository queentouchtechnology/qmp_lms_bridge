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

No manual `hooks.py` edits on the server, no `sites/apps.txt` edits
required — the fix ships in this repository (see "Why `qtt_platform` is
not in `required_apps`" above) and takes effect the moment you pull it.

## Tests

- `qmp_lms_bridge/tests/test_install.py` — bench-independent, verifies
  `check_dependencies()`'s actual logic by injecting fake `frappe` /
  `qtt_platform` modules; runs with plain Python, no bench needed:
  `python -m unittest qmp_lms_bridge.tests.test_install -v`. This is the
  test that was actually run while building the fix above.
- `qmp_lms_bridge/tests/test_install_integration.py` — a real
  `FrappeTestCase` integration test for a live bench: `bench --site
  <test-site> run-tests --app qmp_lms_bridge --module
  qmp_lms_bridge.tests.test_install_integration`. Not executed during
  development (no bench access) — run it on your own bench to confirm
  end-to-end.
