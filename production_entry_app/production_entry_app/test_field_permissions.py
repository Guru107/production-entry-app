from __future__ import annotations

from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.access_control import DEFAULT_READ_ROLE, DEFAULT_WRITE_ROLE
from production_entry_app.production_entry_app.field_permissions import PEA_FIELD_PERMLEVEL, ensure_pea_field_permissions


class TestFieldPermissions(FrappeTestCase):
	def test_ensures_pea_permlevel_docperms_for_app_custom_field_doctypes(self) -> None:
		inserted: list[dict] = []

		def fake_exists(doctype: str, filters: dict | str) -> str | None:
			self.assertEqual(doctype, "DocPerm")
			return None

		def fake_get_doc(values: dict) -> MagicMock:
			inserted.append(values)
			doc = MagicMock()
			doc.insert.return_value = doc
			return doc

		with (
			patch(
				"production_entry_app.production_entry_app.field_permissions._get_pea_custom_field_doctypes",
				return_value=("Stock Entry", "Item"),
			),
			patch("production_entry_app.production_entry_app.field_permissions._validate_permlevel_is_pea_owned"),
			patch("production_entry_app.production_entry_app.field_permissions.frappe.db.exists", side_effect=fake_exists),
			patch("production_entry_app.production_entry_app.field_permissions.frappe.get_all", return_value=[]),
			patch("production_entry_app.production_entry_app.field_permissions._get_next_docperm_idx", return_value=7),
			patch("production_entry_app.production_entry_app.field_permissions.frappe.get_doc", side_effect=fake_get_doc),
			patch("production_entry_app.production_entry_app.field_permissions.frappe.clear_cache") as clear_cache,
		):
			ensure_pea_field_permissions(write_role=DEFAULT_WRITE_ROLE, read_role=DEFAULT_READ_ROLE)

		self.assertEqual(
			[(row["parent"], row["role"], row["permlevel"], row["read"], row["write"]) for row in inserted],
			[
				("Stock Entry", DEFAULT_WRITE_ROLE, PEA_FIELD_PERMLEVEL, 1, 1),
				("Stock Entry", DEFAULT_READ_ROLE, PEA_FIELD_PERMLEVEL, 1, 0),
				("Item", DEFAULT_WRITE_ROLE, PEA_FIELD_PERMLEVEL, 1, 1),
				("Item", DEFAULT_READ_ROLE, PEA_FIELD_PERMLEVEL, 1, 0),
			],
		)
		clear_cache.assert_any_call(doctype="Stock Entry")
		clear_cache.assert_any_call(doctype="Item")

	def test_removes_stale_pea_docperms_for_previous_app_roles(self) -> None:
		def fake_get_all(doctype: str, **kwargs: object) -> list[dict] | list[str]:
			if doctype == "DocPerm":
				return [
					{
						"name": "stale-stock-entry",
						"role": "Old Write",
						"permlevel": PEA_FIELD_PERMLEVEL,
						"select": 1,
						"read": 1,
						"write": 1,
						"create": 0,
						"delete": 0,
						"submit": 0,
						"cancel": 0,
						"amend": 0,
						"report": 1,
						"export": 1,
						"import": 0,
						"share": 0,
						"print": 1,
						"email": 1,
						"if_owner": 0,
					},
					{
						"name": "production-stock-entry",
						"role": "Old Write",
						"permlevel": PEA_FIELD_PERMLEVEL,
						"select": 1,
						"read": 1,
						"write": 1,
						"create": 1,
						"delete": 0,
						"submit": 0,
						"cancel": 0,
						"amend": 0,
						"report": 1,
						"export": 1,
						"import": 0,
						"share": 0,
						"print": 1,
						"email": 1,
						"if_owner": 0,
					},
				]
			raise AssertionError(doctype)

		with (
			patch(
				"production_entry_app.production_entry_app.field_permissions._get_pea_custom_field_doctypes",
				return_value=("Stock Entry",),
			),
			patch("production_entry_app.production_entry_app.field_permissions._validate_permlevel_is_pea_owned"),
			patch("production_entry_app.production_entry_app.field_permissions.frappe.get_all", side_effect=fake_get_all),
			patch("production_entry_app.production_entry_app.field_permissions.frappe.delete_doc") as delete_doc,
			patch("production_entry_app.production_entry_app.field_permissions.frappe.db.exists", return_value="current"),
			patch(
				"production_entry_app.production_entry_app.field_permissions.frappe.db.get_value",
				return_value={
					"permlevel": PEA_FIELD_PERMLEVEL,
					"select": 1,
					"read": 1,
					"write": 1,
					"create": 0,
					"delete": 0,
					"submit": 0,
					"cancel": 0,
					"amend": 0,
					"report": 1,
					"export": 1,
					"import": 0,
					"share": 0,
					"print": 1,
					"email": 1,
					"if_owner": 0,
				},
			),
			patch("production_entry_app.production_entry_app.field_permissions.frappe.db.set_value"),
			patch("production_entry_app.production_entry_app.field_permissions.frappe.clear_cache"),
		):
			ensure_pea_field_permissions(
				write_role="New Write",
				read_role="New Read",
				managed_roles=("Old Write", "New Read"),
			)

		delete_doc.assert_called_once_with("DocPerm", "stale-stock-entry", ignore_permissions=True, force=True)

	def test_rejects_existing_non_pea_docperm_for_active_role(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.field_permissions._get_pea_custom_field_doctypes",
				return_value=("Stock Entry",),
			),
			patch("production_entry_app.production_entry_app.field_permissions._validate_permlevel_is_pea_owned"),
			patch("production_entry_app.production_entry_app.field_permissions.frappe.get_all", return_value=[]),
			patch("production_entry_app.production_entry_app.field_permissions.frappe.db.exists", return_value="production-row"),
			patch(
				"production_entry_app.production_entry_app.field_permissions.frappe.db.get_value",
				return_value={
					"permlevel": PEA_FIELD_PERMLEVEL,
					"select": 1,
					"read": 1,
					"write": 1,
					"create": 1,
					"delete": 0,
					"submit": 0,
					"cancel": 0,
					"amend": 0,
					"report": 1,
					"export": 1,
					"import": 0,
					"share": 0,
					"print": 1,
					"email": 1,
					"if_owner": 0,
				},
			),
			patch("production_entry_app.production_entry_app.field_permissions.frappe.throw", side_effect=Exception) as throw,
		):
			with self.assertRaises(Exception):
				ensure_pea_field_permissions(write_role=DEFAULT_WRITE_ROLE, read_role=DEFAULT_READ_ROLE)

		throw.assert_called_once()

	def test_custom_field_discovery_uses_only_pea_permlevel_fields(self) -> None:
		rows = [
			{"dt": "Stock Entry"},
			{"dt": "Stock Entry"},
			{"dt": "Item"},
		]
		with patch(
			"production_entry_app.production_entry_app.field_permissions.frappe.get_all",
			return_value=rows,
		) as get_all:
			from production_entry_app.production_entry_app.field_permissions import _get_pea_custom_field_doctypes

			self.assertEqual(_get_pea_custom_field_doctypes(), ("Stock Entry", "Item"))

		get_all.assert_called_once_with(
			"Custom Field",
			filters={"module": "Production Entry App", "permlevel": PEA_FIELD_PERMLEVEL},
			fields=["dt"],
			order_by="dt asc",
		)

	def test_rejects_pea_permlevel_collision_with_non_pea_fields(self) -> None:
		def fake_get_all(doctype: str, **kwargs: object) -> list[str]:
			if doctype == "Custom Field" and kwargs.get("filters") == {
				"dt": "Stock Entry",
				"module": "Production Entry App",
				"permlevel": PEA_FIELD_PERMLEVEL,
			}:
				return ["custom_pea_shift"]
			if doctype == "Custom Field":
				return ["custom_existing_production_field"]
			if doctype == "DocField":
				return ["existing_standard_field"]
			raise AssertionError(doctype)

		with (
			patch("production_entry_app.production_entry_app.field_permissions.frappe.get_all", side_effect=fake_get_all),
			patch("production_entry_app.production_entry_app.field_permissions.frappe.throw", side_effect=Exception) as throw,
		):
			from production_entry_app.production_entry_app.field_permissions import _validate_permlevel_is_pea_owned

			with self.assertRaises(Exception):
				_validate_permlevel_is_pea_owned("Stock Entry")

		throw.assert_called_once()
