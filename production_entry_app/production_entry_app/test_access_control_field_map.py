from __future__ import annotations

import json
import re
from pathlib import Path

from frappe.tests.utils import FrappeTestCase

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "production_entry_app" / "fixtures" / "custom_field.json"
GENERATED_PATH = ROOT / "production_entry_app" / "public" / "js" / "generated_access_control_field_map.js"

EXPECTED_DOCTYPES: tuple[str, ...] = (
	"Stock Entry",
	"Stock Entry Detail",
	"Item",
	"Workstation",
	"Manufacturing Settings",
	"Downtime Entry",
)


class TestAccessControlFieldMap(FrappeTestCase):
	def test_generated_map_matches_custom_field_fixture(self) -> None:
		expected = _build_expected_map()
		rendered = GENERATED_PATH.read_text()
		parsed = _parse_generated_map(rendered)
		self.assertEqual(parsed, expected)

		for doctype in EXPECTED_DOCTYPES:
			self.assertIn(doctype, parsed)
			self.assertGreater(len(parsed[doctype]), 0)


def _build_expected_map() -> dict[str, list[str]]:
	rows = json.loads(FIXTURE_PATH.read_text())
	field_map: dict[str, list[str]] = {doctype: [] for doctype in EXPECTED_DOCTYPES}
	for row in rows:
		if row.get("module") != "Production Entry App":
			continue
		doctype = row.get("dt")
		fieldname = row.get("fieldname")
		if doctype in field_map and fieldname:
			field_map[doctype].append(str(fieldname))
	return field_map


def _parse_generated_map(rendered: str) -> dict[str, list[str]]:
	match = re.search(r"const GENERATED_ACCESS_CONTROL_FIELD_MAP = (\{.*?\});\n", rendered, re.S)
	if not match:
		raise AssertionError("Generated access-control field map JS artifact is malformed.")
	return json.loads(match.group(1))
