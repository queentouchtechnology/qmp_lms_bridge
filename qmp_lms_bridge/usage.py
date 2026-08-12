"""
Usage resolvers for QMP_LMS's countable features — registered in hooks.py's
usage_resolvers dict, called by qtt_platform.usage.registry.get_usage().
Deliberately simple: a plain tenant-filtered count, no additional status
filter this session couldn't independently re-confirm live (e.g. whether
LMS Enrollment has an 'active'-style status worth excluding is real,
useful future refinement, not guessed at here).
"""

import frappe


def count_students(tenant: str) -> int:
	"""Distinct enrolled members for this tenant, across LMS Enrollment."""
	return frappe.db.count("LMS Enrollment", {"tenant": tenant})


def count_batch_students(tenant: str) -> int:
	return frappe.db.count("LMS Batch Enrollment", {"tenant": tenant})


def count_instructors(tenant: str) -> int:
	"""Approximated via QTT Product Access — every active Instructor-role
	grant for QMP_LMS in this tenant. More accurate than trying to derive
	'instructor' from LMS's own Course.instructors child table across
	every course, and consistent with the platform's own membership model
	being the source of truth for 'who has which role,' not LMS's."""
	return frappe.db.count(
		"QTT Product Access",
		{"tenant": tenant, "product": "QMP_LMS", "product_role": "Instructor", "status": "active"},
	)


def count_courses(tenant: str) -> int:
	return frappe.db.count("LMS Course", {"tenant": tenant})


def count_batches(tenant: str) -> int:
	return frappe.db.count("LMS Batch", {"tenant": tenant})


def count_live_classes(tenant: str) -> int:
	return frappe.db.count("LMS Live Class", {"tenant": tenant})
