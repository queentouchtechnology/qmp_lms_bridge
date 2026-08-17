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
from qtt_platform.document_security import assert_tenant_access
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

#: "topic" (default, existing behavior — free-text topic, no grounding
#: material) plus four ways to ground generation in real course content
#: instead of asking the model to invent everything from a topic string.
_SOURCE_TYPES = ("topic", "course", "chapter", "lesson", "text")

#: Cap on how much source material gets sent to the provider per call —
#: a cost/latency guard, same spirit as num_questions' hard cap below,
#: not a correctness requirement.
_MAX_SOURCE_TEXT_CHARS = 8000

_SYSTEM_PROMPT = (
	"You are a quiz question generator for an online learning platform. "
	"Always respond with valid JSON only, no other text, matching exactly this shape: "
	'{"questions": [{"question": "...", "options": ["...", "...", "...", "..."], '
	'"correct_answer": "...", "explanation": "..."}]}. '
	'For question_type "Open Ended", omit "options" and "correct_answer", and include '
	'"sample_answer" instead. '
	'For question_type "User Input", omit "options" and "correct_answer", and include '
	'"possible_answers" instead — a JSON array of 1 to 4 short acceptable answer strings '
	'(alternate phrasings/spellings the platform will match the student\'s typed answer '
	'against case-insensitively).'
)


def generate_quiz(*, tenant: str, user: str, inputs: dict) -> dict:
	"""Registered as "QMP_LMS::quiz_generation" — see hooks.py.
	Instructor/Manager enters difficulty/count/type, plus either a free
	topic or a source to ground generation in (an existing course,
	chapter, lesson, or a pasted passage — see `_resolve_source`).
	Returns generated questions with options, correct answers, and
	explanations (or a sample answer for open-ended questions)."""
	require_product_role(tenant, PRODUCT_KEY, list(_ALLOWED_ROLES), user=user)

	source_type = (inputs.get("source_type") or "topic").strip().lower()
	if source_type not in _SOURCE_TYPES:
		frappe.throw(
			_("source_type must be one of: {0}").format(", ".join(_SOURCE_TYPES)), frappe.ValidationError
		)
	topic, context_text = _resolve_source(source_type, inputs, tenant=tenant, user=user)

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

	user_message = (
		f"Generate {num_questions} {difficulty}-difficulty quiz questions about '{topic}'. "
		f"Question type: {question_type}. Each question needs a clear explanation."
	)
	if context_text:
		user_message += (
			"\n\nBase every question strictly on the following material — do not invent "
			f"facts outside it:\n{context_text}"
		)

	request = AiRequest(
		task="quiz_generation",
		messages=[
			AiMessage(role="system", content=_SYSTEM_PROMPT),
			AiMessage(role="user", content=user_message),
		],
		structured_output=True,
		metadata={"feature": "quiz_generation", "tenant": tenant, "source_type": source_type},
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
		"source_type": source_type,
		"difficulty": difficulty,
		"question_type": question_type,
		"questions": questions,
		"credits_used": QUIZ_GENERATION_CREDIT_COST,
		"provider": response.provider,
		"model": response.model,
	}


def _resolve_source(source_type: str, inputs: dict, *, tenant: str, user: str) -> tuple[str, str]:
	"""Returns `(topic, context_text)`. `topic` is always a short label
	for prompts/UI; `context_text` is empty for "topic" (today's
	behavior — the model gets nothing but the topic string) and holds
	real grounding material for the other four source types. Each
	doctype lookup asserts tenant access itself rather than trusting
	the caller's `tenant` blindly — the same one-liner every other
	document-bearing whitelisted method in this app uses.
	"""
	if source_type == "topic":
		topic = (inputs.get("topic") or "").strip()
		if not topic:
			frappe.throw(_("A topic is required to generate a quiz."), frappe.ValidationError)
		return topic, ""

	if source_type == "text":
		source_text = (inputs.get("source_text") or "").strip()
		if len(source_text) < 20:
			frappe.throw(
				_("Paste at least a short paragraph of material to generate from."), frappe.ValidationError
			)
		return "the provided material", source_text[:_MAX_SOURCE_TEXT_CHARS]

	source_id = (inputs.get("source_id") or "").strip()
	if not source_id:
		frappe.throw(
			_("source_id is required for source_type '{0}'.").format(source_type), frappe.ValidationError
		)

	if source_type == "course":
		assert_tenant_access("LMS Course", source_id, user=user)
		course = frappe.get_doc("LMS Course", source_id)
		parts = [course.title, course.short_introduction, course.description]
		context = "\n\n".join(p for p in parts if p)
		return course.title, context[:_MAX_SOURCE_TEXT_CHARS]

	if source_type == "lesson":
		assert_tenant_access("Course Lesson", source_id, user=user)
		lesson = frappe.get_doc("Course Lesson", source_id)
		body = lesson.body or lesson.content or ""
		context = f"{lesson.title}\n\n{body}" if body else lesson.title
		return lesson.title, context[:_MAX_SOURCE_TEXT_CHARS]

	# chapter — `Course Chapter` itself has no `tenant` field (it's not
	# one of the tenant-isolated anchor doctypes), so access is asserted
	# via its parent course instead.
	chapter = frappe.get_doc("Course Chapter", source_id)
	assert_tenant_access("LMS Course", chapter.course, user=user)
	lessons = frappe.get_all(
		"Course Lesson",
		filters={"chapter": source_id},
		fields=["title", "body", "content"],
		order_by="idx",
	)
	parts = [chapter.title]
	for lesson in lessons:
		body = lesson.body or lesson.content or ""
		parts.append(f"{lesson.title}\n{body}" if body else lesson.title)
	return chapter.title, "\n\n".join(parts)[:_MAX_SOURCE_TEXT_CHARS]


def _parse_quiz_response(content: str) -> list[dict]:
	try:
		data = json.loads(content)
	except (TypeError, ValueError):
		frappe.throw(_("The AI provider returned an unreadable response. Please try again."), frappe.ValidationError)

	questions = data.get("questions") if isinstance(data, dict) else None
	if not isinstance(questions, list):
		frappe.throw(_("The AI provider returned an unexpected response shape."), frappe.ValidationError)
	return questions


#: Cheaper than a full generation call (QUIZ_GENERATION_CREDIT_COST) —
#: rewording one question's text is a much smaller task than drafting a
#: whole batch from scratch.
QUESTION_REWORD_CREDIT_COST = 1.0

_REWORD_SYSTEM_PROMPT = (
	"You are an editor improving quiz question wording for an online "
	"learning platform. Given a quiz question's text, propose 3 "
	"alternative phrasings that ask exactly the same thing and test "
	"exactly the same knowledge, just clearer or more naturally worded. "
	"Never change what is being asked, never introduce new facts, and "
	"never suggest or hint at an answer. Always respond with valid JSON "
	'only, no other text, matching exactly this shape: {"alternatives": '
	'["...", "...", "..."]}.'
)


def reword_question(*, tenant: str, user: str, inputs: dict) -> dict:
	"""Registered as "QMP_LMS::question_rewording" — see hooks.py.
	Deliberately rewords the question TEXT ONLY — options, correct
	answers, and possible/sample answers are never touched by this
	feature, so nothing it returns can silently change what's being
	tested. The caller applies a chosen alternative through the exact
	same `QuestionProvider.updateQuestion` path a manual text edit
	already uses; this only ever proposes text.
	"""
	require_product_role(tenant, PRODUCT_KEY, list(_ALLOWED_ROLES), user=user)

	quiz_name = (inputs.get("quiz") or "").strip()
	question_name = (inputs.get("question") or "").strip()
	if not quiz_name or not question_name:
		frappe.throw(_("Both quiz and question are required."), frappe.ValidationError)

	assert_tenant_access("LMS Quiz", quiz_name, user=user)
	quiz_doc = frappe.get_doc("LMS Quiz", quiz_name)
	question_names = {row.question for row in (quiz_doc.get("questions") or [])}
	if question_name not in question_names:
		frappe.throw(_("That question does not belong to this quiz."), frappe.ValidationError)

	question_text = frappe.db.get_value("LMS Question", question_name, "question")
	if not question_text:
		frappe.throw(_("Question not found."), frappe.ValidationError)

	# `QTT AI Model` has a unique constraint on (provider, model_id), and
	# `default_for_task` lives on that same row — so a model can only be
	# the routing default for ONE task. Rather than registering a second
	# row for the same model (rejected by the constraint) or a distinct
	# model just to have one, this explicitly reuses whatever model is
	# currently configured for quiz_generation — see ai_setup.py's
	# module docstring for the full reasoning. `task` is still set for
	# usage/credit accounting even though it plays no role in routing
	# once provider/model are both explicit (see routing.resolve_routing).
	reuse_model = frappe.db.get_value(
		"QTT AI Model", {"default_for_task": "quiz_generation"}, ["provider", "model_id"], as_dict=True
	)
	if not reuse_model:
		frappe.throw(_("No AI model is configured yet."), frappe.ValidationError)

	request = AiRequest(
		task="question_rewording",
		messages=[
			AiMessage(role="system", content=_REWORD_SYSTEM_PROMPT),
			AiMessage(role="user", content=f"Original question text: {question_text}"),
		],
		provider=reuse_model.provider,
		model=reuse_model.model_id,
		structured_output=True,
		metadata={"feature": "question_rewording", "tenant": tenant},
	)

	response = generate_and_track(
		tenant=tenant,
		product=PRODUCT_KEY,
		user=user,
		feature="question_rewording",
		request=request,
		credit_cost=QUESTION_REWORD_CREDIT_COST,
	)

	try:
		data = json.loads(response.content)
	except (TypeError, ValueError):
		frappe.throw(_("The AI provider returned an unreadable response. Please try again."), frappe.ValidationError)

	alternatives = data.get("alternatives") if isinstance(data, dict) else None
	if not isinstance(alternatives, list):
		frappe.throw(_("The AI provider returned an unexpected response shape."), frappe.ValidationError)

	return {
		"question": question_name,
		"original": question_text,
		"alternatives": [str(a) for a in alternatives],
		"credits_used": QUESTION_REWORD_CREDIT_COST,
		"provider": response.provider,
		"model": response.model,
	}


def _reuse_quiz_generation_model() -> dict:
	"""Shared by every AI feature added after quiz_generation — see
	reword_question's own comment for why: `QTT AI Model` has a unique
	constraint on (provider, model_id), and `default_for_task` lives on
	that same row, so a model can only be the routing default for ONE
	task. Rather than registering a second row per new feature (rejected
	by the constraint) or a distinct model just to have one, every
	feature here explicitly reuses whatever model is currently
	configured for quiz_generation."""
	reuse_model = frappe.db.get_value(
		"QTT AI Model", {"default_for_task": "quiz_generation"}, ["provider", "model_id"], as_dict=True
	)
	if not reuse_model:
		frappe.throw(_("No AI model is configured yet."), frappe.ValidationError)
	return reuse_model


#: A full course description (title + intro + multi-paragraph body) is a
#: comparable-sized generation to a quiz batch, not a small edit like
#: rewording one question — priced the same as quiz_generation.
COURSE_CONTENT_CREDIT_COST = 5.0

_COURSE_CONTENT_SYSTEM_PROMPT = (
	"You are a course-description writer for an online learning platform. Given a course "
	"topic, write a compelling course title, a one-sentence short introduction (shown on "
	"course cards), and a longer description (2-4 paragraphs, plain text — no markdown) "
	"explaining what students will learn and why the course is worth taking. "
	"Always respond with valid JSON only, no other text, matching exactly this shape: "
	'{"title": "...", "short_introduction": "...", "description": "..."}.'
)


def generate_course_content(*, tenant: str, user: str, inputs: dict) -> dict:
	"""Registered as "QMP_LMS::course_content" — see hooks.py. Manager/
	Instructor enters a topic; returns a draft title/short_introduction/
	description for `CreateCourseScreen`'s own fields — reviewed and
	editable there before the course is actually created, the same
	"never silently insert an AI suggestion" rule `quiz_generation`'s
	review screen already follows."""
	require_product_role(tenant, PRODUCT_KEY, list(_ALLOWED_ROLES), user=user)

	topic = (inputs.get("topic") or "").strip()
	if not topic:
		frappe.throw(_("A topic is required to generate course content."), frappe.ValidationError)

	reuse_model = _reuse_quiz_generation_model()
	request = AiRequest(
		task="course_content",
		messages=[
			AiMessage(role="system", content=_COURSE_CONTENT_SYSTEM_PROMPT),
			AiMessage(role="user", content=f"Course topic: {topic}"),
		],
		provider=reuse_model.provider,
		model=reuse_model.model_id,
		structured_output=True,
		metadata={"feature": "course_content", "tenant": tenant},
	)

	response = generate_and_track(
		tenant=tenant,
		product=PRODUCT_KEY,
		user=user,
		feature="course_content",
		request=request,
		credit_cost=COURSE_CONTENT_CREDIT_COST,
	)

	try:
		data = json.loads(response.content)
	except (TypeError, ValueError):
		frappe.throw(_("The AI provider returned an unreadable response. Please try again."), frappe.ValidationError)
	if not isinstance(data, dict):
		frappe.throw(_("The AI provider returned an unexpected response shape."), frappe.ValidationError)

	return {
		"topic": topic,
		"title": str(data.get("title") or ""),
		"short_introduction": str(data.get("short_introduction") or ""),
		"description": str(data.get("description") or ""),
		"credits_used": COURSE_CONTENT_CREDIT_COST,
		"provider": response.provider,
		"model": response.model,
	}


#: Cheaper than a full course (one lesson's worth of body text, not an
#: entire course's worth of copy) — priced between question_rewording
#: and a full quiz/course generation.
LESSON_CONTENT_CREDIT_COST = 3.0

_LESSON_CONTENT_SYSTEM_PROMPT = (
	"You are a lesson-content writer for an online learning platform. Given a lesson topic "
	"(and optionally the course/chapter it belongs to, for context), write a clear lesson "
	"title and the lesson body content — plain text, well-organized into short paragraphs, "
	"suitable for a student reading it directly. Always respond with valid JSON only, no "
	'other text, matching exactly this shape: {"title": "...", "body": "..."}.'
)


def generate_lesson_content(*, tenant: str, user: str, inputs: dict) -> dict:
	"""Registered as "QMP_LMS::lesson_content" — see hooks.py. Instructor/
	Manager enters a lesson topic (and optionally the course/chapter
	title it belongs to, purely as prompt context — never a DB lookup,
	since a lesson may be created before its chapter is saved); returns
	a draft title/body for `CreateLessonScreen`'s own fields, reviewed
	and editable there before the lesson is actually created."""
	require_product_role(tenant, PRODUCT_KEY, list(_ALLOWED_ROLES), user=user)

	topic = (inputs.get("topic") or "").strip()
	if not topic:
		frappe.throw(_("A topic is required to generate lesson content."), frappe.ValidationError)
	context = (inputs.get("context") or "").strip()[:500]

	user_message = f"Lesson topic: {topic}"
	if context:
		user_message += f"\nThis lesson is part of: {context}"

	reuse_model = _reuse_quiz_generation_model()
	request = AiRequest(
		task="lesson_content",
		messages=[
			AiMessage(role="system", content=_LESSON_CONTENT_SYSTEM_PROMPT),
			AiMessage(role="user", content=user_message),
		],
		provider=reuse_model.provider,
		model=reuse_model.model_id,
		structured_output=True,
		metadata={"feature": "lesson_content", "tenant": tenant},
	)

	response = generate_and_track(
		tenant=tenant,
		product=PRODUCT_KEY,
		user=user,
		feature="lesson_content",
		request=request,
		credit_cost=LESSON_CONTENT_CREDIT_COST,
	)

	try:
		data = json.loads(response.content)
	except (TypeError, ValueError):
		frappe.throw(_("The AI provider returned an unreadable response. Please try again."), frappe.ValidationError)
	if not isinstance(data, dict):
		frappe.throw(_("The AI provider returned an unexpected response shape."), frappe.ValidationError)

	return {
		"topic": topic,
		"title": str(data.get("title") or ""),
		"body": str(data.get("body") or ""),
		"credits_used": LESSON_CONTENT_CREDIT_COST,
		"provider": response.provider,
		"model": response.model,
	}


#: Title + instructions + a model answer — comparable scope to a lesson.
ASSIGNMENT_CONTENT_CREDIT_COST = 3.0

_ASSIGNMENT_CONTENT_SYSTEM_PROMPT = (
	"You are an instructor writing a student assignment for an online learning platform. "
	"Given a topic, write a clear assignment title, the assignment question (specific "
	"instructions for what the student must do or submit — plain text, no markdown), and a "
	"model answer that demonstrates a strong response to it. Always respond with valid JSON "
	'only, no other text, matching exactly this shape: {"title": "...", "question": "...", '
	'"answer": "..."}.'
)


def generate_assignment_content(*, tenant: str, user: str, inputs: dict) -> dict:
	"""Registered as "QMP_LMS::assignment_content" — see hooks.py.
	Instructor/Manager enters a topic; returns a draft title/question/
	answer for `CreateAssignmentScreen`'s own fields, reviewed and
	editable there before the assignment is actually created."""
	require_product_role(tenant, PRODUCT_KEY, list(_ALLOWED_ROLES), user=user)

	topic = (inputs.get("topic") or "").strip()
	if not topic:
		frappe.throw(_("A topic is required to generate an assignment."), frappe.ValidationError)

	reuse_model = _reuse_quiz_generation_model()
	request = AiRequest(
		task="assignment_content",
		messages=[
			AiMessage(role="system", content=_ASSIGNMENT_CONTENT_SYSTEM_PROMPT),
			AiMessage(role="user", content=f"Assignment topic: {topic}"),
		],
		provider=reuse_model.provider,
		model=reuse_model.model_id,
		structured_output=True,
		metadata={"feature": "assignment_content", "tenant": tenant},
	)

	response = generate_and_track(
		tenant=tenant,
		product=PRODUCT_KEY,
		user=user,
		feature="assignment_content",
		request=request,
		credit_cost=ASSIGNMENT_CONTENT_CREDIT_COST,
	)

	try:
		data = json.loads(response.content)
	except (TypeError, ValueError):
		frappe.throw(_("The AI provider returned an unreadable response. Please try again."), frappe.ValidationError)
	if not isinstance(data, dict):
		frappe.throw(_("The AI provider returned an unexpected response shape."), frappe.ValidationError)

	return {
		"topic": topic,
		"title": str(data.get("title") or ""),
		"question": str(data.get("question") or ""),
		"answer": str(data.get("answer") or ""),
		"credits_used": ASSIGNMENT_CONTENT_CREDIT_COST,
		"provider": response.provider,
		"model": response.model,
	}
