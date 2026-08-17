"""Runtime patches for bugs in the vendor `lms` app — never edit `lms`
itself (see this app's own hooks.py docstring for why); patch it from
here instead, applied once per worker process at `__init__.py` import
time (not a hook — `boot_session` was tried first but only fires when
building desk bootinfo, which this app's REST-only mobile client never
triggers).
"""

import frappe


def _patch_lms_certificate_after_insert():
	"""`LMSCertificate.after_insert` (lms/lms/doctype/lms_certificate/
	lms_certificate.py) reads `frappe.in_test`, which doesn't exist on
	this Frappe version (the real attribute is `frappe.flags.in_test`) —
	confirmed live: `hasattr(frappe, "in_test")` is `False`,
	`hasattr(frappe.flags, "in_test")` is `True`. Every certificate
	creation raises `AttributeError` inside `after_insert`, which runs
	in the same transaction as the insert, so the whole request fails
	and no `LMS Certificate` can ever be issued. This replaces just the
	broken method with an identical copy that reads the real attribute.
	"""
	from lms.lms.doctype.lms_certificate.lms_certificate import LMSCertificate

	def after_insert(self):
		if not frappe.flags.in_test:
			outgoing_email_account = frappe.get_cached_value(
				"Email Account", {"default_outgoing": 1, "enable_outgoing": 1}, "name"
			)
			if outgoing_email_account or frappe.conf.get("mail_login"):
				self.send_mail()

	LMSCertificate.after_insert = after_insert


def _patch_lms_batch_validate_timetable():
	"""`LMSBatch.validate_timetable` (lms/lms/doctype/lms_batch/
	lms_batch.py) compares `schedule.date < self.start_date` without
	normalizing types first. Reproduced live: a REST `PUT` on `LMS
	Batch` populates child-table `timetable` rows from a raw dict (a
	JSON body, same as any client sends), and Frappe does not cast a
	child row's `Date`-typed field to `datetime.date` the way it casts
	the parent doc's own `start_date`/`end_date` fields — so
	`schedule.date` stays a plain `str` while `self.start_date` is a
	real `date` object, and the comparison raises
	`TypeError: '<' not supported between instances of 'str' and
	'datetime.date'` for every single `LMS Batch` update that includes
	a timetable row, every time. This replaces the method with an
	identical copy, the only change being `getdate()` on both sides of
	the date comparison — same logic, normalized types.
	"""
	from frappe.utils import get_time, getdate
	from lms.lms.doctype.lms_batch.lms_batch import LMSBatch

	def validate_timetable(self):
		for schedule in self.timetable:
			if schedule.start_time and schedule.end_time:
				if get_time(schedule.start_time) > get_time(schedule.end_time) or get_time(
					schedule.start_time
				) == get_time(schedule.end_time):
					frappe.throw(
						frappe._("Row #{0} Start time cannot be greater than or equal to end time.").format(
							schedule.idx
						)
					)

				if get_time(schedule.start_time) < get_time(self.start_time) or get_time(
					schedule.start_time
				) > get_time(self.end_time):
					frappe.throw(
						frappe._("Row #{0} Start time cannot be outside the batch duration.").format(schedule.idx)
					)

				if get_time(schedule.end_time) < get_time(self.start_time) or get_time(
					schedule.end_time
				) > get_time(self.end_time):
					frappe.throw(
						frappe._("Row #{0} End time cannot be outside the batch duration.").format(schedule.idx)
					)

			if getdate(schedule.date) < getdate(self.start_date) or getdate(schedule.date) > getdate(
				self.end_date
			):
				frappe.throw(frappe._("Row #{0} Date cannot be outside the batch duration.").format(schedule.idx))

	LMSBatch.validate_timetable = validate_timetable


_applied = False


def apply():
	"""Called once from `__init__.py` at module-import time — every
	worker process imports this app's `hooks.py` (which imports
	`__init__.py`) to resolve `get_hooks()` before it can serve any
	request, REST or otherwise, so this is guaranteed to run before any
	certificate-creating or batch-updating call. Guarded by `_applied`
	since re-patching the classes on every import would be pointless,
	not because it's unsafe to repeat.
	"""
	global _applied
	if _applied:
		return
	_patch_lms_certificate_after_insert()
	_patch_lms_batch_validate_timetable()
	_applied = True
