from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import frappe
from erpnext.stock.valuation import round_off_if_near_zero
from frappe import _
from frappe.model.base_document import BaseDocument
from frappe.model.document import Document
from frappe.utils import cint, cstr, flt

from production_entry_app.production_entry_app.doctype.rejection_breakup.rejection_breakup import (
	validate_rejection_breakup_row,
)
from production_entry_app.production_entry_app.utils.production_warehouses import (
	get_production_warehouses,
	require_warehouse,
	set_production_header_warehouses,
)
from production_entry_app.production_entry_app.utils.stock_entry_type_flags import (
	is_joint_lh_rh_stock_entry_type,
	is_joint_production_stock_entry_type,
)
from production_entry_app.production_entry_app.utils.system_precision import (
	exceeds_one_unit,
	get_system_currency_precision,
	get_system_float_precision,
)

WHOLE_NUMBER_QUANTUM: Decimal = Decimal("1")
JOINT_LH_RH_STOCK_ENTRY_TYPE: str = "Joint LH RH Production"
JOINT_PRODUCTION_STOCK_ENTRY_TYPE: str = "Joint Production"
JOINT_PRODUCTION_LINES_FIELD: str = "custom_pea_joint_production_lines"
MIN_JOINT_PRODUCTION_LINES: int = 2
MAX_JOINT_PRODUCTION_BOM_SIDES: int = 10
SHEARING_OPERATION: str = "Shearing"
JOINT_BOM_OPERATING_COST_DESCRIPTION: str = "Operating Cost as per BOM"


@dataclass(frozen=True)
class JointScrapItem:
	item_code: str
	qty: float
	uom: str
	rate: float

	@property
	def role(self) -> str:
		return f"scrap:{self.item_code}"


@dataclass(frozen=True)
class JointInputItem:
	item_code: str
	qty: float
	uom: str


@dataclass(frozen=True)
class JointBomDetails:
	name: str
	company: str
	item_code: str
	quantity: float
	total_cost: float
	operating_cost: float
	operation: str
	input_items: tuple[JointInputItem, ...]
	scrap_items: tuple[JointScrapItem, ...]

	@property
	def unit_cost(self) -> float:
		return self.total_cost / self.quantity

	@property
	def rm_item_code(self) -> str:
		return self.input_items[0].item_code

	@property
	def rm_qty(self) -> float:
		return self.input_items[0].qty

	@property
	def rm_uom(self) -> str:
		return self.input_items[0].uom


@dataclass(frozen=True)
class JointProductionLine:
	bom: JointBomDetails
	gross_qty: float
	rejection_qty: float
	side: str

	@property
	def good_qty(self) -> float:
		return self.gross_qty - self.rejection_qty

	@property
	def good_role(self) -> str:
		return f"good:{self.side}"

	@property
	def rejection_role(self) -> str:
		return f"rejection:{self.side}"


@dataclass(frozen=True)
class JointProductionPlan:
	lines: tuple[JointProductionLine, ...]
	total_rm_consumption: float
	scrap_items: tuple[JointScrapItem, ...]
	is_shearing: bool
	same_finished_item: bool = False

	@property
	def first_line(self) -> JointProductionLine:
		return self.lines[0]

	@property
	def second_line(self) -> JointProductionLine:
		return self.lines[1]

	@property
	def first_side(self) -> str:
		return self.lines[0].side

	@property
	def second_side(self) -> str:
		return self.lines[1].side

	@property
	def output_sides(self) -> tuple[str, ...]:
		return tuple(line.side for line in self.lines)

	def line_for_side(self, side: str | None) -> JointProductionLine | None:
		return next((line for line in self.lines if line.side == side), None)

	@property
	def expected_role_quantities(self) -> dict[str, float]:
		quantities: dict[str, float] = {}
		for line in self.lines:
			quantities[line.good_role] = line.good_qty
			quantities[line.rejection_role] = line.rejection_qty
		if self.is_shearing:
			quantities["rm"] = self.total_rm_consumption
		else:
			quantities.update(self._expected_post_shearing_source_quantities())
		quantities.update({scrap.role: scrap.qty for scrap in self.scrap_items})
		return quantities

	def _expected_post_shearing_source_quantities(self) -> dict[str, float]:
		quantities: dict[str, float] = {}
		for line in self.lines:
			for item_code, qty in _merged_post_shearing_input_quantities(line.bom, line.gross_qty).items():
				quantities[_post_shearing_source_role(line.bom.name, item_code)] = qty
		return quantities


def is_shearing_joint_operation(operation: str | None) -> bool:
	return _normalize_operation(operation) == SHEARING_OPERATION


def _post_shearing_source_role(bom_no: str, item_code: str) -> str:
	return f"source:{bom_no}:{item_code}"


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
	_validate_shearing_bom_inputs(lh_bom)
	_validate_shearing_bom_inputs(rh_bom)
	_validate_joint_bom_pair(lh_bom, rh_bom, require_common_rm=True)
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
	warehouses = get_production_warehouses(doc)
	set_production_header_warehouses(doc, warehouses)
	plan = _build_joint_production_plan(doc)
	_validate_joint_operating_cost_account(doc, plan)
	source_item_codes = (
		[plan.first_line.bom.rm_item_code]
		if plan.is_shearing
		else [item.item_code for line in plan.lines for item in line.bom.input_items]
	)
	item_details = _get_item_details(
		[
			*source_item_codes,
			*(line.bom.item_code for line in plan.lines),
			*(scrap.item_code for scrap in plan.scrap_items),
		]
	)
	rejection_warehouse = (
		require_warehouse(warehouses, "rejection_warehouse")
		if any(line.rejection_qty > 0 for line in plan.lines)
		else ""
	)

	if plan.is_shearing:
		rows = [
			_item_row(
				item_code=plan.first_line.bom.rm_item_code,
				qty=plan.total_rm_consumption,
				s_warehouse=doc.get("from_warehouse"),
				item_details=item_details,
			),
		]
	else:
		rows = [
			row
			for line in plan.lines
			for row in _build_post_shearing_source_rows(
				bom=line.bom,
				gross_qty=line.gross_qty,
				s_warehouse=doc.get("from_warehouse"),
				item_details=item_details,
			)
		]
	for line in plan.lines:
		rows.extend(
			_build_side_rows(
				side=line.side,
				bom=line.bom,
				gross_qty=line.gross_qty,
				rejection_qty=line.rejection_qty,
				fg_warehouse=doc.get("to_warehouse"),
				rejection_warehouse=rejection_warehouse,
				item_details=item_details,
			)
		)
	for scrap in plan.scrap_items:
		scrap_row = _item_row(
			item_code=scrap.item_code,
			qty=scrap.qty,
			t_warehouse=require_warehouse(warehouses, "scrap_warehouse"),
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
	_set_rows_actual_qty(rows)
	return rows


def _set_scrap_row_classification(row: dict[str, Any]) -> None:
	stock_entry_detail_meta = frappe.get_meta("Stock Entry Detail", cached=True)
	if stock_entry_detail_meta.has_field("is_scrap_item"):
		row["is_scrap_item"] = 1
	elif stock_entry_detail_meta.has_field("secondary_item_type"):
		row["secondary_item_type"] = "Scrap"
	else:
		row["type"] = "Scrap"


def joint_production_line_side(index: int) -> str:
	return f"BOM {index + 1}"


def joint_production_output_side_select_options() -> str:
	"""Select options for joint output_side fields (LH/RH plus BOM 1…BOM N)."""
	return "\n".join(
		[
			"",
			"LH",
			"RH",
			*[joint_production_line_side(index) for index in range(MAX_JOINT_PRODUCTION_BOM_SIDES)],
		]
	)


def _build_joint_production_plan(doc: Document) -> JointProductionPlan:
	if is_joint_production(doc):
		return _build_joint_production_plan_from_lines(doc)
	same_finished_item = False
	first_side, second_side = ("LH", "RH")
	_validate_joint_header(
		doc,
		first_side=first_side,
		second_side=second_side,
		same_finished_item=same_finished_item,
	)
	operation = _get_joint_operation(doc, same_finished_item=same_finished_item)
	is_shearing = False if same_finished_item else is_shearing_joint_operation(operation)
	lines = (
		JointProductionLine(
			bom=_get_joint_bom_details(doc.get("custom_pea_lh_bom")),
			gross_qty=flt(doc.get("custom_pea_lh_gross_qty")),
			rejection_qty=flt(doc.get("custom_pea_lh_rejection_qty")),
			side=first_side,
		),
		JointProductionLine(
			bom=_get_joint_bom_details(doc.get("custom_pea_rh_bom")),
			gross_qty=flt(doc.get("custom_pea_rh_gross_qty")),
			rejection_qty=flt(doc.get("custom_pea_rh_rejection_qty")),
			side=second_side,
		),
	)
	_validate_joint_bom_operations(lines, operation)
	input_validator = _validate_shearing_bom_inputs if is_shearing else _validate_post_shearing_bom_inputs
	for line in lines:
		input_validator(line.bom)
	_validate_joint_bom_pair(lines[0].bom, lines[1].bom, require_common_rm=is_shearing)
	_validate_joint_bom_company(lines, doc.get("company"))
	for line in lines:
		_validate_side_quantities(line.side, line.gross_qty, line.rejection_qty, same_finished_item)

	if is_shearing:
		total_rm_consumption = _calculate_shearing_rm_consumption(lines)
	else:
		total_rm_consumption = _calculate_post_shearing_source_consumption(lines)
	scrap_items = _build_planned_scrap_items(lines)
	return JointProductionPlan(
		lines=lines,
		total_rm_consumption=total_rm_consumption,
		scrap_items=scrap_items,
		is_shearing=is_shearing,
		same_finished_item=same_finished_item,
	)


def _build_joint_production_plan_from_lines(doc: Document) -> JointProductionPlan:
	_validate_joint_production_lines_header(doc)
	table_rows = list(doc.get(JOINT_PRODUCTION_LINES_FIELD) or [])
	if len(table_rows) < MIN_JOINT_PRODUCTION_LINES:
		frappe.throw(
			_(
				"Add at least two Joint Production Lines. "
				"If only one recipe is produced, create a Manufacture Production Entry instead of Joint Production."
			)
		)
	if len(table_rows) > MAX_JOINT_PRODUCTION_BOM_SIDES:
		frappe.throw(_("Joint Production supports at most {0} lines.").format(MAX_JOINT_PRODUCTION_BOM_SIDES))
	operation = _get_joint_operation(doc, same_finished_item=True)
	lines = tuple(
		JointProductionLine(
			bom=_get_joint_bom_details(cstr(row.get("bom_no"))),
			gross_qty=flt(row.get("gross_qty")),
			rejection_qty=flt(row.get("rejection_qty")),
			side=joint_production_line_side(index),
		)
		for index, row in enumerate(table_rows)
	)
	_validate_joint_bom_operations(lines, operation)
	for line in lines:
		_validate_post_shearing_bom_inputs(line.bom)
	_validate_joint_production_duplicate_recipes(lines)
	_validate_joint_bom_company(lines, doc.get("company"))
	for line in lines:
		_validate_side_quantities(line.side, line.gross_qty, line.rejection_qty, same_finished_item=True)
	total_rm_consumption = _calculate_post_shearing_source_consumption(lines)
	scrap_items = _build_planned_scrap_items(lines)
	return JointProductionPlan(
		lines=lines,
		total_rm_consumption=total_rm_consumption,
		scrap_items=scrap_items,
		is_shearing=False,
		same_finished_item=True,
	)


def _validate_joint_production_lines_header(doc: Document) -> None:
	pairing = _("Joint Production")
	if doc.get("purpose") != "Repack":
		frappe.throw(_("{0} must use Repack purpose.").format(pairing))
	if not doc.get("custom_pea_operation"):
		frappe.throw(_("Operation is required for {0}.").format(pairing))
	if doc.get("custom_pea_shift") and not doc.get("custom_pea_die_tool_item"):
		frappe.throw(_("Die Tool Item is required for {0}.").format(pairing))
	if flt(doc.get("custom_pea_total_strokes")) < 0:
		frappe.throw(_("Total Press Strokes cannot be negative."))


def _joint_production_recipe_signature(bom: JointBomDetails) -> tuple[str, frozenset[str]]:
	return bom.item_code, frozenset(item.item_code for item in bom.input_items)


def _validate_joint_production_duplicate_recipes(lines: tuple[JointProductionLine, ...]) -> None:
	bom_names = [line.bom.name for line in lines]
	if len(bom_names) != len(set(bom_names)):
		frappe.throw(_("Each Joint Production Line must use a different BOM."))
	seen: dict[tuple[str, frozenset[str]], str] = {}
	for line in lines:
		signature = _joint_production_recipe_signature(line.bom)
		previous_side = seen.get(signature)
		if previous_side:
			frappe.throw(
				_(
					"Lines {0} and {1} repeat the same finished item and input items. "
					"Merge them into one Joint Production Line."
				).format(previous_side, line.side)
			)
		seen[signature] = line.side


def _calculate_shearing_rm_consumption(lines: tuple[JointProductionLine, ...]) -> float:
	first, second = lines[0], lines[1]
	return calculate_joint_rm_consumption(
		lh_gross_qty=first.gross_qty,
		lh_bom_quantity=first.bom.quantity,
		lh_rm_qty=first.bom.rm_qty,
		rh_gross_qty=second.gross_qty,
		rh_bom_quantity=second.bom.quantity,
		rh_rm_qty=second.bom.rm_qty,
	)


def _build_planned_scrap_items(
	lines: tuple[JointProductionLine, ...],
) -> tuple[JointScrapItem, ...]:
	quantities: defaultdict[str, float] = defaultdict(float)
	values: defaultdict[str, float] = defaultdict(float)
	uoms: dict[str, str] = {}
	for line in lines:
		production_factor = flt(line.gross_qty) / line.bom.quantity
		for scrap in line.bom.scrap_items:
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
	planned_items: list[JointScrapItem] = []
	for item_code, precise_qty in quantities.items():
		uom = uoms[item_code]
		qty = (
			float(Decimal(str(precise_qty)).quantize(WHOLE_NUMBER_QUANTUM, rounding=ROUND_HALF_UP))
			if uom in whole_number_uoms
			else precise_qty
		)
		# Native Stock Entry cannot post a zero-quantity row; the omitted value remains in output valuation.
		if qty <= 0:
			continue
		planned_items.append(
			JointScrapItem(
				item_code=item_code,
				qty=qty,
				uom=uom,
				rate=values[item_code] / qty,
			)
		)
	return tuple(planned_items)


def is_joint_lh_rh_production(doc: Document) -> bool:
	return is_joint_lh_rh_stock_entry_type(doc)


def is_joint_production(doc: Document) -> bool:
	return is_joint_production_stock_entry_type(doc)


def is_paired_production(doc: Document) -> bool:
	return is_joint_lh_rh_production(doc) or is_joint_production(doc)


def validate_and_apply_joint_production(doc: Document) -> None:
	if not is_paired_production(doc):
		return
	plan = _build_joint_production_plan(doc)
	_validate_joint_item_rows(doc, plan)
	_validate_joint_rejection_breakup(doc, plan)
	_apply_joint_bom_operating_costs(doc, plan)
	_set_joint_output_valuation(doc, plan)


def _joint_scaled_operating_cost(bom: JointBomDetails, gross_qty: float) -> float:
	return flt(bom.operating_cost) / bom.quantity * flt(gross_qty)


def _joint_bom_operating_cost_amount(plan: JointProductionPlan) -> float:
	return sum(_joint_scaled_operating_cost(line.bom, line.gross_qty) for line in plan.lines)


def _validate_joint_operating_cost_account(doc: Document, plan: JointProductionPlan) -> str | None:
	amount = _joint_bom_operating_cost_amount(plan)
	if amount <= 0:
		return None
	expense_account = frappe.db.get_value("Company", doc.get("company"), "default_operating_cost_account")
	if not expense_account:
		frappe.throw(
			_(
				"Set Default Operating Cost Account on Company {0} to apply BOM operating cost for Joint LH/RH production."
			).format(frappe.bold(frappe.utils.escape_html(cstr(doc.get("company")))))
		)
	return expense_account


def _apply_joint_bom_operating_costs(doc: Document, plan: JointProductionPlan) -> None:
	for index in range(len(doc.get("additional_costs") or []) - 1, -1, -1):
		if cint(doc.additional_costs[index].get("has_operating_cost")):
			doc.additional_costs.pop(index)

	expense_account = _validate_joint_operating_cost_account(doc, plan)
	if not expense_account:
		return

	amount = flt(
		_joint_bom_operating_cost_amount(plan),
		frappe.get_precision("Landed Cost Taxes and Charges", "amount"),
	)
	doc.append(
		"additional_costs",
		{
			"expense_account": expense_account,
			"description": JOINT_BOM_OPERATING_COST_DESCRIPTION,
			"amount": amount,
			"has_operating_cost": 1,
		},
	)


def _validate_joint_item_rows(doc: Document, plan: JointProductionPlan) -> None:
	precision = get_system_float_precision()
	actual_quantities: defaultdict[str, float] = defaultdict(float)
	for row in doc.get("items") or []:
		role = _get_joint_row_role(row, plan)
		actual_quantities[role] += _get_row_stock_qty(row)

	for role, expected_qty in plan.expected_role_quantities.items():
		actual_qty = actual_quantities.get(role, 0)
		if exceeds_one_unit(actual_qty, expected_qty, precision):
			_throw_stale_joint_rows(
				_("{0} is {1}; expected {2}.").format(
					_get_joint_role_label(role),
					flt(actual_qty, precision),
					flt(expected_qty, precision),
				)
			)


def _get_joint_role_label(role: str) -> str:
	if role == "rm":
		return _("Source RM quantity")
	if role.startswith("good:"):
		return _("{0} Good quantity").format(role.removeprefix("good:"))
	if role.startswith("rejection:"):
		return _("{0} Rejection quantity").format(role.removeprefix("rejection:"))
	if role.startswith("scrap:"):
		return _("Scrap quantity for {0}").format(role.removeprefix("scrap:"))
	if role.startswith("source:"):
		_prefix, bom_no, item_code = role.split(":", 2)
		return _("Source quantity for {0} from BOM {1}").format(item_code, bom_no)
	raise KeyError(role)


def _get_joint_row_role(row: BaseDocument, plan: JointProductionPlan) -> str:
	has_source = bool(row.get("s_warehouse"))
	has_target = bool(row.get("t_warehouse"))
	if has_source == has_target:
		_throw_stale_joint_rows(_("Every row must be either source-only or target-only."))

	side = row.get("custom_pea_joint_output_side")
	is_rejection = bool(row.get("custom_pea_is_rejection_item"))
	is_scrap = is_scrap_row(row)
	item_code = row.get("item_code")

	if has_source:
		if side or is_rejection or is_scrap:
			_throw_stale_joint_rows(_("The source row must be source-only BOM input."))
		if plan.is_shearing:
			if item_code != plan.first_line.bom.rm_item_code:
				_throw_stale_joint_rows(_("The source row must be the common BOM raw material."))
			return "rm"
		role = _post_shearing_source_role(cstr(row.get("bom_no")), cstr(item_code))
		if role not in plan.expected_role_quantities:
			_throw_stale_joint_rows(_("The source row does not match the selected BOMs."))
		return role

	if is_scrap:
		scrap = next((scrap for scrap in plan.scrap_items if scrap.item_code == item_code), None)
		if side or is_rejection or not scrap:
			_throw_stale_joint_rows(_("The scrap row does not match the selected BOMs."))
		return scrap.role

	line = plan.line_for_side(side)
	if line is None:
		expected_sides = _format_joint_output_sides(plan.output_sides)
		_throw_stale_joint_rows(
			_("Every output row must specify one of these Output Sides: {0}.").format(expected_sides)
		)
	if item_code != line.bom.item_code:
		_throw_stale_joint_rows(_("The {0} output item does not match its BOM.").format(side))

	if is_rejection:
		if row.get("bom_no"):
			_throw_stale_joint_rows(_("The {0} rejection row cannot carry a BOM.").format(side))
		return line.rejection_role

	if row.get("bom_no") != line.bom.name:
		_throw_stale_joint_rows(_("The {0} good-output row must use BOM {1}.").format(side, line.bom.name))
	return line.good_role


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
		if is_scrap_row(row):
			row.set_basic_rate_manually = 1
			row.basic_rate = scrap_rates[row.get("item_code")]
			row.basic_amount = flt(
				_get_row_stock_qty(row) * row.basic_rate,
				row.precision("basic_amount"),
			)
	if plan.is_shearing:
		_set_shearing_output_valuation(rows, plan)
	else:
		_set_post_shearing_output_valuation(rows, plan)

	# Native Stock Entry recalculation applies the manual rates consistently to
	# basic amounts, valuation rates, totals, and additional-cost distribution.
	doc.calculate_rate_and_amount(reset_outgoing_rate=False)


def _net_production_value_after_scrap(net_production_value: float) -> float:
	if net_production_value < 0:
		net_production_value = round_off_if_near_zero(net_production_value, get_system_currency_precision())
	if net_production_value < 0:
		frappe.throw(_("Joint production scrap value cannot exceed the consumed raw material value."))
	return net_production_value


def _set_shearing_output_valuation(rows: list[Any], plan: JointProductionPlan) -> None:
	outgoing_value = sum(
		flt(row.get("basic_amount")) for row in rows if row.get("s_warehouse") and not row.get("t_warehouse")
	)
	scrap_value = sum(
		_get_row_stock_qty(row) * flt(row.get("basic_rate")) for row in rows if is_scrap_row(row)
	)
	first, second = plan.first_line, plan.second_line
	allocation = allocate_joint_output_value(
		net_production_value=_net_production_value_after_scrap(outgoing_value - scrap_value),
		lh_gross_qty=first.gross_qty,
		lh_bom_unit_cost=first.bom.unit_cost,
		rh_gross_qty=second.gross_qty,
		rh_bom_unit_cost=second.bom.unit_cost,
	)
	for side in (first.side, second.side):
		_apply_side_output_rate(rows, side, allocation[side])


def _set_post_shearing_output_valuation(rows: list[Any], plan: JointProductionPlan) -> None:
	"""Value each line like Manufacture: (line consumed amount - line scrap) / line qty."""
	side_scrap_values = _post_shearing_side_scrap_values(plan)
	for line in plan.lines:
		outgoing_value = sum(
			flt(row.get("basic_amount"))
			for row in rows
			if row.get("s_warehouse") and not row.get("t_warehouse") and row.get("bom_no") == line.bom.name
		)
		_apply_side_output_rate(
			rows,
			line.side,
			_net_production_value_after_scrap(outgoing_value - side_scrap_values[line.side]),
		)


def _post_shearing_side_scrap_values(plan: JointProductionPlan) -> dict[str, float]:
	side_values = {line.side: 0.0 for line in plan.lines}
	for scrap in plan.scrap_items:
		posted_value = flt(scrap.qty) * flt(scrap.rate)
		contributions = {
			line.side: _side_scrap_contribution(line.bom, line.gross_qty, scrap.item_code)
			for line in plan.lines
		}
		total = sum(contributions.values())
		if total <= 0:
			continue
		for side, contribution in contributions.items():
			side_values[side] += posted_value * contribution / total
	return side_values


def _side_scrap_contribution(bom: JointBomDetails, gross_qty: float, item_code: str) -> float:
	production_factor = flt(gross_qty) / bom.quantity
	return sum(
		production_factor * scrap.qty * scrap.rate
		for scrap in bom.scrap_items
		if scrap.item_code == item_code
	)


def _apply_side_output_rate(rows: list[Any], side: str, side_value: float) -> None:
	side_rows = [
		row for row in rows if row.get("custom_pea_joint_output_side") == side and not is_scrap_row(row)
	]
	side_qty = sum(_get_row_stock_qty(row) for row in side_rows)
	if side_qty <= 0:
		frappe.throw(_("Joint production requires at least one {0} output row.").format(side))
	side_rate = flt(side_value) / side_qty
	for row in side_rows:
		row.set_basic_rate_manually = 1
		row.basic_rate = side_rate
		row.basic_amount = flt(
			_get_row_stock_qty(row) * side_rate,
			row.precision("basic_amount"),
		)


def is_scrap_row(row: BaseDocument) -> bool:
	return bool(
		row.get("is_scrap_item")
		or row.get("is_legacy_scrap_item")
		or row.get("secondary_item_type") == "Scrap"
		or row.get("type") == "Scrap"
	)


def _format_joint_output_sides(sides: tuple[str, ...]) -> str:
	return ", ".join(sides)


def _validate_joint_rejection_breakup(doc: Document, plan: JointProductionPlan) -> None:
	precision = get_system_float_precision()
	sides = plan.output_sides
	expected = {line.side: flt(line.rejection_qty, precision) for line in plan.lines}
	actual = {line.side: 0.0 for line in plan.lines}
	items = {line.side: line.bom.item_code for line in plan.lines}
	rework_qty = 0.0
	for row in doc.get("custom_pea_rejection_breakup") or []:
		row_qty = validate_rejection_breakup_row(row)
		side = row.get("output_side")
		if side not in actual:
			frappe.throw(
				_("Every joint rejection breakup row must specify one of these Output Sides: {0}.").format(
					_format_joint_output_sides(sides)
				)
			)
		if not row.get("item_code"):
			row.set("item_code", items[side])
		elif row.get("item_code") != items[side]:
			frappe.throw(_("Joint rejection breakup Item must match the selected {0} BOM.").format(side))
		actual[side] += flt(row_qty, precision)
		if row.get("is_rework"):
			rework_qty += row_qty
	for side in sides:
		if exceeds_one_unit(actual[side], expected[side], precision):
			frappe.throw(_("{0} rejection breakup total must equal {0} Rejection Quantity.").format(side))
	doc.custom_pea_rework_qty = flt(rework_qty)


def _validate_joint_header(
	doc: Document,
	*,
	first_side: str,
	second_side: str,
	same_finished_item: bool,
) -> None:
	pairing = _("Joint Production") if same_finished_item else _("joint LH/RH production")
	if doc.get("purpose") != "Repack":
		frappe.throw(_("{0} must use Repack purpose.").format(pairing))
	for fieldname, label in (
		("custom_pea_operation", _("Operation")),
		("custom_pea_lh_bom", _(first_side) if same_finished_item else _("LH BOM")),
		("custom_pea_rh_bom", _(second_side) if same_finished_item else _("RH BOM")),
	):
		if not doc.get(fieldname):
			frappe.throw(_("{0} is required for {1}.").format(label, pairing))
	if doc.get("custom_pea_shift") and not doc.get("custom_pea_die_tool_item"):
		frappe.throw(_("Die Tool Item is required for {0}.").format(pairing))
	# Warehouses are required by Fetch Items, not by recipe validation: native Repack
	# clears mixed-direction headers on save. ERPNext validates the actual item rows.
	if flt(doc.get("custom_pea_total_strokes")) < 0:
		frappe.throw(_("Total Press Strokes cannot be negative."))


def _get_joint_operation(doc: Document, *, same_finished_item: bool) -> str:
	operation = _normalize_operation(doc.get("custom_pea_operation"))
	if not operation:
		pairing = _("Joint Production") if same_finished_item else _("joint LH/RH production")
		frappe.throw(_("Operation is required for {0}.").format(pairing))
	if not frappe.get_meta("BOM", cached=True).has_field("custom_operation"):
		frappe.throw(_("BOM custom_operation metadata is required for joint LH/RH production."))
	return operation


def _normalize_operation(operation: Any) -> str:
	return cstr(operation).strip()


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
	if not items:
		frappe.throw(_("BOM {0} must contain at least one input item.").format(bold_bom_no))
	if flt(bom.quantity) <= 0:
		frappe.throw(_("BOM {0} quantity must be greater than zero.").format(bold_bom_no))
	total_cost = flt(bom.total_cost)
	if total_cost <= 0:
		frappe.throw(
			_("BOM-derived manufacturing cost cannot be calculated for BOM {0}.").format(bold_bom_no)
		)
	stock_uom_by_item = _get_item_stock_uoms(
		(*(row.item_code for row in items), *(scrap.item_code for scrap in scrap_items))
	)
	return JointBomDetails(
		name=bom.name,
		company=cstr(bom.company),
		item_code=bom.item,
		quantity=flt(bom.quantity),
		total_cost=total_cost,
		operating_cost=flt(bom.operating_cost),
		operation=_normalize_operation(bom.get("custom_operation")),
		input_items=tuple(
			JointInputItem(
				item_code=row.item_code,
				qty=flt(row.stock_qty or row.qty),
				uom=row.stock_uom or row.uom or stock_uom_by_item[row.item_code],
			)
			for row in items
		),
		scrap_items=tuple(_get_bom_scrap_item_details(scrap, stock_uom_by_item) for scrap in scrap_items),
	)


def _validate_joint_bom_operations(
	lines: tuple[JointProductionLine, ...],
	operation: str,
) -> None:
	mismatches = [
		_("{0} BOM {1}").format(line.side, frappe.bold(frappe.utils.escape_html(line.bom.name)))
		for line in lines
		if line.bom.operation != operation
	]
	if not mismatches:
		return
	bold_operation = frappe.bold(frappe.utils.escape_html(operation))
	if len(mismatches) == 1:
		frappe.throw(_("{0} must match Operation {1}.").format(mismatches[0], bold_operation))
	if len(mismatches) == 2:
		frappe.throw(
			_("{0} and {1} must match Operation {2}.").format(
				mismatches[0],
				mismatches[1],
				bold_operation,
			)
		)
	frappe.throw(
		_("The following BOMs must match Operation {0}: {1}").format(
			bold_operation,
			", ".join(mismatches),
		)
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


def _get_bom_scrap_item_details(scrap: BaseDocument, stock_uom_by_item: dict[str, str]) -> JointScrapItem:
	qty = flt(scrap.get("stock_qty") or scrap.get("qty"))
	rate = flt(scrap.get("rate"))
	if not rate and qty > 0:
		total_value = (
			flt(scrap.get("cost"))
			if scrap.get("doctype") == "BOM Secondary Item"
			else flt(scrap.get("base_amount") or scrap.get("amount"))
		)
		rate = total_value / qty
	return JointScrapItem(
		item_code=scrap.item_code,
		qty=qty,
		uom=stock_uom_by_item[scrap.item_code],
		rate=rate,
	)


def _validate_shearing_bom_inputs(bom: JointBomDetails) -> None:
	bold_bom_no = frappe.bold(frappe.utils.escape_html(bom.name))
	if len(bom.input_items) != 1:
		frappe.throw(_("BOM {0} must contain exactly one raw material item.").format(bold_bom_no))
	if bom.input_items[0].qty <= 0:
		frappe.throw(_("LH and RH raw material quantities must be greater than zero."))


def _validate_post_shearing_bom_inputs(bom: JointBomDetails) -> None:
	bold_bom_no = frappe.bold(frappe.utils.escape_html(bom.name))
	if not bom.input_items:
		frappe.throw(_("BOM {0} must contain at least one input item.").format(bold_bom_no))
	if any(item.qty <= 0 for item in bom.input_items):
		frappe.throw(_("BOM {0} input quantities must be greater than zero.").format(bold_bom_no))


def _validate_joint_bom_pair(
	lh_bom: JointBomDetails,
	rh_bom: JointBomDetails,
	*,
	require_common_rm: bool,
) -> None:
	if lh_bom.name == rh_bom.name:
		frappe.throw(_("LH and RH BOMs must be different."))
	if lh_bom.item_code == rh_bom.item_code:
		frappe.throw(_("LH and RH BOM output items must differ."))
	if lh_bom.company != rh_bom.company:
		frappe.throw(_("LH and RH BOMs must belong to the same Company."))
	if not require_common_rm:
		return
	if (lh_bom.rm_item_code, lh_bom.rm_uom) != (rh_bom.rm_item_code, rh_bom.rm_uom):
		frappe.throw(_("LH and RH BOMs must use the same raw material item and UOM."))
	precision = get_system_float_precision()
	if exceeds_one_unit(lh_bom.rm_qty, rh_bom.rm_qty, precision):
		frappe.throw(_("LH and RH BOMs must use the same raw material quantity."))


def _calculate_post_shearing_source_consumption(
	lines: tuple[JointProductionLine, ...],
) -> float:
	return flt(
		sum(
			_scale_bom_input_qty(item.qty, line.bom.quantity, line.gross_qty)
			for line in lines
			for item in line.bom.input_items
		)
	)


def _scale_bom_input_qty(bom_item_qty: float, bom_quantity: float, gross_qty: float) -> float:
	return flt(gross_qty) * flt(bom_item_qty) / flt(bom_quantity)


def _merged_post_shearing_input_quantities(bom: JointBomDetails, gross_qty: float) -> dict[str, float]:
	quantities: dict[str, float] = {}
	for item in bom.input_items:
		quantities[item.item_code] = quantities.get(item.item_code, 0) + _scale_bom_input_qty(
			item.qty, bom.quantity, gross_qty
		)
	return {item_code: qty for item_code, qty in quantities.items() if qty > 0}


def _build_post_shearing_source_rows(
	*,
	bom: JointBomDetails,
	gross_qty: float,
	s_warehouse: str | None,
	item_details: dict[str, frappe._dict],
) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []
	for item_code, qty in _merged_post_shearing_input_quantities(bom, gross_qty).items():
		row = _item_row(
			item_code=item_code,
			qty=qty,
			s_warehouse=s_warehouse,
			item_details=item_details,
		)
		row["bom_no"] = bom.name
		rows.append(row)
	return rows


def _validate_same_finished_item_pair(lh_bom: JointBomDetails, rh_bom: JointBomDetails) -> None:
	if lh_bom.name == rh_bom.name:
		frappe.throw(_("BOM 1 and BOM 2 must be different."))
	if lh_bom.company != rh_bom.company:
		frappe.throw(_("BOM 1 and BOM 2 must belong to the same Company."))
	if lh_bom.item_code != rh_bom.item_code:
		frappe.throw(
			_(
				"Joint Production BOMs must produce the same finished item. "
				"Use Joint LH/RH Production when the finished items differ."
			)
		)
	if {item.item_code for item in lh_bom.input_items} == {item.item_code for item in rh_bom.input_items}:
		frappe.throw(_("Joint Production BOMs must use different raw materials."))


def _validate_joint_bom_company(
	lines: tuple[JointProductionLine, ...],
	company: str | None,
) -> None:
	stock_entry_company = cstr(company)
	for line in lines:
		if line.bom.company != stock_entry_company:
			frappe.throw(
				_("{0} BOM {1} must belong to Company {2}.").format(
					line.side,
					frappe.bold(frappe.utils.escape_html(line.bom.name)),
					frappe.bold(frappe.utils.escape_html(stock_entry_company)),
				)
			)


def _validate_side_quantities(
	side: str, gross_qty: float, rejection_qty: float, same_finished_item: bool = False
) -> None:
	if gross_qty < 0:
		frappe.throw(_("{0} Gross Quantity cannot be negative.").format(side))
	if gross_qty == 0:
		if same_finished_item:
			frappe.throw(
				_(
					"{0} Gross Quantity must be greater than zero. "
					"If only one recipe is produced, create a Manufacture Production Entry "
					"instead of Joint Production."
				).format(side)
			)
		frappe.throw(
			_(
				"{0} Gross Quantity must be greater than zero. "
				"If only one side is produced, create a normal independent Manufacture Production Entry "
				"instead of Joint LH/RH."
			).format(side)
		)
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


def _set_rows_actual_qty(rows: list[dict[str, Any]]) -> None:
	"""Stamp Bin actual_qty so the grid shows stock at each row's warehouse."""
	pairs = set()
	for row in rows:
		warehouse = row.get("s_warehouse") or row.get("t_warehouse")
		if warehouse:
			pairs.add((row["item_code"], warehouse))
	if not pairs:
		return
	balances = {
		(bin_row.item_code, bin_row.warehouse): flt(bin_row.actual_qty)
		for bin_row in frappe.get_all(
			"Bin",
			filters={
				"item_code": ["in", sorted({item_code for item_code, _ in pairs})],
				"warehouse": ["in", sorted({warehouse for _, warehouse in pairs})],
			},
			fields=["item_code", "warehouse", "actual_qty"],
		)
	}
	for row in rows:
		warehouse = row.get("s_warehouse") or row.get("t_warehouse")
		if warehouse:
			row["actual_qty"] = balances.get((row["item_code"], warehouse), 0.0)


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


def _reject_duplicate_stock_entry_type_flag(doc: Document, *, flag_fieldname: str, message: str) -> None:
	# Site-wide invariant: a caller who cannot see the existing flagged type must still be blocked.
	existing_types = frappe.get_all(
		"Stock Entry Type",
		filters={flag_fieldname: 1, "name": ["!=", doc.name]},
		pluck="name",
		limit=1,
	)
	if not existing_types:
		return
	frappe.throw(message.format(frappe.bold(frappe.utils.escape_html(existing_types[0]))))


def validate_stock_entry_type(doc: Document, method: str | None = None) -> None:
	if doc.get("custom_pea_joint_production") and doc.get("custom_pea_joint_lh_rh_production"):
		frappe.throw(_("A Stock Entry Type cannot be both Joint Production and Joint LH/RH Production."))
	if doc.get("custom_pea_joint_production") and doc.get("custom_pea_rework_entry"):
		frappe.throw(_("A Stock Entry Type cannot be both Joint Production and Rework."))
	if doc.get("custom_pea_joint_production") and doc.get("purpose") != "Repack":
		frappe.throw(_("Joint Production Stock Entry Types must use Repack purpose."))
	if doc.get("custom_pea_joint_production"):
		_reject_duplicate_stock_entry_type_flag(
			doc,
			flag_fieldname="custom_pea_joint_production",
			message=_("Only one Stock Entry Type can be configured for Joint Production. Use {0}."),
		)
	if doc.get("custom_pea_joint_lh_rh_production") and doc.get("custom_pea_rework_entry"):
		frappe.throw(_("A Stock Entry Type cannot be both Joint LH/RH Production and Rework."))
	if doc.get("custom_pea_joint_lh_rh_production") and doc.get("purpose") != "Repack":
		frappe.throw(_("Joint LH/RH Stock Entry Types must use Repack purpose."))
	if doc.get("custom_pea_joint_lh_rh_production"):
		_reject_duplicate_stock_entry_type_flag(
			doc,
			flag_fieldname="custom_pea_joint_lh_rh_production",
			message=_("Only one Stock Entry Type can be configured for Joint LH/RH Production. Use {0}."),
		)
	if doc.get("custom_pea_rework_entry") and doc.get("purpose") != "Material Transfer":
		frappe.throw(_("Rework Stock Entry Types must use Material Transfer purpose."))
