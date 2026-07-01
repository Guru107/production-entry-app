from __future__ import annotations

import json
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
DOCTYPE_ROOT = Path(__file__).parent / "doctype"
CUSTOM_FIELD_FIXTURE = APP_ROOT / "production_entry_app" / "fixtures" / "custom_field.json"

REQUIRED_SEARCH_INDEXES: dict[str, set[str]] = {
	"Shift": {"branch", "shift_date", "status"},
}

REQUIRED_CUSTOM_FIELD_SEARCH_INDEXES: set[str] = {
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


def test_stock_entry_detail_rejection_flag_uses_cross_version_anchor() -> None:
	fields_by_name = {field.get("name"): field for field in load_custom_field_fixture() if field.get("name")}
	assert (
		fields_by_name["Stock Entry Detail-custom_pea_is_rejection_item"].get("insert_after")
		== "is_finished_item"
	)


def test_access_role_settings_document_static_report_role_contract() -> None:
	fields_by_name = {
		field.get("fieldname"): field
		for field in assert_doctype_json("Production Entry Settings").get("fields", [])
		if field.get("fieldname")
	}
	for fieldname in ("write_role", "read_role"):
		description = fields_by_name.get(fieldname, {}).get("description") or ""
		assert "DocType" in description
		assert "Report access" in description
		assert "source-controlled roles" in description


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
			test_stock_entry_detail_rejection_flag_uses_cross_version_anchor,
			test_access_role_settings_document_static_report_role_contract,
		)
	)
