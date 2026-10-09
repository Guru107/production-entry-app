"""One-shot install migration (post-model-sync): convert Downtime Reasons and retire the legacy time UI.

Runs after schema sync on the ``bench migrate`` path: seed the standard codes,
convert legacy-named masters to code identities with link rewrites, verify the
result against the pre-adoption export, then apply the ordered legacy cutover
(script disable → hide). Every step guards on current state, so a rerun after
a partial failure converges, and a failed patch (never logged) simply reruns
on the next migrate. The same entry points are recoverable directly via
``bench --site <site> execute``.

This patch must never be removed from ``patches.txt`` in later releases: Patch
Log rows must keep matching it for every site that has already run it.
"""

from __future__ import annotations

from production_entry_app.production_entry_app.utils.downtime_reason_adoption import (
	convert_host_downtime_reasons,
)
from production_entry_app.production_entry_app.utils.legacy_time_cutover import (
	execute_legacy_time_cutover,
)


def execute() -> None:
	convert_host_downtime_reasons()
	execute_legacy_time_cutover()
