from __future__ import annotations

import json
import re
from pathlib import Path

from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.access_control_field_map import (
	build_access_control_field_map,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "production_entry_app" / "fixtures" / "custom_field.json"
GENERATED_PATH = ROOT / "production_entry_app" / "public" / "js" / "generated_access_control_field_map.js"

EXPECTED_DOCTYPES: tuple[str, ...] = (
	"Stock Entry",
	"Stock Entry Detail",
	"Item",
	"Workstation",
	"Downtime Entry",
)


class TestAccessControlFieldMap(FrappeTestCase):
	def test_stock_entry_branch_is_not_app_owned(self) -> None:
		field_names = {field.get("name") for field in _load_custom_field_fixture()}
		self.assertNotIn("Stock Entry-branch", field_names)

	def test_generated_map_matches_custom_field_fixture(self) -> None:
		expected = _build_expected_map()
		rendered = GENERATED_PATH.read_text()
		parsed = _parse_generated_map(rendered)
		self.assertEqual(parsed, expected)

		for doctype in EXPECTED_DOCTYPES:
			self.assertIn(doctype, parsed)
			self.assertGreater(len(parsed[doctype]), 0)

	def test_unlisted_app_owned_doctypes_fail_loudly(self) -> None:
		with self.assertRaisesRegex(ValueError, "unlisted doctypes"):
			build_access_control_field_map(
				custom_fields=[
					{
						"module": "Production Entry App",
						"dt": "Core Doctype Not In Allowlist",
						"fieldname": "custom_field",
					}
				]
			)


def _build_expected_map() -> dict[str, list[str]]:
	field_map: dict[str, list[str]] = {doctype: [] for doctype in EXPECTED_DOCTYPES}
	for row in _load_custom_field_fixture():
		if row.get("module") != "Production Entry App":
			continue
		doctype = row.get("dt")
		fieldname = row.get("fieldname")
		if doctype in field_map and fieldname:
			field_map[doctype].append(str(fieldname))
	return field_map


def _load_custom_field_fixture() -> list[dict]:
	return json.loads(FIXTURE_PATH.read_text())


def _parse_generated_map(rendered: str) -> dict[str, list[str]]:
	match = re.search(r"const GENERATED_ACCESS_CONTROL_FIELD_MAP = (\{.*?\});\n", rendered, re.S)
	if not match:
		raise AssertionError("Generated access-control field map JS artifact is malformed.")
	return json.loads(match.group(1))
