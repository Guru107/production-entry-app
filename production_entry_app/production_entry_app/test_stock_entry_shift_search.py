from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.api import stock_entry_shift_query
from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
	bootstrap_manufacture_masters,
	make_completed_shift,
)
from production_entry_app.production_entry_app.utils.test_bootstrap import ensure_branch, save_test_user

_RESTRICTED_USER = "test_shift_search_branch_user@example.com"


def _make_branch_restricted_user(branch: str) -> str:
	user = frappe.get_doc("User", _RESTRICTED_USER) if frappe.db.exists("User", _RESTRICTED_USER) else None
	if not user:
		user = frappe.new_doc("User")
		user.email = _RESTRICTED_USER
		user.first_name = "Shift Search"
		user.user_type = "System User"
	user.set("roles", [{"role": "PEA User"}])
	save_test_user(user)
	frappe.get_doc(
		{"doctype": "User Permission", "user": _RESTRICTED_USER, "allow": "Branch", "for_value": branch}
	).insert(ignore_permissions=True)
	frappe.clear_cache(user=_RESTRICTED_USER)
	return _RESTRICTED_USER


class TestStockEntryShiftSearch(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.set_user("Administrator")

	def test_stock_entry_shift_query_orders_by_shift_date_desc(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.api.frappe.get_list",
			return_value=[frappe._dict(name="SHIFT-NEW", shift_date="2026-12-31", status="Running")],
		) as get_list:
			rows = stock_entry_shift_query("Shift", "2026-12", "shift_date", 0, 10, None)

		self.assertEqual(rows, [["SHIFT-NEW", "2026-12-31 · Running"]])
		kwargs = get_list.call_args.kwargs
		self.assertEqual(kwargs["order_by"], "shift_date desc, name desc")
		self.assertEqual(kwargs["filters"]["shift_date"], ["like", "%2026-12%"])

	def test_stock_entry_shift_query_applies_branch_user_permissions(self) -> None:
		shift = make_completed_shift(bootstrap_manufacture_masters())

		frappe.set_user(_make_branch_restricted_user(shift.branch))
		self.assertIn(shift.name, _search_shift_names())

		frappe.set_user("Administrator")
		other_branch = ensure_branch("_Test Shift Search Other Branch")
		frappe.db.set_value("User Permission", {"user": _RESTRICTED_USER}, "for_value", other_branch)
		frappe.clear_cache(user=_RESTRICTED_USER)
		frappe.set_user(_RESTRICTED_USER)
		self.assertNotIn(shift.name, _search_shift_names())


def _search_shift_names() -> set[str]:
	return {row[0] for row in stock_entry_shift_query("Shift", "", "name", 0, 500, None)}
