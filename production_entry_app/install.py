"""Install lifecycle for Production Entry App.

``before_install`` runs the guarded in-place adoption of the host custom
Downtime Reason DocType (recovery export + reshape) so doctype sync proceeds
under the same DocType name without collision. ``after_install`` runs after
doctype sync: seed/convert + verification, then the legacy cutover engine
(script disable → hide).

A failure mid-``after_install`` is recoverable by re-invoking the same entry
points via ``bench --site <site> execute`` — every step guards on current
state, so the re-run converges without Patch Log surgery or a reinstall.
"""

from __future__ import annotations

from production_entry_app.production_entry_app.utils.downtime_reason_adoption import (
	adopt_host_downtime_reason_schema,
	convert_host_downtime_reasons,
)
from production_entry_app.production_entry_app.utils.legacy_time_cutover import (
	execute_legacy_time_cutover,
)


def before_install() -> None:
	adopt_host_downtime_reason_schema()


def after_install() -> None:
	convert_host_downtime_reasons()
	execute_legacy_time_cutover()
