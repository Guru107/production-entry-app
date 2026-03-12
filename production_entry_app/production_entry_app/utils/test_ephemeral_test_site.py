from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.utils import ephemeral_test_site


class TestEphemeralTestSite(FrappeTestCase):
	def test_build_site_name_uses_expected_prefix_and_run_id(self) -> None:
		self.assertEqual(
			ephemeral_test_site.build_site_name("py", "abc123"),
			"pea-py-abc123.localhost",
		)
		self.assertEqual(
			ephemeral_test_site.build_site_name("e2e", "run-9"),
			"pea-e2e-run-9.localhost",
		)

	def test_validate_ephemeral_site_accepts_allowed_prefixes_only(self) -> None:
		self.assertIsNone(ephemeral_test_site.validate_ephemeral_site_name("pea-e2e-42.localhost"))
		self.assertIsNone(ephemeral_test_site.validate_ephemeral_site_name("pea-py-42.localhost"))

	def test_validate_ephemeral_site_rejects_non_ephemeral_names(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			ephemeral_test_site.validate_ephemeral_site_name("development.localhost")

	def test_list_ephemeral_site_directories_filters_known_prefixes(self) -> None:
		with TemporaryDirectory() as tmpdir:
			root = Path(tmpdir)
			(root / "pea-py-1.localhost").mkdir()
			(root / "pea-e2e-2.localhost").mkdir()
			(root / "assets").mkdir()
			(root / "development.localhost").mkdir()

			self.assertEqual(
				[path.name for path in ephemeral_test_site.list_ephemeral_site_directories(root)],
				["pea-e2e-2.localhost", "pea-py-1.localhost"],
			)

	def test_describe_site_directory_includes_age_and_modified_timestamp(self) -> None:
		with TemporaryDirectory() as tmpdir:
			site_path = Path(tmpdir) / "pea-py-1.localhost"
			site_path.mkdir()

			description = ephemeral_test_site.describe_site_directory(
				site_path,
				now=datetime.fromtimestamp(site_path.stat().st_mtime + 120),
			)

		self.assertEqual(description["site_name"], "pea-py-1.localhost")
		self.assertEqual(description["path"], str(site_path))
		self.assertEqual(description["age_seconds"], 120)
		self.assertRegex(description["modified"], r"^\d{4}-\d{2}-\d{2}T")

	def test_list_stale_site_descriptions_filters_by_minimum_age(self) -> None:
		with TemporaryDirectory() as tmpdir:
			root = Path(tmpdir)
			old_path = root / "pea-py-old.localhost"
			fresh_path = root / "pea-e2e-fresh.localhost"
			old_path.mkdir()
			fresh_path.mkdir()
			base_timestamp = old_path.stat().st_mtime
			os.utime(old_path, (base_timestamp - 600, base_timestamp - 600))
			os.utime(fresh_path, (base_timestamp - 30, base_timestamp - 30))
			now = datetime.fromtimestamp(base_timestamp)

			old_descriptions = ephemeral_test_site.list_stale_site_descriptions(
				root,
				minimum_age_seconds=300,
				now=now,
			)

		self.assertEqual([item["site_name"] for item in old_descriptions], ["pea-py-old.localhost"])

	def test_build_new_site_command_uses_expected_root_and_admin_flags(self) -> None:
		self.assertEqual(
			ephemeral_test_site.build_new_site_command(
				"pea-py-abc.localhost",
				db_root_password="root",
				admin_password="admin",
			),
			[
				"bench",
				"new-site",
				"pea-py-abc.localhost",
				"--db-root-username",
				"root",
				"--db-root-password",
				"root",
				"--admin-password",
				"admin",
			],
		)

	def test_build_drop_site_command_enables_force_and_no_backup(self) -> None:
		self.assertEqual(
			ephemeral_test_site.build_drop_site_command(
				"pea-e2e-abc.localhost",
				db_root_password="root",
			),
			[
				"bench",
				"drop-site",
				"pea-e2e-abc.localhost",
				"--force",
				"--no-backup",
				"--db-root-username",
				"root",
				"--db-root-password",
				"root",
			],
		)
