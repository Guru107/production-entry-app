from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Final

import frappe
from frappe import _

EPHEMERAL_SITE_PREFIXES: Final[tuple[str, ...]] = ("pea-py-", "pea-e2e-")
_VALID_KINDS: Final[frozenset[str]] = frozenset({"py", "e2e"})


def build_site_name(kind: str, run_id: str) -> str:
	if kind not in _VALID_KINDS:
		frappe.throw(_("Unsupported ephemeral site kind: {0}").format(kind))
	clean_run_id = run_id.strip()
	if not clean_run_id:
		frappe.throw(_("Ephemeral site run id is required."))
	return f"pea-{kind}-{clean_run_id}.localhost"


def is_ephemeral_site_name(site_name: str) -> bool:
	return site_name.startswith(EPHEMERAL_SITE_PREFIXES)


def validate_ephemeral_site_name(site_name: str) -> None:
	if is_ephemeral_site_name(site_name):
		return
	frappe.throw(_("Refusing to operate on non-ephemeral site {0}.").format(site_name))


def list_ephemeral_site_directories(sites_root: Path) -> list[Path]:
	if not sites_root.exists():
		return []
	return sorted(
		path for path in sites_root.iterdir() if path.is_dir() and is_ephemeral_site_name(path.name)
	)


def describe_site_directory(site_path: Path, now: datetime | None = None) -> dict[str, object]:
	validate_ephemeral_site_name(site_path.name)
	modified_at = datetime.fromtimestamp(site_path.stat().st_mtime)
	current_time = now or datetime.now()
	age_seconds = max(0, int((current_time - modified_at).total_seconds()))
	return {
		"site_name": site_path.name,
		"path": str(site_path),
		"modified": modified_at.isoformat(timespec="seconds"),
		"age_seconds": age_seconds,
	}


def list_stale_site_descriptions(
	sites_root: Path,
	*,
	minimum_age_seconds: int,
	now: datetime | None = None,
) -> list[dict[str, object]]:
	current_time = now or datetime.now()
	descriptions = [
		describe_site_directory(site_path, now=current_time)
		for site_path in list_ephemeral_site_directories(sites_root)
	]
	return [
		description for description in descriptions if int(description["age_seconds"]) >= minimum_age_seconds
	]


def build_new_site_command(
	site_name: str,
	*,
	db_root_password: str | None = None,
	admin_password: str,
	db_root_username: str = "root",
) -> list[str]:
	validate_ephemeral_site_name(site_name)
	command = [
		"bench",
		"new-site",
		site_name,
		"--db-root-username",
		db_root_username,
	]
	if db_root_password:
		command.extend(["--db-root-password", db_root_password])
	command.extend(["--admin-password", admin_password])
	return command


def build_drop_site_command(
	site_name: str,
	*,
	db_root_password: str | None = None,
	db_root_username: str = "root",
) -> list[str]:
	validate_ephemeral_site_name(site_name)
	command = [
		"bench",
		"drop-site",
		site_name,
		"--force",
		"--no-backup",
		"--db-root-username",
		db_root_username,
	]
	if db_root_password:
		command.extend(["--db-root-password", db_root_password])
	return command
