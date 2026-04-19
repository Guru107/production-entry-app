from __future__ import annotations

from dataclasses import dataclass
from traceback import format_exc
from typing import Any

import frappe
from frappe import _

SETTINGS_DOCTYPE: str = "Production Entry Settings"
ACCESS_CONTROL_CACHE_KEY: str = "pea:access_control:config"
USER_BRANCH_CACHE_KEY_PREFIX: str = "pea:access_control:branch:"
ACCESS_CONTROL_CACHE_TTL_SEC: int = 30
SYSTEM_MANAGER_ROLE: str = "System Manager"
BRANCH_DOCTYPE: str = "Branch"
USER_PERMISSION_DOCTYPE: str = "User Permission"


@dataclass(frozen=True)
class AccessConfiguration:
	enabled: bool
	rules: tuple[tuple[str, str], ...]


def invalidate_access_control_cache() -> None:
	frappe.cache().delete_value(ACCESS_CONTROL_CACHE_KEY)


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

	When document context is provided, evaluate access against the target document branch
	instead of the user's default branch. If the target document has no branch field,
	fall back to role-only access evaluation.
	"""
	effective_user = _resolve_user(None)
	if doctype or docname or branch:
		target_branch = branch
		if target_branch is None and doctype and docname:
			target_branch = _get_document_branch(doctype, docname)
		if target_branch is not None:
			if _can_access(effective_user, branch=target_branch):
				return
		elif _has_allowed_role(effective_user):
			return
		frappe.throw(_("You do not have access to Production Entry App."), frappe.PermissionError)
	if has_app_permission():
		return
	frappe.throw(_("You do not have access to Production Entry App."), frappe.PermissionError)


def has_gated_doctype_permission(doc: Any = None, ptype: str = "read", user: str | None = None) -> bool:
	"""Return whether a gated document or doctype action is allowed."""
	del ptype
	effective_user = _resolve_user(user)
	try:
		doc_branch = _extract_branch(doc)
		return _can_access(effective_user, branch=doc_branch)
	except Exception:
		_log_access_error("Unable to evaluate gated doctype access.", effective_user)
		return _is_system_manager(effective_user)


def _can_access(user: str, branch: str | None = None) -> bool:
	config = _get_access_configuration()
	if _is_system_manager(user):
		return True
	if not config.enabled:
		return True

	effective_branch = branch or _resolve_user_branch(user)
	if not effective_branch:
		return False

	user_roles = set(frappe.get_roles(user))
	for role, allowed_branch in config.rules:
		if allowed_branch == effective_branch and role in user_roles:
			return True
	return False


def _has_allowed_role(user: str) -> bool:
	config = _get_access_configuration()
	if _is_system_manager(user):
		return True
	if not config.enabled:
		return True

	user_roles = set(frappe.get_roles(user))
	for role, allowed_branch in config.rules:
		del allowed_branch
		if role in user_roles:
			return True
	return False


def _get_access_configuration() -> AccessConfiguration:
	cache = frappe.cache()
	cached = cache.get_value(ACCESS_CONTROL_CACHE_KEY)
	if cached is not None:
		return _normalize_access_configuration(cached)

	config = _load_access_configuration()
	config = _normalize_access_configuration(config)
	cache.set_value(
		ACCESS_CONTROL_CACHE_KEY,
		{"enabled": config.enabled, "rules": list(config.rules)},
		expires_in_sec=ACCESS_CONTROL_CACHE_TTL_SEC,
	)
	return config


def _load_access_configuration() -> AccessConfiguration:
	settings = frappe.get_single(SETTINGS_DOCTYPE)
	if settings is None:
		raise ValueError(f"{SETTINGS_DOCTYPE} is missing.")

	enabled = bool(_get_field_value(settings, "enable_access_control", default=False))
	raw_rules = _get_field_value(settings, "allowed_access_rules", default=())
	if raw_rules is None:
		raw_rules = ()
	if not isinstance(raw_rules, list | tuple):
		raise ValueError(f"{SETTINGS_DOCTYPE} access_rules is corrupt.")

	rules: list[tuple[str, str]] = []
	for row in raw_rules:
		role = _get_field_value(row, "role")
		branch = _get_field_value(row, "branch")
		is_active = _get_field_value(row, "is_active", default=1)
		if role is None or branch is None:
			raise ValueError(f"{SETTINGS_DOCTYPE} access rule is corrupt.")
		if not bool(is_active):
			continue
		rules.append((str(role), str(branch)))

	return AccessConfiguration(enabled=enabled, rules=tuple(rules))


def _normalize_access_configuration(value: Any) -> AccessConfiguration:
	if isinstance(value, AccessConfiguration):
		return value
	if not isinstance(value, dict):
		enabled = _get_field_value(value, "enabled", default=None)
		rules = _get_field_value(value, "rules", default=None)
		if enabled is None and rules is None:
			enabled = _get_field_value(value, "enable_access_control", default=None)
			rules = _get_field_value(value, "allowed_access_rules", default=None)
		if enabled is None and rules is None:
			raise ValueError("Access configuration is corrupt.")
		return _normalize_access_configuration(
			{"enabled": enabled, "rules": rules if rules is not None else ()}
		)

	enabled = bool(value.get("enabled", False))
	raw_rules = value.get("rules", ())
	if not isinstance(raw_rules, list | tuple):
		raise ValueError("Cached access configuration is corrupt.")

	rules: list[tuple[str, str]] = []
	for rule in raw_rules:
		if isinstance(rule, dict):
			role = rule.get("role")
			branch = rule.get("branch")
		elif isinstance(rule, list | tuple) and len(rule) == 2:
			role, branch = rule
		else:
			raise ValueError("Cached access configuration is corrupt.")
		if role is None or branch is None:
			raise ValueError("Cached access configuration is corrupt.")
		rules.append((str(role), str(branch)))
	return AccessConfiguration(enabled=enabled, rules=tuple(rules))


def _resolve_user_branch(user: str) -> str | None:
	cache_key = f"{USER_BRANCH_CACHE_KEY_PREFIX}{user}"
	cache = frappe.cache()
	cached_branch = cache.get_value(cache_key)
	if cached_branch is not None:
		return cached_branch or None

	branch = _get_user_default_branch(user)
	if not branch:
		branch_permissions = _get_user_branch_permissions(user)
		if len(branch_permissions) == 1:
			branch = branch_permissions[0]

	cache.set_value(cache_key, branch or "", expires_in_sec=ACCESS_CONTROL_CACHE_TTL_SEC)
	return branch or None


def _get_user_default_branch(user: str) -> str | None:
	for key in ("Branch", "branch"):
		default_branch = frappe.defaults.get_user_default(key, user=user)
		if default_branch:
			return str(default_branch)
	return None


def _get_user_branch_permissions(user: str) -> list[str]:
	permissions = frappe.get_all(
		USER_PERMISSION_DOCTYPE,
		filters={"user": user, "allow": BRANCH_DOCTYPE},
		pluck="for_value",
	)
	branches: list[str] = []
	seen: set[str] = set()
	for permission in permissions:
		branch = _get_field_value(permission, "for_value", default=permission)
		if branch:
			branch_name = str(branch)
			if branch_name in seen:
				continue
			seen.add(branch_name)
			branches.append(branch_name)
	return branches


def _extract_branch(doc: Any) -> str | None:
	if doc is None:
		return None
	if isinstance(doc, dict):
		branch = doc.get("branch")
		return str(branch) if branch else None
	branch = getattr(doc, "branch", None)
	return str(branch) if branch else None


def _get_document_branch(doctype: str, docname: str) -> str | None:
	if not frappe.db.has_column(doctype, "branch"):
		return None

	branch = frappe.db.get_value(doctype, docname, "branch")
	return str(branch) if branch else None


def _resolve_user(user: str | None) -> str:
	return user or frappe.session.user


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
