from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app import hooks as app_hooks
from production_entry_app import install
from production_entry_app.production_entry_app.doctype.downtime_reason.downtime_reason import (
	CODE_FORMAT,
)
from production_entry_app.production_entry_app.tests.support import host_parity
from production_entry_app.production_entry_app.utils.downtime_reason_adoption import (
	adoption_export_path,
)
from production_entry_app.production_entry_app.utils.downtime_reason_seed import (
	STANDARD_DOWNTIME_REASONS,
)

BEFORE_INSTALL_HOOK = "production_entry_app.install.before_install"
AFTER_INSTALL_HOOK = "production_entry_app.install.after_install"


def _reason_rows() -> list[dict]:
	return frappe.get_all(
		"Downtime Reason", fields=["name", "code", "description", "is_active"], order_by="name"
	)


def _enabled(name: str) -> int:
	return int(frappe.db.get_value("Client Script", name, "enabled") or 0)


def _hidden(doctype: str, fieldname: str) -> int:
	field = frappe.get_meta(doctype, cached=False).get_field(fieldname)
	return int(getattr(field, "hidden", 0) or 0)


def _script_state() -> dict[str, int]:
	rows = frappe.get_all("Client Script", fields=["name", "enabled"])
	return {row.name: int(row.enabled or 0) for row in rows}


def _property_setter_state() -> dict[str, str]:
	rows = frappe.get_all(
		"Property Setter",
		filters={"module": "Production Entry App"},
		fields=["name", "value"],
		order_by="name",
	)
	return {row.name: row.value for row in rows}


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


class CleanSiteTestCase(FrappeTestCase):
	"""Base: a site without any host drift (the clean-install shape)."""

	def setUp(self) -> None:
		super().setUp()
		self.neutralized_drift = host_parity.neutralize_module_pea_drift()
		self.addCleanup(host_parity.restore_module_pea_drift, self.neutralized_drift)
		host_parity.clear_adoption_export()
		self.addCleanup(host_parity.clear_adoption_export)
		self.addCleanup(host_parity.restore_app_downtime_reason)


class TestInstallHooksOnCleanSite(CleanSiteTestCase):
	def test_before_install_is_noop_when_doctype_is_absent(self) -> None:
		host_parity.delete_downtime_reason_doctype()

		install.before_install()

		self.assertFalse(frappe.db.exists("DocType", "Downtime Reason"))
		self.assertFalse(Path(adoption_export_path()).exists())

	def test_install_hooks_are_noops_on_app_owned_doctype(self) -> None:
		"""Clean sites (no host DocType) install unchanged: no reason, meta or UI change."""
		host_parity.restore_app_downtime_reason()
		rows_before = _reason_rows()
		meta_before = host_parity.doctype_snapshot()
		setters_before = _property_setter_state()
		scripts_before = _script_state()

		run_install_sequence()

		self.assertEqual(_reason_rows(), rows_before)
		self.assertEqual(host_parity.doctype_snapshot(), meta_before)
		self.assertEqual(_property_setter_state(), setters_before)
		self.assertEqual(_script_state(), scripts_before)


class HostParityInstallTestCase(CleanSiteTestCase):
	"""Base: host (production-like) state — host DocType, legacy UI, links and drift."""

	def setUp(self) -> None:
		super().setUp()
		self.property_setters_before = host_parity.snapshot_module_property_setters()
		self.addCleanup(host_parity.restore_module_property_setters, self.property_setters_before)
		host_parity.restore_app_downtime_reason()
		host_parity.delete_downtime_reason_doctype()
		host_parity.install_host_downtime_reason_doctype()
		host_parity.insert_host_downtime_reason("Setup Time", legacy_docstatus=1)
		host_parity.insert_host_downtime_reason("Inventory")
		host_parity.install_host_loss_time()
		self.addCleanup(host_parity.remove_host_loss_time)
		self.stock_entry = host_parity.make_host_stock_entry_with_loss_times(["Setup Time", "Inventory"])
		self.addCleanup(host_parity.discard_stock_entry, self.stock_entry)
		host_parity.install_legacy_time_fields()
		self.addCleanup(host_parity.remove_legacy_time_fields)
		host_parity.ensure_legacy_workstation()
		self.addCleanup(host_parity.remove_legacy_workstation)
		for name in host_parity.LEGACY_TIME_CLIENT_SCRIPTS + host_parity.KEPT_CLIENT_SCRIPTS:
			host_parity.ensure_client_script(name)
			self.addCleanup(host_parity.remove_client_script, name)


class TestBeforeInstallOnHostParity(HostParityInstallTestCase):
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


class TestInstallSequenceOnHostParity(HostParityInstallTestCase):
	def test_install_sequence_adopts_converts_and_applies_cutover(self) -> None:
		run_install_sequence()

		names = {row["name"] for row in _reason_rows()}
		self.assertTrue(names)
		for name in names:
			self.assertRegex(name, CODE_FORMAT.pattern)
		self.assertTrue(names >= set(STANDARD_DOWNTIME_REASONS))
		self.assertEqual(frappe.db.get_value("Downtime Reason", "01", "description"), "Setup")
		self.assertEqual(frappe.db.get_value("Downtime Reason", "23", "description"), "Inventory")
		self.assertEqual(sorted(host_parity.loss_time_reason_values(self.stock_entry)), ["01", "23"])
		for name in host_parity.LEGACY_TIME_CLIENT_SCRIPTS:
			self.assertEqual(_enabled(name), 0, name)
		for name in host_parity.KEPT_CLIENT_SCRIPTS:
			self.assertEqual(_enabled(name), 1, name)
		self.assertEqual(_hidden("Stock Entry", "custom_operation_details"), 1)
		self.assertEqual(_hidden("Stock Entry", "custom_actual_time"), 1)
		self.assertEqual(_hidden("Stock Entry", "custom_loss_time"), 1)
		self.assertEqual(_hidden("Workstation", "custom_standard_spm"), 1)

	def test_reinstall_converges_without_duplicate_work(self) -> None:
		run_install_sequence()
		rows_after_first = _reason_rows()
		meta_after_first = host_parity.doctype_snapshot()
		setters_after_first = _property_setter_state()
		scripts_after_first = _script_state()
		export_after_first = Path(adoption_export_path()).read_text()

		run_install_sequence()

		self.assertEqual(_reason_rows(), rows_after_first)
		self.assertEqual(host_parity.doctype_snapshot(), meta_after_first)
		self.assertEqual(_property_setter_state(), setters_after_first)
		self.assertEqual(_script_state(), scripts_after_first)
		self.assertEqual(sorted(host_parity.loss_time_reason_values(self.stock_entry)), ["01", "23"])
		self.assertEqual(Path(adoption_export_path()).read_text(), export_after_first)


class TestAfterInstallFailureRecovery(HostParityInstallTestCase):
	def test_after_install_failure_recovers_via_bench_execute_reinvocation(self) -> None:
		install.before_install()

		with (
			patch.object(install, "execute_legacy_time_cutover", side_effect=RuntimeError("boom")),
			self.assertRaises(RuntimeError),
		):
			install.after_install()

		# Conversion completed before the failure; the cutover did not run.
		self.assertTrue(all(CODE_FORMAT.fullmatch(row["name"]) for row in _reason_rows()))
		self.assertEqual(_enabled("Actual & Loss Time Calculation"), 1)

		# Re-invoke the same entry point the way ``bench --site <site> execute`` does.
		frappe.get_attr(AFTER_INSTALL_HOOK)()

		for name in host_parity.LEGACY_TIME_CLIENT_SCRIPTS:
			self.assertEqual(_enabled(name), 0, name)
		self.assertEqual(_hidden("Stock Entry", "custom_loss_time"), 1)
		self.assertEqual(sorted(host_parity.loss_time_reason_values(self.stock_entry)), ["01", "23"])
