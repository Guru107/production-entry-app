from __future__ import annotations

from typing import Any

from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry
from erpnext.stock.doctype.stock_entry_detail.stock_entry_detail import StockEntryDetail

class ProductionEntryAppStockEntry(StockEntry):
	"""Keep custom rejection rows out of ERPNext's primary FG-row selection."""

	# Native get_finished_item_row picks the LAST is_finished_item row
	# (v15 stock_entry.py:1673, v16 stock_entry.py:1834). Our rejection row is
	# also is_finished_item, so we skip it here. If ERPNext changes multi-FG /
	# bundle selection, the regression tests in test_stock_entry_override.py
	# (manufacture+rejection SLEs) will fail -- do not silence them.
	def get_finished_item_row(self) -> StockEntryDetail | None:
		if self.purpose in ("Manufacture", "Repack"):
			for row in self.get("items"):
				if row.is_finished_item and not row.get("custom_pea_is_rejection_item"):
					return row

		return super().get_finished_item_row()
