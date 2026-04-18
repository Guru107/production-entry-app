from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase


def _settings(enabled: bool, rules: list[dict] | None = None) -> SimpleNamespace:
	return SimpleNamespace(
		enable_access_control=1 if enabled else 0,
		allowed_access_rules=rules or [],
	)


def _default_branch_or_none(key: str, user: str | None = None) -> str | None:
	del user
	return "Default Branch" if key == "Branch" else None


def _settings_doc(
	enabled: bool,
	rules: list[dict] | None = None,
	access_rules: list[dict] | None = None,
) -> SimpleNamespace:
	return SimpleNamespace(
		enable_access_control=1 if enabled else 0,
		allowed_access_rules=rules or [],
		access_rules=access_rules or [],
	)


class TestAccessControl(FrappeTestCase):
	def test_settings_default_enable_access_control_is_zero(self) -> None:
		settings = frappe.get_single("Production Entry Settings")
		self.assertEqual(settings.enable_access_control, 0)

	def test_settings_update_invalidates_access_cache(self) -> None:
		from production_entry_app.production_entry_app import access_control

		cache = frappe.cache()
		cache.set_value(
			access_control.ACCESS_CONTROL_CACHE_KEY,
			{"enabled": True, "rules": []},
			expires_in_sec=access_control.ACCESS_CONTROL_CACHE_TTL_SEC,
		)

		settings = frappe.get_single("Production Entry Settings")
		settings.enable_access_control = 1 if not settings.enable_access_control else 0
		settings.save()

		self.assertIsNone(cache.get_value(access_control.ACCESS_CONTROL_CACHE_KEY))

	def test_non_admin_cannot_modify_production_entry_settings(self) -> None:
		_ensure_user_with_role("test_pea_settings_user@example.com", "Manufacturing User")
		original_user = frappe.session.user
		try:
			frappe.set_user("test_pea_settings_user@example.com")
			settings = frappe.get_single("Production Entry Settings")
			settings.enable_access_control = 1
			with self.assertRaises(frappe.PermissionError):
				settings.save()
		finally:
			frappe.set_user(original_user)

	def test_system_manager_always_allowed(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_settings(True, []),
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
				return_value=_settings(False, []),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["Manufacturing User"],
			),
		):
			from production_entry_app.production_entry_app import access_control

			self.assertTrue(access_control.can_use_production_entry_app("user@example.com"))

	def test_exact_role_branch_match_allows(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_settings(
					True,
					[{"role": "Manufacturing User", "branch": "Nashik", "is_active": 1}],
				),
			),
			patch(
				"production_entry_app.production_entry_app.access_control._resolve_user_branch",
				return_value="Nashik",
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["Manufacturing User"],
			),
		):
			from production_entry_app.production_entry_app import access_control

			self.assertTrue(access_control.can_use_production_entry_app("user@example.com"))

	def test_role_match_branch_mismatch_denies(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_settings(
					True,
					[{"role": "Manufacturing User", "branch": "Nashik", "is_active": 1}],
				),
			),
			patch(
				"production_entry_app.production_entry_app.access_control._resolve_user_branch",
				return_value="Pune",
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["Manufacturing User"],
			),
		):
			from production_entry_app.production_entry_app import access_control

			self.assertFalse(access_control.can_use_production_entry_app("user@example.com"))

	def test_no_rules_enabled_denies_non_manager(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_settings(True, []),
			),
			patch(
				"production_entry_app.production_entry_app.access_control._resolve_user_branch",
				return_value="Nashik",
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["Manufacturing User"],
			),
		):
			from production_entry_app.production_entry_app import access_control

			self.assertFalse(access_control.can_use_production_entry_app("user@example.com"))

	def test_branch_resolution_default_then_single_permission(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.defaults.get_user_default",
				side_effect=_default_branch_or_none,
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_all",
				return_value=[{"for_value": "Permission Branch"}],
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.cache",
				return_value=SimpleNamespace(
					get_value=lambda *_: None, set_value=lambda *args, **kwargs: None
				),
			),
		):
			from production_entry_app.production_entry_app import access_control

			self.assertEqual(
				access_control._resolve_user_branch("user@example.com"),
				"Default Branch",
			)

		with (
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.defaults.get_user_default",
				return_value=None,
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_all",
				return_value=[{"for_value": "Permission Branch"}],
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.cache",
				return_value=SimpleNamespace(
					get_value=lambda *_: None, set_value=lambda *args, **kwargs: None
				),
			),
		):
			from production_entry_app.production_entry_app import access_control

			self.assertEqual(
				access_control._resolve_user_branch("user@example.com"),
				"Permission Branch",
			)

	def test_branch_resolution_multiple_permissions_denies(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.defaults.get_user_default",
				return_value=None,
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_all",
				return_value=[
					{"for_value": "Nashik"},
					{"for_value": "Pune"},
				],
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.cache",
				return_value=SimpleNamespace(
					get_value=lambda *_: None, set_value=lambda *args, **kwargs: None
				),
			),
		):
			from production_entry_app.production_entry_app import access_control

			self.assertIsNone(access_control._resolve_user_branch("user@example.com"))

	def test_duplicate_user_permission_rows_same_branch_are_treated_as_single_branch(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control._load_access_configuration",
				return_value=_settings(
					True,
					[{"role": "Manufacturing User", "branch": "Nashik", "is_active": 1}],
				),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.defaults.get_user_default",
				return_value=None,
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_all",
				return_value=[
					{"for_value": "Nashik"},
					{"for_value": "Nashik"},
				],
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["Manufacturing User"],
			),
		):
			from production_entry_app.production_entry_app import access_control

			self.assertTrue(access_control.can_use_production_entry_app("user@example.com"))

	def test_load_access_configuration_normalizes_allowed_access_rules(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.access_control.frappe.get_single",
			return_value=_settings_doc(
				True,
				rules=[
					{"role": "Manufacturing User", "branch": "Nashik", "is_active": 1},
					{"role": "Manufacturing Manager", "branch": "Pune", "is_active": 0},
				],
			),
		):
			from production_entry_app.production_entry_app import access_control

			config = access_control._load_access_configuration()
			self.assertTrue(config.enabled)
			self.assertEqual(config.rules, (("Manufacturing User", "Nashik"),))

	def test_has_gated_doctype_permission_uses_real_loader_path(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_single",
				return_value=_settings_doc(
					True,
					rules=[{"role": "Manufacturing User", "branch": "Nashik", "is_active": 1}],
				),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.cache",
				return_value=SimpleNamespace(
					get_value=lambda *_: None, set_value=lambda *args, **kwargs: None
				),
			),
			patch(
				"production_entry_app.production_entry_app.access_control.frappe.get_roles",
				return_value=["Manufacturing User"],
			),
		):
			from production_entry_app.production_entry_app import access_control

			self.assertTrue(
				access_control.has_gated_doctype_permission(
					doc=SimpleNamespace(branch="Nashik"),
					user="user@example.com",
				)
			)

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
