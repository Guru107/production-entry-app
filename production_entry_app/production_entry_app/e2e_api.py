from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import DocType
from frappe.utils import add_to_date, cint, get_datetime
from pypika import Order

from production_entry_app.production_entry_app.api import (
	_cleanup_orphan_stock_entry_loss_links,
	reset_die_tool_counter,
)
from production_entry_app.production_entry_app.utils.shift_time import get_shift_planned_end_datetime
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	cleanup_running_shifts,
	ensure_branch,
	ensure_default_bom,
	ensure_department,
	ensure_downtime_reason,
	ensure_fiscal_year_for_date,
	ensure_item,
	ensure_joint_test_bom,
	ensure_operator,
	ensure_rejection_reason,
	ensure_stock,
	ensure_warehouse,
	ensure_workstation,
	resolve_test_branch,
	resolve_test_company,
)

_E2E_SETTINGS_FIELDS: tuple[str, ...] = (
	"shift_wip_warehouse",
	"shift_raw_material_warehouse",
	"shift_rejection_warehouse",
	"shift_scrap_warehouse",
	"shift_start_buffer_mins",
	"shift_end_buffer_mins",
)
_E2E_SYSTEM_SETTINGS_FIELDS: tuple[str, ...] = ("float_precision",)
_E2E_RESERVED_USER_EMAIL_PREFIX: str = "e2e-user-"
_E2E_RESERVED_ROLE_PREFIX: str = "E2E ROLE "
_E2E_RESERVED_DOWNTIME_PREFIX: str = "E2E-DOWNTIME-"


def _ensure_e2e_settings_fields_loaded() -> None:
	meta = frappe.get_meta("Production Entry Settings", cached=True)
	if all(meta.has_field(fieldname) for fieldname in _E2E_SETTINGS_FIELDS):
		return
	frappe.reload_doc("production_entry_app", "doctype", "production_entry_settings")
	frappe.clear_document_cache("Production Entry Settings")


@frappe.whitelist()
def set_e2e_branch_user_permission(user: str, branch: str) -> dict:
	"""Assign a native Branch User Permission for E2E isolation."""
	_assert_e2e_api_allowed()
	user_value = (user or "").strip()
	branch_value = (branch or "").strip()
	if not user_value or not branch_value:
		frappe.throw(_("user and branch are required."), frappe.ValidationError)
	if not user_value.startswith(_E2E_RESERVED_USER_EMAIL_PREFIX):
		frappe.throw(_("user must be an E2E reserved test user."), frappe.ValidationError)
	if not frappe.db.exists("User", user_value):
		frappe.throw(
			_("user {0} does not exist.").format(frappe.bold(frappe.utils.escape_html(user_value))),
			frappe.ValidationError,
		)
	if not frappe.db.exists("Branch", branch_value):
		frappe.throw(
			_("branch {0} does not exist.").format(frappe.bold(frappe.utils.escape_html(branch_value))),
			frappe.ValidationError,
		)
	existing = frappe.get_all(
		"User Permission",
		filters={"user": user_value, "allow": "Branch", "for_value": branch_value},
		pluck="name",
	)
	if not existing:
		permission = frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user_value,
				"allow": "Branch",
				"for_value": branch_value,
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True)
		permission_name = permission.name
	else:
		permission_name = existing[0]
	frappe.db.commit()  # nosemgrep: frappe-manual-commit - E2E setup must persist
	return {"user": user_value, "branch": branch_value, "permission_name": permission_name}


def _e2e_base_date(prefix: str) -> str:
	offset = sum(ord(ch) for ch in (prefix or "E2E")) % 30
	return add_to_date("2099-01-01", days=7 + offset, as_string=True)


def _get_e2e_settings_cache_key(prefix: str) -> str:
	return f"pea:e2e:settings:{prefix or 'E2E'}"


def _get_e2e_shift_names_cache_key(prefix: str) -> str:
	return f"pea:e2e:shift-names:{prefix or 'E2E'}"


def _get_production_entry_settings_snapshot() -> dict[str, str | int | None]:
	_ensure_e2e_settings_fields_loaded()
	return {
		fieldname: frappe.db.get_single_value("Production Entry Settings", fieldname)
		for fieldname in _E2E_SETTINGS_FIELDS
	}


def _get_manufacturing_settings_snapshot() -> dict[str, str | int | None]:
	"""Backward-compatible alias for test helpers still importing the old name."""
	return _get_production_entry_settings_snapshot()


def _get_system_settings_snapshot() -> dict[str, str | int | None]:
	return {
		fieldname: frappe.db.get_single_value("System Settings", fieldname)
		for fieldname in _E2E_SYSTEM_SETTINGS_FIELDS
	}


def _cache_e2e_settings_snapshot(prefix: str) -> None:
	cache_key = _get_e2e_settings_cache_key(prefix)
	if frappe.cache().get_value(cache_key):
		return
	frappe.cache().set_value(
		cache_key,
		{
			"production_entry_settings": _get_production_entry_settings_snapshot(),
			"system_settings": _get_system_settings_snapshot(),
		},
	)


def _cache_e2e_shift_name(prefix: str, shift_name: str | None) -> None:
	if not shift_name:
		return
	cache_key = _get_e2e_shift_names_cache_key(prefix)
	cached_names = frappe.cache().get_value(cache_key) or []
	if shift_name in cached_names:
		return
	frappe.cache().set_value(cache_key, [*cached_names, shift_name])


def _restore_production_entry_settings(snapshot: dict[str, str | int | None] | None) -> None:
	if not snapshot:
		return
	_ensure_e2e_settings_fields_loaded()
	for fieldname in _E2E_SETTINGS_FIELDS:
		frappe.db.set_single_value("Production Entry Settings", fieldname, snapshot.get(fieldname))
	frappe.clear_document_cache("Production Entry Settings")


def _restore_manufacturing_settings(snapshot: dict[str, str | int | None] | None) -> None:
	"""Backward-compatible alias for test helpers still importing the old name."""
	_restore_production_entry_settings(snapshot)


def _restore_system_settings(snapshot: dict[str, str | int | None] | None) -> None:
	if not snapshot:
		return
	for fieldname in _E2E_SYSTEM_SETTINGS_FIELDS:
		frappe.db.set_single_value("System Settings", fieldname, snapshot.get(fieldname))


def _restore_cached_e2e_settings(prefix: str) -> None:
	cache_key = _get_e2e_settings_cache_key(prefix)
	snapshot = frappe.cache().get_value(cache_key)
	if snapshot:
		settings_snapshot = snapshot.get("production_entry_settings") or snapshot.get(
			"manufacturing_settings"
		)
		_restore_production_entry_settings(settings_snapshot)
		_restore_system_settings(snapshot.get("system_settings"))
		frappe.cache().delete_value(cache_key)

	shift_names_key = _get_e2e_shift_names_cache_key(prefix)
	frappe.cache().delete_value(shift_names_key)


def _is_developer_mode_enabled() -> bool:
	return bool(cint(getattr(frappe.conf, "developer_mode", 0)))


def _is_allow_e2e_tests_enabled() -> bool:
	return bool(cint(getattr(frappe.conf, "allow_e2e_tests", 0)))


def _assert_e2e_api_allowed() -> None:
	frappe.only_for("Administrator")
	if not _is_developer_mode_enabled():
		frappe.throw(_("E2E bootstrap APIs are only available in developer mode."), frappe.PermissionError)
	if not _is_allow_e2e_tests_enabled():
		frappe.throw(
			_("E2E APIs require allow_e2e_tests=1 in site_config.json."),
			frappe.PermissionError,
		)


def _stock_entry_matches_cleanup_target(se, target_operator: str, target_fg_item: str) -> bool:
	operator_match = se.get("custom_pea_operator") == target_operator
	fg_item_match = any(
		(row.get("is_finished_item") == 1) and (row.get("item_code") == target_fg_item)
		for row in (se.get("items") or [])
	)
	return bool(operator_match or fg_item_match)


def _get_candidate_e2e_stock_entries(
	target_operator: str,
	target_workstation: str,
	target_fg_item: str | None = None,
	target_rm_item: str | None = None,
) -> list[frappe._dict]:
	stock_entry = DocType("Stock Entry")
	stock_entry_detail = DocType("Stock Entry Detail")
	item_code_filters = []
	if target_fg_item:
		item_code_filters.append(stock_entry_detail.item_code == target_fg_item)
	if target_rm_item:
		item_code_filters.append(stock_entry_detail.item_code == target_rm_item)
	match_criteria = (stock_entry.custom_pea_operator == target_operator) | (
		stock_entry.custom_pea_workstation == target_workstation
	)
	item_code_match = item_code_filters[0] if item_code_filters else None
	for condition in item_code_filters[1:]:
		item_code_match = item_code_match | condition
	if item_code_match is not None:
		match_criteria = match_criteria | item_code_match

	query = (
		frappe.qb.from_(stock_entry)
		.left_join(stock_entry_detail)
		.on(stock_entry_detail.parent == stock_entry.name)
		.distinct()
		.select(stock_entry.name, stock_entry.docstatus)
		.where((stock_entry.purpose == "Manufacture") | (stock_entry.custom_pea_is_joint_lh_rh == 1))
		.where(match_criteria)
		.orderby(stock_entry.creation, order=Order.desc)
	)
	return query.run(as_dict=True)


def _item_has_live_stock_entry_references(item_code: str) -> bool:
	if not item_code:
		return False

	stock_entry = DocType("Stock Entry")
	stock_entry_detail = DocType("Stock Entry Detail")
	rows = (
		frappe.qb.from_(stock_entry_detail)
		.inner_join(stock_entry)
		.on(stock_entry.name == stock_entry_detail.parent)
		.select(stock_entry.name)
		.where(stock_entry_detail.item_code == item_code)
		.where(stock_entry.docstatus != 2)
		.limit(1)
		.run()
	)
	return bool(rows)


def _safe_force_delete(doctype: str, name: str, *, context: str) -> None:
	try:
		frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
	except Exception:
		frappe.log_error(
			title="E2E cleanup delete failed",
			message=f"{context}: unable to delete {doctype} {name}",
		)


def _safe_cancel_and_delete(doctype: str, name: str, *, context: str) -> None:
	if not frappe.db.exists(doctype, name):
		return
	try:
		docstatus = frappe.db.get_value(doctype, name, "docstatus")
		if docstatus == 1:
			doc = frappe.get_doc(doctype, name)
			doc.flags.ignore_permissions = True
			doc.cancel()
		_safe_force_delete(doctype, name, context=context)
	except Exception:
		frappe.log_error(
			title="E2E cleanup delete failed",
			message=f"{context}: unable to cancel/delete {doctype} {name}",
		)


def _get_or_create_e2e_employee(prefix: str, company: str) -> str:
	employee_number = f"{prefix}-EMP"
	existing = frappe.db.get_value("Employee", {"employee_number": employee_number}, "name")
	if existing:
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": prefix,
				"last_name": "E2E",
				"gender": "Female",
				"date_of_birth": "1990-01-01",
				"date_of_joining": "2020-01-01",
				"company": company,
				"status": "Active",
				"employee_number": employee_number,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _clear_timeline_cache_for_context(ctx: dict, shift_name: str) -> None:
	for doctype, docname in (
		("Workstation", ctx.get("workstation")),
		("Operator", ctx.get("operator")),
	):
		if not docname:
			continue
		frappe.cache().delete_keys(f"pea:timeline:admin:{doctype}:{docname}:{shift_name}:")


def _build_e2e_shift_doc(
	*,
	base_date: str,
	department: str,
	branch: str,
	wip_warehouse: str,
	rm_warehouse: str,
	rejection_warehouse: str,
) -> dict:
	return {
		"doctype": "Shift",
		"department": department,
		"branch": branch,
		"shift_label": "1",
		"shift_duration": "8",
		"shift_date": base_date,
		"planned_start_time": "08:00:00",
		"work_in_progress_warehouse": wip_warehouse,
		"raw_material_warehouse": rm_warehouse,
		"rejection_warehouse": rejection_warehouse,
	}


def _complete_other_running_e2e_shifts(*, keep_department: str | None = None) -> None:
	reserved_departments = frappe.get_all(
		"Department",
		filters={"department_name": ("like", "E2E% Department")},
		pluck="name",
	)
	if keep_department:
		reserved_departments = [name for name in reserved_departments if name != keep_department]
	if not reserved_departments:
		return
	for shift_name in frappe.get_all(
		"Shift",
		filters={"status": "Running", "department": ["in", reserved_departments]},
		pluck="name",
	):
		frappe.db.set_value("Shift", shift_name, "status", "Completed", update_modified=False)


def _get_or_create_e2e_shift(
	*,
	base_date: str,
	department: str,
	branch: str,
	wip_warehouse: str,
	rm_warehouse: str,
	rejection_warehouse: str,
):
	existing_names = frappe.get_all(
		"Shift",
		filters={
			"department": department,
			"branch": branch,
			"shift_date": base_date,
			"shift_label": "1",
		},
		pluck="name",
		limit=1,
	)
	if existing_names:
		shift_name = existing_names[0]
	else:
		shift = frappe.get_doc(
			_build_e2e_shift_doc(
				base_date=base_date,
				department=department,
				branch=branch,
				wip_warehouse=wip_warehouse,
				rm_warehouse=rm_warehouse,
				rejection_warehouse=rejection_warehouse,
			)
		).insert(ignore_permissions=True)
		shift.start_shift()
		return shift

	shift = frappe.get_doc("Shift", shift_name)
	if shift.status in ("Completed", "Cancelled"):
		frappe.delete_doc("Shift", shift_name, force=True, ignore_permissions=True)
		shift = frappe.get_doc(
			_build_e2e_shift_doc(
				base_date=base_date,
				department=department,
				branch=branch,
				wip_warehouse=wip_warehouse,
				rm_warehouse=rm_warehouse,
				rejection_warehouse=rejection_warehouse,
			)
		).insert(ignore_permissions=True)
		shift.start_shift()
		return shift
	if shift.status == "Draft":
		shift.start_shift()
		return shift
	if shift.status == "Running":
		return shift

	frappe.throw(_("Unexpected Shift status for E2E bootstrap: {0}").format(shift.status))


def _get_e2e_joint_item_codes(prefix: str) -> tuple[str, str, str, str, str]:
	return (
		f"_{prefix}_Joint_LH_Item",
		f"_{prefix}_Joint_RH_Item",
		f"_{prefix}_Joint_RM_Item",
		f"_{prefix}_Joint_Scrap_Item",
		f"_{prefix}_Joint_Scrap_Nos_Item",
	)


@frappe.whitelist()
def bootstrap_e2e_context(prefix: str = "E2E", cleanup_running: int = 1) -> dict:
	"""Create deterministic test masters for Playwright E2E tests."""
	_assert_e2e_api_allowed()
	if cint(cleanup_running):
		cleanup_running_shifts()
	_ensure_e2e_settings_fields_loaded()
	_cache_e2e_settings_snapshot(prefix)
	company = resolve_test_company()
	abbr = frappe.db.get_value("Company", company, "abbr") or "TC"
	branch = ensure_branch(resolve_test_branch() or "_Test Branch")
	base_date = _e2e_base_date(prefix)
	ensure_fiscal_year_for_date(base_date)

	wip_warehouse = ensure_warehouse(f"{prefix} WIP - {abbr}", company)
	rm_warehouse = ensure_warehouse(f"{prefix} RM - {abbr}", company)
	fg_warehouse = ensure_warehouse(f"{prefix} FG - {abbr}", company)
	rejection_warehouse = ensure_warehouse(f"{prefix} Rejection - {abbr}", company)
	if frappe.get_meta("Warehouse", cached=True).has_field("is_rejected_warehouse"):
		frappe.db.set_value(
			"Warehouse", rejection_warehouse, "is_rejected_warehouse", 1, update_modified=False
		)

	fg_item = ensure_item(f"_{prefix}_FG_Item")
	rm_item = ensure_item(f"_{prefix}_RM_Item")
	frappe.db.set_value("Item", fg_item, "custom_pea_stroke_capacity", 10000, update_modified=False)
	if frappe.get_meta("Item", cached=True).has_field("custom_pea_has_die_tool"):
		frappe.db.set_value("Item", fg_item, "custom_pea_has_die_tool", 1, update_modified=False)

	operator_name = f"{prefix} Operator"
	workstation_name = f"{prefix} Workstation"
	ensure_operator(operator_name)
	ensure_workstation(workstation_name, standard_spm=2)
	ensure_rejection_reason("Burr")
	ensure_rejection_reason("Crack")
	ensure_downtime_reason("Tea Break")
	ensure_downtime_reason("Lunch Break")
	ensure_downtime_reason("Shift Start Up")
	ensure_downtime_reason("JH Activity")
	ensure_downtime_reason("Dinner")

	frappe.db.set_single_value("Production Entry Settings", "shift_wip_warehouse", wip_warehouse)
	frappe.db.set_single_value("Production Entry Settings", "shift_raw_material_warehouse", rm_warehouse)
	frappe.db.set_single_value("Production Entry Settings", "shift_rejection_warehouse", rejection_warehouse)
	frappe.db.set_single_value("Production Entry Settings", "shift_start_buffer_mins", 60)
	frappe.db.set_single_value("Production Entry Settings", "shift_end_buffer_mins", 60)
	frappe.clear_document_cache("Production Entry Settings")

	bom = ensure_default_bom(fg_item=fg_item, rm_item=rm_item, company=company)
	ensure_stock(rm_item, wip_warehouse, company, target_qty=1000, posting_date=base_date)
	joint_lh_item, joint_rh_item, joint_rm_item, joint_scrap_item, joint_scrap_nos_item = (
		_get_e2e_joint_item_codes(prefix)
	)
	ensure_item(joint_lh_item)
	ensure_item(joint_rh_item)
	ensure_item(joint_rm_item, stock_uom="Kg")
	ensure_item(joint_scrap_item, stock_uom="Kg")
	ensure_item(joint_scrap_nos_item, stock_uom="Nos")
	if frappe.get_meta("Item", cached=True).has_field("custom_pea_has_die_tool"):
		frappe.db.set_value("Item", joint_lh_item, "custom_pea_has_die_tool", 1, update_modified=False)
	frappe.db.set_value("Item", joint_lh_item, "custom_pea_stroke_capacity", 10000, update_modified=False)
	joint_lh_bom = ensure_joint_test_bom(
		item_code=joint_lh_item,
		rm_item=joint_rm_item,
		scrap_items=[(joint_scrap_item, 1.125, 10), (joint_scrap_nos_item, 2, 4)],
		company=company,
		is_default=True,
	)
	joint_rh_bom = ensure_joint_test_bom(
		item_code=joint_rh_item,
		rm_item=joint_rm_item,
		scrap_items=[(joint_scrap_item, 2.125, 10), (joint_scrap_nos_item, 20, 4)],
		company=company,
		is_default=True,
	)
	ensure_stock(joint_rm_item, wip_warehouse, company, target_qty=1000, posting_date=base_date)

	dept_name = f"{prefix} Department"
	department = ensure_department(dept_name, company)
	_complete_other_running_e2e_shifts(keep_department=department)
	shift = _get_or_create_e2e_shift(
		base_date=base_date,
		department=department,
		branch=branch,
		wip_warehouse=wip_warehouse,
		rm_warehouse=rm_warehouse,
		rejection_warehouse=rejection_warehouse,
	)
	_cache_e2e_shift_name(prefix, shift.name)

	frappe.db.commit()  # nosemgrep: frappe-manual-commit - tests need deterministic persisted setup
	return {
		"company": company,
		"branch": branch,
		"wip_warehouse": wip_warehouse,
		"rm_warehouse": rm_warehouse,
		"fg_warehouse": fg_warehouse,
		"rejection_warehouse": rejection_warehouse,
		"fg_item": fg_item,
		"rm_item": rm_item,
		"operator": operator_name,
		"workstation": workstation_name,
		"bom": bom,
		"joint_lh_item": joint_lh_item,
		"joint_rh_item": joint_rh_item,
		"joint_rm_item": joint_rm_item,
		"joint_scrap_item": joint_scrap_item,
		"joint_scrap_nos_item": joint_scrap_nos_item,
		"joint_lh_bom": joint_lh_bom,
		"joint_rh_bom": joint_rh_bom,
		"shift_name": shift.name,
		"shift_date": base_date,
	}


@frappe.whitelist()
def set_e2e_system_float_precision(prefix: str = "E2E", precision: int = 3) -> dict:
	"""Set System Settings float precision for a specific E2E context."""
	_assert_e2e_api_allowed()
	_cache_e2e_settings_snapshot(prefix)
	frappe.db.set_single_value("System Settings", "float_precision", cint(precision))
	frappe.clear_cache()
	frappe.db.commit()  # nosemgrep: frappe-manual-commit - tests need deterministic persisted setup
	return {"float_precision": cint(precision)}


def _get_e2e_cleanup_targets(prefix: str) -> dict[str, object]:
	target_operator = f"{prefix} Operator"
	target_workstation = f"{prefix} Workstation"
	target_fg_item = f"_{prefix}_FG_Item"
	target_rm_item = f"_{prefix}_RM_Item"
	dept_name = f"{prefix} Department"
	departments = frappe.get_all("Department", filters={"department_name": dept_name}, pluck="name")
	if not departments:
		departments = [dept_name]
	base_date = _e2e_base_date(prefix)
	next_date = add_to_date(base_date, days=1, as_string=True)
	e2e_shift_names = list(frappe.cache().get_value(_get_e2e_shift_names_cache_key(prefix)) or [])
	for shift_date in (base_date, next_date):
		for label in ("1", "2"):
			legacy_name = f"SHIFT-{shift_date}.Shift-{label}"
			if legacy_name not in e2e_shift_names:
				e2e_shift_names.append(legacy_name)
	for department in departments:
		rows = frappe.get_all(
			"Shift",
			filters={"department": department, "shift_date": ("in", [base_date, next_date])},
			pluck="name",
		)
		for row_name in rows:
			if row_name not in e2e_shift_names:
				e2e_shift_names.append(row_name)

	return {
		"target_operator": target_operator,
		"target_workstation": target_workstation,
		"target_fg_item": target_fg_item,
		"target_rm_item": target_rm_item,
		"e2e_shift_names": e2e_shift_names,
	}


def _cleanup_e2e_shifts(prefix: str, targets: dict[str, object] | None = None) -> None:
	targets = targets or _get_e2e_cleanup_targets(prefix)
	for name in targets["e2e_shift_names"]:
		if not frappe.db.exists("Shift", name):
			continue
		doc = frappe.get_doc("Shift", name)
		if doc.status == "Running":
			doc.end_shift()
			doc.reload()
		if doc.status in ("Draft", "Cancelled", "Completed"):
			try:
				_cleanup_orphan_stock_entry_loss_links(name)
			except Exception:
				frappe.log_error(
					title="E2E cleanup shift orphan cleanup failed",
					message=f"cleanup_e2e_context: unable to clean Shift orphan links for {name}",
				)
				raise
			_safe_force_delete("Shift", name, context="cleanup_e2e_context")


def _cleanup_e2e_stock_entries(targets: dict[str, object]) -> None:
	target_operator = str(targets["target_operator"])
	target_workstation = str(targets["target_workstation"])
	target_fg_item = str(targets["target_fg_item"])
	target_rm_item = str(targets["target_rm_item"])
	stock_entries = _get_candidate_e2e_stock_entries(
		target_operator=target_operator,
		target_workstation=target_workstation,
		target_fg_item=target_fg_item,
		target_rm_item=target_rm_item,
	)

	seen_entries = set()
	for row in stock_entries:
		if row.name in seen_entries:
			continue
		seen_entries.add(row.name)
		se = frappe.get_doc("Stock Entry", row.name)
		if not _stock_entry_matches_cleanup_target(
			se, target_operator=target_operator, target_fg_item=target_fg_item
		) and not any(
			row_item.get("item_code") in {target_fg_item, target_rm_item}
			for row_item in (se.get("items") or [])
		):
			continue
		if se.docstatus == 1:
			try:
				se.cancel()
			except Exception:
				frappe.log_error(
					title="E2E cleanup cancel failed",
					message=f"Unable to cancel Stock Entry {se.name}",
				)
				continue
		if se.docstatus in (0, 2):
			_safe_force_delete("Stock Entry", se.name, context="cleanup_e2e_context")


def _cleanup_e2e_downtime_entries(targets: dict[str, object]) -> None:
	target_workstation = str(targets["target_workstation"])
	for name in frappe.get_all(
		"Downtime Entry",
		filters={"workstation": target_workstation},
		pluck="name",
	):
		_safe_force_delete("Downtime Entry", name, context="cleanup_e2e_context")


def _cleanup_e2e_master_data(prefix: str) -> None:
	target_operator = f"{prefix} Operator"
	target_workstation = f"{prefix} Workstation"
	target_fg_item = f"_{prefix}_FG_Item"
	target_rm_item = f"_{prefix}_RM_Item"
	for doctype, name in (("Workstation", target_workstation), ("Operator", target_operator)):
		if frappe.db.exists(doctype, name):
			_safe_force_delete(doctype, name, context="cleanup_e2e_context")

	joint_lh_item, joint_rh_item, joint_rm_item, joint_scrap_item, joint_scrap_nos_item = (
		_get_e2e_joint_item_codes(prefix)
	)
	for item in (
		target_fg_item,
		joint_lh_item,
		joint_rh_item,
		joint_scrap_item,
		joint_scrap_nos_item,
		joint_rm_item,
		target_rm_item,
	):
		if frappe.db.exists("Die Tool Counter", {"die_tool_item": item}):
			for counter_name in frappe.get_all(
				"Die Tool Counter", filters={"die_tool_item": item}, pluck="name"
			):
				_safe_force_delete("Die Tool Counter", counter_name, context="cleanup_e2e_context")
		for log_name in frappe.get_all(
			"Die Tool Maintenance Log", filters={"die_tool_item": item}, pluck="name"
		):
			doc = frappe.get_doc("Die Tool Maintenance Log", log_name)
			if doc.docstatus == 1:
				try:
					doc.cancel()
				except Exception:
					frappe.log_error(
						title="E2E cleanup cancel failed",
						message=f"Unable to cancel Die Tool Maintenance Log {log_name}",
					)
					continue
			_safe_force_delete("Die Tool Maintenance Log", log_name, context="cleanup_e2e_context")
		for bom_name in frappe.get_all("BOM", filters={"item": item}, pluck="name"):
			bom = frappe.get_doc("BOM", bom_name)
			if bom.docstatus == 1:
				try:
					bom.cancel()
				except Exception:
					frappe.log_error(
						title="E2E cleanup cancel failed",
						message=f"Unable to cancel BOM {bom_name}",
					)
					continue
			_safe_force_delete("BOM", bom_name, context="cleanup_e2e_context")
		if frappe.db.exists("Item", item) and not _item_has_live_stock_entry_references(item):
			_safe_force_delete("Item", item, context="cleanup_e2e_context")

	company = resolve_test_company()
	abbr = frappe.db.get_value("Company", company, "abbr") or "TC"
	for warehouse_name in (
		f"{prefix} WIP - {abbr}",
		f"{prefix} RM - {abbr}",
		f"{prefix} FG - {abbr}",
		f"{prefix} Rejection - {abbr}",
	):
		if frappe.db.exists("Warehouse", warehouse_name):
			_safe_force_delete("Warehouse", warehouse_name, context="cleanup_e2e_context")


def _finalize_e2e_cleanup(prefix: str, result: dict[str, object]) -> dict[str, object]:
	_restore_cached_e2e_settings(prefix)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit - deterministic cleanup for test reruns
	return result


def _cleanup_e2e_context(prefix: str = "E2E") -> dict:
	result: dict[str, object] = {"ok": True}
	try:
		targets = _get_e2e_cleanup_targets(prefix)
		_cleanup_e2e_shifts(prefix, targets)
		_cleanup_e2e_stock_entries(targets)
		_cleanup_e2e_downtime_entries(targets)
		_cleanup_e2e_master_data(prefix)
	except Exception:
		result["ok"] = False
		raise
	finally:
		_finalize_e2e_cleanup(prefix, result)
	return result


@frappe.whitelist()
def cleanup_e2e_context(prefix: str = "E2E") -> dict:
	"""Remove seeded E2E docs and end running shifts created for E2E."""
	_assert_e2e_api_allowed()
	return _cleanup_e2e_context(prefix=prefix)


@frappe.whitelist()
def reset_e2e_die_tool_counter(prefix: str = "E2E") -> dict:
	"""Reset only the finished-good item reserved for an E2E context."""
	_assert_e2e_api_allowed()
	prefix_value = (prefix or "").strip()
	if prefix_value != "E2E" and not prefix_value.startswith("E2E_"):
		frappe.throw(_("Prefix must identify a reserved E2E context."), frappe.ValidationError)
	return reset_die_tool_counter(f"_{prefix_value}_FG_Item")


def _collect_reserved_e2e_prefixes() -> list[str]:
	prefixes: set[str] = set()
	for item_code in frappe.get_all("Item", filters={"item_code": ("like", "%FG_Item")}, pluck="name"):
		if item_code.startswith("_") and item_code.endswith("_FG_Item"):
			prefixes.add(item_code[1:-8])
	for workstation_name in frappe.get_all(
		"Workstation", filters={"name": ("like", "E2E% Workstation")}, pluck="name"
	):
		if workstation_name.startswith("E2E") and workstation_name.endswith(" Workstation"):
			prefixes.add(workstation_name[:-12])
	return sorted(prefixes)


def _cleanup_reserved_e2e_artifacts() -> dict[str, object]:
	cleaned_prefixes = []
	for prefix in _collect_reserved_e2e_prefixes():
		_cleanup_e2e_context(prefix=prefix)
		cleaned_prefixes.append(prefix)

	for email in frappe.get_all(
		"User",
		filters={"name": ("like", f"{_E2E_RESERVED_USER_EMAIL_PREFIX}%@example.com")},
		pluck="name",
	):
		_safe_force_delete("User", email, context="cleanup_reserved_e2e_artifacts")

	for role_name in frappe.get_all(
		"Role", filters={"name": ("like", f"{_E2E_RESERVED_ROLE_PREFIX}%")}, pluck="name"
	):
		_safe_force_delete("Role", role_name, context="cleanup_reserved_e2e_artifacts")

	for reason_name in frappe.get_all(
		"Downtime Reason", filters={"name": ("like", f"{_E2E_RESERVED_DOWNTIME_PREFIX}%")}, pluck="name"
	):
		_safe_force_delete("Downtime Reason", reason_name, context="cleanup_reserved_e2e_artifacts")

	frappe.db.commit()  # nosemgrep: frappe-manual-commit - reserved E2E sweep must be durable
	return {"ok": True, "prefixes": cleaned_prefixes}


@frappe.whitelist()
def cleanup_reserved_e2e_artifacts() -> dict[str, object]:
	_assert_e2e_api_allowed()
	return _cleanup_reserved_e2e_artifacts()


@frappe.whitelist()
def create_e2e_submitted_stock_entry(
	prefix: str = "E2E",
	rejection_qty: float = 0,
	complete_shift_before_submit: int = 0,
	shift_name: str | None = None,
	actual_start_time: str = "08:00:00",
	actual_end_time: str = "09:00:00",
) -> dict:
	"""Create and submit one manufacture stock entry for E2E report coverage."""
	_assert_e2e_api_allowed()
	ctx = bootstrap_e2e_context(prefix=prefix, cleanup_running=0 if shift_name else 1)
	target_shift_name = (shift_name or ctx["shift_name"] or "").strip()
	shift = frappe.get_doc("Shift", target_shift_name)
	if cint(complete_shift_before_submit) and shift.status != "Completed":
		shift.end_shift()
		shift.reload()
	shift_date = str(shift.shift_date)
	actual_start_time = actual_start_time or "08:00:00"
	actual_end_time = actual_end_time or "09:00:00"

	doc = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Manufacture",
			"purpose": "Manufacture",
			"company": ctx["company"],
			"from_bom": 1,
			"bom_no": ctx["bom"],
			"from_warehouse": ctx["wip_warehouse"],
			"to_warehouse": ctx["fg_warehouse"],
			"fg_completed_qty": 100,
			"custom_pea_shift": shift.name,
			"custom_pea_operator": ctx["operator"],
			"custom_pea_workstation": ctx["workstation"],
			"custom_pea_rejection_qty": float(rejection_qty or 0),
			"custom_pea_actual_start_date": f"{shift_date} {actual_start_time}",
			"custom_pea_actual_end_date": f"{shift_date} {actual_end_time}",
			"set_posting_time": 1,
			"posting_date": shift_date,
			"posting_time": actual_end_time,
		}
	)
	_finalize_e2e_submitted_stock_entry(
		doc,
		rejection_qty=rejection_qty,
		wip_warehouse=ctx["wip_warehouse"],
		fg_warehouse=ctx["fg_warehouse"],
	)
	_clear_timeline_cache_for_context(ctx, shift.name)

	frappe.db.commit()  # nosemgrep: frappe-manual-commit - required for report read-after-write checks
	return {
		"name": doc.name,
		"docstatus": doc.docstatus,
		"posting_date": shift_date,
		"shift_name": shift.name,
		"branch": getattr(doc, "branch", None),
	}


def _finalize_e2e_submitted_stock_entry(
	doc: Document,
	*,
	rejection_qty: float,
	wip_warehouse: str | None,
	fg_warehouse: str | None,
) -> Document:
	doc.get_items()
	for row in doc.get("items") or []:
		if not row.get("s_warehouse"):
			row.s_warehouse = wip_warehouse
		if row.get("is_finished_item") and not row.get("t_warehouse"):
			row.t_warehouse = fg_warehouse
	if float(rejection_qty or 0) > 0:
		doc.append(
			"custom_pea_rejection_breakup", {"rejection_reason": "Burr", "qty": float(rejection_qty or 0)}
		)
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc


def _build_e2e_full_shift_entry_payloads(ctx: dict) -> list[dict]:
	slot_mins = ctx["slot_mins"]
	shift_end = ctx["shift_end"]
	current_start = ctx["shift_start"]
	payloads = []
	while current_start < shift_end:
		next_end = add_to_date(current_start, minutes=slot_mins, as_datetime=True)
		current_end = min(next_end, shift_end)
		payloads.append(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Manufacture",
				"purpose": "Manufacture",
				"company": ctx["company"],
				"from_bom": 1,
				"bom_no": ctx["bom"],
				"from_warehouse": ctx["wip_warehouse"],
				"to_warehouse": ctx["fg_warehouse"],
				"fg_completed_qty": 100,
				"custom_pea_shift": ctx["shift_name"],
				"custom_pea_operator": ctx["operator"],
				"custom_pea_workstation": ctx["workstation"],
				"custom_pea_rejection_qty": float(ctx["rejection_qty"] or 0),
				"custom_pea_actual_start_date": str(current_start),
				"custom_pea_actual_end_date": str(current_end),
				"set_posting_time": 1,
				"posting_date": str(current_end.date()),
				"posting_time": str(current_end.time()),
				"_pea_wip_warehouse": ctx["wip_warehouse"],
				"_pea_fg_warehouse": ctx["fg_warehouse"],
				"_pea_rejection_qty": ctx["rejection_qty"],
			}
		)
		current_start = current_end
	return payloads


def _insert_e2e_full_shift_stock_entry(payload: dict) -> str:
	wip_warehouse = payload.get("_pea_wip_warehouse")
	fg_warehouse = payload.get("_pea_fg_warehouse")
	rejection_qty = payload.get("_pea_rejection_qty")
	doc_payload = {key: value for key, value in payload.items() if not key.startswith("_pea_")}
	doc = frappe.get_doc(doc_payload)
	_finalize_e2e_submitted_stock_entry(
		doc,
		rejection_qty=rejection_qty,
		wip_warehouse=wip_warehouse,
		fg_warehouse=fg_warehouse,
	)
	return doc.name


@frappe.whitelist()
def create_e2e_full_shift_stock_entries(
	prefix: str = "E2E", slot_minutes: int = 60, rejection_qty: float = 0
) -> dict:
	"""Create contiguous submitted manufacture entries spanning the entire planned shift duration."""
	_assert_e2e_api_allowed()
	slot_mins = max(1, cint(slot_minutes or 60))
	ctx = bootstrap_e2e_context(prefix=prefix)
	shift = frappe.get_doc("Shift", ctx["shift_name"])
	shift_start = get_datetime(f"{shift.shift_date} {shift.planned_start_time}")
	shift_end = get_shift_planned_end_datetime(
		shift_date=shift.shift_date,
		planned_start_time=shift.planned_start_time,
		planned_end_time=shift.planned_end_time,
		shift_end_date=shift.shift_end_date,
		shift_duration=shift.shift_duration,
	)
	if not shift_end or shift_end <= shift_start:
		frappe.throw(_("Invalid shift window for E2E stock entry generation."))

	created_names = []
	full_shift_ctx = {
		**ctx,
		"rejection_qty": rejection_qty,
		"shift_start": shift_start,
		"shift_end": shift_end,
		"slot_mins": slot_mins,
	}
	for payload in _build_e2e_full_shift_entry_payloads(full_shift_ctx):
		created_names.append(_insert_e2e_full_shift_stock_entry(payload))
	_clear_timeline_cache_for_context(ctx, ctx["shift_name"])

	frappe.db.commit()  # nosemgrep: frappe-manual-commit - required for report read-after-write checks
	return {
		"count": len(created_names),
		"stock_entries": created_names,
		"shift_name": ctx["shift_name"],
		"shift_start": str(shift_start),
		"shift_end": str(shift_end),
		"slot_minutes": slot_mins,
	}


@frappe.whitelist()
def create_e2e_downtime_entry(
	prefix: str = "E2E",
	from_time: str = "10:00:00",
	to_time: str = "10:30:00",
	stop_reason: str = "Other",
) -> dict:
	"""Create one downtime entry for E2E timeline coverage."""
	_assert_e2e_api_allowed()
	ctx = bootstrap_e2e_context(prefix=prefix)
	shift = frappe.get_doc("Shift", ctx["shift_name"])
	employee = _get_or_create_e2e_employee(prefix, ctx["company"])
	allowed_stop_reasons = {
		"",
		"Excessive machine set up time",
		"Unplanned machine maintenance",
		"On-machine press checks",
		"Machine operator errors",
		"Machine malfunction",
		"Electricity down",
		"Other",
	}
	normalized_reason = stop_reason if stop_reason in allowed_stop_reasons else "Other"
	doc = frappe.get_doc(
		{
			"doctype": "Downtime Entry",
			"workstation": ctx["workstation"],
			"operator": employee,
			"from_time": f"{shift.shift_date} {from_time}",
			"to_time": f"{shift.shift_date} {to_time}",
			"stop_reason": normalized_reason,
		}
	).insert(ignore_permissions=True)
	_clear_timeline_cache_for_context(ctx, ctx["shift_name"])
	frappe.db.commit()  # nosemgrep: frappe-manual-commit - required for report read-after-write checks
	return {"name": doc.name, "workstation": ctx["workstation"], "shift_name": ctx["shift_name"]}
