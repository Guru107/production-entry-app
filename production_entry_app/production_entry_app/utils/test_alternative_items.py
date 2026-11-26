from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.doctype.shift import shift as shift_module
from production_entry_app.production_entry_app.overrides import stock_entry_hooks
from production_entry_app.production_entry_app.utils import alternative_items

ROWS = [
	{"item_code": "RM1", "allow_alternative_item": 1},
	{"item_code": "RM2", "allow_alternative_item": 0},
]


class TestAlternativeItems(FrappeTestCase):
	def test_bom_rows_read_top_level_only_in_one_query(self) -> None:
		with patch.object(alternative_items.frappe, "get_all", return_value=ROWS) as get_all:
			alternative_items.get_bom_item_rows("BOM-X")

		get_all.assert_called_once()
		self.assertEqual(get_all.call_args.kwargs["filters"], {"parent": "BOM-X", "parenttype": "BOM"})

	def test_codes_and_allowed_items_reuse_supplied_rows(self) -> None:
		with patch.object(alternative_items.frappe, "get_all") as get_all:
			codes = alternative_items.get_bom_item_codes("BOM-X", ROWS)
			allowed = alternative_items.get_bom_alternative_allowed_items("BOM-X", ROWS)

		get_all.assert_not_called()
		self.assertEqual(codes, {"RM1", "RM2"})
		self.assertEqual(allowed, {"RM1"})

	def test_flags_and_validation_reuse_supplied_rows(self) -> None:
		doc = frappe._dict(purpose="Manufacture", from_bom=1, bom_no="BOM-X", work_order=None, items=[])
		with (
			patch.object(alternative_items.frappe, "get_all", return_value=[]) as get_all,
			patch.object(alternative_items.frappe.db, "exists", return_value=False),
		):
			stock_entry_hooks._set_direct_manufacture_alternative_flags(doc, ROWS)
			stock_entry_hooks._validate_direct_manufacture_alternative_items(doc, ROWS)

		bom_item_reads = [call for call in get_all.call_args_list if call.args[0] == "BOM Item"]
		self.assertEqual(bom_item_reads, [])

	def test_active_reason_checker_uses_one_query(self) -> None:
		with patch.object(shift_module.frappe, "get_all", wraps=frappe.get_all) as get_all:
			is_active = shift_module._get_active_downtime_reason_checker()
			for reason in ("10", "13", "14", "19", "20", "missing"):
				is_active(reason)

		self.assertEqual(get_all.call_count, 1)
		self.assertFalse(is_active("missing"))
