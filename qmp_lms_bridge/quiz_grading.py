"""
Server-side quiz grading (Quiz Integrity pass) — replaces the previous
client-computed-score flow (qzmaster's quiz_repository_impl.dart, Phase 1
of the SaaS rebuild). The client now sends only the quiz name and the
student's raw answers; it never computes a score and never fetches
is_correct_*/possibility_* for itself. Both closes the "a modified
client can submit any score" gap and the "correct answers reach the
device before grading" gap the original architecture audit flagged
together as one finding.

Grading rules are a direct port of the Dart logic Phase 1 wrote in
quiz_repository_impl.dart's submitAnswers — same rules, moved here, not
redesigned: Choices single-select (exact index match), Choices
multi-select (exact set match against every is_correct_N), User Input
(case-insensitive match against any non-empty possibility_N), Open Ended
(never auto-graded — no answer key exists for it, see the sample_answer
Custom Field's own docstring).

Directly `@frappe.whitelist()`'d, not routed through the AI feature
registry (ai_features.py) — this isn't a per-product-feature AI handler,
it's a plain LMS action, same shape as reports.py's get_report.
"""

import json

import frappe
from frappe import _

from qtt_platform.document_security import assert_tenant_access
from qtt_platform.tenant.context import resolve_active_tenant

PRODUCT_KEY = "QMP_LMS"

_CORRECTNESS_FIELDS = [
	"name", "question", "type", "multiple",
	"option_1", "option_2", "option_3", "option_4",
	"is_correct_1", "is_correct_2", "is_correct_3", "is_correct_4",
	"possibility_1", "possibility_2", "possibility_3", "possibility_4",
]


def _as_int(value):
	try:
		return int(value)
	except (TypeError, ValueError):
		return None


def _grade_choices_multiple(question: dict, answer) -> tuple[bool, str]:
	selected: set[int] = set()
	if isinstance(answer, list):
		for value in answer:
			parsed = _as_int(value)
			if parsed is not None:
				selected.add(parsed)
	correct = {i for i in range(1, 5) if question.get(f"is_correct_{i}")}
	is_correct = bool(selected) and selected == correct
	answer_text = ",".join(f"option_{i}" for i in sorted(selected))
	return is_correct, answer_text


def _grade_choices_single(question: dict, answer) -> tuple[bool, str]:
	selected_no = _as_int(answer)
	is_correct = selected_no is not None and bool(question.get(f"is_correct_{selected_no}"))
	answer_text = f"option_{selected_no}" if selected_no is not None else ""
	return is_correct, answer_text


def _grade_user_input(question: dict, answer) -> tuple[bool, str]:
	typed = answer.strip().lower() if isinstance(answer, str) else ""
	acceptable = {
		question[f"possibility_{i}"].strip().lower()
		for i in range(1, 5)
		if (question.get(f"possibility_{i}") or "").strip()
	}
	is_correct = bool(typed) and typed in acceptable
	answer_text = answer if isinstance(answer, str) else ""
	return is_correct, answer_text


@frappe.whitelist()
def submit_quiz(quiz: str, answers) -> dict:
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("You must be logged in to submit a quiz."), frappe.PermissionError)

	if isinstance(answers, str):
		try:
			answers = json.loads(answers)
		except (TypeError, ValueError):
			frappe.throw(_("Invalid answers payload."), frappe.ValidationError)
	if not isinstance(answers, dict):
		frappe.throw(_("Invalid answers payload."), frappe.ValidationError)

	if not frappe.db.exists("LMS Quiz", quiz):
		frappe.throw(_("Quiz not found."), frappe.ValidationError)

	tenant = resolve_active_tenant(user=user)
	if not tenant:
		frappe.throw(_("No active tenant."), frappe.PermissionError)
	# Raises frappe.PermissionError if this quiz doesn't belong to the
	# caller's active tenant or they lack QMP_LMS product access.
	assert_tenant_access("LMS Quiz", quiz, user=user)

	quiz_doc = frappe.get_doc("LMS Quiz", quiz)

	max_attempts = quiz_doc.get("max_attempts") or 0
	if max_attempts:
		# Not previously enforced anywhere — Flutter only ever displayed
		# the limit, never blocked a resubmission past it.
		existing_attempts = frappe.db.count("LMS Quiz Submission", {"quiz": quiz, "member": user})
		if existing_attempts >= max_attempts:
			frappe.throw(
				_("You have used all {0} attempt(s) allowed for this quiz.").format(max_attempts),
				frappe.ValidationError,
			)

	question_refs = quiz_doc.get("questions") or []
	question_names = [row.question for row in question_refs if row.question]
	questions_by_name = {
		row["name"]: row
		for row in (
			frappe.get_all(
				"LMS Question",
				filters={"name": ["in", question_names]},
				fields=_CORRECTNESS_FIELDS,
			)
			if question_names
			else []
		)
	}

	enable_negative_marking = bool(quiz_doc.get("enable_negative_marking"))
	marks_to_cut = quiz_doc.get("marks_to_cut") or 0

	score = 0
	result_rows = []
	for ref in question_refs:
		question = questions_by_name.get(ref.question)
		if not question:
			continue
		answer = answers.get(ref.question)
		marks_for_question = ref.marks or 0

		if question["type"] == "Choices" and question["multiple"]:
			is_correct, answer_text = _grade_choices_multiple(question, answer)
			is_graded = True
		elif question["type"] == "Choices":
			is_correct, answer_text = _grade_choices_single(question, answer)
			is_graded = True
		elif question["type"] == "User Input":
			is_correct, answer_text = _grade_user_input(question, answer)
			is_graded = True
		else:
			# Open Ended — no answer key exists; never auto-graded. The raw
			# text is preserved for a human grader (see sample_answer's
			# own docstring); the Flutter result screen already knows to
			# show "Awaiting grading" rather than implying a wrong answer
			# (cross-referencing question type against a zero mark).
			is_correct = False
			answer_text = answer if isinstance(answer, str) else ""
			is_graded = False

		if not is_graded or not answer_text:
			marks_awarded = 0
		elif is_correct:
			marks_awarded = marks_for_question
		elif enable_negative_marking:
			marks_awarded = -marks_to_cut
		else:
			marks_awarded = 0
		score += marks_awarded

		result_rows.append({
			"question": question["question"],
			"question_name": ref.question,
			"answer": answer_text,
			"marks": marks_awarded,
			"marks_out_of": marks_for_question,
			"is_correct": 1 if is_correct else 0,
		})

	# A negative-marking quiz can drive the raw sum below zero — clamp for
	# display, matching the same reasoning the client-side version this
	# replaces already documented.
	if score < 0:
		score = 0
	score_out_of = quiz_doc.get("total_marks") or 0
	percentage = round((score / score_out_of) * 100) if score_out_of else 0

	submission = frappe.get_doc({
		"doctype": "LMS Quiz Submission",
		"quiz": quiz,
		"quiz_title": quiz_doc.title,
		"course": quiz_doc.get("course"),
		"tenant": tenant,
		"member": user,
		"member_name": frappe.db.get_value("User", user, "full_name") or user,
		"score": score,
		"score_out_of": score_out_of,
		"percentage": percentage,
		"passing_percentage": quiz_doc.get("passing_percentage") or 0,
		"result": result_rows,
	})
	# ignore_permissions=True after the explicit assert_tenant_access +
	# max_attempts guards above — the universal pattern this codebase
	# uses for every doc created by trusted server-side logic behind its
	# own guard (ai_setup.py, plans.py, native_roles.py, qtt_platform's
	# entire service layer): the guard is the real gate, DocPerm is
	# deliberately bypassed on the write itself.
	submission.insert(ignore_permissions=True)
	return submission.as_dict()
