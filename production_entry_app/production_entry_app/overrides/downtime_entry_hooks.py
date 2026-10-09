from __future__ import annotations

from collections.abc import Iterable

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime


def validate_downtime_entry(doc: Document, method: str | None = None) -> None:
	"""Validate Downtime Entry time order and required Downtime Reason link."""
	_validate_downtime_reason_required(doc)
	_validate_from_time_before_to_time(doc)
	_default_native_stop_reason(doc)


def get_downtime_reason_labels(codes: Iterable[str | None]) -> dict[str, str]:
	"""Map Downtime Reason codes to their display descriptions."""
	unique_codes = sorted({str(code) for code in codes if code})
	if not unique_codes:
		return {}
	rows = frappe.get_all(
		"Downtime Reason",
		filters={"name": ["in", unique_codes]},
		fields=["name", "description"],
	)
	return {row.name: str(row.description or row.name) for row in rows}


def _validate_downtime_reason_required(doc: Document) -> None:
	meta = frappe.get_meta("Downtime Entry", cached=True)
	if not meta.has_field("custom_pea_downtime_reason"):
		return
	if doc.get("custom_pea_downtime_reason"):
		return
	frappe.throw(_("Downtime Reason is required."))


def _validate_from_time_before_to_time(doc: Document) -> None:
	from_time = get_datetime(doc.get("from_time")) if doc.get("from_time") else None
	to_time = get_datetime(doc.get("to_time")) if doc.get("to_time") else None
	if not from_time or not to_time:
		return
	if from_time >= to_time:
		frappe.throw(_("From Time must be before To Time."))


def _default_native_stop_reason(doc: Document) -> None:
	"""Keep the hidden native Select populated so legacy reqd does not block saves."""
	if doc.get("stop_reason"):
		return
	doc.stop_reason = "Other"
