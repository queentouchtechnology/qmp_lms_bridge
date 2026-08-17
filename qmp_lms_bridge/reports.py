"""
LMS-level reports (production-readiness audit, P4) — six reports over
data this app already governs (course/quiz/enrollment/certificate rows,
all carrying the `tenant` Custom Field this app's own fixtures add — see
hooks.py's own docstring on the 12 anchor doctypes that get one).

Same one-dispatcher-per-app shape as `qtt_platform/api/reports.py`
(dict of report_key -> handler, one whitelisted entrypoint) — kept
separate from that module rather than shared because the role gate here
is product-level (`require_product_role`, Manager/Instructor — the same
function and role pair `ai_features.py` already uses for AI spend) while
qtt_platform's reports are tenant-governance-level
(`require_tenant_role`, Owner/Admin); qtt_platform must never import
this app, so a shared dispatcher isn't an option anyway.

Two of the originally-sketched report definitions were corrected against
real LMS field data (fetched live from the LMS source, not guessed) while
writing this file:
- "Batch attendance" doesn't correspond to any real field on `LMS Batch
  Enrollment` (member, member_name, batch, payment, source — no
  attendance/present concept at all) — renamed to "Batch enrollment"
  (headcount per batch), which the real fields actually support.
- "Instructor activity" groups by `owner` (Frappe's own standard
  created-by field), not `LMS Course.instructors` — that field is a
  child table whose exact shape wasn't independently verified this pass,
  and `owner` already answers "who authored this content," the same
  question the report is asking.
"""

import frappe

from qtt_platform.errors import fail, ok
from qtt_platform.product.guards import require_product_role
from qtt_platform.tenant.context import resolve_active_tenant

PRODUCT_KEY = "QMP_LMS"
_REPORT_ROLES = ("Manager", "Instructor")


def _date_filter(field: str, date_from: str | None, date_to: str | None) -> tuple[str, list]:
	if date_from and date_to:
		return f" AND {field} BETWEEN %s AND %s", [date_from, date_to]
	if date_from:
		return f" AND {field} >= %s", [date_from]
	if date_to:
		return f" AND {field} <= %s", [date_to]
	return "", []


def _course_engagement_report(tenant: str, date_from: str | None, date_to: str | None) -> dict:
	date_clause, date_params = _date_filter("e.creation", date_from, date_to)
	rows = frappe.db.sql(
		f"""
		SELECT c.name AS course, c.title, COUNT(e.name) AS enrollment_count,
			AVG(e.progress) AS avg_progress
		FROM `tabLMS Course` c
		LEFT JOIN `tabLMS Enrollment` e ON e.course = c.name AND e.tenant = %s {date_clause}
		WHERE c.tenant = %s
		GROUP BY c.name, c.title
		ORDER BY enrollment_count DESC
		""",
		[tenant, *date_params, tenant],
		as_dict=True,
	)
	return {
		"summary": {
			"course_count": len(rows),
			"total_enrollments": sum(r.enrollment_count or 0 for r in rows),
		},
		"rows": rows,
	}


def _quiz_performance_report(tenant: str, date_from: str | None, date_to: str | None) -> dict:
	# `tenant` (Custom Field added alongside quiz_grading.py's grading
	# endpoint — this doctype had none before, so this query previously
	# referenced a column that didn't exist and would have thrown a real
	# SQL error on every call). Pass/fail is derived from
	# percentage/passing_percentage — `LMS Quiz Submission` has no Pass/
	# Fail string field; `result` is the per-question child table, not a
	# scalar column, so comparing it to a string would also have failed.
	date_clause, date_params = _date_filter("creation", date_from, date_to)
	rows = frappe.db.sql(
		f"""
		SELECT quiz, quiz_title,
			COUNT(*) AS submission_count,
			AVG(percentage) AS avg_percentage,
			SUM(CASE WHEN percentage >= passing_percentage THEN 1 ELSE 0 END) AS pass_count,
			SUM(CASE WHEN percentage < passing_percentage THEN 1 ELSE 0 END) AS fail_count
		FROM `tabLMS Quiz Submission`
		WHERE tenant = %s {date_clause}
		GROUP BY quiz, quiz_title
		ORDER BY submission_count DESC
		""",
		[tenant, *date_params],
		as_dict=True,
	)
	total_submissions = sum(r.submission_count or 0 for r in rows)
	total_pass = sum(r.pass_count or 0 for r in rows)
	return {
		"summary": {
			"quiz_count": len(rows),
			"total_submissions": total_submissions,
			"overall_pass_rate": (total_pass / total_submissions * 100) if total_submissions else 0,
		},
		"rows": rows,
	}


def _batch_enrollment_report(tenant: str, date_from: str | None, date_to: str | None) -> dict:
	date_clause, date_params = _date_filter("be.creation", date_from, date_to)
	rows = frappe.db.sql(
		f"""
		SELECT b.name AS batch, b.title, COUNT(be.name) AS enrollment_count
		FROM `tabLMS Batch` b
		LEFT JOIN `tabLMS Batch Enrollment` be ON be.batch = b.name AND be.tenant = %s {date_clause}
		WHERE b.tenant = %s
		GROUP BY b.name, b.title
		ORDER BY enrollment_count DESC
		""",
		[tenant, *date_params, tenant],
		as_dict=True,
	)
	return {
		"summary": {"batch_count": len(rows), "total_enrollments": sum(r.enrollment_count or 0 for r in rows)},
		"rows": rows,
	}


def _instructor_activity_report(tenant: str, date_from: str | None, date_to: str | None) -> dict:
	course_clause, course_params = _date_filter("creation", date_from, date_to)
	courses = frappe.db.sql(
		f"""SELECT owner, COUNT(*) AS course_count FROM `tabLMS Course`
		WHERE tenant = %s {course_clause} GROUP BY owner""",
		[tenant, *course_params],
		as_dict=True,
	)
	quiz_clause, quiz_params = _date_filter("creation", date_from, date_to)
	quizzes = frappe.db.sql(
		f"""SELECT owner, COUNT(*) AS quiz_count FROM `tabLMS Quiz`
		WHERE tenant = %s {quiz_clause} GROUP BY owner""",
		[tenant, *quiz_params],
		as_dict=True,
	)
	by_owner: dict[str, dict] = {}
	for row in courses:
		by_owner.setdefault(row.owner, {"instructor": row.owner, "course_count": 0, "quiz_count": 0})
		by_owner[row.owner]["course_count"] = row.course_count
	for row in quizzes:
		by_owner.setdefault(row.owner, {"instructor": row.owner, "course_count": 0, "quiz_count": 0})
		by_owner[row.owner]["quiz_count"] = row.quiz_count

	rows = sorted(by_owner.values(), key=lambda r: r["course_count"] + r["quiz_count"], reverse=True)
	return {"summary": {"instructor_count": len(rows)}, "rows": rows}


def _certificate_issuance_report(tenant: str, date_from: str | None, date_to: str | None) -> dict:
	date_clause, date_params = _date_filter("issue_date", date_from, date_to)
	rows = frappe.db.sql(
		f"""
		SELECT name, course, course_title, member, member_name, issue_date, expiry_date, published
		FROM `tabLMS Certificate`
		WHERE tenant = %s {date_clause}
		ORDER BY issue_date DESC
		""",
		[tenant, *date_params],
		as_dict=True,
	)
	return {"summary": {"certificate_count": len(rows)}, "rows": rows}


def _student_progress_report(tenant: str, date_from: str | None, date_to: str | None) -> dict:
	date_clause, date_params = _date_filter("e.creation", date_from, date_to)
	rows = frappe.db.sql(
		f"""
		SELECT e.member, e.member_name, e.course, c.title AS course_title, e.progress, e.current_lesson
		FROM `tabLMS Enrollment` e
		INNER JOIN `tabLMS Course` c ON c.name = e.course
		WHERE e.tenant = %s {date_clause}
		ORDER BY e.member_name ASC
		""",
		[tenant, *date_params],
		as_dict=True,
	)
	completed = [r for r in rows if (r.progress or 0) >= 100]
	return {
		"summary": {"enrollment_count": len(rows), "completed_count": len(completed)},
		"rows": rows,
	}


_REPORTS = {
	"course_engagement": _course_engagement_report,
	"quiz_performance": _quiz_performance_report,
	"batch_enrollment": _batch_enrollment_report,
	"instructor_activity": _instructor_activity_report,
	"certificate_issuance": _certificate_issuance_report,
	"student_progress": _student_progress_report,
}


@frappe.whitelist()
def get_report(report_key: str, date_from: str | None = None, date_to: str | None = None) -> dict:
	tenant = resolve_active_tenant()
	if not tenant:
		return fail("TENANT_ACCESS_DENIED", "No active tenant.")

	try:
		require_product_role(tenant, PRODUCT_KEY, list(_REPORT_ROLES))
	except frappe.PermissionError as exc:
		return fail("ROLE_PERMISSION_DENIED", str(exc))

	handler = _REPORTS.get(report_key)
	if not handler:
		return fail("REPORT_NOT_FOUND", f"Unknown report: {report_key}")

	return ok(handler(tenant, date_from, date_to))
