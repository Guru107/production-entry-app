from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app import lifecycle
from production_entry_app.production_entry_app.tests.support import host_parity
from production_entry_app.production_entry_app.utils import legacy_time_cutover
from production_entry_app.production_entry_app.utils.legacy_time_cutover import (
	execute_legacy_time_cutover,
	unhide_legacy_time_fields,
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


class DriftNeutralTestCase(FrappeTestCase):
	"""Base: make the shared dev site's real staging-style drift invisible.

	The engine hides any module-PEA custom field outside current fixtures, so
	tests that do not build drift must neutralize the site's own first —
	otherwise the engine's decisions (and the state snapshots) depend on which
	fields happen to have drifted on this site.
	"""

	def setUp(self) -> None:
		super().setUp()
		self.neutralized_drift = host_parity.neutralize_module_pea_drift()
		self.addCleanup(host_parity.restore_module_pea_drift, self.neutralized_drift)


class TestCutoverOnCleanSite(DriftNeutralTestCase):
	"""No host drift at all: the cutover must be a clean no-op."""

	def setUp(self) -> None:
		super().setUp()
		self.property_setters_before = host_parity.snapshot_module_property_setters()
		self.addCleanup(host_parity.restore_module_property_setters, self.property_setters_before)
		self.scripts_before = _script_state()

	def test_cutover_is_noop_on_clean_site(self) -> None:
		execute_legacy_time_cutover()

		self.assertEqual(
			_property_setter_state(),
			{name: row["value"] for name, row in self.property_setters_before.items()},
		)
		self.assertEqual(_script_state(), self.scripts_before)


class TestCutoverClientScripts(DriftNeutralTestCase):
	def setUp(self) -> None:
		super().setUp()
		for name in host_parity.LEGACY_TIME_CLIENT_SCRIPTS + host_parity.KEPT_CLIENT_SCRIPTS:
			host_parity.ensure_client_script(name)
			self.addCleanup(host_parity.remove_client_script, name)

	def test_cutover_disables_exactly_the_two_legacy_time_scripts(self) -> None:
		execute_legacy_time_cutover()

		for name in host_parity.LEGACY_TIME_CLIENT_SCRIPTS:
			self.assertEqual(_enabled(name), 0, name)
		for name in host_parity.KEPT_CLIENT_SCRIPTS:
			self.assertEqual(_enabled(name), 1, name)

	def test_cutover_skips_cleanly_when_scripts_absent(self) -> None:
		for name in host_parity.LEGACY_TIME_CLIENT_SCRIPTS:
			host_parity.remove_client_script(name)

		execute_legacy_time_cutover()

		for name in host_parity.LEGACY_TIME_CLIENT_SCRIPTS:
			self.assertFalse(frappe.db.exists("Client Script", name))

	def test_cutover_skips_already_disabled_scripts(self) -> None:
		host_parity.ensure_client_script("Actual & Loss Time Calculation", enabled=False)

		execute_legacy_time_cutover()

		self.assertEqual(_enabled("Actual & Loss Time Calculation"), 0)
		self.assertEqual(_enabled("Stock Auto Time"), 0)

	def test_cutover_disables_scripts_before_hiding_sections(self) -> None:
		manager = MagicMock()
		with (
			patch.object(legacy_time_cutover, "_disable_legacy_client_scripts", manager.disable),
			patch.object(legacy_time_cutover, "_hide_legacy_time_sections", manager.hide_sections),
			patch.object(legacy_time_cutover, "_hide_obsolete_pea_custom_fields", manager.hide_obsolete),
		):
			execute_legacy_time_cutover()

		self.assertEqual(
			[call[0] for call in manager.mock_calls],
			["disable", "hide_sections", "hide_obsolete"],
		)


class CutoverHostParityTestCase(DriftNeutralTestCase):
	"""Base: legacy time fields, the five host client scripts, and drift in place."""

	def setUp(self) -> None:
		super().setUp()
		self.property_setters_before = host_parity.snapshot_module_property_setters()
		self.addCleanup(host_parity.restore_module_property_setters, self.property_setters_before)
		self.addCleanup(host_parity.remove_legacy_time_fields)
		host_parity.install_legacy_time_fields()
		self.addCleanup(host_parity.remove_legacy_workstation)
		host_parity.ensure_legacy_workstation()
		for name in host_parity.LEGACY_TIME_CLIENT_SCRIPTS + host_parity.KEPT_CLIENT_SCRIPTS:
			host_parity.ensure_client_script(name)
			self.addCleanup(host_parity.remove_client_script, name)

	def run_cutover(self) -> None:
		execute_legacy_time_cutover()


class TestCutoverHiding(CutoverHostParityTestCase):
	def test_cutover_hides_legacy_sections_and_workstation_spm_in_fresh_meta(self) -> None:
		self.run_cutover()

		for doctype, fieldname in legacy_time_cutover.LEGACY_TIME_FIELDS:
			self.assertEqual(_hidden(doctype, fieldname), 1, f"{doctype}.{fieldname}")

	def test_cutover_hides_sections_without_hiding_leaf_fields_or_deleting_custom_fields(self) -> None:
		self.run_cutover()

		# Leaf fields stay unhidden; hiding the section hides the whole group in the UI.
		self.assertEqual(_hidden("Stock Entry", "custom_workstation"), 0)
		self.assertEqual(_hidden("Stock Entry", "custom_actual_start_date"), 0)
		for doctype, fieldname in legacy_time_cutover.LEGACY_TIME_FIELDS:
			self.assertTrue(frappe.db.exists("Custom Field", f"{doctype}-{fieldname}"))

	def test_cutover_hides_obsolete_pea_custom_fields(self) -> None:
		host_parity.ensure_obsolete_pea_custom_field()
		self.addCleanup(host_parity.remove_obsolete_pea_custom_field)

		self.run_cutover()

		self.assertEqual(_hidden("Stock Entry", "custom_pea_abandoned_metric"), 1)
		self.assertTrue(frappe.db.exists("Custom Field", "Stock Entry-custom_pea_abandoned_metric"))

	def test_cutover_skips_obsolete_hiding_when_no_drift_exists(self) -> None:
		self.run_cutover()

		# Every fixture-shipped PEA custom field on Stock Entry keeps its visibility:
		# the cutover must not create hidden property setters for fields it still ships.
		fixture_fieldnames = {
			row.fieldname
			for row in frappe.get_all(
				"Custom Field",
				filters={"module": "Production Entry App", "dt": "Stock Entry"},
				fields=["fieldname"],
			)
		}
		self.assertTrue(fixture_fieldnames)
		for fieldname in fixture_fieldnames:
			self.assertNotIn(f"Stock Entry-{fieldname}-hidden", _property_setter_state())

	def test_cutover_leaves_host_and_production_owned_metadata_untouched(self) -> None:
		host_parity.ensure_host_custom_field(
			"Stock Entry",
			{
				"fieldname": "custom_stock_entry_purpose",
				"label": "Stock Entry Purpose",
				"fieldtype": "Data",
				"read_only": 1,
			},
		)
		self.addCleanup(host_parity.remove_host_custom_field, "Stock Entry", "custom_stock_entry_purpose")
		host_parity.ensure_host_custom_field(
			"Workstation",
			{"fieldname": "custom_press_rate", "label": "Press Rate", "fieldtype": "Float"},
		)
		self.addCleanup(host_parity.remove_host_custom_field, "Workstation", "custom_press_rate")
		host_parity.ensure_host_custom_field(
			"BOM", {"fieldname": "custom_operation", "label": "Operation", "fieldtype": "Data"}
		)
		self.addCleanup(host_parity.remove_host_custom_field, "BOM", "custom_operation")

		self.run_cutover()

		self.assertEqual(_hidden("Stock Entry", "custom_stock_entry_purpose"), 0)
		self.assertEqual(_hidden("Workstation", "custom_press_rate"), 0)
		self.assertEqual(_hidden("BOM", "custom_operation"), 0)
		self.assertEqual(_hidden("Workstation", "custom_standard_spm"), 1)

	def test_cutover_keeps_legacy_values_on_submitted_entries(self) -> None:
		entry = host_parity.make_legacy_stock_entry()
		self.addCleanup(host_parity.discard_stock_entry, entry)

		self.run_cutover()

		self.assertEqual(
			frappe.db.get_value("Stock Entry", entry, "custom_workstation"),
			"Host Parity Workstation",
		)
		self.assertEqual(
			frappe.db.get_value("Stock Entry", entry, "custom_actual_start_date"),
			frappe.utils.get_datetime("2026-10-01 09:00:00"),
		)

	def test_cutover_never_touches_host_owned_hidden_setters(self) -> None:
		"""Host customizations are neither hijacked nor forced: report and skip.

		A host-owned ``hidden=0`` setter on a legacy target is an unaudited host
		shape; the cutover must not rewrite or delete it, and must not hide the
		field behind the host's back either.
		"""
		host_parity.ensure_host_property_setter("Stock Entry", "custom_actual_time", value="0")
		self.addCleanup(host_parity.remove_property_setter, "Stock Entry", "custom_actual_time")

		self.run_cutover()

		setter = frappe.db.get_value(
			"Property Setter",
			"Stock Entry-custom_actual_time-hidden",
			["value", "module"],
			as_dict=True,
		)
		self.assertEqual(int(setter.value), 0)
		self.assertEqual(setter.module, "Manufacturing")
		self.assertEqual(_hidden("Stock Entry", "custom_actual_time"), 0)

	def test_cutover_leaves_host_hidden_target_to_the_host_setter(self) -> None:
		"""A host-owned hidden=1 setter already meets the goal; it stays host-owned."""
		host_parity.ensure_host_property_setter("Stock Entry", "custom_loss_time", value="1")
		self.addCleanup(host_parity.remove_property_setter, "Stock Entry", "custom_loss_time")

		self.run_cutover()

		self.assertEqual(
			frappe.db.get_value("Property Setter", "Stock Entry-custom_loss_time-hidden", "module"),
			"Manufacturing",
		)
		self.assertEqual(_hidden("Stock Entry", "custom_loss_time"), 1)

	def test_cutover_rehides_an_app_owned_setter_that_was_flipped_visible(self) -> None:
		"""A PEA-owned hidden setter flipped back to visible converges to hidden."""
		self.run_cutover()
		frappe.db.set_value(
			"Property Setter",
			"Stock Entry-custom_actual_time-hidden",
			"value",
			"0",
			update_modified=False,
		)
		frappe.clear_cache(doctype="Stock Entry")
		self.assertEqual(_hidden("Stock Entry", "custom_actual_time"), 0)

		self.run_cutover()

		self.assertEqual(_hidden("Stock Entry", "custom_actual_time"), 1)

	def test_cutover_is_idempotent(self) -> None:
		host_parity.ensure_obsolete_pea_custom_field()
		self.addCleanup(host_parity.remove_obsolete_pea_custom_field)

		self.run_cutover()
		property_setters_after_first = _property_setter_state()
		scripts_after_first = _script_state()
		hidden_after_first = {
			(doctype, fieldname): _hidden(doctype, fieldname)
			for doctype, fieldname in legacy_time_cutover.LEGACY_TIME_FIELDS
		}
		hidden_after_first[("Stock Entry", "custom_pea_abandoned_metric")] = _hidden(
			"Stock Entry", "custom_pea_abandoned_metric"
		)

		self.run_cutover()

		self.assertEqual(_property_setter_state(), property_setters_after_first)
		self.assertEqual(_script_state(), scripts_after_first)
		hidden_after_second = {
			(doctype, fieldname): _hidden(doctype, fieldname)
			for doctype, fieldname in legacy_time_cutover.LEGACY_TIME_FIELDS
		}
		hidden_after_second[("Stock Entry", "custom_pea_abandoned_metric")] = _hidden(
			"Stock Entry", "custom_pea_abandoned_metric"
		)
		self.assertEqual(hidden_after_second, hidden_after_first)


class TestUnhideLegacyTimeFields(CutoverHostParityTestCase):
	def test_unhide_restores_visibility_but_keeps_scripts_disabled(self) -> None:
		self.run_cutover()

		unhide_legacy_time_fields()

		for doctype, fieldname in legacy_time_cutover.LEGACY_TIME_FIELDS:
			self.assertEqual(_hidden(doctype, fieldname), 0, f"{doctype}.{fieldname}")
			self.assertNotIn(f"{doctype}-{fieldname}-hidden", _property_setter_state())
		for name in host_parity.LEGACY_TIME_CLIENT_SCRIPTS:
			self.assertEqual(_enabled(name), 0, name)

	def test_unhide_is_noop_when_cutover_never_ran(self) -> None:
		property_setters_before = _property_setter_state()

		unhide_legacy_time_fields()

		self.assertEqual(_property_setter_state(), property_setters_before)
		for doctype, fieldname in legacy_time_cutover.LEGACY_TIME_FIELDS:
			self.assertEqual(_hidden(doctype, fieldname), 0, f"{doctype}.{fieldname}")

	def test_unhide_keeps_host_owned_hidden_setters(self) -> None:
		"""A host-owned hidden setter is not the cutover's to delete."""
		host_parity.ensure_host_property_setter("Stock Entry", "custom_loss_time", value="1")
		self.addCleanup(host_parity.remove_property_setter, "Stock Entry", "custom_loss_time")

		unhide_legacy_time_fields()

		self.assertTrue(frappe.db.exists("Property Setter", "Stock Entry-custom_loss_time-hidden"))
		self.assertEqual(_hidden("Stock Entry", "custom_loss_time"), 1)

	def test_before_uninstall_customization_cleanup_unhides_legacy_sections(self) -> None:
		self.run_cutover()
		for doctype, fieldname in legacy_time_cutover.LEGACY_TIME_FIELDS:
			self.assertEqual(_hidden(doctype, fieldname), 1, f"{doctype}.{fieldname}")

		lifecycle._delete_customizations("Property Setter")

		for doctype, fieldname in legacy_time_cutover.LEGACY_TIME_FIELDS:
			self.assertEqual(_hidden(doctype, fieldname), 0, f"{doctype}.{fieldname}")
