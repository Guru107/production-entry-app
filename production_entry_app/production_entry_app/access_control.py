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
DEFAULT_REQUIRED_ROLE: str = "PEA User"


@dataclass(frozen=True)
class AccessConfiguration:
	enabled: bool
	required_role: str


def invalidate_access_control_cache() -> None:
	cache = frappe.cache()
	cache.delete_value(ACCESS_CONTROL_CACHE_KEY)
	cache.delete_value(LEGACY_ACCESS_CONTROL_CACHE_KEY)


def can_use_production_entry_app(user: str | None = None) -> bool:
	"""Return whether the user can access Production Entry App."""
	effective_user = _resolve_user(user)
	try:
		return _can_access(effective_user)
	except Exception:
		_log_access_error("Unable to evaluate Production Entry App access.", effective_user)
		return _is_system_manager(effective_user)


def has_app_permission() -> bool:
	"""Return whether the current session user can access Production Entry App."""
	return can_use_production_entry_app()


def assert_app_access(
	*, doctype: str | None = None, docname: str | None = None, branch: str | None = None
) -> None:
	"""Raise if the current session user cannot access Production Entry App.

	Document context is accepted for API compatibility, but access is evaluated by role only.
	"""
	del doctype, docname, branch
	effective_user = _resolve_user(None)
	try:
		if _can_access(effective_user):
			return
	except Exception:
		_log_access_error("Unable to evaluate Production Entry App access.", effective_user)
		if _is_system_manager(effective_user):
			return
	frappe.throw(_("You do not have access to Production Entry App."), frappe.PermissionError)


def has_gated_doctype_permission(doc: Any = None, ptype: str = "read", user: str | None = None) -> bool:
	"""Return whether a gated document or doctype action is allowed."""
	del doc, ptype
	effective_user = _resolve_user(user)
	try:
		return _can_access(effective_user)
	except Exception:
		_log_access_error("Unable to evaluate gated doctype access.", effective_user)
		return _is_system_manager(effective_user)


def _can_access(user: str, branch: str | None = None) -> bool:
	del branch
	config = _get_access_configuration()
	if _is_system_manager(user):
		return True
	if not config.enabled:
		return True
	if not config.required_role:
		return False
	return config.required_role in set(frappe.get_roles(user))


def _get_access_configuration() -> AccessConfiguration:
	cache = frappe.cache()
	cached = cache.get_value(ACCESS_CONTROL_CACHE_KEY)
	if cached is not None:
		return _normalize_access_configuration(cached)

	config = _load_access_configuration()
	config = _normalize_access_configuration(config)
	cache.set_value(
		ACCESS_CONTROL_CACHE_KEY,
		{"enabled": config.enabled, "required_role": config.required_role},
		expires_in_sec=ACCESS_CONTROL_CACHE_TTL_SEC,
	)
	return config


def _load_access_configuration() -> AccessConfiguration:
	settings = frappe.get_single(SETTINGS_DOCTYPE)
	if settings is None:
		raise ValueError(f"{SETTINGS_DOCTYPE} is missing.")

	enabled = bool(_get_field_value(settings, "enable_access_control", default=False))
	required_role = _normalize_required_role(
		_get_field_value(settings, "required_role", default=DEFAULT_REQUIRED_ROLE)
	)
	return AccessConfiguration(enabled=enabled, required_role=required_role)


def _normalize_access_configuration(value: Any) -> AccessConfiguration:
	if isinstance(value, AccessConfiguration):
		return value
	if not isinstance(value, dict):
		enabled = _get_field_value(value, "enabled", default=None)
		required_role = _get_field_value(value, "required_role", default=None)
		if enabled is None and required_role is None:
			enabled = _get_field_value(value, "enable_access_control", default=None)
			required_role = _get_field_value(value, "required_role", default=DEFAULT_REQUIRED_ROLE)
		if enabled is None and required_role is None:
			raise ValueError("Access configuration is corrupt.")
		return _normalize_access_configuration({"enabled": enabled, "required_role": required_role})

	enabled = bool(value.get("enabled", value.get("enable_access_control", False)))
	required_role = _normalize_required_role(value.get("required_role", DEFAULT_REQUIRED_ROLE))
	return AccessConfiguration(enabled=enabled, required_role=required_role)


def _resolve_user(user: str | None) -> str:
	return user or frappe.session.user


def _normalize_required_role(required_role: Any) -> str:
	if required_role is None:
		return DEFAULT_REQUIRED_ROLE
	return str(required_role).strip()


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
