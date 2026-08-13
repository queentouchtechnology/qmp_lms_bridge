"""
QMP_LMS's own AI features — production-readiness audit, the one real AI
feature this product defines (Part 9's own recommendation: AI Quiz
Generation). Registered via hooks.py's ai_feature_handlers
("QMP_LMS::quiz_generation" -> generate_quiz), the same hooks.py-
registered-dotted-path pattern already used for usage_resolvers and
tenant_parent_links — qtt_platform.api.ai.generate() never imports this
module directly; it only knows how to look the handler up and call it.

Each handler here owns everything qtt_platform must never know about:
its own role check (require_product_role — a DIFFERENT question from
roles.py's document-write matrix, which governs LMS *doctypes*; this
governs who may spend the tenant's AI credits), its own prompt, its own
credit cost, and its own result shape.
"""

import json

import frappe
from frappe import _

from qtt_platform.ai.core.request import AiMessage, AiRequest
from qtt_platform.ai.service import generate_and_track
from qtt_platform.product.guards import require_product_role

PRODUCT_KEY = "QMP_LMS"

#: A flat cost per generation, charged every call — deliberately NOT
#: read from QTT Plan Feature (that mechanism is for numeric USAGE
#: limits like max_students, checked against a running total; a
#: per-call AI cost is charged once per call, not compared against
#: anything). QTT AI Credit Ledger's own append-only design already
#: assumes a fixed amount is known at call time.
QUIZ_GENERATION_CREDIT_COST = 5.0

#: Who may spend tenant AI credits on this feature — Manager (LMS
#: administration) and Instructor (the role that actually authors
#: course content) only. Staff/Student cannot trigger AI generation
#: at all, distinct from — and narrower than — roles.py's document
#: matrix, which is about who may write which LMS doctype, not who may
#: spend money-equivalent AI credits.
_ALLOWED_ROLES = ("Manager", "Instructor")

_QUESTION_TYPES = ("Choices", "User Input", "Open Ended")
_DIFFICULTIES = ("easy", "medium", "hard")

_SYSTEM_PROMPT = (
	"You are a quiz question generator for an online learning platform. "
	"Always respond with valid JSON only, no other text, matching exactly this shape: "
	'{"questions": [{"question": "...", "options": ["...", "...", "...", "..."], '
	'"correct_answer": "...", "explanation": "..."}]}. '
	'For question_type "Open Ended", omit "options" and "correct_answer", and include '
	'"sample_answer" instead.'
)


def generate_quiz(*, tenant: str, user: str, inputs: dict) -> dict:
	"""Registered as "QMP_LMS::quiz_generation" — see hooks.py.
	Instructor/Manager enters topic/difficulty/count/type; returns
	generated questions with options, correct answers, and explanations
	(or a sample answer for open-ended questions)."""
	require_product_role(tenant, PRODUCT_KEY, list(_ALLOWED_ROLES), user=user)

	topic = (inputs.get("topic") or "").strip()
	if not topic:
		frappe.throw(_("A topic is required to generate a quiz."), frappe.ValidationError)

	difficulty = (inputs.get("difficulty") or "medium").strip().lower()
	if difficulty not in _DIFFICULTIES:
		frappe.throw(_("difficulty must be one of: {0}").format(", ".join(_DIFFICULTIES)), frappe.ValidationError)

	question_type = inputs.get("question_type") or "Choices"
	if question_type not in _QUESTION_TYPES:
		frappe.throw(
			_("question_type must be one of: {0}").format(", ".join(_QUESTION_TYPES)), frappe.ValidationError
		)

	try:
		num_questions = int(inputs.get("num_questions") or 5)
	except (TypeError, ValueError):
		frappe.throw(_("num_questions must be a number."), frappe.ValidationError)
	# Hard cap — never let a client (or a confused caller) ask for an
	# unbounded number of questions in one call; credit cost here is
	# flat per-call, not per-question, so this is a cost/latency/output-
	# size guard, not a billing guard.
	num_questions = max(1, min(num_questions, 20))

	request = AiRequest(
		task="quiz_generation",
		messages=[
			AiMessage(role="system", content=_SYSTEM_PROMPT),
			AiMessage(
				role="user",
				content=(
					f"Generate {num_questions} {difficulty}-difficulty quiz questions about '{topic}'. "
					f"Question type: {question_type}. Each question needs a clear explanation."
				),
			),
		],
		structured_output=True,
		metadata={"feature": "quiz_generation", "tenant": tenant},
	)

	response = generate_and_track(
		tenant=tenant,
		product=PRODUCT_KEY,
		user=user,
		feature="quiz_generation",
		request=request,
		credit_cost=QUIZ_GENERATION_CREDIT_COST,
	)

	# Credits are already spent by this point (generate_and_track()
	# reserves before calling the provider and only refunds on a
	# PROVIDER failure — see that function's own docstring). A malformed
	# JSON response from an otherwise-successful provider call is not a
	# provider failure in that sense, so it is NOT refunded here — the
	# generation happened and consumed real provider capacity; this is a
	# parsing problem on our side, surfaced as a clear error rather than
	# silently returning an empty result.
	questions = _parse_quiz_response(response.content)

	return {
		"topic": topic,
		"difficulty": difficulty,
		"question_type": question_type,
		"questions": questions,
		"credits_used": QUIZ_GENERATION_CREDIT_COST,
		"provider": response.provider,
		"model": response.model,
	}


def _parse_quiz_response(content: str) -> list[dict]:
	try:
		data = json.loads(content)
	except (TypeError, ValueError):
		frappe.throw(_("The AI provider returned an unreadable response. Please try again."), frappe.ValidationError)

	questions = data.get("questions") if isinstance(data, dict) else None
	if not isinstance(questions, list):
		frappe.throw(_("The AI provider returned an unexpected response shape."), frappe.ValidationError)
	return questions
