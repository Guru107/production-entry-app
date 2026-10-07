from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app import hooks as app_hooks
from production_entry_app import install
from production_entry_app.production_entry_app.doctype.downtime_reason.downtime_reason import (
	CODE_FORMAT,
)
from production_entry_app.production_entry_app.tests.support import host_parity, install_parity
from production_entry_app.production_entry_app.utils.downtime_reason_adoption import (
	adoption_export_path,
)

BEFORE_INSTALL_HOOK = "production_entry_app.install.before_install"
AFTER_INSTALL_HOOK = "production_entry_app.install.after_install"


def run_install_sequence() -> None:
	"""Invoke the install entry points exactly as frappe's installer does."""
	frappe.get_attr(BEFORE_INSTALL_HOOK)()
	frappe.get_attr(AFTER_INSTALL_HOOK)()


class TestInstallHookWiring(FrappeTestCase):
	def test_before_and_after_install_hooks_are_registered(self) -> None:
		self.assertIn(BEFORE_INSTALL_HOOK, app_hooks.before_install)
		self.assertIn(AFTER_INSTALL_HOOK, app_hooks.after_install)

	def test_install_hooks_resolve_to_callable_entry_points(self) -> None:
		"""The dotted paths must resolve the way ``bench execute`` resolves them."""
		self.assertTrue(callable(frappe.get_attr(BEFORE_INSTALL_HOOK)))
		self.assertTrue(callable(frappe.get_attr(AFTER_INSTALL_HOOK)))

	def test_sync_and_migrate_hooks_are_unchanged(self) -> None:
		self.assertEqual(
			app_hooks.after_sync,
			["production_entry_app.production_entry_app.lifecycle.after_sync"],
		)
		self.assertEqual(
			app_hooks.after_migrate,
			["production_entry_app.production_entry_app.lifecycle.after_migrate"],
		)


class TestInstallHooksOnCleanSite(install_parity.CleanSiteTestCase):
	def test_before_install_is_noop_when_doctype_is_absent(self) -> None:
		host_parity.delete_downtime_reason_doctype()

		install.before_install()

		self.assertFalse(frappe.db.exists("DocType", "Downtime Reason"))
		self.assertFalse(Path(adoption_export_path()).exists())

	def test_install_hooks_are_noops_on_app_owned_doctype(self) -> None:
		"""Clean sites (no host DocType) install unchanged: no reason, meta or UI change."""
		host_parity.restore_app_downtime_reason()
		state_before = install_parity.migration_state()

		run_install_sequence()

		self.assertEqual(install_parity.migration_state(), state_before)


class TestBeforeInstallOnHostParity(install_parity.HostParityMigrationTestCase):
	def test_before_install_reshapes_host_doctype_in_place(self) -> None:
		install.before_install()

		snapshot = host_parity.doctype_snapshot()
		self.assertEqual(snapshot["module"], "Production Entry App")
		self.assertEqual(snapshot["custom"], 0)
		self.assertEqual(snapshot["autoname"], "field:code")
		self.assertTrue(Path(adoption_export_path()).exists())
		self.assertTrue(frappe.db.exists("Downtime Reason", "Setup Time"))
		self.assertTrue(frappe.db.exists("Downtime Reason", "Inventory"))

	def test_before_install_aborts_install_on_unexpected_shape_without_mutation(self) -> None:
		host_parity.delete_downtime_reason_doctype()
		host_parity.install_host_downtime_reason_doctype(
			extra_fields=({"fieldname": "code", "fieldtype": "Data"},)
		)
		host_parity.insert_host_downtime_reason("Setup Time")
		before = host_parity.doctype_snapshot()

		with self.assertRaises(frappe.ValidationError):
			install.before_install()

		self.assertEqual(host_parity.doctype_snapshot(), before)
		self.assertFalse(Path(adoption_export_path()).exists())
		self.assertTrue(frappe.db.exists("Downtime Reason", "Setup Time"))


class TestInstallSequenceOnHostParity(install_parity.HostParityMigrationTestCase):
	def test_install_sequence_adopts_converts_and_applies_cutover(self) -> None:
		run_install_sequence()

		self.assert_adopted_converted_and_cut_over()

	def test_reinstall_converges_without_duplicate_work(self) -> None:
		run_install_sequence()
		state_after_first = install_parity.migration_state()
		export_after_first = Path(adoption_export_path()).read_text()

		run_install_sequence()

		self.assertEqual(install_parity.migration_state(), state_after_first)
		self.assertEqual(sorted(host_parity.loss_time_reason_values(self.stock_entry)), ["01", "23"])
		self.assertEqual(Path(adoption_export_path()).read_text(), export_after_first)


class TestAfterInstallFailureRecovery(install_parity.HostParityMigrationTestCase):
	def test_after_install_failure_recovers_via_bench_execute_reinvocation(self) -> None:
		install.before_install()

		with (
			patch.object(install, "execute_legacy_time_cutover", side_effect=RuntimeError("boom")),
			self.assertRaises(RuntimeError),
		):
			install.after_install()

		# Conversion completed before the failure; the cutover did not run.
		self.assertTrue(all(CODE_FORMAT.fullmatch(row["name"]) for row in install_parity.reason_rows()))
		self.assertEqual(install_parity.script_enabled("Actual & Loss Time Calculation"), 1)

		# Re-invoke the same entry point the way ``bench --site <site> execute`` does.
		frappe.get_attr(AFTER_INSTALL_HOOK)()

		for name in host_parity.LEGACY_TIME_CLIENT_SCRIPTS:
			self.assertEqual(install_parity.script_enabled(name), 0, name)
		self.assertIsNone(frappe.get_meta("Stock Entry", cached=False).get_field("custom_loss_time"))
		self.assertEqual(sorted(host_parity.loss_time_reason_values(self.stock_entry)), ["01", "23"])
