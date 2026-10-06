from __future__ import annotations

from importlib import import_module
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.modules.patch_handler import PatchType, get_patches_from_app
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.doctype.downtime_reason.downtime_reason import (
	CODE_FORMAT,
)
from production_entry_app.production_entry_app.tests.support import host_parity, install_parity
from production_entry_app.production_entry_app.utils.downtime_reason_adoption import (
	adoption_export_path,
)

PRE_PATCH = "production_entry_app.patches.adopt_host_downtime_reason"
POST_PATCH = "production_entry_app.patches.convert_and_cutover_legacy_time"


def run_patch_pair() -> None:
	"""Invoke the patch entry points exactly as ``bench migrate`` does, in order."""
	frappe.get_attr(f"{PRE_PATCH}.execute")()
	frappe.get_attr(f"{POST_PATCH}.execute")()


class TestPatchRegistration(FrappeTestCase):
	def test_patches_txt_registers_the_pair_in_sync_ordered_sections(self) -> None:
		"""Read patches.txt the way the patch handler does; entries never get removed."""
		pre = get_patches_from_app("production_entry_app", patch_type=PatchType.pre_model_sync)
		post = get_patches_from_app("production_entry_app", patch_type=PatchType.post_model_sync)

		self.assertIn(PRE_PATCH, [patch.split()[0] for patch in pre])
		self.assertIn(POST_PATCH, [patch.split()[0] for patch in post])

	def test_patch_modules_resolve_to_execute_the_way_migrate_does(self) -> None:
		for dotted in (PRE_PATCH, POST_PATCH):
			self.assertTrue(callable(frappe.get_attr(f"{dotted}.execute")))

	def test_patch_modules_document_the_one_shot_install_migration(self) -> None:
		for dotted in (PRE_PATCH, POST_PATCH):
			docstring = import_module(dotted).__doc__ or ""
			self.assertTrue(docstring.strip(), dotted)
			self.assertIn("one-shot", docstring.lower())


class TestPatchPairOnCleanSite(install_parity.CleanSiteTestCase):
	def test_patch_pair_is_noop_on_clean_site(self) -> None:
		host_parity.restore_app_downtime_reason()
		state_before = install_parity.migration_state()

		run_patch_pair()

		self.assertEqual(install_parity.migration_state(), state_before)


class TestPatchPairOnHostParity(install_parity.HostParityMigrationTestCase):
	def test_patch_pair_adopts_converts_and_applies_cutover_in_order(self) -> None:
		"""Pre patch adopts before schema sync; post patch converts, verifies and cuts over."""
		run_patch_pair()

		self.assert_adopted_converted_and_cut_over()
		self.assertTrue(Path(adoption_export_path()).exists())

	def test_second_invocation_of_the_pair_changes_nothing(self) -> None:
		run_patch_pair()
		state_after_first = install_parity.migration_state()
		export_after_first = Path(adoption_export_path()).read_text()

		run_patch_pair()

		self.assertEqual(install_parity.migration_state(), state_after_first)
		self.assertEqual(Path(adoption_export_path()).read_text(), export_after_first)


class TestFailedPatchRerun(install_parity.HostParityMigrationTestCase):
	def test_failed_post_patch_reruns_from_the_start_and_converges(self) -> None:
		"""A failed patch is never logged, so the next migrate reruns it; guards converge."""
		frappe.get_attr(f"{PRE_PATCH}.execute")()
		post_module = import_module(POST_PATCH)

		with (
			patch.object(post_module, "execute_legacy_time_cutover", side_effect=RuntimeError("boom")),
			self.assertRaises(RuntimeError),
		):
			post_module.execute()

		# Conversion completed before the failure; the cutover did not run.
		self.assertTrue(all(CODE_FORMAT.fullmatch(row["name"]) for row in install_parity.reason_rows()))
		self.assertEqual(install_parity.script_enabled("Actual & Loss Time Calculation"), 1)

		post_module.execute()

		for name in host_parity.LEGACY_TIME_CLIENT_SCRIPTS:
			self.assertEqual(install_parity.script_enabled(name), 0, name)
		self.assertEqual(install_parity.field_hidden("Stock Entry", "custom_loss_time"), 1)
		self.assertEqual(sorted(host_parity.loss_time_reason_values(self.stock_entry)), ["01", "23"])
