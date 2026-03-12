from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
BENCH_ROOT = Path(__file__).resolve().parents[3]
for import_root in (APP_ROOT, BENCH_ROOT / "apps" / "frappe"):
	if str(import_root) not in sys.path:
		sys.path.insert(0, str(import_root))

from production_entry_app.production_entry_app.utils import ephemeral_test_site


def _default_sites_root() -> Path:
	return Path(__file__).resolve().parents[3] / "sites"


def _delete_site(site_name: str, *, sites_root: Path) -> int:
	ephemeral_test_site.validate_ephemeral_site_name(site_name)
	site_path = sites_root / site_name
	if not site_path.exists():
		print(f"No site directory found for {site_name} under {sites_root}")
		return 1

	command = ephemeral_test_site.build_drop_site_command(
		site_name,
		db_root_username=os.environ.get("DB_ROOT_USERNAME", "root"),
		db_root_password=os.environ.get("DB_ROOT_PASSWORD"),
	)
	subprocess.run(command, check=True, cwd=BENCH_ROOT)
	print(f"Deleted {site_name}")
	return 0


def main() -> int:
	parser = argparse.ArgumentParser(description="List or delete stale ephemeral Frappe test sites.")
	parser.add_argument("--sites-root", type=Path, default=_default_sites_root())
	parser.add_argument("--min-age-seconds", type=int, default=3600)
	parser.add_argument("--delete", dest="site_to_delete")
	args = parser.parse_args()

	if args.site_to_delete:
		return _delete_site(args.site_to_delete, sites_root=args.sites_root)

	for description in ephemeral_test_site.list_stale_site_descriptions(
		args.sites_root,
		minimum_age_seconds=args.min_age_seconds,
	):
		print(
			f"{description['site_name']}\tage={description['age_seconds']}s\t"
			f"modified={description['modified']}\tpath={description['path']}"
		)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
