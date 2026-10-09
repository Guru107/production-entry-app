"""One-shot install migration (pre-model-sync): adopt the host Downtime Reason.

Sites that receive the app via ``bench migrate`` (files deployed without a
fresh ``install-app``) run this patch before schema sync, so the host custom
``Downtime Reason`` DocType — when present in the expected shape — is exported
and reshaped in place before doctype sync ever touches the name. The engine's
state guards make this a no-op when the DocType is absent, already app-owned,
or our own partially-reshaped record.

This patch must never be removed from ``patches.txt`` in later releases: Patch
Log rows must keep matching it for every site that has already run it.
"""

from __future__ import annotations

from production_entry_app.production_entry_app.utils.downtime_reason_adoption import (
	adopt_host_downtime_reason_schema,
)


def execute() -> None:
	adopt_host_downtime_reason_schema()
