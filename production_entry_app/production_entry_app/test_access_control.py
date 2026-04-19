from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

DEFAULT_REQUIRED_ROLE: str = "PEA User"


def _settings(enabled: bool, required_role: str | None = DEFAULT_REQUIRED_ROLE) -> SimpleNamespace:
	return SimpleNamespace(
		enabled=enabled,
		required_role=required_role,
	)


def _settings_doc(enabled: bool, required_role: str | None = DEFAULT_REQUIRED_ROLE) -> SimpleNamespace:
	return SimpleNamespace(
		enable_access_control=1 if enabled else 0,
		required_role=required_role,
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
		meta = frappe.get_meta("Production Entry Settings")
		field = meta.get_field("required_role")

		self.assertIsNotNone(field)
		self.assertEqual(field.fieldtype, "Link")
		self.assertEqual(field.options, "Role")
		self.assertFalse(field.default)
		self.assertIsNone(meta.get_field("allowed_access_rules"))

	def test_settings_default_enable_access_control_is_zero(self) -> None:
		meta = frappe.get_meta("Production Entry Settings")
		field = meta.get_field("enable_access_control")

		self.assertIsNotNone(field)
		self.assertEqual(field.default, "0")

	def test_settings_singleton_default_enable_access_control_is_zero(self) -> None:
		frappe.db.delete("Singles", {"doctype": "Production Entry Settings"})
		frappe.clear_document_cache("Production Entry Settings")

		settings = frappe.get_single("Production Entry Settings")

		self.assertEqual(settings.enable_access_control, 0)

	def test_settings_validation_rejects_blank_required_role_when_enabled(self) -> None:
		settings = frappe.get_single("Production Entry Settings")
		settings.enable_access_control = 1
		settings.required_role = ""

		with self.assertRaises(frappe.ValidationError):
			settings.save()

	def test_settings_update_invalidates_access_cache(self) -> None:
		from production_entry_app.production_entry_app import access_control

		cache = frappe.cache()
		cache.set_value(
			access_control.ACCESS_CONTROL_CACHE_KEY,
			{"enabled": True, "required_role": DEFAULT_REQUIRED_ROLE},
			expires_in_sec=access_control.ACCESS_CONTROL_CACHE_TTL_SEC,
		)

		settings = frappe.get_single("Production Entry Settings")
		settings.enable_access_control = 1 if not settings.enable_access_control else 0
		if settings.enable_access_control:
			settings.required_role = DEFAULT_REQUIRED_ROLE
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
		_ensure_user_with_role("test_pea_settings_user@example.com", "Manufacturing User")
		original_user = frappe.session.user
		try:
			frappe.set_user("test_pea_settings_user@example.com")
			settings = frappe.get_single("Production Entry Settings")
			settings.enable_access_control = 1
			settings.required_role = DEFAULT_REQUIRED_ROLE
			with self.assertRaises(frappe.PermissionError):
				settings.save()
		finally:
			frappe.set_user(original_user)

	def test_system_manager_always_allowed(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_settings(True, DEFAULT_REQUIRED_ROLE),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["System Manager"],
			),
		):
			from production_entry_app.production_entry_app import access_control

			self.assertTrue(access_control.can_use_production_entry_app("manager@example.com"))

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

	def test_enabled_allows_when_user_has_required_role(self) -> None:
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

			self.assertTrue(access_control.can_use_production_entry_app("user@example.com"))

	def test_enabled_denies_when_user_missing_required_role(self) -> None:
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

	def test_enabled_denies_when_required_role_blank(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_settings(True, ""),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=[DEFAULT_REQUIRED_ROLE],
			),
		):
			from production_entry_app.production_entry_app import access_control

			self.assertFalse(access_control.can_use_production_entry_app("user@example.com"))

	def test_enabled_allows_when_custom_required_role_matches(self) -> None:
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

	def test_load_access_configuration_reads_required_role(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.access_control.frappe.get_single",
			return_value=_settings_doc(True, "Manufacturing User"),
		):
			from production_entry_app.production_entry_app import access_control

			config = access_control._load_access_configuration()
			self.assertTrue(config.enabled)
			self.assertEqual(config.required_role, "Manufacturing User")

	def test_load_access_configuration_falls_back_to_default_required_role_when_missing(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.access_control.frappe.get_single",
			return_value=SimpleNamespace(enable_access_control=1),
		):
			from production_entry_app.production_entry_app import access_control

			config = access_control._load_access_configuration()
			self.assertTrue(config.enabled)
			self.assertEqual(config.required_role, DEFAULT_REQUIRED_ROLE)

	def test_load_access_configuration_preserves_blank_required_role(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.access_control.frappe.get_single",
			return_value=_settings_doc(True, ""),
		):
			from production_entry_app.production_entry_app import access_control

			config = access_control._load_access_configuration()
			self.assertTrue(config.enabled)
			self.assertEqual(config.required_role, "")

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
	frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed for permission tests to see user roles
