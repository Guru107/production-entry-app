from __future__ import annotations

from production_entry_app.production_entry_app.lifecycle import (
	remove_obsolete_total_rm_consumption_field,
)


def execute() -> None:
	"""Drop obsolete Joint LH/RH Total RM Consumption header field (#121)."""
	remove_obsolete_total_rm_consumption_field()
