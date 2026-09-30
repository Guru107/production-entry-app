from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.model.document import Document

CODE_FORMAT: re.Pattern[str] = re.compile(r"^\d{2}$")


class DowntimeReason(Document):
	def validate(self) -> None:
		if not CODE_FORMAT.fullmatch(str(self.code or "")):
			frappe.throw(_("Code must be a two-digit number, e.g. 01."))
