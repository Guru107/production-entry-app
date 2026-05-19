from __future__ import annotations

from production_entry_app.production_entry_app.access_control import ensure_access_roles_and_settings


def before_install() -> None:
	ensure_access_roles_and_settings()
