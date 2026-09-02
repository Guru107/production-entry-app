from __future__ import annotations

import json
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
DOCTYPE_ROOT = Path(__file__).parent / "doctype"
CUSTOM_FIELD_FIXTURE = APP_ROOT / "production_entry_app" / "fixtures" / "custom_field.json"
ROLE_FIXTURE = APP_ROOT / "production_entry_app" / "fixtures" / "role.json"

EXPECTED_PEA_ROLE_NAMES = ("PEA User", "PEA Read Only")

REQUIRED_SEARCH_INDEXES: dict[str, set[str]] = {
	"Rejection Breakup": {"is_rework"},
	"Rework Type": {"is_active"},
	"Shift": {"branch", "shift_date", "status"},
}

REQUIRED_CUSTOM_FIELD_SEARCH_INDEXES: set[str] = {
	"Stock Entry Type-custom_pea_joint_lh_rh_production",
	"Stock Entry Type-custom_pea_rework_entry",
	"Stock Entry-custom_pea_is_joint_lh_rh",
	"Stock Entry-custom_pea_shift",
	"Stock Entry-custom_pea_workstation",
	"Stock Entry-custom_pea_operator",
	"Stock Entry Detail-custom_pea_is_rejection_item",
}


def test_required_apps_declares_erpnext() -> None:
	from production_entry_app import hooks

	assert getattr(hooks, "required_apps", None) == ["erpnext"]


def test_master_data_doctypes_do_not_allow_rename() -> None:
	assert assert_doctype_json("Operator")["allow_rename"] == 0
	assert assert_doctype_json("Downtime Reason")["allow_rename"] == 0
	assert assert_doctype_json("Rejection Reason")["allow_rename"] == 0
	assert assert_doctype_json("Rework Type")["allow_rename"] == 0


def test_filtered_doctype_fields_are_search_indexed() -> None:
	for doctype, fieldnames in REQUIRED_SEARCH_INDEXES.items():
		fields_by_name = {
			field.get("fieldname"): field
			for field in assert_doctype_json(doctype).get("fields", [])
			if field.get("fieldname")
		}
		missing = sorted(
			fieldname
			for fieldname in fieldnames
			if fields_by_name.get(fieldname, {}).get("search_index") != 1
		)
		assert not missing, f"{doctype} fields must set search_index: {', '.join(missing)}"


def test_filtered_custom_fields_are_search_indexed() -> None:
	fields_by_name = {field.get("name"): field for field in load_custom_field_fixture() if field.get("name")}
	missing = sorted(
		fieldname
		for fieldname in REQUIRED_CUSTOM_FIELD_SEARCH_INDEXES
		if fields_by_name.get(fieldname, {}).get("search_index") != 1
	)
	assert not missing, f"Custom fields must set search_index: {', '.join(missing)}"


def test_no_app_custom_field_uses_nonzero_permlevel() -> None:
	offenders = sorted(
		field.get("name") or "<unnamed>" for field in load_custom_field_fixture() if field.get("permlevel")
	)
	assert offenders == [], f"custom fields still at a nonzero permlevel: {offenders}"


def test_stock_entry_detail_rejection_flag_uses_cross_version_anchor() -> None:
	fields_by_name = {field.get("name"): field for field in load_custom_field_fixture() if field.get("name")}
	assert (
		fields_by_name["Stock Entry Detail-custom_pea_is_rejection_item"].get("insert_after")
		== "is_finished_item"
	)


def test_joint_lh_rh_production_metadata_is_exported() -> None:
	fields_by_name = {field.get("name"): field for field in load_custom_field_fixture() if field.get("name")}
	required_fields = {
		"Stock Entry Type-custom_pea_joint_lh_rh_production",
		"Stock Entry-custom_pea_is_joint_lh_rh",
		"Stock Entry-custom_pea_lh_bom",
		"Stock Entry-custom_pea_lh_gross_qty",
		"Stock Entry-custom_pea_lh_rejection_qty",
		"Stock Entry-custom_pea_rh_bom",
		"Stock Entry-custom_pea_rh_gross_qty",
		"Stock Entry-custom_pea_rh_rejection_qty",
		"Stock Entry-custom_pea_total_strokes",
		"Stock Entry-custom_pea_die_tool_item",
		"Stock Entry-custom_pea_total_rm_consumption",
		"Stock Entry-custom_pea_joint_fetch_items",
		"Stock Entry Detail-custom_pea_joint_output_side",
	}
	missing_fields = sorted(required_fields.difference(fields_by_name))
	assert not missing_fields, f"Missing joint-production custom fields: {missing_fields}"
	joint_flag = fields_by_name["Stock Entry-custom_pea_is_joint_lh_rh"]
	assert not joint_flag.get("fetch_from")
	assert not joint_flag.get("read_only")
	total_rm_field = fields_by_name["Stock Entry-custom_pea_total_rm_consumption"]
	assert total_rm_field.get("read_only") == 1
	assert not total_rm_field.get("mandatory_depends_on")
	assert "Stock Entry-custom_pea_joint_scrap_qty" not in fields_by_name
	for fieldname in (
		"Stock Entry-custom_pea_lh_gross_qty",
		"Stock Entry-custom_pea_lh_rejection_qty",
		"Stock Entry-custom_pea_rh_gross_qty",
		"Stock Entry-custom_pea_rh_rejection_qty",
		"Stock Entry-custom_pea_total_strokes",
	):
		assert fields_by_name[fieldname].get("non_negative") == 1

	rejection_fields = {
		field.get("fieldname"): field
		for field in assert_doctype_json("Rejection Breakup").get("fields", [])
		if field.get("fieldname")
	}
	missing_rejection_fields = sorted({"output_side", "item_code"}.difference(rejection_fields))
	assert not missing_rejection_fields, f"Missing Rejection Breakup fields: {missing_rejection_fields}"
	assert rejection_fields["output_side"]["options"] == "\nLH\nRH"
	assert rejection_fields["item_code"]["options"] == "Item"


def test_rework_stock_entry_metadata_is_exported() -> None:
	fields_by_name = {field.get("name"): field for field in load_custom_field_fixture() if field.get("name")}
	rework_fields = {
		"Stock Entry-custom_pea_rework_type": ("Link", "Rework Type"),
		"Stock Entry-custom_pea_rework_workstation": ("Link", "Workstation"),
		"Stock Entry-custom_pea_rework_actual_start": ("Datetime", None),
		"Stock Entry-custom_pea_rework_actual_end": ("Datetime", None),
		"Stock Entry-custom_pea_rework_operators": ("Table", "Rework Operator"),
		"Stock Entry-custom_pea_rework_cost": ("Currency", None),
	}

	for name, (fieldtype, options) in rework_fields.items():
		field = fields_by_name[name]
		assert field["fieldtype"] == fieldtype
		assert field.get("options") == options
		assert "stock_entry_type" in field.get("depends_on", "")

	for name in set(rework_fields).difference({"Stock Entry-custom_pea_rework_cost"}):
		assert fields_by_name[name].get("mandatory_depends_on") == fields_by_name[name].get("depends_on")
	assert fields_by_name["Stock Entry-custom_pea_rework_cost"].get("read_only") == 1
	assert fields_by_name["Stock Entry-custom_pea_rework_cost"].get("non_negative") == 1
	assert "__pea_rework_stock_entry_type" in fields_by_name["Stock Entry-custom_pea_shift"].get(
		"depends_on", ""
	)

	rework_operator = assert_doctype_json("Rework Operator")
	assert rework_operator["istable"] == 1
	assert rework_operator["permissions"] == []
	assert rework_operator["field_order"] == ["operator"]
	assert rework_operator["fields"] == [
		{
			"fieldname": "operator",
			"fieldtype": "Link",
			"in_list_view": 1,
			"label": "Operator",
			"options": "Operator",
			"reqd": 1,
		}
	]


def test_rework_fields_have_a_dedicated_two_column_section() -> None:
	fields_by_name = {field.get("name"): field for field in load_custom_field_fixture() if field.get("name")}

	def field(fieldname: str) -> dict:
		return fields_by_name[f"Stock Entry-{fieldname}"]

	rework_condition = field("custom_pea_rework_type")["depends_on"]

	assert field("custom_pea_shift")["insert_after"] == "custom_pea_is_joint_lh_rh"
	assert field("custom_pea_rework_details_section") == {
		"doctype": "Custom Field",
		"name": "Stock Entry-custom_pea_rework_details_section",
		"dt": "Stock Entry",
		"fieldname": "custom_pea_rework_details_section",
		"fieldtype": "Section Break",
		"label": "Rework Details",
		"insert_after": "apply_putaway_rule",
		"depends_on": rework_condition,
		"module": "Production Entry App",
		"permlevel": 0,
	}
	assert field("custom_pea_rework_type")["insert_after"] == "custom_pea_rework_details_section"
	assert field("custom_pea_rework_actual_start")["insert_after"] == "custom_pea_rework_type"
	assert field("custom_pea_rework_actual_end")["insert_after"] == "custom_pea_rework_actual_start"
	assert field("custom_pea_rework_column_break") == {
		"doctype": "Custom Field",
		"name": "Stock Entry-custom_pea_rework_column_break",
		"dt": "Stock Entry",
		"fieldname": "custom_pea_rework_column_break",
		"fieldtype": "Column Break",
		"insert_after": "custom_pea_rework_actual_end",
		"module": "Production Entry App",
		"permlevel": 0,
	}
	assert field("custom_pea_rework_workstation")["insert_after"] == "custom_pea_rework_column_break"
	assert field("custom_pea_rework_operators")["insert_after"] == "custom_pea_rework_workstation"
	assert field("custom_pea_rework_cost")["insert_after"] == "custom_pea_rework_operators"
	assert field("custom_pea_rework_details_end_section") == {
		"doctype": "Custom Field",
		"name": "Stock Entry-custom_pea_rework_details_end_section",
		"dt": "Stock Entry",
		"fieldname": "custom_pea_rework_details_end_section",
		"fieldtype": "Section Break",
		"insert_after": "custom_pea_rework_cost",
		"module": "Production Entry App",
		"permlevel": 0,
	}


def test_metadata_load_tests_includes_rework_layout_contract() -> None:
	suite = load_tests(unittest.TestLoader(), unittest.TestSuite(), None)
	loaded_functions = {test_case._testFunc for test_case in suite}

	assert test_rework_fields_have_a_dedicated_two_column_section in loaded_functions


def test_settings_has_no_access_control_fields() -> None:
	fields_by_name = {
		field.get("fieldname"): field
		for field in assert_doctype_json("Production Entry Settings").get("fields", [])
		if field.get("fieldname")
	}
	for fieldname in (
		"enable_access_control",
		"write_role",
		"read_role",
		"last_synced_write_role",
		"last_synced_read_role",
	):
		assert fieldname not in fields_by_name


def test_pea_roles_are_shipped() -> None:
	import frappe

	from production_entry_app import hooks

	fixtures_by_dt = {
		fixture["dt"]: fixture
		for fixture in hooks.fixtures
		if isinstance(fixture, dict) and fixture.get("dt")
	}
	assert fixtures_by_dt["Role"]["filters"] == [["name", "in", list(EXPECTED_PEA_ROLE_NAMES)]]

	role_fixture = json.loads(ROLE_FIXTURE.read_text())
	assert [row["name"] for row in role_fixture] == list(EXPECTED_PEA_ROLE_NAMES)
	assert [row["doctype"] for row in role_fixture] == ["Role", "Role"]
	expected_role_keys = {
		"desk_access",
		"disabled",
		"docstatus",
		"doctype",
		"home_page",
		"is_custom",
		"modified",
		"name",
		"restrict_to_domain",
		"role_name",
		"two_factor_auth",
	}
	for row in role_fixture:
		assert set(row) == expected_role_keys
		assert row["name"] in EXPECTED_PEA_ROLE_NAMES
		assert row["doctype"] == "Role"
		assert row["role_name"] == row["name"]
	assert frappe.db.exists("Role", "PEA User")
	assert frappe.db.exists("Role", "PEA Read Only")


def test_workspace_has_forms_and_reports_cards() -> None:
	import frappe

	ws = frappe.get_doc("Workspace", "Production Entry App")
	card_labels = [row.label for row in ws.links if row.type == "Card Break"]
	assert card_labels == ["Forms", "Reports"]
	report_links = [row.link_to for row in ws.links if row.link_type == "Report"]
	assert "Production OEE Report" in report_links
	assert len(report_links) == 18


def assert_doctype_json(doctype: str) -> dict:
	doctype_path = DOCTYPE_ROOT / scrub_doctype(doctype) / f"{scrub_doctype(doctype)}.json"
	return json.loads(doctype_path.read_text())


def load_custom_field_fixture() -> list[dict]:
	return json.loads(CUSTOM_FIELD_FIXTURE.read_text())


def scrub_doctype(doctype: str) -> str:
	return doctype.lower().replace(" ", "_")


def load_tests(
	loader: unittest.TestLoader,
	tests: unittest.TestSuite,
	pattern: str | None,
) -> unittest.TestSuite:
	del loader, tests, pattern
	return unittest.TestSuite(
		unittest.FunctionTestCase(test_func)
		for test_func in (
			test_required_apps_declares_erpnext,
			test_master_data_doctypes_do_not_allow_rename,
			test_filtered_doctype_fields_are_search_indexed,
			test_filtered_custom_fields_are_search_indexed,
			test_no_app_custom_field_uses_nonzero_permlevel,
			test_stock_entry_detail_rejection_flag_uses_cross_version_anchor,
			test_joint_lh_rh_production_metadata_is_exported,
			test_rework_stock_entry_metadata_is_exported,
			test_rework_fields_have_a_dedicated_two_column_section,
			test_metadata_load_tests_includes_rework_layout_contract,
			test_settings_has_no_access_control_fields,
			test_pea_roles_are_shipped,
			test_workspace_has_forms_and_reports_cards,
		)
	)
