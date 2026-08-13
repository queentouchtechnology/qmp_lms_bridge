"""
Seeds the QTT AI Provider / QTT AI Model rows QMP_LMS's own AI features
need — production-readiness audit. Default provider: DeepSeek
(OpenAI-compatible, already a real, implemented provider in
qtt_platform/ai/providers/deepseek.py — not a placeholder).

Deliberately does NOT set QTT AI Provider.api_key — that field is a
Frappe Password fieldtype, encrypted with the SITE's own encryption key;
there is no safe way for a fixture, a seed script argument, or anything
committed to a repository to carry a real API key, and this project's
own standing rule (see qtt_platform/README's Razorpay config section,
same reasoning) is that credentials never appear in source, hooks.py,
fixtures, or git. This function creates the row ENABLED and ready, with
the key left blank — `OpenAiCompatibleProvider.is_configured()` (base
class for DeepSeek, unmodified) correctly reports "not configured" until
a real key is entered through the ONE safe path: the Desk UI's own
Password field widget (System Manager -> QTT AI Provider -> deepseek ->
API Key), which encrypts it via Frappe's own site-level mechanism the
moment it's saved. See this app's own README for the exact steps.

Unlike register_product()/seed_plans() (Phase 2/B), which fully
re-apply their own catalog on every migrate, this function only CREATES
what's missing and never touches an existing QTT AI Provider row again
— re-running it must never silently disable a provider an admin turned
off, or blank out a key that's already been entered through the Desk.
"""

import frappe

PROVIDER_KEY = "deepseek"
TASK = "quiz_generation"


def seed_ai_defaults() -> None:
	_ensure_provider()
	_ensure_model()


def _ensure_provider() -> None:
	if frappe.db.exists("QTT AI Provider", PROVIDER_KEY):
		return
	frappe.get_doc(
		{
			"doctype": "QTT AI Provider",
			"provider_key": PROVIDER_KEY,
			"enabled": 1,
			"is_fallback": 0,
			# base_url intentionally left blank — DeepSeekProvider's own
			# default_base_url ("https://api.deepseek.com/v1") is used
			# automatically when this field is empty (see
			# OpenAiCompatibleProvider.generate(), unmodified).
			# api_key intentionally left blank — see module docstring.
		}
	).insert(ignore_permissions=True)


def _ensure_model() -> None:
	if frappe.db.exists("QTT AI Model", {"default_for_task": TASK}):
		return
	frappe.get_doc(
		{
			"doctype": "QTT AI Model",
			"provider": PROVIDER_KEY,
			# Confirmed live against DeepSeek's own current API docs
			# (api-docs.deepseek.com) while building this, via two
			# independent page fetches — NOT the older "deepseek-chat" /
			# "deepseek-reasoner" naming this project would otherwise have
			# assumed from training data. DeepSeek's docs state these
			# identifiers auto-route to the latest underlying version.
			# "flash" (the lighter/cheaper tier) is the reasonable default
			# for a per-generation-costed feature like quiz generation;
			# swap to "deepseek-v4-pro" via the Desk if higher quality is
			# worth the extra cost for this task.
			"model_id": "deepseek-v4-flash",
			"default_for_task": TASK,
			"cost_input_per_1m": 0,
			"cost_output_per_1m": 0,
		}
	).insert(ignore_permissions=True)
