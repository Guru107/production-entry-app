from __future__ import annotations

from production_entry_app.production_entry_app.lifecycle import reconcile_stock_entry_purpose_field


def execute() -> None:
	"""Ensure production-owned Stock Entry Purpose and drop the obsolete PEA copy."""
	reconcile_stock_entry_purpose_field()
