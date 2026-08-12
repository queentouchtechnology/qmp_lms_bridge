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

`install-app` triggers `after_install` (registers the product). `migrate`
syncs the Custom Field fixtures and re-runs registration (idempotent).
Confirm all 12 Custom Fields exist and `QTT Product/QMP_LMS` resolves
before treating this as live — and re-run the full `qtt_platform`
security test suite (see its own README) against real two-tenant LMS
data before this governs production access.
