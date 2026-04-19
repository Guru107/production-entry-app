from __future__ import annotations

from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry
from erpnext.stock.doctype.stock_entry_detail.stock_entry_detail import StockEntryDetail


class ProductionEntryAppStockEntry(StockEntry):
	"""Keep custom rejection rows out of ERPNext's primary FG-row selection."""

	def get_finished_item_row(self) -> StockEntryDetail | None:
		if self.purpose in ("Manufacture", "Repack"):
			for row in self.get("items"):
				if row.is_finished_item and not row.get("custom_is_rejection_item"):
					return row

		return super().get_finished_item_row()
