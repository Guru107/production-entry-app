from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import frappe
from frappe import _
from frappe.model.base_document import BaseDocument
from frappe.model.document import Document
from frappe.utils import cint, flt

from production_entry_app.production_entry_app.doctype.rejection_breakup.rejection_breakup import (
	validate_rejection_breakup_row,
)
from production_entry_app.production_entry_app.utils.rejection_warehouse import resolve_rejection_warehouse

WHOLE_NUMBER_QUANTUM: Decimal = Decimal("1")
VALUATION_TOLERANCE: float = 1e-9


@dataclass(frozen=True)
class JointBomScrapItem:
	item_code: str
	qty: float
	uom: str
	rate: float


@dataclass(frozen=True)
class JointPlannedScrapItem:
	item_code: str
	qty: float
	uom: str
	rate: float

	@property
	def role(self) -> str:
		return f"scrap:{self.item_code}"


@dataclass(frozen=True)
class JointBomDetails:
	name: str
	item_code: str
	quantity: float
	total_cost: float
	rm_item_code: str
	rm_qty: float
	rm_uom: str
	scrap_items: tuple[JointBomScrapItem, ...]

	@property
	def unit_cost(self) -> float:
		return self.total_cost / self.quantity


@dataclass(frozen=True)
class JointProductionPlan:
	lh_bom: JointBomDetails
	rh_bom: JointBomDetails
	lh_gross_qty: float
	lh_rejection_qty: float
	rh_gross_qty: float
	rh_rejection_qty: float
	total_rm_consumption: float
	scrap_items: tuple[JointPlannedScrapItem, ...]

	@property
	def expected_role_quantities(self) -> dict[str, float]:
		quantities = {
			"rm": self.total_rm_consumption,
			"lh_good": self.lh_gross_qty - self.lh_rejection_qty,
			"lh_rejection": self.lh_rejection_qty,
			"rh_good": self.rh_gross_qty - self.rh_rejection_qty,
			"rh_rejection": self.rh_rejection_qty,
		}
		quantities.update({scrap.role: scrap.qty for scrap in self.scrap_items})
		return quantities


def calculate_joint_rm_consumption(
	*,
	lh_gross_qty: float,
	lh_bom_quantity: float,
	lh_rm_qty: float,
	rh_gross_qty: float,
	rh_bom_quantity: float,
	rh_rm_qty: float,
) -> float:
	lh_bom_quantity = flt(lh_bom_quantity)
	rh_bom_quantity = flt(rh_bom_quantity)
	lh_rm_qty = flt(lh_rm_qty)
	rh_rm_qty = flt(rh_rm_qty)
	if lh_bom_quantity <= 0 or rh_bom_quantity <= 0:
		frappe.throw(_("LH and RH BOM quantities must be greater than zero."))
	if lh_rm_qty <= 0 or rh_rm_qty <= 0:
		frappe.throw(_("LH and RH raw material quantities must be greater than zero."))
	if flt(lh_gross_qty) < 0 or flt(rh_gross_qty) < 0:
		frappe.throw(_("LH and RH Gross Quantities cannot be negative."))

	return flt(
		(flt(lh_gross_qty) * lh_rm_qty / lh_bom_quantity) + (flt(rh_gross_qty) * rh_rm_qty / rh_bom_quantity)
	)


def calculate_joint_rm_consumption_from_boms(
	*,
	lh_bom_no: str,
	rh_bom_no: str,
	lh_gross_qty: float,
	rh_gross_qty: float,
) -> float:
	lh_bom = _get_joint_bom_details(lh_bom_no)
	rh_bom = _get_joint_bom_details(rh_bom_no)
	_validate_joint_bom_pair(lh_bom, rh_bom)
	return calculate_joint_rm_consumption(
		lh_gross_qty=lh_gross_qty,
		lh_bom_quantity=lh_bom.quantity,
		lh_rm_qty=lh_bom.rm_qty,
		rh_gross_qty=rh_gross_qty,
		rh_bom_quantity=rh_bom.quantity,
		rh_rm_qty=rh_bom.rm_qty,
	)


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


def materialize_joint_production_rows(doc: Document) -> list[dict[str, Any]]:
	plan = _build_joint_production_plan(doc)
	item_details = _get_item_details(
		[
			plan.lh_bom.rm_item_code,
			plan.lh_bom.item_code,
			plan.rh_bom.item_code,
			*(scrap.item_code for scrap in plan.scrap_items),
		]
	)
	rejection_warehouse = (
		resolve_rejection_warehouse(doc) if plan.lh_rejection_qty > 0 or plan.rh_rejection_qty > 0 else ""
	)

	rows = [
		_item_row(
			item_code=plan.lh_bom.rm_item_code,
			qty=plan.total_rm_consumption,
			s_warehouse=doc.get("from_warehouse"),
			item_details=item_details,
		),
	]
	rows.extend(
		_build_side_rows(
			side="LH",
			bom=plan.lh_bom,
			gross_qty=plan.lh_gross_qty,
			rejection_qty=plan.lh_rejection_qty,
			fg_warehouse=doc.get("to_warehouse"),
			rejection_warehouse=rejection_warehouse,
			item_details=item_details,
		)
	)
	rows.extend(
		_build_side_rows(
			side="RH",
			bom=plan.rh_bom,
			gross_qty=plan.rh_gross_qty,
			rejection_qty=plan.rh_rejection_qty,
			fg_warehouse=doc.get("to_warehouse"),
			rejection_warehouse=rejection_warehouse,
			item_details=item_details,
		)
	)
	for scrap in plan.scrap_items:
		scrap_row = _item_row(
			item_code=scrap.item_code,
			qty=scrap.qty,
			t_warehouse=doc.get("to_warehouse"),
			item_details=item_details,
		)
		scrap_row.update(
			{
				"is_finished_item": 1,
				"set_basic_rate_manually": 1,
				"basic_rate": scrap.rate,
			}
		)
		_set_scrap_row_classification(scrap_row)
		rows.append(scrap_row)
	return rows


def _set_scrap_row_classification(row: dict[str, Any]) -> None:
	stock_entry_detail_meta = frappe.get_meta("Stock Entry Detail", cached=True)
	if stock_entry_detail_meta.has_field("is_scrap_item"):
		row["is_scrap_item"] = 1
	elif stock_entry_detail_meta.has_field("secondary_item_type"):
		row["secondary_item_type"] = "Scrap"
	else:
		row["type"] = "Scrap"


def _build_joint_production_plan(doc: Document) -> JointProductionPlan:
	_validate_joint_header(doc)
	lh_bom = _get_joint_bom_details(doc.get("custom_pea_lh_bom"))
	rh_bom = _get_joint_bom_details(doc.get("custom_pea_rh_bom"))
	_validate_joint_bom_pair(lh_bom, rh_bom)

	lh_gross_qty = flt(doc.get("custom_pea_lh_gross_qty"))
	lh_rejection_qty = flt(doc.get("custom_pea_lh_rejection_qty"))
	rh_gross_qty = flt(doc.get("custom_pea_rh_gross_qty"))
	rh_rejection_qty = flt(doc.get("custom_pea_rh_rejection_qty"))
	_validate_side_quantities("LH", lh_gross_qty, lh_rejection_qty)
	_validate_side_quantities("RH", rh_gross_qty, rh_rejection_qty)

	total_rm_consumption = calculate_joint_rm_consumption(
		lh_gross_qty=lh_gross_qty,
		lh_bom_quantity=lh_bom.quantity,
		lh_rm_qty=lh_bom.rm_qty,
		rh_gross_qty=rh_gross_qty,
		rh_bom_quantity=rh_bom.quantity,
		rh_rm_qty=rh_bom.rm_qty,
	)
	scrap_items = _build_planned_scrap_items(
		lh_bom=lh_bom,
		lh_gross_qty=lh_gross_qty,
		rh_bom=rh_bom,
		rh_gross_qty=rh_gross_qty,
	)
	doc.set("custom_pea_total_rm_consumption", total_rm_consumption)
	return JointProductionPlan(
		lh_bom=lh_bom,
		rh_bom=rh_bom,
		lh_gross_qty=lh_gross_qty,
		lh_rejection_qty=lh_rejection_qty,
		rh_gross_qty=rh_gross_qty,
		rh_rejection_qty=rh_rejection_qty,
		total_rm_consumption=total_rm_consumption,
		scrap_items=scrap_items,
	)


def _build_planned_scrap_items(
	*,
	lh_bom: JointBomDetails,
	lh_gross_qty: float,
	rh_bom: JointBomDetails,
	rh_gross_qty: float,
) -> tuple[JointPlannedScrapItem, ...]:
	quantities: defaultdict[str, float] = defaultdict(float)
	values: defaultdict[str, float] = defaultdict(float)
	uoms: dict[str, str] = {}
	for bom, gross_qty in ((lh_bom, lh_gross_qty), (rh_bom, rh_gross_qty)):
		production_factor = flt(gross_qty) / bom.quantity
		for scrap in bom.scrap_items:
			generated_qty = production_factor * scrap.qty
			if generated_qty <= 0:
				continue
			quantities[scrap.item_code] += generated_qty
			values[scrap.item_code] += generated_qty * scrap.rate
			uoms[scrap.item_code] = scrap.uom

	uom_names = set(uoms.values())
	uom_rows = (
		frappe.get_list(
			"UOM",
			filters={"name": ("in", tuple(uom_names))},
			fields=["name", "must_be_whole_number"],
		)
		if uom_names
		else []
	)
	whole_number_uoms = {row.get("name") for row in uom_rows if row.get("must_be_whole_number")}
	planned_items: list[JointPlannedScrapItem] = []
	for item_code, precise_qty in quantities.items():
		uom = uoms[item_code]
		qty = (
			float(Decimal(str(precise_qty)).quantize(WHOLE_NUMBER_QUANTUM, rounding=ROUND_HALF_UP))
			if uom in whole_number_uoms
			else precise_qty
		)
		if qty <= 0:
			continue
		planned_items.append(
			JointPlannedScrapItem(
				item_code=item_code,
				qty=qty,
				uom=uom,
				rate=values[item_code] / qty,
			)
		)
	return tuple(planned_items)


def _is_joint_stock_entry_type(doc: Document) -> bool:
	stock_entry_type = doc.get("stock_entry_type")
	if not stock_entry_type:
		return False
	flags = getattr(doc, "flags", None)
	cached = flags.get("pea_joint_stock_entry_type") if flags is not None else None
	if cached and cached[0] == stock_entry_type:
		return bool(cached[1])
	is_joint_type = bool(
		frappe.db.get_value(
			"Stock Entry Type",
			stock_entry_type,
			"custom_pea_joint_lh_rh_production",
		)
	)
	if flags is not None:
		flags.pea_joint_stock_entry_type = (stock_entry_type, is_joint_type)
	return is_joint_type


def is_joint_lh_rh_production(doc: Document) -> bool:
	if cint(doc.get("custom_pea_is_joint_lh_rh")):
		return True
	return _is_joint_stock_entry_type(doc)


def validate_and_apply_joint_production(doc: Document) -> None:
	if not is_joint_lh_rh_production(doc):
		return
	if not _is_joint_stock_entry_type(doc):
		frappe.throw(_("Select a Stock Entry Type configured for Joint LH/RH Production."))
	doc.set("custom_pea_is_joint_lh_rh", 1)
	plan = _build_joint_production_plan(doc)
	_validate_joint_item_rows(doc, plan)
	_validate_joint_rejection_breakup(doc, plan)
	_set_joint_output_valuation(doc, plan)


def _validate_joint_item_rows(doc: Document, plan: JointProductionPlan) -> None:
	actual_quantities: defaultdict[str, float] = defaultdict(float)
	for row in doc.get("items") or []:
		role = _get_joint_row_role(row, plan)
		actual_quantities[role] += _get_row_stock_qty(row)

	for role, expected_qty in plan.expected_role_quantities.items():
		actual_qty = actual_quantities.get(role, 0)
		if flt(actual_qty, 6) != flt(expected_qty, 6):
			_throw_stale_joint_rows(
				_("{0} is {1}; expected {2}.").format(
					_get_joint_role_label(role),
					flt(actual_qty),
					flt(expected_qty),
				)
			)


def _get_joint_role_label(role: str) -> str:
	labels = {
		"rm": _("Total RM Consumption"),
		"lh_good": _("LH Good quantity"),
		"lh_rejection": _("LH Rejection quantity"),
		"rh_good": _("RH Good quantity"),
		"rh_rejection": _("RH Rejection quantity"),
	}
	if role.startswith("scrap:"):
		return _("Scrap quantity for {0}").format(role.removeprefix("scrap:"))
	return labels[role]


def _get_joint_row_role(row: BaseDocument, plan: JointProductionPlan) -> str:
	has_source = bool(row.get("s_warehouse"))
	has_target = bool(row.get("t_warehouse"))
	if has_source == has_target:
		_throw_stale_joint_rows(_("Every row must be either source-only or target-only."))

	side = row.get("custom_pea_joint_output_side")
	is_rejection = bool(row.get("custom_pea_is_rejection_item"))
	is_scrap = _is_scrap_row(row)
	item_code = row.get("item_code")

	if has_source:
		if side or is_rejection or is_scrap or item_code != plan.lh_bom.rm_item_code:
			_throw_stale_joint_rows(_("The source row must be the common BOM raw material."))
		return "rm"

	if is_scrap:
		scrap = next((scrap for scrap in plan.scrap_items if scrap.item_code == item_code), None)
		if side or is_rejection or not scrap:
			_throw_stale_joint_rows(_("The scrap row does not match the selected BOMs."))
		return scrap.role

	if side not in ("LH", "RH"):
		_throw_stale_joint_rows(_("Every output row must specify LH or RH Output Side."))
	bom = plan.lh_bom if side == "LH" else plan.rh_bom
	if item_code != bom.item_code:
		_throw_stale_joint_rows(_("The {0} output item does not match its BOM.").format(side))

	if is_rejection:
		if row.get("bom_no"):
			_throw_stale_joint_rows(_("The {0} rejection row cannot carry a BOM.").format(side))
		return f"{side.lower()}_rejection"

	if row.get("bom_no") != bom.name:
		_throw_stale_joint_rows(_("The {0} good-output row must use BOM {1}.").format(side, bom.name))
	return f"{side.lower()}_good"


def _get_row_stock_qty(row: BaseDocument) -> float:
	return flt(row.get("qty")) * flt(row.get("conversion_factor") or 1)


def _throw_stale_joint_rows(detail: str) -> None:
	frappe.throw(
		_(
			"Joint Production Items do not match the selected BOMs and quantities. {0} Run Fetch Items again."
		).format(detail)
	)


def _set_joint_output_valuation(
	doc: Document,
	plan: JointProductionPlan,
) -> None:
	rows = doc.get("items") or []
	scrap_rates = {scrap.item_code: scrap.rate for scrap in plan.scrap_items}
	for row in rows:
		if _is_scrap_row(row):
			row.set_basic_rate_manually = 1
			row.basic_rate = scrap_rates[row.get("item_code")]
			row.basic_amount = flt(
				_get_row_stock_qty(row) * row.basic_rate,
				row.precision("basic_amount"),
			)
	outgoing_value = sum(
		flt(row.get("basic_amount")) for row in rows if row.get("s_warehouse") and not row.get("t_warehouse")
	)
	scrap_value = sum(
		_get_row_stock_qty(row) * flt(row.get("basic_rate")) for row in rows if _is_scrap_row(row)
	)
	net_production_value = outgoing_value - scrap_value
	if net_production_value < -VALUATION_TOLERANCE:
		frappe.throw(_("Joint production scrap value cannot exceed the consumed raw material value."))
	allocation = allocate_joint_output_value(
		net_production_value=max(net_production_value, 0),
		lh_gross_qty=plan.lh_gross_qty,
		lh_bom_unit_cost=plan.lh_bom.unit_cost,
		rh_gross_qty=plan.rh_gross_qty,
		rh_bom_unit_cost=plan.rh_bom.unit_cost,
	)
	for side in ("LH", "RH"):
		side_rows = [
			row for row in rows if row.get("custom_pea_joint_output_side") == side and not _is_scrap_row(row)
		]
		side_qty = sum(_get_row_stock_qty(row) for row in side_rows)
		if side_qty <= 0:
			frappe.throw(_("Joint production requires at least one {0} output row.").format(side))
		side_rate = allocation[side] / side_qty
		for row in side_rows:
			row.set_basic_rate_manually = 1
			row.basic_rate = side_rate
			row.basic_amount = flt(
				_get_row_stock_qty(row) * side_rate,
				row.precision("basic_amount"),
			)

	# Native Stock Entry recalculation applies the manual rates consistently to
	# basic amounts, valuation rates, totals, and the eventual ledger entries.
	doc.calculate_rate_and_amount(reset_outgoing_rate=False)


def _is_scrap_row(row: BaseDocument) -> bool:
	return bool(
		row.get("is_scrap_item")
		or row.get("is_legacy_scrap_item")
		or row.get("secondary_item_type") == "Scrap"
		or row.get("type") == "Scrap"
	)


def _validate_joint_rejection_breakup(doc: Document, plan: JointProductionPlan) -> None:
	expected = {
		"LH": flt(plan.lh_rejection_qty, 6),
		"RH": flt(plan.rh_rejection_qty, 6),
	}
	actual = {"LH": 0.0, "RH": 0.0}
	items = {
		"LH": plan.lh_bom.item_code,
		"RH": plan.rh_bom.item_code,
	}
	rework_qty = 0.0
	for row in doc.get("custom_pea_rejection_breakup") or []:
		row_qty = validate_rejection_breakup_row(row)
		side = row.get("output_side")
		if side not in actual:
			frappe.throw(_("Every joint rejection breakup row must specify LH or RH Output Side."))
		if not row.get("item_code"):
			row.set("item_code", items[side])
		elif row.get("item_code") != items[side]:
			frappe.throw(_("Joint rejection breakup Item must match the selected {0} BOM.").format(side))
		actual[side] += flt(row_qty, 6)
		if row.get("is_rework"):
			rework_qty += row_qty
	for side in ("LH", "RH"):
		if flt(actual[side], 6) != expected[side]:
			frappe.throw(_("{0} rejection breakup total must equal {0} Rejection Quantity.").format(side))
	doc.custom_pea_rework_qty = flt(rework_qty)


def _validate_joint_header(doc: Document) -> None:
	if doc.get("purpose") != "Repack":
		frappe.throw(_("Joint LH/RH production must use Repack purpose."))
	for fieldname, label in (
		("custom_pea_lh_bom", _("LH BOM")),
		("custom_pea_rh_bom", _("RH BOM")),
		("custom_pea_die_tool_item", _("Die Tool Item")),
		("from_warehouse", _("Source Warehouse")),
		("to_warehouse", _("Target Warehouse")),
	):
		if not doc.get(fieldname):
			frappe.throw(_("{0} is required for joint LH/RH production.").format(label))
	if flt(doc.get("custom_pea_total_strokes")) <= 0:
		frappe.throw(_("Total Press Strokes must be greater than zero."))


def _get_joint_bom_details(bom_no: str) -> JointBomDetails:
	bom = frappe.get_doc("BOM", bom_no)
	bold_bom_no = frappe.bold(frappe.utils.escape_html(str(bom_no)))
	if bom.docstatus != 1 or not bom.is_active:
		frappe.throw(_("BOM {0} must be submitted and active.").format(bold_bom_no))
	items = list(bom.get("items") or [])
	secondary_scrap_items = [
		row
		for row in (bom.get("secondary_items") or [])
		if row.get("secondary_item_type") == "Scrap" or row.get("type") == "Scrap" or row.get("is_legacy")
	]
	scrap_items = secondary_scrap_items or list(bom.get("scrap_items") or [])
	if len(items) != 1:
		frappe.throw(_("BOM {0} must contain exactly one raw material item.").format(bold_bom_no))
	if flt(bom.quantity) <= 0:
		frappe.throw(_("BOM {0} quantity must be greater than zero.").format(bold_bom_no))
	rm = items[0]
	stock_uom_by_item = _get_item_stock_uoms(scrap.item_code for scrap in scrap_items)
	return JointBomDetails(
		name=bom.name,
		item_code=bom.item,
		quantity=flt(bom.quantity),
		total_cost=flt(bom.total_cost),
		rm_item_code=rm.item_code,
		rm_qty=flt(rm.stock_qty or rm.qty),
		rm_uom=rm.stock_uom or rm.uom,
		scrap_items=tuple(_get_bom_scrap_item_details(scrap, stock_uom_by_item) for scrap in scrap_items),
	)


def _get_item_stock_uoms(item_codes: Iterable[str]) -> dict[str, str]:
	unique_item_codes = list(dict.fromkeys(item_codes))
	if not unique_item_codes:
		return {}
	return {
		row.name: row.stock_uom
		for row in frappe.get_list(
			"Item",
			filters={"name": ["in", unique_item_codes]},
			fields=["name", "stock_uom"],
		)
	}


def _get_bom_scrap_item_details(scrap: BaseDocument, stock_uom_by_item: dict[str, str]) -> JointBomScrapItem:
	qty = flt(scrap.get("stock_qty") or scrap.get("qty"))
	rate = flt(scrap.get("rate"))
	if not rate and qty > 0:
		total_value = (
			flt(scrap.get("cost"))
			if scrap.get("doctype") == "BOM Secondary Item"
			else flt(scrap.get("base_amount") or scrap.get("amount"))
		)
		rate = total_value / qty
	return JointBomScrapItem(
		item_code=scrap.item_code,
		qty=qty,
		uom=stock_uom_by_item[scrap.item_code],
		rate=rate,
	)


def _validate_joint_bom_pair(lh_bom: JointBomDetails, rh_bom: JointBomDetails) -> None:
	if (lh_bom.rm_item_code, lh_bom.rm_uom) != (rh_bom.rm_item_code, rh_bom.rm_uom):
		frappe.throw(_("LH and RH BOMs must use the same raw material item and UOM."))
	if abs(lh_bom.rm_qty - rh_bom.rm_qty) > 0.000001:
		frappe.throw(_("LH and RH BOMs must use the same raw material quantity."))


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
	item_details: dict[str, frappe._dict],
) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []
	good_qty = gross_qty - rejection_qty
	if good_qty > 0:
		rows.append(
			_joint_output_row(
				side,
				bom,
				good_qty,
				fg_warehouse,
				is_rejection=False,
				item_details=item_details,
			)
		)
	if rejection_qty > 0:
		rows.append(
			_joint_output_row(
				side,
				bom,
				rejection_qty,
				rejection_warehouse,
				is_rejection=True,
				item_details=item_details,
			)
		)
	return rows


def _joint_output_row(
	side: str,
	bom: JointBomDetails,
	qty: float,
	warehouse: str,
	*,
	is_rejection: bool,
	item_details: dict[str, frappe._dict],
) -> dict[str, Any]:
	row = _item_row(
		item_code=bom.item_code,
		qty=qty,
		t_warehouse=warehouse,
		item_details=item_details,
	)
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
	item_details: dict[str, frappe._dict],
) -> dict[str, Any]:
	item = item_details[item_code]
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


def _get_item_details(item_codes: Iterable[str]) -> dict[str, frappe._dict]:
	unique_item_codes = list(dict.fromkeys(item_codes))
	rows = frappe.get_list(
		"Item",
		filters={"name": ["in", unique_item_codes]},
		fields=["name", "item_name", "description", "stock_uom"],
	)
	details = {row.get("name"): frappe._dict(row) for row in rows}
	missing_item_codes = [item_code for item_code in unique_item_codes if item_code not in details]
	if missing_item_codes:
		frappe.throw(
			_("Unable to load Item(s): {0}.").format(
				", ".join(frappe.utils.escape_html(str(item_code)) for item_code in missing_item_codes)
			)
		)
	return details


def validate_stock_entry_type(doc: Document, method: str | None = None) -> None:
	if not doc.get("custom_pea_joint_lh_rh_production"):
		return
	if doc.get("purpose") != "Repack":
		frappe.throw(_("Joint LH/RH Stock Entry Types must use Repack purpose."))
