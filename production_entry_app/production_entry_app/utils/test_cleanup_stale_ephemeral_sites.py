from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase


def _load_cleanup_script_module() -> ModuleType:
	script_path = Path(__file__).resolve().parents[3] / "scripts" / "cleanup_stale_ephemeral_sites.py"
	spec = importlib.util.spec_from_file_location(
		"production_entry_app_cleanup_stale_ephemeral_sites", script_path
	)
	if not spec or not spec.loader:
		raise RuntimeError(f"Unable to load cleanup script module from {script_path}")
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


cleanup_stale_ephemeral_sites: ModuleType = _load_cleanup_script_module()


class TestCleanupStaleEphemeralSites(FrappeTestCase):
	def test_delete_invokes_bench_drop_site_for_requested_ephemeral_site(self) -> None:
		with TemporaryDirectory() as tmpdir:
			sites_root = Path(tmpdir) / "sites"
			sites_root.mkdir()
			site_name = "pea-e2e-stale.localhost"
			(sites_root / site_name).mkdir()
			bench_root = Path(tmpdir) / "bench"
			bench_root.mkdir()
			stdout = io.StringIO()

			with (
				patch.object(
					cleanup_stale_ephemeral_sites,
					"BENCH_ROOT",
					bench_root,
				),
				patch.object(
					cleanup_stale_ephemeral_sites.sys,
					"argv",
					[
						"cleanup_stale_ephemeral_sites.py",
						"--sites-root",
						str(sites_root),
						"--delete",
						site_name,
					],
				),
				patch.dict(
					cleanup_stale_ephemeral_sites.os.environ,
					{"DB_ROOT_USERNAME": "root", "DB_ROOT_PASSWORD": "secret"},
					clear=False,
				),
				patch.object(cleanup_stale_ephemeral_sites.subprocess, "run") as run_mock,
				patch("sys.stdout", stdout),
			):
				exit_code = cleanup_stale_ephemeral_sites.main()

		self.assertEqual(exit_code, 0)
		run_mock.assert_called_once_with(
			[
				"bench",
				"drop-site",
				site_name,
				"--force",
				"--no-backup",
				"--db-root-username",
				"root",
				"--db-root-password",
				"secret",
			],
			check=True,
			cwd=bench_root,
		)
		self.assertIn(f"Deleted {site_name}", stdout.getvalue())

	def test_delete_returns_nonzero_when_requested_site_directory_is_missing(self) -> None:
		with TemporaryDirectory() as tmpdir:
			sites_root = Path(tmpdir) / "sites"
			sites_root.mkdir()
			stdout = io.StringIO()

			with (
				patch.object(
					cleanup_stale_ephemeral_sites.sys,
					"argv",
					[
						"cleanup_stale_ephemeral_sites.py",
						"--sites-root",
						str(sites_root),
						"--delete",
						"pea-e2e-missing.localhost",
					],
				),
				patch("sys.stdout", stdout),
			):
				exit_code = cleanup_stale_ephemeral_sites.main()

		self.assertEqual(exit_code, 1)
		self.assertIn("No site directory found", stdout.getvalue())
