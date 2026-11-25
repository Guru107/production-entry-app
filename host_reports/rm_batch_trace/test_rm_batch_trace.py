"""Tests for the RM Batch Trace host report, run through Frappe's real safe_exec.

Run from a bench's sites folder against a dev site (all data is rolled back):
    cd /root/workspace/bench15/sites
    ../env/bin/python ../../production-entry-app/host_reports/rm_batch_trace/test_rm_batch_trace.py development.localhost

Each test inserts the Report built from report.json + rm_batch_trace.py (the same payload
publish.py sends), builds real stock documents, and runs the report through
frappe.desk.query_report.run, so role checks, filters and the sandbox are all exercised.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import frappe

sys.path.insert(0, str(Path(__file__).resolve().parent))

from publish import build_report_payload

REPORT = "RM Batch Trace"


class TestRMBatchTrace(unittest.TestCase):
	def setUp(self) -> None:
		from production_entry_app.production_entry_app.utils.test_bootstrap import (
			ensure_branch,
			ensure_item,
			ensure_warehouse,
			resolve_test_company,
		)

		frappe.set_user("Administrator")
		self.ensure_item = ensure_item
		self.company = resolve_test_company()
		abbr = frappe.db.get_value("Company", self.company, "abbr")
		self.stores = ensure_warehouse(f"RMBT Stores - {abbr}", self.company)
		self.wip = ensure_warehouse(f"RMBT WIP - {abbr}", self.company)
		self.fg = ensure_warehouse(f"RMBT FG - {abbr}", self.company)
		self.dispatch = ensure_warehouse(f"RMBT Dispatch - {abbr}", self.company)
		self.scrap_wh = ensure_warehouse(f"RMBT Scrap - {abbr}", self.company)
		self.job_worker = ensure_warehouse(f"RMBT Job Worker - {abbr}", self.company)
		self.customer = self._ensure_customer("_RMBT Customer")
		self.branch = ensure_branch("RMBT Branch")
		self.suffix = frappe.generate_hash(length=5)
		self.rm = self._batched_item(f"_RMBT RM {self.suffix}")
		self.b1 = self._batch(self.rm, f"RMBT-B1-{self.suffix}")
		self.b2 = self._batch(self.rm, f"RMBT-B2-{self.suffix}")
		self.fg_item = ensure_item(f"_RMBT FG {self.suffix}")
		payload = build_report_payload()
		payload["doctype"] = "Report"
		payload["disable_prepared_report_automation"] = 1
		if frappe.db.exists("Report", REPORT):
			frappe.delete_doc("Report", REPORT, force=True)
		frappe.get_doc(payload).insert()

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		frappe.db.rollback()

	# ---------------------------------------------------------------- builders

	def _ensure_customer(self, name: str) -> str:
		if not frappe.db.exists("Customer", name):
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": name,
					"customer_group": frappe.get_all(
						"Customer Group", {"is_group": 0}, pluck="name", limit=1
					)[0],
					"territory": frappe.get_all("Territory", {"is_group": 0}, pluck="name", limit=1)[0],
				}
			).insert()
		return name

	def _ensure_supplier(self, name: str) -> str:
		group = "_RMBT Suppliers"
		if not frappe.db.exists("Supplier Group", group):
			frappe.get_doc(
				{
					"doctype": "Supplier Group",
					"supplier_group_name": group,
					"parent_supplier_group": "All Supplier Groups",
				}
			).insert()
		if not frappe.db.exists("Supplier", name):
			frappe.get_doc({"doctype": "Supplier", "supplier_name": name, "supplier_group": group}).insert()
		return name

	def _batched_item(self, code: str, item_group: str = "Sheet Metals") -> str:
		self.ensure_item(code, item_group=item_group, stock_uom="Kg")
		frappe.db.set_value("Item", code, "has_batch_no", 1)
		return code

	def _batch(self, item: str, batch_id: str) -> str:
		values = {"doctype": "Batch", "item": item, "batch_id": batch_id}
		# Sites that name Sheet Metals batches HEAT-COIL require both numbers on insert.
		if frappe.get_meta("Batch").has_field("custom_heat_number"):
			values.update({"custom_heat_number": batch_id, "custom_coil_number": "C1"})
		return frappe.get_doc(values).insert().name

	def _stock_entry(self, purpose: str, rows: list[dict], **fields) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"purpose": purpose,
				"stock_entry_type": purpose,
				"company": self.company,
				"items": [],
				**fields,
			}
		)
		for row in rows:
			row = {"basic_rate": 10, "conversion_factor": 1, **row}
			if row.get("batch_no"):
				row["use_serial_batch_fields"] = 1
			doc.append("items", row)
		if purpose == "Manufacture":
			doc.fg_completed_qty = sum(
				r["qty"] for r in rows if r.get("is_finished_item") and not r.get("is_scrap_item")
			)
		doc.insert()
		doc.submit()
		return doc.name

	def _receive(self, item: str, qty: float, warehouse: str, batch: str | None = None) -> str:
		return self._stock_entry(
			"Material Receipt", [{"item_code": item, "qty": qty, "t_warehouse": warehouse, "batch_no": batch}]
		)

	def _manufacture(self, inputs: list[tuple], outputs: list[tuple]) -> str:
		"""inputs: (item, qty, batch); outputs: (item, qty, warehouse, kind) with kind fg/scrap."""
		rows = [
			{"item_code": item, "qty": qty, "s_warehouse": self.wip, "batch_no": batch}
			for item, qty, batch in inputs
		]
		for item, qty, warehouse, kind in outputs:
			rows.append(
				{
					"item_code": item,
					"qty": qty,
					"t_warehouse": warehouse,
					"is_finished_item": int(kind == "fg"),
					"is_scrap_item": int(kind == "scrap"),
				}
			)
		return self._stock_entry("Manufacture", rows)

	def _transfer(self, item: str, qty: float, source: str, target: str) -> str:
		return self._stock_entry(
			"Material Transfer",
			[{"item_code": item, "qty": qty, "s_warehouse": source, "t_warehouse": target}],
		)

	def _sales_invoice(
		self, lines: list[tuple], update_stock: int = 1, submit: bool = True, branch: str | None = None
	) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": self.customer,
				"branch": branch or self.branch,
				"update_stock": update_stock,
				"items": [
					{
						"item_code": item,
						"qty": qty,
						"rate": 100,
						"warehouse": warehouse,
						"item_tax_template": self._tax_template(),
					}
					for item, qty, warehouse in lines
				],
			}
		)
		doc.insert()
		if submit:
			doc.submit()
		return doc.name

	def _submit_with_host_fields(self, values: dict):
		"""Insert and submit, filling fields that only the production-parity host makes mandatory."""
		from erpnext.accounts.utils import get_fiscal_year

		doc = frappe.get_doc(values)
		host_fields = {
			"custom_order_type": "Job",
			"custom_purchase_receipt_type": "Material",
			"custom_fiscal_year": get_fiscal_year(frappe.utils.nowdate(), company=self.company)[0],
		}
		for fieldname, value in host_fields.items():
			if doc.meta.has_field(fieldname) and not doc.get(fieldname):
				doc.set(fieldname, value)
		if doc.meta.has_field("taxes") and doc.meta.get_field("taxes").reqd and not doc.get("taxes"):
			template = frappe.db.get_value(
				"Purchase Taxes and Charges Template", {"company": self.company, "disabled": 0}
			)
			doc.taxes_and_charges = template
			for tax in frappe.get_all(
				"Purchase Taxes and Charges",
				filters={"parent": template, "parenttype": "Purchase Taxes and Charges Template"},
				fields=["charge_type", "account_head", "description", "rate", "category", "add_deduct_tax"],
				order_by="idx",
			):
				doc.append("taxes", tax)
		doc.insert()
		doc.submit()
		return doc

	def _tax_template(self) -> str | None:
		# Production-parity sites make item_tax_template mandatory on sales and purchase lines.
		return frappe.db.get_value("Item Tax Template", {"company": self.company, "disabled": 0})

	def _run(self, invoice, **extra) -> dict:
		from frappe.desk.query_report import run

		filters = {"branch": self.branch, "sales_invoice": invoice, **extra}
		return run(REPORT, filters=json.dumps(filters), ignore_prepared_report=True)

	def _traced(self, result: dict) -> dict[tuple[str, str], float]:
		return {
			(row["item_code"], row["batch_no"]): round(row["qty"], 3)
			for row in result["result"]
			if row["status"].startswith("Traced")
		}

	def _untraced(self, result: dict) -> dict[tuple[str, str], float]:
		return {
			(row["status"], row["item_code"]): round(row["qty"], 3)
			for row in result["result"]
			if row["status"].startswith("Untraced")
		}

	# ------------------------------------------------------------------- tests

	def test_fifo_through_manufacture_and_transfer_from_a_sales_invoice(self) -> None:
		self._receive(self.rm, 100, self.wip, self.b1)
		self._receive(self.rm, 100, self.wip, self.b2)
		self._manufacture([(self.rm, 10, self.b1)], [(self.fg_item, 100, self.fg, "fg")])
		self._manufacture([(self.rm, 20, self.b2)], [(self.fg_item, 100, self.fg, "fg")])
		self._transfer(self.fg_item, 200, self.fg, self.dispatch)
		invoice = self._sales_invoice([(self.fg_item, 150, self.dispatch)])

		result = self._run(invoice)

		# FIFO: the first 100 pcs came from the B1 run (10 kg), the next 50 from the B2 run (half of 20 kg).
		self.assertEqual(self._traced(result), {(self.rm, self.b1): 10.0, (self.rm, self.b2): 10.0})
		self.assertEqual(self._untraced(result), {})
		shares = sorted(row["share"] for row in result["result"])
		self.assertEqual(shares, [50.0, 50.0])

	def test_same_item_in_two_rows_maps_each_row_to_its_own_slice(self) -> None:
		self._receive(self.rm, 100, self.wip, self.b1)
		self._receive(self.rm, 100, self.wip, self.b2)
		# Inputs laid end to end: 6 kg B1 then 4 kg B2; outputs 60 pcs to FG then 40 pcs to Dispatch.
		self._manufacture(
			[(self.rm, 6, self.b1), (self.rm, 4, self.b2)],
			[(self.fg_item, 60, self.fg, "fg"), (self.fg_item, 40, self.dispatch, "fg")],
		)
		invoice = self._sales_invoice([(self.fg_item, 40, self.dispatch)])

		self.assertEqual(self._traced(self._run(invoice)), {(self.rm, self.b2): 4.0})

	def test_stock_reconciliation_uses_balance_deltas(self) -> None:
		self._receive(self.rm, 100, self.wip, self.b1)
		self._receive(self.rm, 100, self.wip, self.b2)
		self._manufacture([(self.rm, 10, self.b1)], [(self.fg_item, 100, self.fg, "fg")])
		self._reconcile(self.fg_item, self.fg, 50)
		self._manufacture([(self.rm, 20, self.b2)], [(self.fg_item, 100, self.fg, "fg")])
		self._reconcile(self.fg_item, self.fg, 170)
		invoice = self._sales_invoice([(self.fg_item, 170, self.fg)])

		result = self._run(invoice)

		# The reset to 50 consumed the oldest 50 pcs; the reset to 170 added 20 pcs of unknown origin.
		self.assertEqual(self._traced(result), {(self.rm, self.b1): 5.0, (self.rm, self.b2): 20.0})
		self.assertEqual(self._untraced(result), {("Untraced: Stock Reconciliation", self.fg_item): 20.0})

	def _reconcile(self, item: str, warehouse: str, qty: float) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Stock Reconciliation",
				"company": self.company,
				"purpose": "Stock Reconciliation",
				"expense_account": frappe.db.get_value("Company", self.company, "stock_adjustment_account"),
				"items": [{"item_code": item, "warehouse": warehouse, "qty": qty, "valuation_rate": 10}],
			}
		)
		doc.insert()
		doc.submit()
		return doc.name

	def test_end_pieces_chain_back_to_the_parent_sheet_and_scrap_stops(self) -> None:
		end_piece = self.ensure_item(f"_RMBT EP {self.suffix}", item_group="Reuse", stock_uom="Kg")
		end_piece_2 = self.ensure_item(f"_RMBT EP2 {self.suffix}", item_group="Reuse", stock_uom="Kg")
		scrap = self.ensure_item(f"_RMBT Scrap {self.suffix}", item_group="Scrap", stock_uom="Kg")
		part_b = self.ensure_item(f"_RMBT Part B {self.suffix}")
		part_c = self.ensure_item(f"_RMBT Part C {self.suffix}")
		self._receive(self.rm, 100, self.wip, self.b1)
		self._receive(self.rm, 100, self.wip, self.b2)
		# Shearing 1: 50 kg of B1 → 100 blanks + a 5 kg End Piece back to WIP.
		self._manufacture(
			[(self.rm, 50, self.b1)],
			[(self.fg_item, 100, self.fg, "fg"), (end_piece, 5, self.wip, "scrap")],
		)
		# Shearing 2 runs on that End Piece plus 1 kg of B2 and leaves another End Piece and true scrap.
		self._manufacture(
			[(end_piece, 5, None), (self.rm, 1, self.b2)],
			[
				(part_b, 20, self.fg, "fg"),
				(end_piece_2, 2, self.wip, "scrap"),
				(scrap, 0.5, self.scrap_wh, "scrap"),
			],
		)
		self._manufacture([(end_piece_2, 2, None)], [(part_c, 10, self.fg, "fg")])
		invoice = self._sales_invoice(
			[(part_b, 20, self.fg), (part_c, 10, self.fg), (scrap, 0.5, self.scrap_wh)]
		)

		result = self._run(invoice)
		by_line = {}
		for row in result["result"]:
			by_line.setdefault(row["line"], []).append(row)

		part_b_rows = {(r["item_code"], r["batch_no"]): round(r["qty"], 3) for r in by_line[1]}
		self.assertEqual(part_b_rows, {(self.rm, self.b1): 5.0, (self.rm, self.b2): 1.0})
		# Part C's 2 kg End Piece is the first 2 kg of Shearing 2's kg inputs, i.e. the B1 End Piece.
		part_c_rows = {(r["item_code"], r["batch_no"]): round(r["qty"], 3) for r in by_line[2]}
		self.assertEqual(part_c_rows, {(self.rm, self.b1): 2.0})
		self.assertIn("End Piece", by_line[2][0]["via"])
		self.assertEqual([(r["status"], round(r["qty"], 3)) for r in by_line[3]], [("Untraced: Scrap", 0.5)])

	def test_purchase_receipt_of_unbatched_item_is_untraced(self) -> None:
		bought = self.ensure_item(f"_RMBT Bought {self.suffix}")
		receipt = self._submit_with_host_fields(
			{
				"doctype": "Purchase Receipt",
				"company": self.company,
				"supplier": self._ensure_supplier("_RMBT Supplier"),
				"items": [
					{
						"item_code": bought,
						"qty": 10,
						"rate": 5,
						"warehouse": self.fg,
						"item_tax_template": self._tax_template(),
					}
				],
			}
		)
		invoice = self._sales_invoice([(bought, 4, self.fg)])

		result = self._run(invoice)

		self.assertEqual(self._traced(result), {})
		self.assertEqual(self._untraced(result), {("Untraced: Purchase Receipt", bought): 4.0})
		self.assertIn(receipt.name, result["result"][0]["via"])

	def test_subcontracting_receipt_traces_supplied_raw_material(self) -> None:
		from erpnext.controllers.subcontracting_controller import make_rm_stock_entry
		from erpnext.subcontracting.doctype.subcontracting_order.subcontracting_order import (
			make_subcontracting_receipt,
		)
		from erpnext.subcontracting.doctype.subcontracting_order.test_subcontracting_order import (
			create_subcontracting_order,
		)

		from production_entry_app.production_entry_app.utils.test_bootstrap import ensure_default_bom

		coated = self.ensure_item(f"_RMBT Coated {self.suffix}")
		frappe.db.set_value("Item", coated, "is_sub_contracted_item", 1)
		service = self.ensure_item(f"_RMBT Coating {self.suffix}")
		frappe.db.set_value("Item", service, "is_stock_item", 0)
		bom = ensure_default_bom(fg_item=coated, rm_item=self.fg_item, company=self.company)
		frappe.db.set_value("BOM Item", {"parent": bom}, "qty", 1)
		frappe.db.set_value("BOM Item", {"parent": bom}, "stock_qty", 1)
		frappe.db.set_value("BOM", bom, "quantity", 1)

		self._receive(self.rm, 100, self.wip, self.b1)
		self._manufacture([(self.rm, 10, self.b1)], [(self.fg_item, 100, self.stores, "fg")])
		order = self._submit_with_host_fields(
			{
				"doctype": "Purchase Order",
				"company": self.company,
				"supplier": self._ensure_supplier("_RMBT Supplier"),
				"is_subcontracted": 1,
				"supplier_warehouse": self.job_worker,
				"schedule_date": frappe.utils.add_days(frappe.utils.nowdate(), 7),
				"items": [
					{
						"item_code": service,
						"qty": 50,
						"rate": 5,
						"warehouse": self.fg,
						"fg_item": coated,
						"fg_item_qty": 50,
						"schedule_date": frappe.utils.add_days(frappe.utils.nowdate(), 7),
						"item_tax_template": self._tax_template(),
					}
				],
			}
		)
		sco = create_subcontracting_order(po_name=order.name, warehouse=self.fg)
		transfer = frappe.get_doc(
			make_rm_stock_entry(
				sco.name,
				[
					{
						"item_code": coated,
						"rm_item_code": self.fg_item,
						"item_name": self.fg_item,
						"qty": 50,
						"warehouse": self.stores,
						"stock_uom": "Nos",
					}
				],
			)
		)
		transfer.to_warehouse = self.job_worker
		for row in transfer.items:
			row.s_warehouse = self.stores
			row.t_warehouse = self.job_worker
		transfer.insert()
		transfer.submit()
		self._submit_with_host_fields(make_subcontracting_receipt(sco.name).as_dict())
		invoice = self._sales_invoice([(coated, 50, self.fg)])

		result = self._run(invoice)

		# 50 coated parts used 50 blanks = half of the 100-blank run on 10 kg of B1.
		self.assertEqual(self._traced(result), {(self.rm, self.b1): 5.0})
		self.assertIn("job work", result["result"][0]["via"])

	def test_joint_lh_rh_entry_splits_shared_sheet_by_bom(self) -> None:
		from production_entry_app.production_entry_app.api import get_joint_production_items
		from production_entry_app.production_entry_app.joint_production import JOINT_LH_RH_STOCK_ENTRY_TYPE
		from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
			bootstrap_manufacture_masters,
			make_running_shift,
		)
		from production_entry_app.production_entry_app.utils.test_bootstrap import (
			ensure_joint_test_bom,
			ensure_operation,
			ensure_operator,
			ensure_workstation,
		)

		masters = bootstrap_manufacture_masters()
		operation = ensure_operation("Shearing")
		lh = self.ensure_item(f"_RMBT LH {self.suffix}")
		rh = self.ensure_item(f"_RMBT RH {self.suffix}")
		end_piece = self.ensure_item(f"_RMBT JEP {self.suffix}", item_group="Reuse", stock_uom="Kg")
		# Shearing BOMs share one sheet quantity, so RH weighs twice LH by having half the pieces:
		# 30 kg per 100 LH vs 30 kg per 50 RH.
		lh_bom = ensure_joint_test_bom(
			item_code=lh,
			rm_item=self.rm,
			scrap_items=[(end_piece, 1, 10)],
			company=masters["company"],
			bom_quantity=100,
			rm_qty=30,
		)
		rh_bom = ensure_joint_test_bom(
			item_code=rh,
			rm_item=self.rm,
			scrap_items=[(end_piece, 1, 10)],
			company=masters["company"],
			bom_quantity=50,
			rm_qty=30,
		)
		ensure_workstation("RMBT Workstation", standard_spm=2)
		ensure_operator("RMBT Operator")
		self._stock_entry(
			"Material Receipt",
			[
				{
					"item_code": self.rm,
					"qty": 100,
					"t_warehouse": masters["wip_warehouse"],
					"batch_no": self.b1,
				}
			],
		)
		shift = make_running_shift(masters)
		start = frappe.utils.add_to_date(
			frappe.utils.get_datetime(f"{shift.shift_date} {shift.planned_start_time}"), minutes=15
		)
		doc = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"purpose": "Repack",
				"stock_entry_type": JOINT_LH_RH_STOCK_ENTRY_TYPE,
				"company": masters["company"],
				"from_warehouse": masters["wip_warehouse"],
				"to_warehouse": masters["fg_warehouse"],
				"custom_pea_shift": shift.name,
				"custom_pea_actual_start_date": start,
				"custom_pea_actual_end_date": frappe.utils.add_to_date(start, minutes=45),
				"custom_pea_operation": operation,
				"custom_pea_total_strokes": 40,
				"custom_pea_standard_spm": 2,
				"custom_pea_die_tool_item": lh,
				"custom_pea_workstation": "RMBT Workstation",
				"custom_pea_operator": "RMBT Operator",
				"custom_pea_lh_bom": lh_bom,
				"custom_pea_lh_gross_qty": 40,
				"custom_pea_lh_rejection_qty": 0,
				"custom_pea_rh_bom": rh_bom,
				"custom_pea_rh_gross_qty": 40,
				"custom_pea_rh_rejection_qty": 0,
			}
		)
		doc.set("items", get_joint_production_items(json.dumps(doc.as_dict(), default=str)))
		for row in doc.items:
			if row.s_warehouse:
				row.batch_no = self.b1
				row.use_serial_batch_fields = 1
				row.basic_rate = 50
		doc.insert()
		doc.submit()
		invoice = self._sales_invoice([(rh, 40, masters["fg_warehouse"])])

		result = self._run(invoice)

		# Sheet used: LH 40 x 0.3 = 12 kg, RH 40 x 0.6 = 24 kg. Piece count would have said 18 kg.
		self.assertEqual(self._traced(result), {(self.rm, self.b1): 24.0})
		self.assertIn("Joint RH", result["result"][0]["via"])

	def test_item_filter_traces_only_that_items_lines(self) -> None:
		other = self.ensure_item(f"_RMBT Other {self.suffix}")
		self._receive(self.rm, 100, self.wip, self.b1)
		self._manufacture([(self.rm, 10, self.b1)], [(self.fg_item, 100, self.fg, "fg")])
		self._receive(other, 5, self.fg)
		invoice = self._sales_invoice([(self.fg_item, 10, self.fg), (other, 5, self.fg)])

		result = self._run(invoice, item=self.fg_item)

		self.assertEqual({row["line_item"] for row in result["result"]}, {self.fg_item})

	def test_sales_invoice_without_stock_update_is_rejected(self) -> None:
		self._receive(self.fg_item, 10, self.fg)
		invoice = self._sales_invoice([(self.fg_item, 1, self.fg)], update_stock=0)

		with self.assertRaisesRegex(frappe.ValidationError, "did not update stock"):
			self._run(invoice)

	def test_document_filter_must_be_a_single_name(self) -> None:
		self._receive(self.fg_item, 10, self.fg)
		self._sales_invoice([(self.fg_item, 1, self.fg)])

		with self.assertRaisesRegex(frappe.ValidationError, "Select the Sales Invoice"):
			self._run(["like", "%"])
		invoice = self._sales_invoice([(self.fg_item, 1, self.fg)])
		with self.assertRaisesRegex(frappe.ValidationError, "single Item"):
			self._run(invoice, item=["!=", ""])

	def test_invoice_from_another_branch_is_rejected(self) -> None:
		from production_entry_app.production_entry_app.utils.test_bootstrap import ensure_branch

		self._receive(self.fg_item, 10, self.fg)
		invoice = self._sales_invoice([(self.fg_item, 1, self.fg)], branch=ensure_branch("RMBT Other Branch"))

		with self.assertRaisesRegex(frappe.ValidationError, "belongs to Branch RMBT Other Branch"):
			self._run(invoice)

	def test_branch_is_required(self) -> None:
		self._receive(self.fg_item, 10, self.fg)
		invoice = self._sales_invoice([(self.fg_item, 1, self.fg)])

		with self.assertRaisesRegex(frappe.ValidationError, "Select a Branch"):
			self._run(invoice, branch=None)

	def test_draft_document_is_rejected(self) -> None:
		self._receive(self.fg_item, 10, self.fg)
		invoice = self._sales_invoice([(self.fg_item, 1, self.fg)], submit=False)

		with self.assertRaisesRegex(frappe.ValidationError, "not submitted"):
			self._run(invoice)

	def test_user_who_cannot_read_the_document_is_blocked(self) -> None:
		self._receive(self.fg_item, 10, self.fg)
		invoice = self._sales_invoice([(self.fg_item, 1, self.fg)])
		user = self._user("rmbt-stock-accounts-user@example.com", ["Stock User", "Accounts User"])
		other_customer = self._ensure_customer("_RMBT Other Customer")
		frappe.get_doc(
			{"doctype": "User Permission", "user": user, "allow": "Customer", "for_value": other_customer}
		).insert()

		frappe.set_user(user)
		with self.assertRaisesRegex(frappe.ValidationError, "permission to read"):
			self._run(invoice)

	def test_stock_user_without_sales_invoice_access_is_blocked(self) -> None:
		# Report roles let a Stock User open the report, but the invoice itself must be readable.
		self._receive(self.fg_item, 10, self.fg)
		invoice = self._sales_invoice([(self.fg_item, 1, self.fg)])
		user = self._user("rmbt-stock-user@example.com", ["Stock User"])

		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			self._run(invoice)

	def test_user_without_report_roles_is_blocked(self) -> None:
		self._receive(self.fg_item, 10, self.fg)
		invoice = self._sales_invoice([(self.fg_item, 1, self.fg)])
		user = self._user("rmbt-sales-user@example.com", ["Sales User"])

		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			self._run(invoice)

	def _user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "RMBT", "send_welcome_email": 0}
			).insert()
		user = frappe.get_doc("User", email)
		user.set("roles", [])
		for role in roles:
			user.append("roles", {"role": role})
		user.save()
		return email


def main() -> None:
	site = sys.argv[1] if len(sys.argv) > 1 else "development.localhost"
	frappe.init(site, sites_path=".")
	frappe.connect()
	frappe.flags.in_test = True
	try:
		suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestRMBatchTrace)
		names = sys.argv[2:]
		if names:
			suite = unittest.TestSuite(TestRMBatchTrace(name) for name in names)
		result = unittest.TextTestRunner(verbosity=2).run(suite)
	finally:
		frappe.db.rollback()
		frappe.destroy()
	sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
	main()
