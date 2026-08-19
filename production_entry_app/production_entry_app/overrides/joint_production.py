from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt


@dataclass(frozen=True)
class JointBomDetails:
	name: str
	item_code: str
	quantity: float
	total_cost: float
	rm_item_code: str
	rm_qty: float
	rm_uom: str
	scrap_item_code: str
	scrap_qty: float
	scrap_uom: str
	scrap_rate: float

	@property
	def unit_cost(self) -> float:
		return self.total_cost / self.quantity

	@property
	def unit_net_weight(self) -> float:
		return (self.rm_qty - self.scrap_qty) / self.quantity


def calculate_joint_scrap_quantity(
	*,
	total_rm_consumption: float,
	lh_gross_qty: float,
	lh_unit_net_weight: float,
	rh_gross_qty: float,
	rh_unit_net_weight: float,
) -> float:
	scrap_qty = flt(total_rm_consumption) - (
		flt(lh_gross_qty) * flt(lh_unit_net_weight) + flt(rh_gross_qty) * flt(rh_unit_net_weight)
	)
	if scrap_qty < 0:
		frappe.throw(_("Total RM Consumption cannot be less than the net weight of the joint outputs."))
	return scrap_qty


def allocate_joint_output_value(
	*,
	net_production_value: float,
	lh_gross_qty: float,
	lh_bom_unit_cost: float,
	rh_gross_qty: float,
	rh_bom_unit_cost: float,
) -> dict[str, float]:
	lh_weight = flt(lh_gross_qty) * flt(lh_bom_unit_cost)
	rh_weight = flt(rh_gross_qty) * flt(rh_bom_unit_cost)
	total_weight = lh_weight + rh_weight
	if total_weight <= 0:
		frappe.throw(_("Joint output BOM cost weight must be greater than zero."))
	value = flt(net_production_value)
	lh_value = value * lh_weight / total_weight
	return {"LH": lh_value, "RH": value - lh_value}


def build_joint_item_rows(doc: Any) -> list[dict[str, Any]]:
	_validate_joint_header(doc)
	lh_bom = _get_joint_bom_details(doc.get("custom_pea_lh_bom"))
	rh_bom = _get_joint_bom_details(doc.get("custom_pea_rh_bom"))
	_validate_joint_bom_pair(lh_bom, rh_bom)

	lh_gross = flt(doc.get("custom_pea_lh_gross_qty"))
	lh_rejection = flt(doc.get("custom_pea_lh_rejection_qty"))
	rh_gross = flt(doc.get("custom_pea_rh_gross_qty"))
	rh_rejection = flt(doc.get("custom_pea_rh_rejection_qty"))
	_validate_side_quantities("LH", lh_gross, lh_rejection)
	_validate_side_quantities("RH", rh_gross, rh_rejection)

	scrap_qty = calculate_joint_scrap_quantity(
		total_rm_consumption=flt(doc.get("custom_pea_total_rm_consumption")),
		lh_gross_qty=lh_gross,
		lh_unit_net_weight=lh_bom.unit_net_weight,
		rh_gross_qty=rh_gross,
		rh_unit_net_weight=rh_bom.unit_net_weight,
	)
	doc.set("custom_pea_joint_scrap_qty", scrap_qty)

	rows = [
		_item_row(
			item_code=lh_bom.rm_item_code,
			qty=flt(doc.get("custom_pea_total_rm_consumption")),
			s_warehouse=doc.get("from_warehouse"),
		),
	]
	rows.extend(
		_build_side_rows(
			side="LH",
			bom=lh_bom,
			gross_qty=lh_gross,
			rejection_qty=lh_rejection,
			fg_warehouse=doc.get("to_warehouse"),
			rejection_warehouse=_get_rejection_warehouse(doc),
		)
	)
	rows.extend(
		_build_side_rows(
			side="RH",
			bom=rh_bom,
			gross_qty=rh_gross,
			rejection_qty=rh_rejection,
			fg_warehouse=doc.get("to_warehouse"),
			rejection_warehouse=_get_rejection_warehouse(doc),
		)
	)
	if scrap_qty > 0:
		scrap_row = _item_row(
			item_code=lh_bom.scrap_item_code,
			qty=scrap_qty,
			t_warehouse=doc.get("to_warehouse"),
		)
		scrap_row.update(
			{
				"is_finished_item": 1,
				"set_basic_rate_manually": 1,
				"basic_rate": lh_bom.scrap_rate,
			}
		)
		stock_entry_detail_meta = frappe.get_meta("Stock Entry Detail", cached=True)
		if stock_entry_detail_meta.has_field("is_scrap_item"):
			scrap_row["is_scrap_item"] = 1
		else:
			scrap_row["type"] = "Scrap"
		rows.append(scrap_row)
	return rows


def is_joint_lh_rh_production(doc: Any) -> bool:
	if cint(doc.get("custom_pea_is_joint_lh_rh")):
		return True
	stock_entry_type = doc.get("stock_entry_type")
	if not stock_entry_type:
		return False
	return bool(
		frappe.db.get_value(
			"Stock Entry Type",
			stock_entry_type,
			"custom_pea_joint_lh_rh_production",
		)
	)


def validate_joint_production(doc: Any) -> None:
	if not is_joint_lh_rh_production(doc):
		return
	if not doc.get("stock_entry_type") or not frappe.db.get_value(
		"Stock Entry Type",
		doc.get("stock_entry_type"),
		"custom_pea_joint_lh_rh_production",
	):
		frappe.throw(_("Select a Stock Entry Type configured for Joint LH/RH Production."))
	doc.set("custom_pea_is_joint_lh_rh", 1)
	build_joint_item_rows(doc)
	lh_bom = _get_joint_bom_details(doc.get("custom_pea_lh_bom"))
	rh_bom = _get_joint_bom_details(doc.get("custom_pea_rh_bom"))
	_validate_joint_rm_consumption(doc, lh_bom)
	_validate_joint_rejection_breakup(doc)
	_set_joint_output_valuation(doc, lh_bom, rh_bom)


def _validate_joint_rm_consumption(doc: Any, bom: JointBomDetails) -> None:
	outgoing_rows = [row for row in (doc.get("items") or []) if row.get("s_warehouse")]
	if not outgoing_rows or any(row.get("item_code") != bom.rm_item_code for row in outgoing_rows):
		frappe.throw(_("Joint production outgoing rows must contain only the common BOM raw material."))
	actual_rm_qty = sum(flt(row.get("qty")) * flt(row.get("conversion_factor") or 1) for row in outgoing_rows)
	expected_rm_qty = flt(doc.get("custom_pea_total_rm_consumption"))
	if flt(actual_rm_qty, 6) != flt(expected_rm_qty, 6):
		frappe.throw(
			_("Outgoing raw material quantity must equal Total RM Consumption ({0}).").format(expected_rm_qty)
		)


def _set_joint_output_valuation(
	doc: Any,
	lh_bom: JointBomDetails,
	rh_bom: JointBomDetails,
) -> None:
	rows = doc.get("items") or []
	outgoing_value = sum(
		flt(row.get("basic_amount")) for row in rows if row.get("s_warehouse") and not row.get("t_warehouse")
	)
	scrap_value = sum(
		flt(row.get("transfer_qty") or row.get("qty")) * flt(row.get("basic_rate"))
		for row in rows
		if _is_scrap_row(row)
	)
	allocation = allocate_joint_output_value(
		net_production_value=outgoing_value - scrap_value,
		lh_gross_qty=doc.get("custom_pea_lh_gross_qty"),
		lh_bom_unit_cost=lh_bom.unit_cost,
		rh_gross_qty=doc.get("custom_pea_rh_gross_qty"),
		rh_bom_unit_cost=rh_bom.unit_cost,
	)
	for side in ("LH", "RH"):
		side_rows = [
			row for row in rows if row.get("custom_pea_joint_output_side") == side and not _is_scrap_row(row)
		]
		side_qty = sum(flt(row.get("transfer_qty") or row.get("qty")) for row in side_rows)
		if side_qty <= 0:
			frappe.throw(_("Joint production requires at least one {0} output row.").format(side))
		side_rate = allocation[side] / side_qty
		for row in side_rows:
			row.set_basic_rate_manually = 1
			row.basic_rate = side_rate

	# Native Stock Entry recalculation applies the manual rates consistently to
	# basic amounts, valuation rates, totals, and the eventual ledger entries.
	doc.calculate_rate_and_amount(reset_outgoing_rate=False)


def _is_scrap_row(row: Any) -> bool:
	return bool(row.get("is_scrap_item") or row.get("is_legacy_scrap_item") or row.get("type") == "Scrap")


def _validate_joint_rejection_breakup(doc: Any) -> None:
	expected = {
		"LH": flt(doc.get("custom_pea_lh_rejection_qty"), 6),
		"RH": flt(doc.get("custom_pea_rh_rejection_qty"), 6),
	}
	actual = {"LH": 0.0, "RH": 0.0}
	items = {
		"LH": _get_joint_bom_details(doc.get("custom_pea_lh_bom")).item_code,
		"RH": _get_joint_bom_details(doc.get("custom_pea_rh_bom")).item_code,
	}
	for row in doc.get("custom_pea_rejection_breakup") or []:
		side = row.get("output_side")
		if side not in actual:
			frappe.throw(_("Every joint rejection breakup row must specify LH or RH Output Side."))
		if not row.get("item_code"):
			row.set("item_code", items[side])
		elif row.get("item_code") != items[side]:
			frappe.throw(_("Joint rejection breakup Item must match the selected {0} BOM.").format(side))
		actual[side] += flt(row.get("qty"), 6)
	for side in ("LH", "RH"):
		if flt(actual[side], 6) != expected[side]:
			frappe.throw(_("{0} rejection breakup total must equal {0} Rejection Quantity.").format(side))


def _validate_joint_header(doc: Any) -> None:
	if doc.get("purpose") != "Repack":
		frappe.throw(_("Joint LH/RH production must use Repack purpose."))
	for fieldname, label in (
		("custom_pea_lh_bom", "LH BOM"),
		("custom_pea_rh_bom", "RH BOM"),
		("custom_pea_die_tool_item", "Die Tool Item"),
		("from_warehouse", "Source Warehouse"),
		("to_warehouse", "Target Warehouse"),
	):
		if not doc.get(fieldname):
			frappe.throw(_("{0} is required for joint LH/RH production.").format(label))
	if flt(doc.get("custom_pea_total_rm_consumption")) <= 0:
		frappe.throw(_("Total RM Consumption must be greater than zero."))
	if flt(doc.get("custom_pea_total_strokes")) <= 0:
		frappe.throw(_("Total Press Strokes must be greater than zero."))


def _get_joint_bom_details(bom_no: str) -> JointBomDetails:
	bom = frappe.get_doc("BOM", bom_no)
	if bom.docstatus != 1 or not bom.is_active:
		frappe.throw(_("BOM {0} must be submitted and active.").format(frappe.bold(bom_no)))
	items = list(bom.get("items") or [])
	if bom.meta.has_field("scrap_items"):
		scrap_items = list(bom.get("scrap_items") or [])
	else:
		scrap_items = [
			row
			for row in (bom.get("secondary_items") or [])
			if row.get("type") == "Scrap" or row.get("is_legacy")
		]
	if len(items) != 1:
		frappe.throw(_("BOM {0} must contain exactly one raw material item.").format(frappe.bold(bom_no)))
	if len(scrap_items) != 1:
		frappe.throw(_("BOM {0} must contain exactly one scrap item.").format(frappe.bold(bom_no)))
	if flt(bom.quantity) <= 0:
		frappe.throw(_("BOM {0} quantity must be greater than zero.").format(frappe.bold(bom_no)))
	rm = items[0]
	scrap = scrap_items[0]
	scrap_qty = flt(scrap.get("stock_qty") or scrap.get("qty"))
	scrap_rate = flt(scrap.get("rate"))
	if not scrap_rate and scrap_qty > 0:
		scrap_rate = flt(scrap.get("cost")) / scrap_qty
	return JointBomDetails(
		name=bom.name,
		item_code=bom.item,
		quantity=flt(bom.quantity),
		total_cost=flt(bom.total_cost),
		rm_item_code=rm.item_code,
		rm_qty=flt(rm.stock_qty or rm.qty),
		rm_uom=rm.stock_uom or rm.uom,
		scrap_item_code=scrap.item_code,
		scrap_qty=scrap_qty,
		scrap_uom=scrap.get("stock_uom") or scrap.get("uom"),
		scrap_rate=scrap_rate,
	)


def _validate_joint_bom_pair(lh_bom: JointBomDetails, rh_bom: JointBomDetails) -> None:
	if (lh_bom.rm_item_code, lh_bom.rm_uom) != (rh_bom.rm_item_code, rh_bom.rm_uom):
		frappe.throw(_("LH and RH BOMs must use the same raw material item and UOM."))
	if abs(lh_bom.rm_qty - rh_bom.rm_qty) > 0.000001:
		frappe.throw(_("LH and RH BOMs must use the same raw material quantity per sheet."))
	if (lh_bom.scrap_item_code, lh_bom.scrap_uom) != (
		rh_bom.scrap_item_code,
		rh_bom.scrap_uom,
	):
		frappe.throw(_("LH and RH BOMs must use the same scrap item and UOM."))


def _validate_side_quantities(side: str, gross_qty: float, rejection_qty: float) -> None:
	if gross_qty <= 0:
		frappe.throw(_("{0} Gross Quantity must be greater than zero.").format(side))
	if rejection_qty < 0 or rejection_qty > gross_qty:
		frappe.throw(_("{0} Rejection Quantity must be between zero and Gross Quantity.").format(side))


def _build_side_rows(
	*,
	side: str,
	bom: JointBomDetails,
	gross_qty: float,
	rejection_qty: float,
	fg_warehouse: str,
	rejection_warehouse: str,
) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []
	good_qty = gross_qty - rejection_qty
	if good_qty > 0:
		rows.append(_joint_output_row(side, bom, good_qty, fg_warehouse, is_rejection=False))
	if rejection_qty > 0:
		rows.append(_joint_output_row(side, bom, rejection_qty, rejection_warehouse, is_rejection=True))
	return rows


def _joint_output_row(
	side: str,
	bom: JointBomDetails,
	qty: float,
	warehouse: str,
	*,
	is_rejection: bool,
) -> dict[str, Any]:
	row = _item_row(item_code=bom.item_code, qty=qty, t_warehouse=warehouse)
	row.update(
		{
			"bom_no": bom.name if not is_rejection else "",
			"is_finished_item": 1,
			"is_scrap_item": 0,
			"set_basic_rate_manually": 1,
			"basic_rate": bom.unit_cost,
			"custom_pea_is_rejection_item": int(is_rejection),
			"custom_pea_joint_output_side": side,
		}
	)
	return row


def _item_row(
	*,
	item_code: str,
	qty: float,
	s_warehouse: str | None = None,
	t_warehouse: str | None = None,
) -> dict[str, Any]:
	item = frappe.db.get_value(
		"Item",
		item_code,
		["item_name", "description", "stock_uom"],
		as_dict=True,
	)
	return {
		"item_code": item_code,
		"item_name": item.item_name,
		"description": item.description,
		"qty": flt(qty),
		"transfer_qty": flt(qty),
		"uom": item.stock_uom,
		"stock_uom": item.stock_uom,
		"conversion_factor": 1,
		"s_warehouse": s_warehouse,
		"t_warehouse": t_warehouse,
	}


def _get_rejection_warehouse(doc: Any) -> str:
	if doc.get("custom_pea_shift"):
		warehouse = frappe.db.get_value("Shift", doc.get("custom_pea_shift"), "rejection_warehouse")
		if warehouse:
			return warehouse
	return frappe.db.get_single_value("Production Entry Settings", "shift_rejection_warehouse") or doc.get(
		"to_warehouse"
	)


def validate_stock_entry_type(doc: Any, method: str | None = None) -> None:
	if not doc.get("custom_pea_joint_lh_rh_production"):
		return
	if doc.get("purpose") != "Repack":
		frappe.throw(_("Joint LH/RH Stock Entry Types must use Repack purpose."))
