from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

import frappe
from frappe.tests.utils import FrappeTestCase

DEFAULT_WRITE_ROLE: str = "PEA User"
DEFAULT_READ_ROLE: str = "PEA Read Only"
DEFAULT_REQUIRED_ROLE: str = DEFAULT_WRITE_ROLE
REPORTS_PATH: Path = Path(__file__).parent / "report"


def _settings(
	enabled: bool,
	write_role: str | None = DEFAULT_WRITE_ROLE,
	read_role: str | None = DEFAULT_READ_ROLE,
) -> SimpleNamespace:
	return SimpleNamespace(
		enabled=enabled,
		write_role=write_role,
		read_role=read_role,
	)


def _settings_doc(
	enabled: bool,
	write_role: str | None = DEFAULT_WRITE_ROLE,
	read_role: str | None = DEFAULT_READ_ROLE,
) -> SimpleNamespace:
	return SimpleNamespace(
		enable_access_control=1 if enabled else 0,
		write_role=write_role,
		read_role=read_role,
	)


class TestAccessControl(FrappeTestCase):
	def setUp(self) -> None:
		super().setUp()
		from production_entry_app.production_entry_app import access_control

		access_control.invalidate_access_control_cache()

	def tearDown(self) -> None:
		from production_entry_app.production_entry_app import access_control

		access_control.invalidate_access_control_cache()
		super().tearDown()

	def test_settings_metadata_is_install_safe_and_role_only(self) -> None:
		settings_path = (
			Path(__file__).parent / "doctype" / "production_entry_settings" / "production_entry_settings.json"
		)
		settings_schema = json.loads(settings_path.read_text())
		field_by_name = {field["fieldname"]: field for field in settings_schema["fields"]}
		write_field = field_by_name["write_role"]
		read_field = field_by_name["read_role"]

		self.assertEqual(write_field["fieldtype"], "Link")
		self.assertEqual(write_field["options"], "Role")
		self.assertEqual(write_field["default"], DEFAULT_WRITE_ROLE)
		self.assertEqual(write_field["reqd"], 1)
		self.assertEqual(read_field["fieldtype"], "Link")
		self.assertEqual(read_field["options"], "Role")
		self.assertEqual(read_field["default"], DEFAULT_READ_ROLE)
		self.assertEqual(read_field["reqd"], 1)
		self.assertNotIn("allowed_access_rules", field_by_name)

	def test_access_rule_doctype_controller_is_registered(self) -> None:
		from frappe.model.document import Document

		from production_entry_app.production_entry_app.doctype.production_entry_access_rule.production_entry_access_rule import (
			ProductionEntryAccessRule,
		)

		self.assertTrue(issubclass(ProductionEntryAccessRule, Document))

	def test_report_metadata_uses_pea_read_roles(self) -> None:
		for report_path in REPORTS_PATH.glob("*/*.json"):
			with self.subTest(report=report_path.parent.name):
				report_schema = json.loads(report_path.read_text())
				roles = {role["role"] for role in report_schema.get("roles", [])}
				self.assertEqual(roles, {"System Manager", DEFAULT_WRITE_ROLE, DEFAULT_READ_ROLE})

	def test_report_execute_paths_assert_pea_read_access(self) -> None:
		for report_path in REPORTS_PATH.glob("*/*.py"):
			if report_path.name == "__init__.py":
				continue
			with self.subTest(report=report_path.parent.name):
				self.assertIn("assert_report_read_access()", report_path.read_text())

	def test_before_install_runs_access_setup(self) -> None:
		from production_entry_app import install

		with patch("production_entry_app.install.ensure_access_roles_and_settings") as setup:
			install.before_install()

		setup.assert_called_once_with()

	def test_before_install_hook_registers_default_required_role_setup(self) -> None:
		from production_entry_app import hooks

		self.assertIn("production_entry_app.install.before_install", hooks.before_install)

	def test_lifecycle_hooks_register_access_setup_for_existing_sites(self) -> None:
		from production_entry_app import hooks

		self.assertIn("production_entry_app.production_entry_app.lifecycle.after_sync", hooks.after_sync)
		self.assertIn(
			"production_entry_app.production_entry_app.lifecycle.after_migrate", hooks.after_migrate
		)

	def test_lifecycle_setup_runs_access_setup(self) -> None:
		from production_entry_app.production_entry_app import lifecycle

		with (
			patch.object(lifecycle.access_control, "ensure_access_roles_and_settings") as setup_access,
			patch.object(
				lifecycle.performance_indexes, "ensure_performance_indexes_with_recovery"
			) as setup_indexes,
		):
			lifecycle.after_migrate()

		setup_access.assert_called_once_with()
		setup_indexes.assert_called_once_with()

	def test_access_setup_creates_roles_and_migrates_legacy_settings(self) -> None:
		from production_entry_app.production_entry_app import access_control

		def fake_get_value(doctype: str, filters: dict, fieldname: str) -> str | None:
			self.assertEqual(doctype, "Singles")
			self.assertEqual(fieldname, "value")
			if filters["field"] == "write_role":
				return None
			if filters["field"] == "read_role":
				return None
			if filters["field"] == "required_role":
				return "Legacy PEA User"
			raise AssertionError(filters)

		with (
			patch.object(access_control.frappe.db, "exists", side_effect=[False, False, True]) as exists,
			patch.object(access_control.frappe, "get_doc") as get_doc,
			patch.object(access_control.frappe.db, "get_value", side_effect=fake_get_value),
			patch.object(access_control.frappe.db, "set_single_value") as set_single_value,
			patch.object(access_control, "invalidate_access_control_cache") as invalidate_cache,
		):
			role_doc = get_doc.return_value
			access_control.ensure_access_roles_and_settings()

		self.assertEqual(
			exists.call_args_list,
			[
				call("Role", DEFAULT_WRITE_ROLE),
				call("Role", DEFAULT_READ_ROLE),
				call("DocType", access_control.SETTINGS_DOCTYPE),
			],
		)
		self.assertEqual(
			get_doc.call_args_list,
			[
				call({"doctype": "Role", "role_name": DEFAULT_WRITE_ROLE}),
				call({"doctype": "Role", "role_name": DEFAULT_READ_ROLE}),
			],
		)
		self.assertEqual(role_doc.insert.call_count, 2)
		set_single_value.assert_has_calls(
			[
				call(access_control.SETTINGS_DOCTYPE, "write_role", "Legacy PEA User"),
				call(access_control.SETTINGS_DOCTYPE, "read_role", DEFAULT_READ_ROLE),
			]
		)
		invalidate_cache.assert_called_once_with()

	def test_access_setup_keeps_existing_split_settings(self) -> None:
		from production_entry_app.production_entry_app import access_control

		def fake_get_value(doctype: str, filters: dict, fieldname: str) -> str | None:
			del doctype, fieldname
			return {"write_role": "Custom Write", "read_role": "Custom Read"}.get(filters["field"])

		with (
			patch.object(access_control.frappe.db, "exists", side_effect=[True, True, True]),
			patch.object(access_control.frappe, "get_doc") as get_doc,
			patch.object(access_control.frappe.db, "get_value", side_effect=fake_get_value),
			patch.object(access_control.frappe.db, "set_single_value") as set_single_value,
			patch.object(access_control, "invalidate_access_control_cache") as invalidate_cache,
		):
			access_control.ensure_access_roles_and_settings()

		get_doc.assert_not_called()
		set_single_value.assert_not_called()
		invalidate_cache.assert_called_once_with()

	def test_settings_default_enable_access_control_is_zero(self) -> None:
		meta = frappe.get_meta("Production Entry Settings")
		field = meta.get_field("enable_access_control")

		self.assertIsNotNone(field)
		self.assertEqual(field.default, "0")

	def test_shift_settings_fields_exist_with_expected_metadata(self) -> None:
		meta = frappe.get_meta("Production Entry Settings")
		expected_fields = {
			"shift_raw_material_warehouse": ("Link", "Warehouse", None),
			"shift_wip_warehouse": ("Link", "Warehouse", None),
			"shift_rejection_warehouse": ("Link", "Warehouse", None),
			"shift_scrap_warehouse": ("Link", "Warehouse", None),
			"shift_start_buffer_mins": ("Int", None, "60"),
			"shift_end_buffer_mins": ("Int", None, "60"),
		}

		for fieldname, (fieldtype, options, default) in expected_fields.items():
			with self.subTest(fieldname=fieldname):
				field = meta.get_field(fieldname)
				self.assertIsNotNone(field)
				self.assertEqual(field.fieldtype, fieldtype)
				self.assertEqual(field.options or None, options)
				self.assertEqual(field.default or None, default)

	def test_settings_singleton_default_enable_access_control_is_zero(self) -> None:
		frappe.db.delete("Singles", {"doctype": "Production Entry Settings"})
		frappe.clear_document_cache("Production Entry Settings")

		settings = frappe.get_single("Production Entry Settings")

		self.assertEqual(settings.enable_access_control, 0)

	def test_settings_validation_rejects_blank_access_roles_when_enabled(self) -> None:
		settings = frappe.get_single("Production Entry Settings")
		settings.enable_access_control = 1
		settings.write_role = ""
		settings.read_role = DEFAULT_READ_ROLE

		with self.assertRaises(frappe.ValidationError):
			settings.save()

		settings.write_role = DEFAULT_WRITE_ROLE
		settings.read_role = ""

		with self.assertRaises(frappe.ValidationError):
			settings.save()

	def test_settings_update_invalidates_access_cache(self) -> None:
		from production_entry_app.production_entry_app import access_control

		if not frappe.db.exists("Role", DEFAULT_REQUIRED_ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": DEFAULT_REQUIRED_ROLE}).insert(
				ignore_permissions=True
			)

		cache = frappe.cache()
		cache.set_value(
			access_control.ACCESS_CONTROL_CACHE_KEY,
			{"enabled": True, "write_role": DEFAULT_WRITE_ROLE, "read_role": DEFAULT_READ_ROLE},
			expires_in_sec=access_control.ACCESS_CONTROL_CACHE_TTL_SEC,
		)

		settings = frappe.get_single("Production Entry Settings")
		settings.enable_access_control = 1 if not settings.enable_access_control else 0
		if settings.enable_access_control:
			settings.write_role = DEFAULT_WRITE_ROLE
			settings.read_role = DEFAULT_READ_ROLE
		for fieldname in (
			"shift_raw_material_warehouse",
			"shift_wip_warehouse",
			"shift_rejection_warehouse",
			"shift_scrap_warehouse",
		):
			if settings.meta.has_field(fieldname):
				settings.set(fieldname, None)
		settings.save()

		self.assertIsNone(cache.get_value(access_control.ACCESS_CONTROL_CACHE_KEY))

	def test_legacy_cache_key_payload_is_ignored(self) -> None:
		from production_entry_app.production_entry_app import access_control

		cache = frappe.cache()
		cache.set_value(
			access_control.LEGACY_ACCESS_CONTROL_CACHE_KEY,
			{"enabled": True, "rules": [("Manufacturing User", "Nashik")]},
			expires_in_sec=access_control.ACCESS_CONTROL_CACHE_TTL_SEC,
		)
		with patch(
			"production_entry_app.production_entry_app.access_control._load_access_configuration",
			return_value=_settings(False, DEFAULT_REQUIRED_ROLE),
		):
			self.assertTrue(access_control.can_use_production_entry_app("user@example.com"))

	def test_non_admin_cannot_modify_production_entry_settings(self) -> None:
		user_email = f"test_pea_settings_user_{frappe.generate_hash(length=8)}@example.com"
		_ensure_user_with_role(user_email, "Manufacturing User")
		original_user = frappe.session.user
		try:
			frappe.set_user(user_email)
			settings = frappe.get_single("Production Entry Settings")
			settings.enable_access_control = 1
			settings.write_role = DEFAULT_WRITE_ROLE
			settings.read_role = DEFAULT_READ_ROLE
			with self.assertRaises(frappe.PermissionError):
				settings.save()
		finally:
			frappe.set_user(original_user)

	def test_system_manager_always_allowed(self) -> None:
		from production_entry_app.production_entry_app import access_control

		config = access_control.AccessConfiguration(
			enabled=True,
			write_role=DEFAULT_WRITE_ROLE,
			read_role=DEFAULT_READ_ROLE,
		)
		with (
			patch.object(access_control, "_get_access_configuration", return_value=config),
			patch.object(access_control.frappe, "get_roles", return_value=["System Manager"]),
		):
			self.assertTrue(access_control.can_read_production_entry_app("manager@example.com"))
			self.assertTrue(access_control.can_write_production_entry_app("manager@example.com"))

	def test_pea_user_has_read_and_write_access(self) -> None:
		from production_entry_app.production_entry_app import access_control

		config = access_control.AccessConfiguration(
			enabled=True,
			write_role=DEFAULT_WRITE_ROLE,
			read_role=DEFAULT_READ_ROLE,
		)
		with (
			patch.object(access_control, "_get_access_configuration", return_value=config),
			patch.object(access_control.frappe, "get_roles", return_value=[DEFAULT_WRITE_ROLE]),
		):
			self.assertTrue(access_control.can_read_production_entry_app("test@example.com"))
			self.assertTrue(access_control.can_write_production_entry_app("test@example.com"))

	def test_pea_read_only_has_read_without_write_access(self) -> None:
		from production_entry_app.production_entry_app import access_control

		config = access_control.AccessConfiguration(
			enabled=True,
			write_role=DEFAULT_WRITE_ROLE,
			read_role=DEFAULT_READ_ROLE,
		)
		with (
			patch.object(access_control, "_get_access_configuration", return_value=config),
			patch.object(access_control.frappe, "get_roles", return_value=[DEFAULT_READ_ROLE]),
		):
			self.assertTrue(access_control.can_read_production_entry_app("readonly@example.com"))
			self.assertFalse(access_control.can_write_production_entry_app("readonly@example.com"))

	def test_non_pea_user_has_no_read_or_write_access_when_enabled(self) -> None:
		from production_entry_app.production_entry_app import access_control

		config = access_control.AccessConfiguration(
			enabled=True,
			write_role=DEFAULT_WRITE_ROLE,
			read_role=DEFAULT_READ_ROLE,
		)
		with (
			patch.object(access_control, "_get_access_configuration", return_value=config),
			patch.object(access_control.frappe, "get_roles", return_value=["Manufacturing User"]),
		):
			self.assertFalse(access_control.can_read_production_entry_app("user@example.com"))
			self.assertFalse(access_control.can_write_production_entry_app("user@example.com"))

	def test_disabled_control_allows_read_and_write_for_development(self) -> None:
		from production_entry_app.production_entry_app import access_control

		config = access_control.AccessConfiguration(
			enabled=False,
			write_role=DEFAULT_WRITE_ROLE,
			read_role=DEFAULT_READ_ROLE,
		)
		with (
			patch.object(access_control, "_get_access_configuration", return_value=config),
			patch.object(access_control.frappe, "get_roles", return_value=["Manufacturing User"]),
		):
			self.assertTrue(access_control.can_read_production_entry_app("user@example.com"))
			self.assertTrue(access_control.can_write_production_entry_app("user@example.com"))

	def test_disabled_control_allows_non_manager(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_settings(False, DEFAULT_REQUIRED_ROLE),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["Manufacturing User"],
			),
		):
			from production_entry_app.production_entry_app import access_control

			self.assertTrue(access_control.can_use_production_entry_app("user@example.com"))

	def test_enabled_allows_write_when_user_has_write_role(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_settings(True, DEFAULT_REQUIRED_ROLE),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=[DEFAULT_WRITE_ROLE],
			),
		):
			from production_entry_app.production_entry_app import access_control

			self.assertTrue(access_control.can_use_production_entry_app("user@example.com"))
			self.assertTrue(access_control.can_write_production_entry_app("user@example.com"))

	def test_enabled_denies_write_when_user_missing_write_role(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_settings(True, DEFAULT_REQUIRED_ROLE),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["Manufacturing User"],
			),
		):
			from production_entry_app.production_entry_app import access_control

			self.assertFalse(access_control.can_use_production_entry_app("user@example.com"))
			self.assertFalse(access_control.can_write_production_entry_app("user@example.com"))

	def test_enabled_denies_when_write_role_blank(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_settings(True, "", DEFAULT_READ_ROLE),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=[DEFAULT_REQUIRED_ROLE],
			),
		):
			from production_entry_app.production_entry_app import access_control

			self.assertFalse(access_control.can_write_production_entry_app("user@example.com"))

	def test_enabled_allows_when_custom_write_role_matches(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_settings(True, "Manufacturing User"),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["Manufacturing User"],
			),
		):
			from production_entry_app.production_entry_app import access_control

			self.assertTrue(access_control.can_use_production_entry_app("user@example.com"))

	def test_load_access_configuration_reads_access_roles(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.access_control.frappe.get_single",
			return_value=_settings_doc(True, "Manufacturing User", "Stock User"),
		):
			from production_entry_app.production_entry_app import access_control

			config = access_control._load_access_configuration()
			self.assertTrue(config.enabled)
			self.assertEqual(config.write_role, "Manufacturing User")
			self.assertEqual(config.read_role, "Stock User")

	def test_load_access_configuration_falls_back_to_defaults_when_missing(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.access_control.frappe.get_single",
			return_value=SimpleNamespace(enable_access_control=1),
		):
			from production_entry_app.production_entry_app import access_control

			config = access_control._load_access_configuration()
			self.assertTrue(config.enabled)
			self.assertEqual(config.write_role, DEFAULT_WRITE_ROLE)
			self.assertEqual(config.read_role, DEFAULT_READ_ROLE)

	def test_load_access_configuration_preserves_blank_access_roles(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.access_control.frappe.get_single",
			return_value=_settings_doc(True, "", ""),
		):
			from production_entry_app.production_entry_app import access_control

			config = access_control._load_access_configuration()
			self.assertTrue(config.enabled)
			self.assertEqual(config.write_role, "")
			self.assertEqual(config.read_role, "")

	def test_load_access_configuration_uses_legacy_required_role_for_write_role(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.access_control.frappe.get_single",
			return_value=SimpleNamespace(enable_access_control=1, required_role="Legacy PEA User"),
		):
			from production_entry_app.production_entry_app import access_control

			config = access_control._load_access_configuration()
			self.assertTrue(config.enabled)
			self.assertEqual(config.write_role, "Legacy PEA User")
			self.assertEqual(config.read_role, DEFAULT_READ_ROLE)

	def test_has_gated_doctype_permission_uses_real_loader_path(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_single",
				return_value=_settings_doc(True, DEFAULT_REQUIRED_ROLE),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.cache",
				return_value=SimpleNamespace(
					get_value=lambda *_: None, set_value=lambda *args, **kwargs: None
				),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=[DEFAULT_REQUIRED_ROLE],
			),
		):
			from production_entry_app.production_entry_app import access_control

			self.assertTrue(
				access_control.has_gated_doctype_permission(
					doc=SimpleNamespace(branch="Ignored Branch"),
					user="user@example.com",
				)
			)

	def test_assert_app_access_doc_context_allows_with_required_role_and_skips_branch_lookup(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_settings(True, DEFAULT_REQUIRED_ROLE),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=[DEFAULT_REQUIRED_ROLE],
			),
		):
			from production_entry_app.production_entry_app import access_control

			access_control.assert_app_access(doctype="Shift", docname="SHIFT-00001")

	def test_assert_app_access_doc_context_denies_when_missing_required_role(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_settings(True, DEFAULT_REQUIRED_ROLE),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["Sales User"],
			),
		):
			from production_entry_app.production_entry_app import access_control

			with self.assertRaises(frappe.PermissionError):
				access_control.assert_app_access(doctype="Shift", docname="SHIFT-00001")

	def test_assert_app_access_fails_closed_for_non_manager_when_settings_are_corrupt(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				side_effect=ValueError("corrupt"),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["Manufacturing User"],
			),
			patch("production_entry_app.production_entry_app.access_control.frappe.log_error") as log_error,
		):
			from production_entry_app.production_entry_app import access_control

			with self.assertRaises(frappe.PermissionError):
				access_control.assert_app_access(doctype="Shift", docname="SHIFT-00001")
			self.assertTrue(log_error.called)

	def test_assert_app_access_allows_system_manager_when_settings_are_corrupt(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				side_effect=ValueError("corrupt"),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["System Manager"],
			),
			patch("production_entry_app.production_entry_app.access_control.frappe.log_error") as log_error,
		):
			from production_entry_app.production_entry_app import access_control

			access_control.assert_app_access(doctype="Shift", docname="SHIFT-00001")
			self.assertTrue(log_error.called)

	def test_missing_or_corrupt_settings_fail_closed_for_non_manager(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				side_effect=ValueError("corrupt"),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["Manufacturing User"],
			),
			patch("production_entry_app.production_entry_app.access_control.frappe.log_error") as log_error,
		):
			from production_entry_app.production_entry_app import access_control

			self.assertFalse(access_control.can_use_production_entry_app("user@example.com"))
			self.assertTrue(log_error.called)

	def test_missing_or_corrupt_settings_logs_error_and_allows_system_manager(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				side_effect=ValueError("corrupt"),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["System Manager"],
			),
			patch("production_entry_app.production_entry_app.access_control.frappe.log_error") as log_error,
		):
			from production_entry_app.production_entry_app import access_control

			self.assertTrue(access_control.can_use_production_entry_app("manager@example.com"))
			self.assertTrue(log_error.called)


def _ensure_user_with_role(email: str, role: str) -> None:
	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = email.split("@", 1)[0]
		user.user_type = "System User"
	user.add_roles(role)
	user.save(ignore_permissions=True)
	frappe.clear_cache(user=email)
