from __future__ import annotations

from dataclasses import dataclass
from traceback import format_exc
from typing import Any

import frappe
from frappe import _

SETTINGS_DOCTYPE: str = "Production Entry Settings"
LEGACY_ACCESS_CONTROL_CACHE_KEY: str = "pea:access_control:config"
ACCESS_CONTROL_CACHE_KEY: str = "pea:access_control:config:v2"
ACCESS_CONTROL_CACHE_TTL_SEC: int = 30
SYSTEM_MANAGER_ROLE: str = "System Manager"
DEFAULT_WRITE_ROLE: str = "PEA User"
DEFAULT_READ_ROLE: str = "PEA Read Only"
DEFAULT_REQUIRED_ROLE: str = DEFAULT_WRITE_ROLE
READ_PERMISSION_TYPES: frozenset[str] = frozenset({"read", "select", "print", "email", "export", "report"})


@dataclass(frozen=True)
class AccessConfiguration:
	enabled: bool
	write_role: str
	read_role: str


def invalidate_access_control_cache() -> None:
	cache = frappe.cache()
	cache.delete_value(ACCESS_CONTROL_CACHE_KEY)
	cache.delete_value(LEGACY_ACCESS_CONTROL_CACHE_KEY)


def ensure_access_roles_and_settings() -> None:
	"""Ensure split access roles and migrate legacy singleton settings."""
	_ensure_role(DEFAULT_WRITE_ROLE)
	_ensure_role(DEFAULT_READ_ROLE)
	_migrate_access_settings()
	invalidate_access_control_cache()


def can_use_production_entry_app(user: str | None = None) -> bool:
	"""Return whether the user can write to Production Entry App.

	This remains as a compatibility alias for callers that predate the split read/write role model.
	"""
	return can_write_production_entry_app(user=user)


def can_read_production_entry_app(user: str | None = None) -> bool:
	"""Return whether the user can read Production Entry App surfaces."""
	effective_user = _resolve_user(user)
	try:
		return _can_read(effective_user)
	except Exception:
		_log_access_error("Unable to evaluate Production Entry App access.", effective_user)
		return _is_system_manager(effective_user)


def can_write_production_entry_app(user: str | None = None) -> bool:
	"""Return whether the user can mutate Production Entry App data."""
	effective_user = _resolve_user(user)
	try:
		return _can_write(effective_user)
	except Exception:
		_log_access_error("Unable to evaluate Production Entry App access.", effective_user)
		return _is_system_manager(effective_user)


def has_app_permission() -> bool:
	"""Return whether the current session user can access Production Entry App."""
	return can_read_production_entry_app()


def assert_app_access(
	*, doctype: str | None = None, docname: str | None = None, branch: str | None = None
) -> None:
	"""Compatibility alias for write access checks."""
	assert_app_write_access(doctype=doctype, docname=docname, branch=branch)


def assert_app_read_access(
	*, doctype: str | None = None, docname: str | None = None, branch: str | None = None
) -> None:
	"""Raise if the current session user cannot access Production Entry App.

	Document context is accepted for API compatibility, but access is evaluated by role only.
	"""
	del doctype, docname, branch
	effective_user = _resolve_user(None)
	try:
		if _can_read(effective_user):
			return
	except Exception:
		_log_access_error("Unable to evaluate Production Entry App access.", effective_user)
		if _is_system_manager(effective_user):
			return
	frappe.throw(_("You do not have access to Production Entry App."), frappe.PermissionError)


def assert_app_write_access(
	*, doctype: str | None = None, docname: str | None = None, branch: str | None = None
) -> None:
	"""Raise if the current session user cannot write to Production Entry App."""
	del doctype, docname, branch
	effective_user = _resolve_user(None)
	try:
		if _can_write(effective_user):
			return
	except Exception:
		_log_access_error("Unable to evaluate Production Entry App write access.", effective_user)
		if _is_system_manager(effective_user):
			return
	frappe.throw(_("You do not have write access to Production Entry App."), frappe.PermissionError)


def has_gated_doctype_permission(doc: Any = None, ptype: str = "read", user: str | None = None) -> bool:
	"""Return whether a gated document or doctype action is allowed."""
	del doc
	effective_user = _resolve_user(user)
	try:
		if ptype in READ_PERMISSION_TYPES:
			return _can_read(effective_user)
		return _can_write(effective_user)
	except Exception:
		_log_access_error("Unable to evaluate gated doctype access.", effective_user)
		return _is_system_manager(effective_user)


def _can_read(user: str, branch: str | None = None) -> bool:
	del branch
	config = _get_access_configuration()
	if _is_system_manager(user):
		return True
	if not config.enabled:
		return True
	roles = set(frappe.get_roles(user))
	if config.write_role and config.write_role in roles:
		return True
	if not config.read_role:
		return False
	return config.read_role in roles


def _can_write(user: str, branch: str | None = None) -> bool:
	del branch
	config = _get_access_configuration()
	if _is_system_manager(user):
		return True
	if not config.enabled:
		return True
	if not config.write_role:
		return False
	return config.write_role in set(frappe.get_roles(user))


def _get_access_configuration() -> AccessConfiguration:
	cache = frappe.cache()
	cached = cache.get_value(ACCESS_CONTROL_CACHE_KEY)
	if cached is not None:
		return _normalize_access_configuration(cached)

	config = _load_access_configuration()
	config = _normalize_access_configuration(config)
	cache.set_value(
		ACCESS_CONTROL_CACHE_KEY,
		{"enabled": config.enabled, "write_role": config.write_role, "read_role": config.read_role},
		expires_in_sec=ACCESS_CONTROL_CACHE_TTL_SEC,
	)
	return config


def _ensure_role(role_name: str) -> None:
	if frappe.db.exists("Role", role_name):
		return

	frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert()


def _migrate_access_settings() -> None:
	if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
		return

	write_role = _get_single_value("write_role")
	read_role = _get_single_value("read_role")
	if not str(write_role or "").strip():
		legacy_required_role = _get_single_value("required_role")
		frappe.db.set_single_value(
			SETTINGS_DOCTYPE,
			"write_role",
			str(legacy_required_role or DEFAULT_WRITE_ROLE).strip(),
		)
	if not str(read_role or "").strip():
		frappe.db.set_single_value(SETTINGS_DOCTYPE, "read_role", DEFAULT_READ_ROLE)


def _get_single_value(fieldname: str) -> str | None:
	return frappe.db.get_value(
		"Singles",
		{"doctype": SETTINGS_DOCTYPE, "field": fieldname},
		"value",
	)


def _load_access_configuration() -> AccessConfiguration:
	settings = frappe.get_single(SETTINGS_DOCTYPE)
	if settings is None:
		raise ValueError(f"{SETTINGS_DOCTYPE} is missing.")

	enabled = bool(_get_field_value(settings, "enable_access_control", default=False))
	raw_write_role = _get_field_value(settings, "write_role", default=None)
	write_role = _normalize_role(raw_write_role, DEFAULT_WRITE_ROLE)
	read_role = _normalize_role(_get_field_value(settings, "read_role", default=None), DEFAULT_READ_ROLE)
	if raw_write_role is None:
		write_role = _normalize_role(
			_get_field_value(settings, "required_role", default=DEFAULT_WRITE_ROLE), DEFAULT_WRITE_ROLE
		)
	return AccessConfiguration(enabled=enabled, write_role=write_role, read_role=read_role)


def _normalize_access_configuration(value: Any) -> AccessConfiguration:
	if isinstance(value, AccessConfiguration):
		return value
	if not isinstance(value, dict):
		enabled = _get_field_value(value, "enabled", default=None)
		write_role = _get_field_value(value, "write_role", default=None)
		read_role = _get_field_value(value, "read_role", default=None)
		required_role = _get_field_value(value, "required_role", default=None)
		if enabled is None and write_role is None and read_role is None and required_role is None:
			enabled = _get_field_value(value, "enable_access_control", default=None)
			write_role = _get_field_value(value, "write_role", default=None)
			read_role = _get_field_value(value, "read_role", default=None)
			required_role = _get_field_value(value, "required_role", default=None)
		if enabled is None and write_role is None and read_role is None and required_role is None:
			raise ValueError("Access configuration is corrupt.")
		return _normalize_access_configuration(
			{
				"enabled": enabled,
				"write_role": write_role,
				"read_role": read_role,
				"required_role": required_role,
			}
		)

	enabled = bool(value.get("enabled", value.get("enable_access_control", False)))
	write_role = _normalize_role(value.get("write_role", value.get("required_role")), DEFAULT_WRITE_ROLE)
	read_role = _normalize_role(value.get("read_role"), DEFAULT_READ_ROLE)
	return AccessConfiguration(enabled=enabled, write_role=write_role, read_role=read_role)


def _resolve_user(user: str | None) -> str:
	return user or frappe.session.user


def _normalize_role(role: Any, default: str) -> str:
	if role is None:
		return default
	return str(role).strip()


def _is_system_manager(user: str) -> bool:
	return SYSTEM_MANAGER_ROLE in frappe.get_roles(user)


def _get_field_value(value: Any, fieldname: str, default: Any = None) -> Any:
	if value is None:
		return default
	if isinstance(value, dict):
		return value.get(fieldname, default)
	return getattr(value, fieldname, default)


def _log_access_error(message: str, user: str) -> None:
	frappe.log_error(
		title="Production Entry access control error",
		message=f"{message}\nUser: {user}\n{format_exc()}",
	)
