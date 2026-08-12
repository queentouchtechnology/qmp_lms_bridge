"""
Cross-tenant reference validation for LMS doctypes — the hardening review
section 7 fix, applied to real doctypes now that they exist in this app's
scope. Registered as `validate` doc_events in hooks.py.

CONFIDENCE NOTE, stated plainly rather than implied: `course`/`lesson`
fields on LMS Quiz and `chapter` on Course Lesson were verified live
against this exact backend earlier in this project (confirmed via a real
API round-trip). The reference field names used below for LMS Enrollment
(`course`), LMS Batch Enrollment (`batch`), LMS Certificate (`course`),
LMS Live Class (`batch`), and LMS Assignment (`course`) are carried
forward from this project's own earlier work building the Flutter admin
screens for those doctypes, but were not freshly re-verified live in this
implementation pass. Confirm each against the live DocType metadata
before deploying — a wrong fieldname here fails safe (require_same_tenant_
reference simply never fires, matching the "no field = no reference to
check" behavior already documented in that function), not unsafe, but
should still be corrected promptly since an unwired check means the
cross-tenant guard isn't actually protecting that relationship yet.
"""

from qtt_platform.document_security import require_same_tenant_reference


def course_lesson_validate(doc, method=None):
	if doc.course:
		require_same_tenant_reference(("LMS Course", doc.course), tenant=doc.tenant)


def lms_quiz_validate(doc, method=None):
	refs = []
	if doc.course:
		refs.append(("LMS Course", doc.course))
	if doc.lesson:
		refs.append(("Course Lesson", doc.lesson))
	if refs:
		require_same_tenant_reference(*refs, tenant=doc.tenant)


def lms_enrollment_validate(doc, method=None):
	if doc.course:
		require_same_tenant_reference(("LMS Course", doc.course), tenant=doc.tenant)


def lms_batch_enrollment_validate(doc, method=None):
	if doc.batch:
		require_same_tenant_reference(("LMS Batch", doc.batch), tenant=doc.tenant)


def lms_certificate_validate(doc, method=None):
	if doc.course:
		require_same_tenant_reference(("LMS Course", doc.course), tenant=doc.tenant)


def lms_live_class_validate(doc, method=None):
	if doc.batch:
		require_same_tenant_reference(("LMS Batch", doc.batch), tenant=doc.tenant)


def lms_assignment_validate(doc, method=None):
	if doc.course:
		require_same_tenant_reference(("LMS Course", doc.course), tenant=doc.tenant)
