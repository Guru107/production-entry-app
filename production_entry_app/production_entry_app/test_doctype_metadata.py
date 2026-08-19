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
	"Shift": {"branch", "shift_date", "status"},
}

REQUIRED_CUSTOM_FIELD_SEARCH_INDEXES: set[str] = {
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
		"Stock Entry-custom_pea_joint_scrap_qty",
		"Stock Entry-custom_pea_joint_fetch_items",
		"Stock Entry Detail-custom_pea_joint_output_side",
	}
	assert not required_fields.difference(fields_by_name)
	joint_flag = fields_by_name["Stock Entry-custom_pea_is_joint_lh_rh"]
	assert not joint_flag.get("fetch_from")
	assert not joint_flag.get("read_only")
	total_rm_field = fields_by_name["Stock Entry-custom_pea_total_rm_consumption"]
	assert total_rm_field.get("read_only") == 1
	assert not total_rm_field.get("mandatory_depends_on")

	rejection_fields = {
		field.get("fieldname"): field for field in assert_doctype_json("Rejection Breakup").get("fields", [])
	}
	assert rejection_fields["output_side"]["options"] == "\nLH\nRH"
	assert rejection_fields["item_code"]["options"] == "Item"


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
			test_settings_has_no_access_control_fields,
			test_pea_roles_are_shipped,
			test_workspace_has_forms_and_reports_cards,
		)
	)
