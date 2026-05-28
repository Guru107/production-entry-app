from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from traceback import format_exc
from typing import Any

import frappe
from frappe import _

SETTINGS_DOCTYPE: str = "Production Entry Settings"
LEGACY_ACCESS_CONTROL_CACHE_KEY: str = "pea:access_control:config"
ACCESS_CONTROL_CACHE_KEY: str = "pea:access_control:config:v2"
ACCESS_CONTROL_CACHE_TTL_SEC: int = 30
APP_ROOT: Path = Path(__file__).parent
SYSTEM_MANAGER_ROLE: str = "System Manager"
DEFAULT_WRITE_ROLE: str = "PEA User"
DEFAULT_READ_ROLE: str = "PEA Read Only"
DEFAULT_REQUIRED_ROLE: str = DEFAULT_WRITE_ROLE
READ_PERMISSION_TYPES: frozenset[str] = frozenset({"read", "select", "print", "email", "export", "report"})
GATED_DOCTYPES: tuple[str, ...] = (
	"Shift",
	"Loss Entry",
	"Operator",
	"Die Tool Counter",
	"Die Tool Maintenance Log",
	"Rejection Reason",
	"Rejection Breakup",
)
DOCPERM_FIELDS: tuple[str, ...] = (
	"select",
	"read",
	"write",
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"report",
	"export",
	"import",
	"share",
	"print",
	"email",
	"if_owner",
)


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
	sync_configured_access_roles()


def sync_configured_access_roles(
	*, write_role: str | None = None, read_role: str | None = None, managed_roles: tuple[str | None, ...] = ()
) -> None:
	"""Sync native permissions and report metadata for the configured access roles."""
	effective_write_role, effective_read_role = _get_setup_access_roles()
	if write_role is not None:
		effective_write_role = _normalize_role(write_role, DEFAULT_WRITE_ROLE)
	if read_role is not None:
		effective_read_role = _normalize_role(read_role, DEFAULT_READ_ROLE)
	for role in _unique_roles(effective_write_role, effective_read_role):
		if role not in (DEFAULT_WRITE_ROLE, DEFAULT_READ_ROLE):
			_ensure_role(role)
	managed_roles = _unique_roles(
		*_get_app_managed_access_roles(), *(_clean_role(role) for role in managed_roles)
	)
	_sync_native_doctype_permissions(
		write_role=effective_write_role,
		read_role=effective_read_role,
		managed_roles=managed_roles,
	)
	_migrate_report_access_metadata(write_role=effective_write_role, read_role=effective_read_role)
	_remember_synced_access_roles(write_role=effective_write_role, read_role=effective_read_role)
	invalidate_access_control_cache()
	frappe.clear_cache()


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
		# This disables only PEA's app-level gates; native Frappe DocPerm and Report roles still apply.
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
		# This disables only PEA's app-level gates; native Frappe DocPerm and Report roles still apply.
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
			str(legacy_required_role or "").strip() or DEFAULT_WRITE_ROLE,
		)
	if not str(read_role or "").strip():
		frappe.db.set_single_value(SETTINGS_DOCTYPE, "read_role", DEFAULT_READ_ROLE)


def _get_setup_access_roles() -> tuple[str, str]:
	if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
		return DEFAULT_WRITE_ROLE, DEFAULT_READ_ROLE

	write_role = _normalize_role(_get_single_value("write_role"), DEFAULT_WRITE_ROLE)
	read_role = _normalize_role(_get_single_value("read_role"), DEFAULT_READ_ROLE)
	return write_role, read_role


def _sync_native_doctype_permissions(
	*, write_role: str, read_role: str, managed_roles: tuple[str, ...] | None = None
) -> None:
	if not frappe.db.exists("DocType", "DocPerm"):
		return

	active_roles = _unique_roles(SYSTEM_MANAGER_ROLE, write_role, read_role)
	cleanup_roles = tuple(role for role in (managed_roles or ()) if role not in active_roles)
	for doctype in GATED_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		write_template = _get_docperm_template(doctype, DEFAULT_WRITE_ROLE)
		read_template = _get_docperm_template(doctype, DEFAULT_READ_ROLE)
		_remove_stale_docperms(
			doctype=doctype,
			candidate_roles=cleanup_roles,
			templates=tuple(template for template in (write_template, read_template) if template),
		)
		if write_template:
			_sync_docperm(doctype=doctype, role=write_role, template=write_template)
		if read_template and read_role != write_role:
			_sync_docperm(doctype=doctype, role=read_role, template=read_template)
		frappe.clear_cache(doctype=doctype)


def _get_docperm_template(doctype: str, role: str) -> dict[str, int] | None:
	doctype_path = APP_ROOT / "doctype" / frappe.scrub(doctype) / f"{frappe.scrub(doctype)}.json"
	doctype_schema = json.loads(doctype_path.read_text())
	for permission in doctype_schema.get("permissions", []):
		if permission.get("role") == role and int(permission.get("permlevel") or 0) == 0:
			return {field: int(permission.get(field) or 0) for field in ("permlevel", *DOCPERM_FIELDS)}
	return None


def _sync_docperm(*, doctype: str, role: str, template: dict[str, int]) -> None:
	values = {field: int(template.get(field) or 0) for field in DOCPERM_FIELDS}
	values["permlevel"] = int(template.get("permlevel") or 0)
	existing_name = frappe.db.exists(
		"DocPerm",
		{
			"parent": doctype,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": role,
			"permlevel": values["permlevel"],
		},
	)
	if existing_name:
		frappe.db.set_value("DocPerm", existing_name, values, update_modified=False)
		return

	frappe.get_doc(
		{
			"doctype": "DocPerm",
			"parent": doctype,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": role,
			"idx": _get_next_docperm_idx(doctype),
			**values,
		}
	).insert(ignore_permissions=True)


def _remove_stale_docperms(
	*, doctype: str, candidate_roles: tuple[str, ...], templates: tuple[dict[str, int], ...]
) -> None:
	if not candidate_roles or not templates:
		return

	rows = frappe.get_all(
		"DocPerm",
		filters={"parent": doctype, "parenttype": "DocType", "parentfield": "permissions"},
		fields=["name", "role", "permlevel", *DOCPERM_FIELDS],
	)
	stale_names = [
		row["name"]
		for row in rows
		if row.get("role") in candidate_roles and _matches_any_docperm_template(row, templates)
	]
	for name in stale_names:
		frappe.delete_doc("DocPerm", name, ignore_permissions=True, force=True)


def _matches_any_docperm_template(row: dict[str, Any], templates: tuple[dict[str, int], ...]) -> bool:
	return any(_matches_docperm_template(row, template) for template in templates)


def _matches_docperm_template(row: dict[str, Any], template: dict[str, int]) -> bool:
	return all(
		int(row.get(field) or 0) == int(template.get(field) or 0) for field in ("permlevel", *DOCPERM_FIELDS)
	)


def _get_next_docperm_idx(doctype: str) -> int:
	rows = frappe.get_all(
		"DocPerm",
		filters={"parent": doctype, "parenttype": "DocType"},
		fields=["idx"],
		order_by="idx desc",
		limit=1,
	)
	if not rows:
		return 1
	return int(rows[0].get("idx") or 0) + 1


def _get_existing_report_access_roles() -> tuple[str, ...]:
	if not frappe.db.exists("DocType", "Report"):
		return ()

	roles: list[str] = []
	for report_name in frappe.get_all("Report", filters={"module": "Production Entry App"}, pluck="name"):
		report = frappe.get_doc("Report", report_name)
		roles.extend(row.role for row in report.get("roles") if row.role)
	return _unique_roles(*roles)


def _get_app_managed_access_roles() -> tuple[str, ...]:
	return _unique_roles(
		DEFAULT_WRITE_ROLE,
		DEFAULT_READ_ROLE,
		_clean_role(_get_single_value("required_role")),
		_clean_role(_get_single_value("last_synced_write_role")),
		_clean_role(_get_single_value("last_synced_read_role")),
	)


def _clean_role(role: str | None) -> str | None:
	cleaned = str(role or "").strip()
	return cleaned or None


def _remember_synced_access_roles(*, write_role: str, read_role: str) -> None:
	if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
		return
	frappe.db.set_single_value(SETTINGS_DOCTYPE, "last_synced_write_role", write_role)
	frappe.db.set_single_value(SETTINGS_DOCTYPE, "last_synced_read_role", read_role)


def _migrate_report_access_metadata(*, write_role: str, read_role: str) -> None:
	if not frappe.db.exists("DocType", "Report"):
		return

	report_roles = _unique_roles(SYSTEM_MANAGER_ROLE, write_role, read_role)
	for report_name in frappe.get_all("Report", filters={"module": "Production Entry App"}, pluck="name"):
		# Avoid Report.validate() path for standard reports in non-developer mode.
		frappe.db.set_value("Report", report_name, "ref_doctype", "Shift", update_modified=False)
		frappe.db.delete(
			"Has Role",
			{
				"parenttype": "Report",
				"parentfield": "roles",
				"parent": report_name,
			},
		)
		for role in report_roles:
			frappe.get_doc(
				{
					"doctype": "Has Role",
					"parenttype": "Report",
					"parentfield": "roles",
					"parent": report_name,
					"role": role,
				}
			).insert(ignore_permissions=True)


def _get_single_value(fieldname: str) -> str | None:
	return frappe.db.get_value(
		"Singles",
		{"doctype": SETTINGS_DOCTYPE, "field": fieldname},
		"value",
		order_by=None,
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


def _unique_roles(*roles: str) -> tuple[str, ...]:
	return tuple(dict.fromkeys(role for role in roles if role))


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
