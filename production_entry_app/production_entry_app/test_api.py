from __future__ import annotations

import json
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.api import (
	_cleanup_orphan_stock_entry_loss_links,
	get_die_tool_counter,
	reset_die_tool_counter,
)
from production_entry_app.production_entry_app.e2e_api import (
	_assert_e2e_api_allowed,
	_build_e2e_shift_doc,
	_cache_e2e_settings_snapshot,
	_cache_e2e_shift_name,
	_cleanup_e2e_context,
	_cleanup_e2e_downtime_entries,
	_cleanup_reserved_e2e_artifacts,
	_collect_reserved_e2e_prefixes,
	_e2e_base_date,
	_ensure_e2e_settings_fields_loaded,
	_get_candidate_e2e_stock_entries,
	_get_e2e_shift_names_cache_key,
	_get_or_create_e2e_employee,
	_get_or_create_e2e_shift,
	_insert_e2e_full_shift_stock_entry,
	_item_has_live_stock_entry_references,
	_restore_cached_e2e_settings,
	_safe_cancel_and_delete,
	_safe_force_delete,
	_stock_entry_matches_cleanup_target,
	bootstrap_e2e_context,
	cleanup_e2e_context,
	create_e2e_downtime_entry,
	create_e2e_full_shift_stock_entries,
	create_e2e_submitted_stock_entry,
	reset_e2e_die_tool_counter,
	set_e2e_system_float_precision,
)
from production_entry_app.production_entry_app.utils.alternative_items import (
	apply_direct_manufacture_alternative_flags,
)
from production_entry_app.production_entry_app.utils.test_bootstrap import ensure_stock, save_test_user


def _meta_stub(has_field_result: bool) -> object:
	class _Meta:
		def __init__(self, has_field_result: bool) -> None:
			self._has_field_result = has_field_result

		def has_field(self, _fieldname: str) -> bool:
			return self._has_field_result

		def get_field(self, _fieldname: str) -> object | None:
			return object() if self._has_field_result else None

	return _Meta(has_field_result)


def _patch_bootstrap_settings_reads(
	stack: ExitStack, *, company_code: str = "TC", single_value: int = 3
) -> None:
	stack.enter_context(
		patch(
			"production_entry_app.production_entry_app.e2e_api.frappe.db.get_value",
			side_effect=lambda doctype, *_args, **_kwargs: company_code,
		)
	)
	stack.enter_context(
		patch(
			"production_entry_app.production_entry_app.e2e_api.frappe.db.get_single_value",
			return_value=single_value,
		)
	)


class TestE2EApi(FrappeTestCase):
	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_production_api_module_has_no_e2e_helpers(self) -> None:
		import production_entry_app.production_entry_app.api as api

		for name in (
			"bootstrap_e2e_context",
			"cleanup_e2e_context",
			"cleanup_reserved_e2e_artifacts",
			"create_e2e_submitted_stock_entry",
			"create_e2e_full_shift_stock_entries",
			"create_e2e_downtime_entry",
			"reset_e2e_die_tool_counter",
			"set_e2e_access_control",
			"set_e2e_system_float_precision",
		):
			assert not hasattr(api, name), f"{name} must live in e2e_api, not api"

	def test_e2e_api_module_exposes_helpers(self) -> None:
		import production_entry_app.production_entry_app.e2e_api as e2e_api

		assert callable(e2e_api.bootstrap_e2e_context)
		assert callable(e2e_api.cleanup_e2e_context)

	def test_assert_e2e_api_allowed_calls_only_for_administrator(self) -> None:
		with patch("production_entry_app.production_entry_app.e2e_api.frappe.only_for") as only_for:
			with patch(
				"production_entry_app.production_entry_app.e2e_api._is_developer_mode_enabled",
				return_value=True,
			):
				with patch(
					"production_entry_app.production_entry_app.e2e_api._is_allow_e2e_tests_enabled",
					return_value=True,
				):
					_assert_e2e_api_allowed()
		only_for.assert_called_once_with("Administrator")

	def test_assert_e2e_api_allowed_blocks_when_developer_mode_disabled(self) -> None:
		with patch("production_entry_app.production_entry_app.e2e_api.frappe.only_for"):
			with patch(
				"production_entry_app.production_entry_app.e2e_api._is_developer_mode_enabled",
				return_value=False,
			):
				with self.assertRaises(frappe.PermissionError):
					_assert_e2e_api_allowed()

	def test_assert_e2e_api_allowed_blocks_without_allow_e2e_tests_flag(self) -> None:
		with patch("production_entry_app.production_entry_app.e2e_api.frappe.only_for"):
			with patch(
				"production_entry_app.production_entry_app.e2e_api._is_developer_mode_enabled",
				return_value=True,
			):
				with patch(
					"production_entry_app.production_entry_app.e2e_api._is_allow_e2e_tests_enabled",
					return_value=False,
				):
					with self.assertRaises(frappe.PermissionError):
						_assert_e2e_api_allowed()

	def test_ensure_stock_sets_explicit_posting_date_before_insert(self) -> None:
		stock_entry = MagicMock()
		stock_entry.insert.return_value = stock_entry

		with (
			patch(
				"production_entry_app.production_entry_app.utils.test_bootstrap.frappe.db.get_value",
				return_value=0,
			),
			patch(
				"production_entry_app.production_entry_app.utils.test_bootstrap.ensure_fiscal_year_for_date"
			) as ensure_fiscal_year,
			patch(
				"production_entry_app.production_entry_app.utils.test_bootstrap.frappe.get_doc",
				return_value=stock_entry,
			) as get_doc,
		):
			ensure_stock("RM", "WIP", "_Test Company", target_qty=1000, posting_date="2099-01-20")

		doc = get_doc.call_args.args[0]
		self.assertEqual(doc["posting_date"], "2099-01-20")
		self.assertEqual(doc["posting_time"], "00:00:00")
		self.assertEqual(doc["set_posting_time"], 1)
		ensure_fiscal_year.assert_called_once_with("2099-01-20", "_Test Company")
		stock_entry.insert.assert_called_once_with(ignore_permissions=True)
		stock_entry.submit.assert_called_once_with()

	def test_ensure_e2e_settings_fields_loaded_reloads_when_meta_is_stale(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.e2e_api.frappe.get_meta",
			return_value=_meta_stub(False),
		):
			with patch("production_entry_app.production_entry_app.e2e_api.frappe.reload_doc") as reload_doc:
				with patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.clear_document_cache"
				) as clear_cache:
					_ensure_e2e_settings_fields_loaded()

		reload_doc.assert_called_once_with(
			"production_entry_app",
			"doctype",
			"production_entry_settings",
		)
		clear_cache.assert_called_once_with("Production Entry Settings")

	def test_cache_e2e_settings_snapshot_skips_existing_cache(self) -> None:
		cache = MagicMock()
		cache.get_value.return_value = {"production_entry_settings": {}}
		with patch("production_entry_app.production_entry_app.e2e_api.frappe.cache", return_value=cache):
			with patch(
				"production_entry_app.production_entry_app.e2e_api._get_production_entry_settings_snapshot"
			) as get_settings:
				_cache_e2e_settings_snapshot("E2E-CACHED")

		get_settings.assert_not_called()
		cache.set_value.assert_not_called()

	def test_cache_e2e_shift_name_skips_empty_and_duplicate_names(self) -> None:
		cache = MagicMock()
		cache.get_value.return_value = ["SHIFT-001"]
		with patch("production_entry_app.production_entry_app.e2e_api.frappe.cache", return_value=cache):
			_cache_e2e_shift_name("E2E", None)
			_cache_e2e_shift_name("E2E", "SHIFT-001")
			_cache_e2e_shift_name("E2E", "SHIFT-002")

		cache.set_value.assert_called_once_with("pea:e2e:shift-names:E2E", ["SHIFT-001", "SHIFT-002"])

	def test_restore_cached_e2e_settings_restores_modern_snapshot_and_deletes_cache(self) -> None:
		cache = MagicMock()
		cache.get_value.return_value = {
			"production_entry_settings": {"shift_start_buffer_mins": 60},
			"system_settings": {"float_precision": 3},
		}
		with patch("production_entry_app.production_entry_app.e2e_api.frappe.cache", return_value=cache):
			with patch(
				"production_entry_app.production_entry_app.e2e_api._restore_production_entry_settings"
			) as restore_pea:
				with patch(
					"production_entry_app.production_entry_app.e2e_api._restore_system_settings"
				) as restore_system:
					_restore_cached_e2e_settings("E2E")

		restore_pea.assert_called_once_with({"shift_start_buffer_mins": 60})
		restore_system.assert_called_once_with({"float_precision": 3})
		cache.delete_value.assert_any_call("pea:e2e:settings:E2E")
		cache.delete_value.assert_any_call("pea:e2e:shift-names:E2E")

	def test_all_e2e_endpoints_fail_closed_when_guard_raises(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.e2e_api._assert_e2e_api_allowed",
			side_effect=frappe.PermissionError,
		):
			with self.assertRaises(frappe.PermissionError):
				bootstrap_e2e_context(prefix="E2E-Guard")
			with self.assertRaises(frappe.PermissionError):
				cleanup_e2e_context(prefix="E2E-Guard")
			with self.assertRaises(frappe.PermissionError):
				create_e2e_submitted_stock_entry(prefix="E2E-Guard")
			with self.assertRaises(frappe.PermissionError):
				reset_e2e_die_tool_counter(prefix="E2E_GUARD_W0")

	def test_reset_e2e_die_tool_counter_restricts_item_to_reserved_prefix(self) -> None:
		with (
			patch("production_entry_app.production_entry_app.e2e_api._assert_e2e_api_allowed"),
			patch(
				"production_entry_app.production_entry_app.e2e_api.reset_die_tool_counter"
			) as reset_counter,
		):
			with self.assertRaises(frappe.ValidationError):
				reset_e2e_die_tool_counter(prefix="PRODUCTION")

		reset_counter.assert_not_called()

	def test_reset_e2e_die_tool_counter_resets_only_context_fg_item(self) -> None:
		with (
			patch("production_entry_app.production_entry_app.e2e_api._assert_e2e_api_allowed"),
			patch(
				"production_entry_app.production_entry_app.e2e_api.reset_die_tool_counter",
				return_value={"current_strokes": 0},
			) as reset_counter,
		):
			result = reset_e2e_die_tool_counter(prefix="E2E_DIE_TOOL_METRICS_W0")

		self.assertEqual(result, {"current_strokes": 0})
		reset_counter.assert_called_once_with("_E2E_DIE_TOOL_METRICS_W0_FG_Item")

	def test_stock_entry_matches_cleanup_target_by_operator_or_fg_item(self) -> None:
		operator_only_match = frappe._dict(
			{
				"custom_pea_operator": "E2E Operator",
				"items": [{"is_finished_item": 1, "item_code": "_Another_Item"}],
			}
		)
		self.assertTrue(
			_stock_entry_matches_cleanup_target(
				operator_only_match, target_operator="E2E Operator", target_fg_item="_E2E_FG_Item"
			)
		)

		fg_item_only_match = frappe._dict(
			{
				"custom_pea_operator": "Other Operator",
				"items": [{"is_finished_item": 1, "item_code": "_E2E_FG_Item"}],
			}
		)
		self.assertTrue(
			_stock_entry_matches_cleanup_target(
				fg_item_only_match, target_operator="E2E Operator", target_fg_item="_E2E_FG_Item"
			)
		)

		no_match = frappe._dict(
			{
				"custom_pea_operator": "Other Operator",
				"items": [{"is_finished_item": 1, "item_code": "_Another_Item"}],
			}
		)
		self.assertFalse(
			_stock_entry_matches_cleanup_target(
				no_match, target_operator="E2E Operator", target_fg_item="_E2E_FG_Item"
			)
		)

	def test_apply_direct_manufacture_alternative_flags_preserves_current_row_rules(self) -> None:
		doc = frappe._dict(
			{
				"purpose": "Manufacture",
				"from_bom": 1,
				"bom_no": "BOM-001",
				"work_order": None,
				"items": [
					frappe._dict({"item_code": "RM-ALLOWED", "allow_alternative_item": 0}),
					frappe._dict({"item_code": "RM-EXISTING", "allow_alternative_item": 1}),
					frappe._dict(
						{"item_code": "FG-ITEM", "is_finished_item": 1, "allow_alternative_item": 0}
					),
					frappe._dict({"item_code": "SCRAP", "is_scrap_item": 1, "allow_alternative_item": 0}),
					frappe._dict(
						{
							"item_code": "REJECTION",
							"custom_pea_is_rejection_item": 1,
							"allow_alternative_item": 0,
						}
					),
					frappe._dict(
						{
							"item_code": "SUBSTITUTE",
							"original_item": "RM-ORIGINAL",
							"allow_alternative_item": 0,
						}
					),
					frappe._dict({"item_code": "RM-BLOCKED", "allow_alternative_item": 0}),
				],
			}
		)

		with (
			patch(
				"production_entry_app.production_entry_app.utils.alternative_items.get_bom_alternative_allowed_items",
				return_value={"RM-ALLOWED", "RM-EXISTING", "RM-ORIGINAL"},
			),
			patch(
				"production_entry_app.production_entry_app.utils.alternative_items.get_bom_secondary_item_codes",
				return_value=set(),
			),
		):
			apply_direct_manufacture_alternative_flags(doc)

		self.assertEqual(
			[row.get("item_code") for row in doc.get("items")],
			[
				"RM-ALLOWED",
				"RM-EXISTING",
				"FG-ITEM",
				"SCRAP",
				"REJECTION",
				"SUBSTITUTE",
				"RM-BLOCKED",
			],
		)
		self.assertEqual(
			[row.get("allow_alternative_item") for row in doc.get("items")],
			[1, 1, 0, 0, 0, 1, 0],
		)

	def test_cleanup_orphan_stock_entry_loss_links_deletes_only_orphans(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.api.frappe.get_all",
			side_effect=[
				[
					{"name": "LOSS-001", "parent": "MAT-STE-MISSING"},
					{"name": "LOSS-002", "parent": "MAT-STE-EXISTS"},
				],
				["MAT-STE-EXISTS"],
			],
		):
			with patch("production_entry_app.production_entry_app.api.frappe.db.delete") as db_delete:
				_cleanup_orphan_stock_entry_loss_links("SHIFT-2026-02-22.1.0001")
		db_delete.assert_called_once_with("Loss Entry", {"name": ("in", ["LOSS-001"])})

	def test_deleting_shift_cleans_orphan_stock_entry_loss_links(self) -> None:
		from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
			bootstrap_manufacture_masters,
			make_running_shift,
		)

		masters = bootstrap_manufacture_masters()
		shift = make_running_shift(masters)
		# Simulate an orphan Loss Entry row pointing at a since-deleted Stock Entry parent.
		frappe.get_doc(
			{
				"doctype": "Loss Entry",
				"parenttype": "Stock Entry",
				"parent": "SE-DELETED-0001",
				"parentfield": "custom_pea_unplanned_losses",
				"shift": shift.name,
				"downtime_reason": frappe.db.get_value("Downtime Reason", {}, "name"),
				"start_time": shift.planned_start_time,
				"end_time": shift.planned_start_time,
			}
		).insert(ignore_permissions=True)
		shift.db_set("status", "Draft")
		frappe.delete_doc("Shift", shift.name, force=True)
		assert not frappe.db.exists("Loss Entry", {"shift": shift.name, "parenttype": "Stock Entry"})

	def test_client_delete_override_is_removed(self) -> None:
		from production_entry_app import hooks

		assert "frappe.client.delete" not in getattr(hooks, "override_whitelisted_methods", {})

	def test_cleanup_e2e_shifts_cleans_shift_orphans_before_force_delete(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.e2e_api._get_e2e_cleanup_targets",
			return_value={"e2e_shift_names": ["SHIFT-2026-02-22.1.0001"]},
		):
			with patch(
				"production_entry_app.production_entry_app.e2e_api.frappe.db.exists", return_value=True
			):
				with patch("production_entry_app.production_entry_app.e2e_api.frappe.get_doc") as get_doc:
					with patch(
						"production_entry_app.production_entry_app.e2e_api._cleanup_orphan_stock_entry_loss_links"
					) as cleanup:
						with patch(
							"production_entry_app.production_entry_app.e2e_api._safe_force_delete"
						) as force_delete:
							get_doc.return_value = frappe._dict({"status": "Completed"})

							from production_entry_app.production_entry_app.e2e_api import _cleanup_e2e_shifts

							_cleanup_e2e_shifts("E2E")

		cleanup.assert_called_once_with("SHIFT-2026-02-22.1.0001")
		force_delete.assert_called_once_with(
			"Shift", "SHIFT-2026-02-22.1.0001", context="cleanup_e2e_context"
		)

	def test_cleanup_e2e_shifts_does_not_delete_when_orphan_cleanup_fails(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.e2e_api._get_e2e_cleanup_targets",
			return_value={"e2e_shift_names": ["SHIFT-2026-02-22.1.0001"]},
		):
			with patch(
				"production_entry_app.production_entry_app.e2e_api.frappe.db.exists", return_value=True
			):
				with patch("production_entry_app.production_entry_app.e2e_api.frappe.get_doc") as get_doc:
					with patch(
						"production_entry_app.production_entry_app.e2e_api._cleanup_orphan_stock_entry_loss_links",
						side_effect=RuntimeError("orphan cleanup failed"),
					):
						with patch("production_entry_app.production_entry_app.e2e_api.frappe.log_error"):
							with patch(
								"production_entry_app.production_entry_app.e2e_api._safe_force_delete"
							) as force_delete:
								get_doc.return_value = frappe._dict({"status": "Completed"})

								from production_entry_app.production_entry_app.e2e_api import (
									_cleanup_e2e_shifts,
								)

								with self.assertRaisesRegex(RuntimeError, "orphan cleanup failed"):
									_cleanup_e2e_shifts("E2E")

		force_delete.assert_not_called()

	def test_cleanup_e2e_context_finalizes_after_cleanup_failure(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.e2e_api._get_e2e_cleanup_targets",
			return_value={"e2e_shift_names": []},
		):
			with patch(
				"production_entry_app.production_entry_app.e2e_api._cleanup_e2e_shifts",
				side_effect=RuntimeError("cleanup failed"),
			):
				with patch(
					"production_entry_app.production_entry_app.e2e_api._finalize_e2e_cleanup"
				) as finalize:
					with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
						_cleanup_e2e_context("E2E")

		finalize.assert_called_once()
		self.assertEqual(finalize.call_args.args[0], "E2E")
		self.assertEqual(finalize.call_args.args[1]["ok"], False)

	def test_get_die_tool_counter_preserves_unrounded_utilization_and_threshold_check(self) -> None:
		with (
			patch("production_entry_app.production_entry_app.api.frappe.has_permission", return_value=True),
			patch("production_entry_app.production_entry_app.api.frappe.db.exists", return_value=True),
			patch("production_entry_app.production_entry_app.api.is_die_tool_enabled", return_value=True),
			patch(
				"production_entry_app.production_entry_app.api.frappe.get_list",
				return_value=[
					frappe._dict(
						{
							"current_stroke_count": 1,
							"stroke_capacity": 3,
							"warning_threshold_pct": 33.3333,
						}
					)
				],
			),
		):
			result = get_die_tool_counter("ITEM-001")

		self.assertAlmostEqual(float(result.get("utilization_pct") or 0), 33.3333333333, places=6)
		self.assertEqual(int(result.get("is_maintenance_due") or 0), 1)

	def test_get_die_tool_counter_denies_item_without_read_permission(self) -> None:
		with patch("production_entry_app.production_entry_app.api.frappe.db.exists", return_value=True):
			with patch(
				"production_entry_app.production_entry_app.api.frappe.has_permission", return_value=False
			):
				with self.assertRaises(frappe.PermissionError):
					get_die_tool_counter("ITEM-001")

	def test_get_die_tool_counter_treats_hidden_counter_as_absent(self) -> None:
		with (
			patch("production_entry_app.production_entry_app.api.frappe.db.exists", return_value=True),
			patch("production_entry_app.production_entry_app.api.frappe.has_permission", return_value=True),
			patch("production_entry_app.production_entry_app.api.is_die_tool_enabled", return_value=True),
			patch(
				"production_entry_app.production_entry_app.api.frappe.get_list", return_value=[]
			) as get_list,
		):
			result = get_die_tool_counter("ITEM-001")

		self.assertEqual(result["has_die_tool"], 1)
		self.assertEqual(result["current_strokes"], 0)
		get_list.assert_called_once_with(
			"Die Tool Counter",
			filters={"die_tool_item": "ITEM-001"},
			fields=["name", "current_stroke_count", "stroke_capacity", "warning_threshold_pct"],
			limit=1,
		)

	def test_get_die_tool_counter_includes_float_precision_without_rounding_payload(self) -> None:
		from production_entry_app.production_entry_app.utils.system_precision import (
			get_system_float_precision,
		)

		with (
			patch("production_entry_app.production_entry_app.api.frappe.has_permission", return_value=True),
			patch("production_entry_app.production_entry_app.api.frappe.db.exists", return_value=True),
			patch("production_entry_app.production_entry_app.api.is_die_tool_enabled", return_value=True),
			patch(
				"production_entry_app.production_entry_app.api.frappe.get_list",
				return_value=[
					frappe._dict(
						{
							"current_stroke_count": 12.5,
							"stroke_capacity": 50,
							"warning_threshold_pct": 90,
						}
					)
				],
			),
		):
			result = get_die_tool_counter("ITEM-001")

		self.assertEqual(result["float_precision"], get_system_float_precision())
		self.assertIsInstance(result["current_strokes"], float)
		self.assertIsInstance(result["stroke_capacity"], float)
		self.assertIsInstance(result["warning_threshold_pct"], float)
		self.assertIsInstance(result["utilization_pct"], float)
		self.assertIsInstance(result["is_maintenance_due"], int)

	def test_e2e_base_date_is_deterministic(self) -> None:
		date_a = _e2e_base_date("StablePrefix")
		date_b = _e2e_base_date("StablePrefix")
		self.assertEqual(date_a, date_b)
		self.assertTrue(date_a.startswith("2099-"))

	def test_get_shift_details_for_stock_entry_returns_updated_planned_end_for_running_shift(self) -> None:
		"""When a Running shift's duration is changed, get_shift_details_for_stock_entry
		must return the newly-calculated planned_end_time and shift_end_date, not stale cached values."""
		from unittest.mock import MagicMock

		from production_entry_app.production_entry_app.api import get_shift_details_for_stock_entry

		shift_doc = MagicMock()
		shift_doc.name = "SHIFT-RUNNING-001"
		shift_doc.status = "Running"
		shift_doc.company = "Test Company"
		shift_doc.branch = "Test Branch"
		shift_doc.shift_date = "2026-03-01"
		shift_doc.planned_start_time = "08:00:00"
		# Original duration: 8 hours -> original planned_end: 16:00
		shift_doc.planned_end_time = "16:00:00"
		shift_doc.shift_end_date = "2026-03-01"
		shift_doc.shift_duration = "8"
		shift_doc.work_in_progress_warehouse = "WIP Warehouse"

		self.assertEqual(str(shift_doc.shift_end_date), "2026-03-01")
		self.assertEqual(str(shift_doc.planned_end_time), "16:00:00")

		# Simulate duration change: 8 -> 10 hours
		shift_doc.shift_duration = "10"
		shift_doc.planned_end_time = "18:00:00"
		shift_doc.shift_end_date = "2026-03-01"

		with (
			patch("production_entry_app.production_entry_app.api.frappe.has_permission", return_value=True),
			patch("production_entry_app.production_entry_app.api.frappe.get_doc", return_value=shift_doc),
		):
			updated_result = get_shift_details_for_stock_entry(shift_doc.name)

		# The updated planned_end must reflect the new 10-hour duration ending at 18:00
		self.assertEqual(updated_result.get("company"), "Test Company")
		self.assertIn("18:00", updated_result.get("custom_pea_planned_end_date", ""))

	def test_cleanup_stock_entry_query_uses_single_qb_run(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.e2e_api._get_candidate_e2e_stock_entries",
			return_value=[],
		) as get_candidates:
			with patch("production_entry_app.production_entry_app.e2e_api._assert_e2e_api_allowed"):
				with patch(
					"production_entry_app.production_entry_app.e2e_api._e2e_base_date",
					return_value="2099-01-10",
				):
					with patch(
						"production_entry_app.production_entry_app.e2e_api.frappe.db.exists",
						return_value=False,
					):
						with patch("production_entry_app.production_entry_app.e2e_api.frappe.db.commit"):
							cleanup_e2e_context(prefix="E2E")
		get_candidates.assert_called_once_with(
			target_operator="E2E Operator",
			target_workstation="E2E Workstation",
			target_fg_item="_E2E_FG_Item",
			target_rm_item="_E2E_RM_Item",
		)

	def test_cleanup_e2e_downtime_entries_deletes_target_workstation_entries(self) -> None:
		targets = {"target_workstation": "E2E Workstation"}
		with patch(
			"production_entry_app.production_entry_app.e2e_api.frappe.get_all",
			return_value=["DT-001"],
		) as get_all:
			with patch(
				"production_entry_app.production_entry_app.e2e_api._safe_force_delete"
			) as force_delete:
				_cleanup_e2e_downtime_entries(targets)

		get_all.assert_called_once_with(
			"Downtime Entry",
			filters={"workstation": "E2E Workstation"},
			pluck="name",
		)
		force_delete.assert_called_once_with("Downtime Entry", "DT-001", context="cleanup_e2e_context")

	def test_cleanup_e2e_context_returns_ok_and_remains_safe_when_repeated(self) -> None:
		with ExitStack() as stack:
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api._get_candidate_e2e_stock_entries",
					return_value=[],
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api._e2e_base_date",
					return_value="2099-01-10",
				)
			)
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.frappe.get_all", return_value=[])
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.db.exists", return_value=False
				)
			)
			restore_settings = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._restore_cached_e2e_settings")
			)
			commit = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.frappe.db.commit")
			)

			first_result = _cleanup_e2e_context(prefix="E2E")
			second_result = _cleanup_e2e_context(prefix="E2E")

		self.assertEqual(first_result, {"ok": True})
		self.assertEqual(second_result, {"ok": True})
		self.assertEqual(restore_settings.call_count, 2)
		self.assertEqual(commit.call_count, 2)

	def test_cleanup_e2e_context_uses_cached_shift_name_before_predicted_names(self) -> None:
		cache_key = _get_e2e_shift_names_cache_key("E2E")

		class _Doc:
			status = "Draft"
			docstatus = 0
			name = "DOC"

			def end_shift(self) -> None:
				return None

			def reload(self) -> None:
				return None

			def cancel(self) -> None:
				return None

		def _get_all(doctype: str, *args, **kwargs):
			if doctype == "Department":
				return ["E2E Department - TC"]
			if doctype == "Shift":
				return ["SHIFT-PREDICTED-2099-01-20.2"]
			return []

		with patch("production_entry_app.production_entry_app.e2e_api._assert_e2e_api_allowed"):
			with patch(
				"production_entry_app.production_entry_app.e2e_api._get_candidate_e2e_stock_entries",
				return_value=[],
			):
				with patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.get_all",
					side_effect=_get_all,
				):
					with patch(
						"production_entry_app.production_entry_app.e2e_api._e2e_base_date",
						return_value="2099-01-20",
					):
						with patch(
							"production_entry_app.production_entry_app.e2e_api.frappe.db.exists",
							side_effect=lambda doctype, name=None, *args, **kwargs: (
								doctype == "Shift"
								and name
								in {
									"SHIFT-CACHED-2099-01-20.1",
									"SHIFT-PREDICTED-2099-01-20.2",
								}
							),
						):
							with patch(
								"production_entry_app.production_entry_app.e2e_api.frappe.get_doc",
								side_effect=lambda *args, **kwargs: _Doc(),
							):
								with patch(
									"production_entry_app.production_entry_app.e2e_api._safe_force_delete"
								) as safe_force_delete:
									with patch(
										"production_entry_app.production_entry_app.e2e_api.frappe.db.commit"
									):
										frappe.cache().set_value(
											cache_key,
											["SHIFT-CACHED-2099-01-20.1"],
										)
										_cleanup_e2e_context(prefix="E2E")

		self.assertEqual(
			[
				call.args[1]
				for call in safe_force_delete.call_args_list
				if call.args and call.args[0] == "Shift"
			],
			["SHIFT-CACHED-2099-01-20.1", "SHIFT-PREDICTED-2099-01-20.2"],
		)

	def test_get_candidate_e2e_stock_entries_filters_to_production_and_distinct(self) -> None:
		results = [{"name": "MAT-STE-0001", "docstatus": 1}]
		with patch("production_entry_app.production_entry_app.e2e_api.frappe.qb.from_") as qb_from:
			query = qb_from.return_value
			query.left_join.return_value = query
			query.on.return_value = query
			query.distinct.return_value = query
			query.select.return_value = query
			query.where.return_value = query
			query.orderby.return_value = query
			query.run.return_value = results

			response = _get_candidate_e2e_stock_entries(
				target_operator="E2E Operator",
				target_workstation="E2E Workstation",
				target_fg_item="_E2E_FG_Item",
				target_rm_item="_E2E_RM_Item",
			)

		self.assertEqual(response, results)
		query.distinct.assert_called_once_with()
		self.assertEqual(query.where.call_count, 2)
		production_filter = str(query.where.call_args_list[0].args[0])
		self.assertIn("purpose", production_filter)
		self.assertIn("custom_pea_is_joint_lh_rh", production_filter)

	def test_item_has_live_stock_entry_references_returns_false_for_blank_and_true_for_query_hit(
		self,
	) -> None:
		self.assertFalse(_item_has_live_stock_entry_references(""))

		class _Query:
			def inner_join(self, *_args, **_kwargs):
				return self

			def on(self, *_args, **_kwargs):
				return self

			def select(self, *_args, **_kwargs):
				return self

			def where(self, *_args, **_kwargs):
				return self

			def limit(self, *_args, **_kwargs):
				return self

			def run(self):
				return [["STE-001"]]

		with patch(
			"production_entry_app.production_entry_app.e2e_api.frappe.qb.from_", return_value=_Query()
		):
			self.assertTrue(_item_has_live_stock_entry_references("_E2E_FG_Item"))

	def test_clear_timeline_cache_deletes_workstation_and_operator_keys(self) -> None:
		from production_entry_app.production_entry_app.e2e_api import _clear_timeline_cache_for_context

		cache = MagicMock()
		previous_user = frappe.session.user
		frappe.session.user = "Administrator"
		try:
			with patch("production_entry_app.production_entry_app.e2e_api.frappe.cache", return_value=cache):
				_clear_timeline_cache_for_context(
					{"workstation": "E2E Workstation", "operator": "E2E Operator"},
					"SHIFT-001",
				)
		finally:
			frappe.session.user = previous_user

		self.assertEqual(cache.delete_keys.call_count, 2)
		cache.delete_keys.assert_any_call("pea:timeline:admin:Workstation:E2E Workstation:SHIFT-001:")
		cache.delete_keys.assert_any_call("pea:timeline:admin:Operator:E2E Operator:SHIFT-001:")

	def test_safe_force_delete_logs_delete_failures(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.e2e_api.frappe.delete_doc",
			side_effect=Exception("delete failed"),
		) as delete_doc:
			with patch("production_entry_app.production_entry_app.e2e_api.frappe.log_error") as log_error:
				_safe_force_delete("Stock Entry", "STE-FAIL", context="cleanup_e2e_context")

		delete_doc.assert_called_once_with("Stock Entry", "STE-FAIL", ignore_permissions=True, force=True)
		log_error.assert_called_once()

	def test_cleanup_e2e_context_keeps_items_with_live_stock_entry_references(self) -> None:
		with ExitStack() as stack:
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api._get_candidate_e2e_stock_entries",
					return_value=[],
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api._e2e_base_date",
					return_value="2099-01-10",
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.db.exists",
					side_effect=lambda doctype, name=None, *args, **kwargs: (
						doctype == "Item" and name in {"_E2E_FG_Item", "_E2E_RM_Item"}
					),
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.get_all",
					side_effect=lambda doctype, *args, **kwargs: [] if doctype != "BOM" else [],
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api._item_has_live_stock_entry_references",
					side_effect=lambda item_code: item_code == "_E2E_FG_Item",
				)
			)
			safe_force_delete = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._safe_force_delete")
			)
			stack.enter_context(patch("production_entry_app.production_entry_app.e2e_api.frappe.db.commit"))

			_cleanup_e2e_context(prefix="E2E")

		deleted_items = [
			call.args[1] for call in safe_force_delete.call_args_list if call.args and call.args[0] == "Item"
		]
		self.assertEqual(deleted_items, ["_E2E_RM_Item"])

	def test_cleanup_e2e_context_covers_running_shift_and_related_submitted_docs(self) -> None:
		running_shift = MagicMock()
		running_shift.status = "Running"
		running_shift.reload.side_effect = lambda: setattr(running_shift, "status", "Completed")
		submitted_stock_entry = frappe._dict(
			{
				"name": "STE-SUBMITTED",
				"docstatus": 1,
				"custom_pea_operator": "Other Operator",
				"items": [frappe._dict({"item_code": "_E2E_RM_Item", "is_finished_item": 0})],
			}
		)
		submitted_stock_entry.cancel = MagicMock(
			side_effect=lambda: submitted_stock_entry.update(docstatus=2)
		)
		failing_stock_entry = frappe._dict(
			{"name": "STE-FAIL-CANCEL", "docstatus": 1, "custom_pea_operator": "E2E Operator", "items": []}
		)
		failing_stock_entry.cancel = MagicMock(side_effect=Exception("cancel failed"))
		draft_stock_entry = frappe._dict(
			{"name": "STE-DRAFT", "docstatus": 0, "custom_pea_operator": "E2E Operator", "items": []}
		)
		skipped_stock_entry = frappe._dict(
			{
				"name": "STE-SKIP",
				"docstatus": 0,
				"custom_pea_operator": "Other Operator",
				"items": [frappe._dict({"item_code": "OTHER", "is_finished_item": 0})],
			}
		)
		maintenance_log = frappe._dict({"name": "LOG-001", "docstatus": 1})
		maintenance_log.cancel = MagicMock(side_effect=lambda: maintenance_log.update(docstatus=2))
		failing_maintenance_log = frappe._dict({"name": "LOG-FAIL", "docstatus": 1})
		failing_maintenance_log.cancel = MagicMock(side_effect=Exception("cancel failed"))
		bom = frappe._dict({"name": "BOM-001", "docstatus": 1})
		bom.cancel = MagicMock(side_effect=lambda: bom.update(docstatus=2))
		failing_bom = frappe._dict({"name": "BOM-FAIL", "docstatus": 1})
		failing_bom.cancel = MagicMock(side_effect=Exception("cancel failed"))

		def _get_all(doctype: str, *args, **kwargs):
			if doctype == "Department":
				return ["E2E Department - TC"]
			if doctype == "Shift":
				return ["SHIFT-RUNNING-001"]
			if doctype == "Die Tool Counter":
				return ["DTC-001"]
			if doctype == "Die Tool Maintenance Log":
				return ["LOG-001", "LOG-FAIL"]
			if doctype == "BOM":
				return ["BOM-001", "BOM-FAIL"]
			return []

		def _exists(doctype: str, name=None, *args, **kwargs):
			if doctype == "Shift":
				return name == "SHIFT-RUNNING-001"
			if doctype in {"Workstation", "Operator", "Item", "Warehouse", "Die Tool Counter"}:
				return True
			return False

		def _get_doc(doctype: str, name=None):
			if doctype == "Shift":
				return running_shift
			if doctype == "Stock Entry":
				return {
					"STE-SUBMITTED": submitted_stock_entry,
					"STE-FAIL-CANCEL": failing_stock_entry,
					"STE-DRAFT": draft_stock_entry,
					"STE-SKIP": skipped_stock_entry,
				}[name]
			if doctype == "Die Tool Maintenance Log":
				return {"LOG-001": maintenance_log, "LOG-FAIL": failing_maintenance_log}[name]
			if doctype == "BOM":
				return {"BOM-001": bom, "BOM-FAIL": failing_bom}[name]
			raise AssertionError(f"Unexpected get_doc: {doctype} {name}")

		with ExitStack() as stack:
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api._get_candidate_e2e_stock_entries",
					return_value=[
						frappe._dict({"name": "STE-SUBMITTED", "docstatus": 1}),
						frappe._dict({"name": "STE-SUBMITTED", "docstatus": 1}),
						frappe._dict({"name": "STE-FAIL-CANCEL", "docstatus": 1}),
						frappe._dict({"name": "STE-DRAFT", "docstatus": 0}),
						frappe._dict({"name": "STE-SKIP", "docstatus": 0}),
					],
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api._e2e_base_date",
					return_value="2099-01-10",
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.get_all", side_effect=_get_all
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.db.exists", side_effect=_exists
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.get_doc", side_effect=_get_doc
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api._item_has_live_stock_entry_references",
					return_value=False,
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.resolve_test_company",
					return_value="_Test Company",
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.db.get_value", return_value="TC"
				)
			)
			safe_force_delete = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._safe_force_delete")
			)
			log_error = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.frappe.log_error")
			)
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._restore_cached_e2e_settings")
			)
			stack.enter_context(patch("production_entry_app.production_entry_app.e2e_api.frappe.db.commit"))

			result = _cleanup_e2e_context(prefix="E2E")

		self.assertEqual(result, {"ok": True})
		running_shift.end_shift.assert_called_once()
		running_shift.reload.assert_called_once()
		submitted_stock_entry.cancel.assert_called_once()
		failing_stock_entry.cancel.assert_called_once()
		maintenance_log.cancel.assert_called_once()
		bom.cancel.assert_called_once()
		self.assertGreaterEqual(safe_force_delete.call_count, 8)
		safe_force_delete.assert_any_call("Stock Entry", "STE-DRAFT", context="cleanup_e2e_context")
		self.assertGreaterEqual(log_error.call_count, 3)

	def test_collect_reserved_e2e_prefixes_derives_item_and_workstation_names(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.e2e_api.frappe.get_all",
			side_effect=[
				["_E2E_SAMPLE_W0_FG_Item", "OTHER_FG_Item"],
				["E2E Workstation", "E2E_SAMPLE_W0 Workstation", "X2E_SAMPLE_W0 Workstation"],
			],
		):
			self.assertEqual(_collect_reserved_e2e_prefixes(), ["E2E", "E2E_SAMPLE_W0"])

	def test_cleanup_reserved_e2e_artifacts_sweeps_prefixes_and_permission_docs(self) -> None:
		with ExitStack() as stack:
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api._collect_reserved_e2e_prefixes",
					return_value=["E2E_SAMPLE_W0"],
				)
			)
			cleanup_prefix = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._cleanup_e2e_context")
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.get_all",
					side_effect=[
						["e2e-user-sample@example.com"],
						["E2E ROLE SAMPLE"],
						["E2E-DOWNTIME-SAMPLE"],
					],
				)
			)
			delete_doc = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.frappe.delete_doc")
			)
			stack.enter_context(patch("production_entry_app.production_entry_app.e2e_api.frappe.db.commit"))

			result = _cleanup_reserved_e2e_artifacts()

		self.assertEqual(result, {"ok": True, "prefixes": ["E2E_SAMPLE_W0"]})
		cleanup_prefix.assert_called_once_with(prefix="E2E_SAMPLE_W0")
		self.assertEqual(delete_doc.call_count, 3)

	def test_cleanup_reserved_e2e_artifacts_wrapper_checks_access_and_guard(self) -> None:
		from production_entry_app.production_entry_app.e2e_api import cleanup_reserved_e2e_artifacts

		with ExitStack() as stack:
			app_access = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._assert_e2e_api_allowed")
			)
			cleanup = stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api._cleanup_reserved_e2e_artifacts",
					return_value={"ok": True, "prefixes": []},
				)
			)

			result = cleanup_reserved_e2e_artifacts()

		self.assertEqual(result, {"ok": True, "prefixes": []})
		app_access.assert_called_once()
		cleanup.assert_called_once()

	def test_safe_cancel_and_delete_handles_missing_submitted_and_exception_paths(self) -> None:
		submitted_doc = MagicMock()
		submitted_doc.name = "DOC-001"
		with ExitStack() as stack:
			exists = stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.db.exists",
					side_effect=[False, True, True],
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.db.get_value",
					side_effect=[1, 1],
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.get_doc",
					side_effect=[submitted_doc, Exception("read failed")],
				)
			)
			force_delete = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._safe_force_delete")
			)
			log_error = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.frappe.log_error")
			)

			_safe_cancel_and_delete("BOM", "MISSING", context="unit-test")
			_safe_cancel_and_delete("BOM", "BOM-001", context="unit-test")
			_safe_cancel_and_delete("BOM", "BOM-ERR", context="unit-test")

		self.assertEqual(exists.call_count, 3)
		submitted_doc.cancel.assert_called_once()
		force_delete.assert_called_once_with("BOM", "BOM-001", context="unit-test")
		log_error.assert_called_once()

	def test_build_e2e_shift_doc_contains_expected_fields(self) -> None:
		doc = _build_e2e_shift_doc(
			base_date="2099-01-20",
			department="E2E Department - TC",
			branch="_Test Branch",
			wip_warehouse="WIP",
			rm_warehouse="RM",
			rejection_warehouse="REJ",
		)
		self.assertEqual(doc["doctype"], "Shift")
		self.assertEqual(doc["department"], "E2E Department - TC")
		self.assertEqual(doc["branch"], "_Test Branch")
		self.assertEqual(doc["shift_date"], "2099-01-20")
		self.assertEqual(doc["work_in_progress_warehouse"], "WIP")
		self.assertEqual(doc["raw_material_warehouse"], "RM")
		self.assertEqual(doc["rejection_warehouse"], "REJ")

	def test_get_or_create_e2e_shift_keeps_running_shift(self) -> None:
		shift = MagicMock()
		shift.status = "Running"
		with patch(
			"production_entry_app.production_entry_app.e2e_api.frappe.get_all",
			return_value=["SHIFT-2099-01-20.1.0001"],
		):
			with patch(
				"production_entry_app.production_entry_app.e2e_api.frappe.get_doc", return_value=shift
			):
				result = _get_or_create_e2e_shift(
					base_date="2099-01-20",
					department="E2E Department - TC",
					branch="_Test Branch",
					wip_warehouse="WIP",
					rm_warehouse="RM",
					rejection_warehouse="REJ",
				)
		self.assertIs(result, shift)
		shift.start_shift.assert_not_called()

	def test_get_or_create_e2e_shift_reuses_legacy_named_shift_by_fields(self) -> None:
		shift = MagicMock()
		shift.status = "Running"
		with patch(
			"production_entry_app.production_entry_app.e2e_api.frappe.get_all",
			return_value=["SHIFT-2099-01-20.Shift-1"],
		):
			with patch(
				"production_entry_app.production_entry_app.e2e_api.frappe.get_doc", return_value=shift
			):
				result = _get_or_create_e2e_shift(
					base_date="2099-01-20",
					department="E2E Department - TC",
					branch="_Test Branch",
					wip_warehouse="WIP",
					rm_warehouse="RM",
					rejection_warehouse="REJ",
				)
		self.assertIs(result, shift)
		shift.start_shift.assert_not_called()

	def test_get_or_create_e2e_shift_starts_draft_shift(self) -> None:
		shift = MagicMock()
		shift.status = "Draft"
		with patch(
			"production_entry_app.production_entry_app.e2e_api.frappe.get_all",
			return_value=["SHIFT-2099-01-20.1.0001"],
		):
			with patch(
				"production_entry_app.production_entry_app.e2e_api.frappe.get_doc", return_value=shift
			):
				result = _get_or_create_e2e_shift(
					base_date="2099-01-20",
					department="E2E Department - TC",
					branch="_Test Branch",
					wip_warehouse="WIP",
					rm_warehouse="RM",
					rejection_warehouse="REJ",
				)
		self.assertIs(result, shift)
		shift.start_shift.assert_called_once()

	def test_get_or_create_e2e_shift_recreates_completed_shift(self) -> None:
		existing = MagicMock()
		existing.status = "Completed"
		recreated = MagicMock()
		recreated.status = "Draft"
		doc_builder = MagicMock()
		doc_builder.insert.return_value = recreated

		with patch(
			"production_entry_app.production_entry_app.e2e_api.frappe.get_all",
			return_value=["SHIFT-2099-01-20.1.0001"],
		):
			with patch(
				"production_entry_app.production_entry_app.e2e_api.frappe.get_doc",
				side_effect=[existing, doc_builder],
			):
				with patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.delete_doc"
				) as delete_doc:
					result = _get_or_create_e2e_shift(
						base_date="2099-01-20",
						department="E2E Department - TC",
						branch="_Test Branch",
						wip_warehouse="WIP",
						rm_warehouse="RM",
						rejection_warehouse="REJ",
					)

		delete_doc.assert_called_once_with(
			"Shift", "SHIFT-2099-01-20.1.0001", force=True, ignore_permissions=True
		)
		self.assertIs(result, recreated)
		recreated.start_shift.assert_called_once()

	def test_get_or_create_e2e_shift_creates_when_missing_and_rejects_unexpected_status(self) -> None:
		created = MagicMock()
		created.status = "Draft"
		builder = MagicMock()
		builder.insert.return_value = created

		with patch("production_entry_app.production_entry_app.e2e_api.frappe.get_all", return_value=[]):
			with patch(
				"production_entry_app.production_entry_app.e2e_api.frappe.get_doc", return_value=builder
			):
				result = _get_or_create_e2e_shift(
					base_date="2099-01-20",
					department="E2E Department - TC",
					branch="_Test Branch",
					wip_warehouse="WIP",
					rm_warehouse="RM",
					rejection_warehouse="REJ",
				)

		self.assertIs(result, created)
		created.start_shift.assert_called_once()

		invalid = MagicMock()
		invalid.status = "Paused"
		with patch(
			"production_entry_app.production_entry_app.e2e_api.frappe.get_all",
			return_value=["SHIFT-2099-01-20.1.0001"],
		):
			with patch(
				"production_entry_app.production_entry_app.e2e_api.frappe.get_doc", return_value=invalid
			):
				with self.assertRaisesRegex(frappe.ValidationError, "Unexpected Shift status"):
					_get_or_create_e2e_shift(
						base_date="2099-01-20",
						department="E2E Department - TC",
						branch="_Test Branch",
						wip_warehouse="WIP",
						rm_warehouse="RM",
						rejection_warehouse="REJ",
					)

	def test_get_or_create_e2e_employee_reuses_existing_employee(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.e2e_api.frappe.db.get_value",
			return_value="HR-EMP-001",
		):
			self.assertEqual(_get_or_create_e2e_employee("E2E", "_Test Company"), "HR-EMP-001")

	def test_get_or_create_e2e_employee_inserts_missing_employee(self) -> None:
		inserted = MagicMock()
		inserted.name = "HR-EMP-NEW"
		doc_builder = MagicMock()
		doc_builder.insert.return_value = inserted

		with patch(
			"production_entry_app.production_entry_app.e2e_api.frappe.db.get_value", return_value=None
		):
			with patch(
				"production_entry_app.production_entry_app.e2e_api.frappe.get_doc",
				return_value=doc_builder,
			) as get_doc:
				result = _get_or_create_e2e_employee("E2E", "_Test Company")

		self.assertEqual(result, "HR-EMP-NEW")
		get_doc.assert_called_once()
		self.assertEqual(get_doc.call_args.args[0]["employee_number"], "E2E-EMP")
		doc_builder.insert.assert_called_once_with(ignore_permissions=True)

	def test_complete_other_running_e2e_shifts_marks_only_other_reserved_departments_completed(self) -> None:
		with patch(
			"production_entry_app.production_entry_app.e2e_api.frappe.get_all",
			side_effect=[
				["E2E Department - TC", "E2E Other Department - TC"],
				["SHIFT-OTHER-001"],
			],
		):
			with patch("production_entry_app.production_entry_app.e2e_api.frappe.db.set_value") as set_value:
				from production_entry_app.production_entry_app.e2e_api import (
					_complete_other_running_e2e_shifts,
				)

				_complete_other_running_e2e_shifts(keep_department="E2E Department - TC")

		set_value.assert_called_once_with(
			"Shift",
			"SHIFT-OTHER-001",
			"status",
			"Completed",
			update_modified=False,
		)

	def test_bootstrap_e2e_context_re_enables_die_tool_flag_for_fg_item(self) -> None:
		shift = MagicMock()
		shift.name = "SHIFT-2099-01-20.1.0001"

		def _get_meta(doctype: str, cached: bool = True):
			if doctype == "Warehouse":
				return _meta_stub(True)
			if doctype == "Item":
				return _meta_stub(True)
			return _meta_stub(False)

		with ExitStack() as stack:
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._assert_e2e_api_allowed")
			)
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.cleanup_running_shifts")
			)
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._ensure_e2e_settings_fields_loaded")
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.resolve_test_company",
					return_value="_Test Company",
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.resolve_test_branch",
					return_value="_Test Branch",
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.ensure_branch",
					return_value="_Test Branch",
				)
			)
			_patch_bootstrap_settings_reads(stack)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.ensure_warehouse",
					side_effect=["WIP", "RM", "FG", "REJ"],
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.ensure_item",
					side_effect=[
						"_FG_ITEM",
						"_RM_ITEM",
						"_E2E-DIE_Joint_LH_Item",
						"_E2E-DIE_Joint_RH_Item",
						"_E2E-DIE_Joint_RM_Item",
						"_E2E-DIE_Joint_Scrap_Item",
					],
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.get_meta",
					side_effect=_get_meta,
				)
			)
			set_value = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.frappe.db.set_value")
			)
			stack.enter_context(patch("production_entry_app.production_entry_app.e2e_api.ensure_operator"))
			stack.enter_context(patch("production_entry_app.production_entry_app.e2e_api.ensure_workstation"))
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.ensure_rejection_reason")
			)
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.ensure_downtime_reason")
			)
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.frappe.db.set_single_value")
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.ensure_default_bom",
					return_value="BOM-001",
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api._ensure_e2e_joint_bom",
					side_effect=["BOM-JOINT-LH", "BOM-JOINT-RH"],
				)
			)
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.ensure_fiscal_year_for_date")
			)
			stack.enter_context(patch("production_entry_app.production_entry_app.e2e_api.ensure_stock"))
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api._e2e_base_date",
					return_value="2099-01-20",
				)
			)
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._complete_other_running_e2e_shifts")
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api._get_or_create_e2e_shift",
					return_value=shift,
				)
			)
			stack.enter_context(patch("production_entry_app.production_entry_app.e2e_api.frappe.db.commit"))
			bootstrap_e2e_context(prefix="E2E-DIE")

		set_value.assert_any_call("Item", "_FG_ITEM", "custom_pea_has_die_tool", 1, update_modified=False)

	def test_bootstrap_e2e_context_passes_branch_to_shift_creation(self) -> None:
		shift = MagicMock()
		shift.name = "SHIFT-2099-01-20.1.0001"

		def _get_meta(doctype: str, cached: bool = True):
			if doctype in {"Warehouse", "Item"}:
				return _meta_stub(True)
			return _meta_stub(False)

		with ExitStack() as stack:
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._assert_e2e_api_allowed")
			)
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.cleanup_running_shifts")
			)
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._ensure_e2e_settings_fields_loaded")
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.resolve_test_company",
					return_value="_Test Company",
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.resolve_test_branch",
					return_value="_Test Branch",
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.ensure_branch",
					return_value="_Test Branch",
				)
			)
			_patch_bootstrap_settings_reads(stack)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.ensure_warehouse",
					side_effect=["WIP", "RM", "FG", "REJ"],
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.ensure_item",
					side_effect=[
						"_FG_ITEM",
						"_RM_ITEM",
						"_E2E_Joint_LH_Item",
						"_E2E_Joint_RH_Item",
						"_E2E_Joint_RM_Item",
						"_E2E_Joint_Scrap_Item",
					],
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.get_meta",
					side_effect=_get_meta,
				)
			)
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.frappe.db.set_value")
			)
			stack.enter_context(patch("production_entry_app.production_entry_app.e2e_api.ensure_operator"))
			stack.enter_context(patch("production_entry_app.production_entry_app.e2e_api.ensure_workstation"))
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.ensure_rejection_reason")
			)
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.ensure_downtime_reason")
			)
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.frappe.db.set_single_value")
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.ensure_default_bom",
					return_value="BOM-001",
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api._ensure_e2e_joint_bom",
					side_effect=["BOM-JOINT-LH", "BOM-JOINT-RH"],
				)
			)
			ensure_fiscal_year = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.ensure_fiscal_year_for_date")
			)
			ensure_stock = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.ensure_stock")
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.ensure_department",
					return_value="E2E Department - TC",
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api._e2e_base_date",
					return_value="2099-01-20",
				)
			)
			complete_other = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._complete_other_running_e2e_shifts")
			)
			get_or_create = stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api._get_or_create_e2e_shift",
					return_value=shift,
				)
			)
			stack.enter_context(patch("production_entry_app.production_entry_app.e2e_api.frappe.db.commit"))
			bootstrap_e2e_context(prefix="E2E")

		complete_other.assert_called_once_with(keep_department="E2E Department - TC")
		ensure_fiscal_year.assert_called_once_with("2099-01-20")
		ensure_stock.assert_any_call(
			"_RM_ITEM", "WIP", "_Test Company", target_qty=1000, posting_date="2099-01-20"
		)
		ensure_stock.assert_any_call(
			"_E2E_Joint_RM_Item",
			"WIP",
			"_Test Company",
			target_qty=1000,
			posting_date="2099-01-20",
		)
		self.assertEqual(ensure_stock.call_count, 2)
		get_or_create.assert_called_once_with(
			base_date="2099-01-20",
			department="E2E Department - TC",
			branch="_Test Branch",
			wip_warehouse="WIP",
			rm_warehouse="RM",
			rejection_warehouse="REJ",
		)

	def test_set_e2e_system_float_precision_updates_settings_and_commits(self) -> None:
		with ExitStack() as stack:
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._assert_e2e_api_allowed")
			)
			cache_snapshot = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._cache_e2e_settings_snapshot")
			)
			set_single_value = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.frappe.db.set_single_value")
			)
			clear_cache = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.frappe.clear_cache")
			)
			commit = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.frappe.db.commit")
			)

			result = set_e2e_system_float_precision(prefix="E2E-FLOAT", precision="4")

		self.assertEqual(result, {"float_precision": 4})
		cache_snapshot.assert_called_once_with("E2E-FLOAT")
		set_single_value.assert_called_once_with("System Settings", "float_precision", 4)
		clear_cache.assert_called_once()
		commit.assert_called_once()

	def test_create_e2e_submitted_stock_entry_appends_rejection_breakup_and_returns_doc(self) -> None:
		shift = MagicMock()
		shift.name = "SHIFT-001"
		shift.branch = "_Test Branch"
		shift.shift_date = "2099-01-20"
		doc = MagicMock()
		doc.name = "MAT-STE-001"
		doc.branch = "_Test Branch"
		doc.docstatus = 1
		doc.get.return_value = [
			frappe._dict({"is_finished_item": 0, "s_warehouse": None, "t_warehouse": None}),
			frappe._dict({"is_finished_item": 1, "s_warehouse": None, "t_warehouse": None}),
		]
		with ExitStack() as stack:
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._assert_e2e_api_allowed")
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.bootstrap_e2e_context",
					return_value={
						"company": "_Test Company",
						"bom": "BOM-001",
						"wip_warehouse": "WIP",
						"fg_warehouse": "FG",
						"shift_name": "SHIFT-001",
						"operator": "E2E Operator",
						"workstation": "E2E Workstation",
					},
				)
			)
			get_doc = stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.get_doc",
					side_effect=[shift, doc],
				)
			)
			clear_timeline_cache = stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._clear_timeline_cache_for_context")
			)
			stack.enter_context(patch("production_entry_app.production_entry_app.e2e_api.frappe.db.commit"))

			result = create_e2e_submitted_stock_entry(
				prefix="E2E", rejection_qty=4, actual_end_time="10:30:00"
			)

		self.assertEqual(
			result,
			{
				"name": "MAT-STE-001",
				"docstatus": 1,
				"posting_date": "2099-01-20",
				"shift_name": "SHIFT-001",
				"branch": "_Test Branch",
			},
		)
		doc_payload = get_doc.call_args_list[1].args[0]
		self.assertEqual(get_doc.call_args_list[0].args, ("Shift", "SHIFT-001"))
		self.assertEqual(doc_payload["custom_pea_shift"], "SHIFT-001")
		self.assertEqual(doc_payload["posting_date"], "2099-01-20")
		self.assertEqual(doc_payload["custom_pea_actual_end_date"], "2099-01-20 10:30:00")
		self.assertEqual(doc_payload["posting_time"], "10:30:00")
		self.assertEqual(doc_payload["set_posting_time"], 1)
		doc.get_items.assert_called_once()
		doc.append.assert_called_once_with(
			"custom_pea_rejection_breakup", {"rejection_reason": "Burr", "qty": 4.0}
		)
		doc.insert.assert_called_once_with(ignore_permissions=True)
		doc.submit.assert_called_once()
		clear_timeline_cache.assert_called_once()

	def test_insert_e2e_full_shift_stock_entry_does_not_mutate_payload(self) -> None:
		payload = {
			"doctype": "Stock Entry",
			"stock_entry_type": "Manufacture",
			"purpose": "Manufacture",
			"company": "_Test Company",
			"from_bom": 1,
			"bom_no": "BOM-001",
			"from_warehouse": "WIP",
			"to_warehouse": "FG",
			"fg_completed_qty": 100,
			"custom_pea_shift": "SHIFT-001",
			"custom_pea_operator": "E2E Operator",
			"custom_pea_workstation": "E2E Workstation",
			"custom_pea_rejection_qty": 0.0,
			"custom_pea_actual_start_date": "2099-01-20 08:00:00",
			"custom_pea_actual_end_date": "2099-01-20 08:30:00",
			"posting_date": "2099-01-20",
			"posting_time": "08:30:00",
			"_pea_wip_warehouse": "WIP",
			"_pea_fg_warehouse": "FG",
			"_pea_rejection_qty": 0,
		}
		original_payload = dict(payload)
		doc = MagicMock()
		doc.name = "MAT-STE-FULL-001"
		doc.get.return_value = [
			frappe._dict({"is_finished_item": 1, "s_warehouse": None, "t_warehouse": None})
		]

		with patch(
			"production_entry_app.production_entry_app.e2e_api.frappe.get_doc", return_value=doc
		) as get_doc:
			result = _insert_e2e_full_shift_stock_entry(payload)

		self.assertEqual(result, "MAT-STE-FULL-001")
		self.assertEqual(payload, original_payload)
		get_doc_payload = get_doc.call_args.args[0]
		self.assertNotIn("_pea_wip_warehouse", get_doc_payload)
		self.assertNotIn("_pea_fg_warehouse", get_doc_payload)
		self.assertNotIn("_pea_rejection_qty", get_doc_payload)
		doc.get_items.assert_called_once()
		doc.insert.assert_called_once_with(ignore_permissions=True)
		doc.submit.assert_called_once()

	def test_create_e2e_full_shift_stock_entries_creates_contiguous_entries(self) -> None:
		shift = MagicMock()
		shift.shift_date = "2099-01-20"
		shift.planned_start_time = "08:00:00"
		shift.planned_end_time = "09:00:00"
		shift.shift_end_date = "2099-01-20"
		shift.shift_duration = "8"
		first_doc = MagicMock()
		first_doc.name = "MAT-STE-FULL-001"
		first_doc.get.return_value = [
			frappe._dict({"is_finished_item": 1, "s_warehouse": None, "t_warehouse": None})
		]
		second_doc = MagicMock()
		second_doc.name = "MAT-STE-FULL-002"
		second_doc.get.return_value = [
			frappe._dict({"is_finished_item": 1, "s_warehouse": None, "t_warehouse": None})
		]
		with ExitStack() as stack:
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._assert_e2e_api_allowed")
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.bootstrap_e2e_context",
					return_value={
						"company": "_Test Company",
						"bom": "BOM-001",
						"wip_warehouse": "WIP",
						"fg_warehouse": "FG",
						"shift_name": "SHIFT-001",
						"operator": "E2E Operator",
						"workstation": "E2E Workstation",
					},
				)
			)
			get_doc = stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.get_doc",
					side_effect=[shift, first_doc, second_doc],
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.get_shift_planned_end_datetime",
					return_value=frappe.utils.get_datetime("2099-01-20 09:00:00"),
				)
			)
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._clear_timeline_cache_for_context")
			)
			stack.enter_context(patch("production_entry_app.production_entry_app.e2e_api.frappe.db.commit"))

			result = create_e2e_full_shift_stock_entries(prefix="E2E", slot_minutes=30, rejection_qty=0)

		self.assertTrue(set(result).issuperset({"shift_name", "stock_entries"}))
		self.assertTrue(result["shift_name"])
		self.assertIsInstance(result["stock_entries"], list)
		self.assertEqual(result["count"], 2)
		self.assertEqual(result["stock_entries"], ["MAT-STE-FULL-001", "MAT-STE-FULL-002"])
		self.assertEqual(result["slot_minutes"], 30)
		first_payload = get_doc.call_args_list[1].args[0]
		second_payload = get_doc.call_args_list[2].args[0]
		self.assertEqual(first_payload["custom_pea_actual_start_date"], "2099-01-20 08:00:00")
		self.assertEqual(first_payload["custom_pea_actual_end_date"], "2099-01-20 08:30:00")
		self.assertEqual(first_payload["set_posting_time"], 1)
		self.assertEqual(first_payload["posting_date"], "2099-01-20")
		self.assertEqual(second_payload["custom_pea_actual_start_date"], "2099-01-20 08:30:00")
		self.assertEqual(second_payload["custom_pea_actual_end_date"], "2099-01-20 09:00:00")
		self.assertEqual(second_payload["set_posting_time"], 1)
		self.assertEqual(second_payload["posting_date"], "2099-01-20")
		first_doc.get_items.assert_called_once()
		second_doc.get_items.assert_called_once()
		first_doc.append.assert_not_called()
		second_doc.append.assert_not_called()
		first_doc.insert.assert_called_once_with(ignore_permissions=True)
		second_doc.insert.assert_called_once_with(ignore_permissions=True)
		first_doc.submit.assert_called_once()
		second_doc.submit.assert_called_once()

	def test_create_e2e_full_shift_stock_entries_rejects_invalid_shift_window(self) -> None:
		shift = MagicMock()
		shift.shift_date = "2099-01-20"
		shift.planned_start_time = "08:00:00"
		shift.planned_end_time = "08:00:00"
		shift.shift_end_date = "2099-01-20"
		shift.shift_duration = "8"
		with ExitStack() as stack:
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._assert_e2e_api_allowed")
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.bootstrap_e2e_context",
					return_value={"shift_name": "SHIFT-001"},
				)
			)
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api.frappe.get_doc", return_value=shift)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.get_shift_planned_end_datetime",
					return_value=frappe.utils.get_datetime("2099-01-20 08:00:00"),
				)
			)

			with self.assertRaisesRegex(frappe.ValidationError, "Invalid shift window"):
				create_e2e_full_shift_stock_entries(prefix="E2E")

	def test_get_items_with_rejection_base_rows_match_native(self) -> None:
		from production_entry_app.production_entry_app import api
		from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
			bootstrap_manufacture_masters,
			direct_manufacture_doc_dict,
		)

		masters = bootstrap_manufacture_masters()
		doc_dict = direct_manufacture_doc_dict(masters, fg_qty=100, rejection_qty=0)

		native = frappe.new_doc("Stock Entry")
		native.update({k: v for k, v in doc_dict.items() if k != "custom_pea_rejection_qty"})
		native.from_bom = 1
		native.get_items()
		native_codes = sorted(r.item_code for r in native.items)

		api_rows = api.get_items_with_rejection(json.dumps(doc_dict))
		api_codes = sorted(r["item_code"] for r in api_rows)

		self.assertEqual(api_codes, native_codes)  # rejection_qty=0 => no extra row

	def test_get_shift_summary_denies_without_read_perm(self) -> None:
		from production_entry_app.production_entry_app.doctype.shift.shift import get_shift_summary
		from production_entry_app.production_entry_app.utils.test_bootstrap import (
			ensure_branch,
			ensure_department,
			resolve_test_branch,
			resolve_test_company,
		)

		company = resolve_test_company()
		shift = frappe.get_doc(
			{
				"doctype": "Shift",
				"company": company,
				"department": ensure_department(
					f"API Shift Summary {frappe.generate_hash(length=6)}",
					company=company,
				),
				"branch": ensure_branch(resolve_test_branch() or "_Test Branch"),
				"shift_label": "1",
				"shift_duration": "8",
				"shift_date": "2026-07-10",
				"planned_start_time": "08:00:00",
			}
		).insert(ignore_permissions=True)
		user_email = f"test_shift_summary_denied_{frappe.generate_hash(length=6)}@example.com"
		_ensure_user_with_exact_roles(user_email, ("Manufacturing User",))

		try:
			frappe.set_user(user_email)
			with self.assertRaises(frappe.PermissionError):
				get_shift_summary(shift.name)
		finally:
			frappe.set_user("Administrator")

	def test_get_items_with_rejection_denies_without_stock_entry_create_perm(self) -> None:
		from production_entry_app.production_entry_app import api
		from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
			bootstrap_manufacture_masters,
			direct_manufacture_doc_dict,
		)

		masters = bootstrap_manufacture_masters()
		doc_dict = direct_manufacture_doc_dict(masters, fg_qty=100, rejection_qty=0)
		user_email = f"test_items_rejection_denied_{frappe.generate_hash(length=6)}@example.com"
		_ensure_user_with_exact_roles(user_email, ("PEA Read Only",))

		try:
			frappe.set_user(user_email)
			with self.assertRaises(frappe.PermissionError):
				api.get_items_with_rejection(json.dumps(doc_dict))
		finally:
			frappe.set_user("Administrator")

	def test_get_items_with_rejection_rejects_non_object_json(self) -> None:
		from production_entry_app.production_entry_app import api

		with self.assertRaises(frappe.ValidationError):
			api.get_items_with_rejection('["Stock Entry"]')

	def test_get_items_with_rejection_denies_inaccessible_linked_bom(self) -> None:
		from production_entry_app.production_entry_app import api

		with patch(
			"production_entry_app.production_entry_app.api.frappe.has_permission",
			side_effect=[True, False],
		):
			with self.assertRaises(frappe.PermissionError):
				api.get_items_with_rejection(json.dumps({"doctype": "Stock Entry", "bom_no": "BOM-HIDDEN"}))

	def test_get_items_with_rejection_local_temp_name_uses_create_perm(self) -> None:
		from production_entry_app.production_entry_app import api
		from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
			bootstrap_manufacture_masters,
			direct_manufacture_doc_dict,
		)

		masters = bootstrap_manufacture_masters()
		doc_dict = direct_manufacture_doc_dict(masters, fg_qty=100, rejection_qty=0)
		doc_dict["name"] = "new-stock-entry-1"
		doc_dict["__islocal"] = 1
		user_email = f"test_items_local_temp_denied_{frappe.generate_hash(length=6)}@example.com"
		_ensure_user_with_exact_roles(user_email, ("PEA Read Only",))

		try:
			frappe.set_user(user_email)
			with self.assertRaises(frappe.PermissionError):
				api.get_items_with_rejection(json.dumps(doc_dict))
		finally:
			frappe.set_user("Administrator")

	def test_reset_die_tool_counter_denied_for_read_only(self) -> None:
		from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
			bootstrap_manufacture_masters,
		)

		masters = bootstrap_manufacture_masters()
		_seed_die_tool_counter(masters["fg_item"], current_stroke_count=200, stroke_capacity=1000)
		user_email = f"test_reset_die_tool_readonly_{frappe.generate_hash(length=6)}@example.com"
		_ensure_user_with_exact_roles(user_email, ("PEA Read Only",))

		try:
			frappe.set_user(user_email)
			with self.assertRaises(frappe.PermissionError):
				reset_die_tool_counter(masters["fg_item"], "2026-05-03 10:00:00")
		finally:
			frappe.set_user("Administrator")

	def test_reset_die_tool_counter_denied_without_submit_perm(self) -> None:
		from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
			bootstrap_manufacture_masters,
		)

		masters = bootstrap_manufacture_masters()
		_seed_die_tool_counter(masters["fg_item"], current_stroke_count=200, stroke_capacity=1000)
		role_name = f"PEA Die Tool Create Only {frappe.generate_hash(length=6)}"
		user_email = f"test_reset_die_tool_create_only_{frappe.generate_hash(length=6)}@example.com"
		_ensure_user_with_exact_roles(user_email, (role_name,))
		_set_role_docperm(
			"Die Tool Maintenance Log",
			role_name,
			read=1,
			write=1,
			create=1,
			submit=0,
		)

		try:
			frappe.set_user(user_email)
			self.assertTrue(frappe.has_permission("Die Tool Maintenance Log", "read"))
			self.assertTrue(frappe.has_permission("Die Tool Maintenance Log", "write"))
			self.assertTrue(frappe.has_permission("Die Tool Maintenance Log", "create"))
			self.assertFalse(frappe.has_permission("Die Tool Maintenance Log", "submit"))
			with self.assertRaises(frappe.PermissionError):
				reset_die_tool_counter(masters["fg_item"], "2026-05-03 10:00:00")
		finally:
			frappe.set_user("Administrator")
			_clear_role_docperm("Die Tool Maintenance Log", role_name)

	def test_create_e2e_downtime_entry_normalizes_unknown_stop_reason(self) -> None:
		shift = MagicMock()
		shift.shift_date = "2099-01-20"
		doc = MagicMock()
		doc.name = "DT-001"
		builder = MagicMock()
		builder.insert.return_value = doc
		with ExitStack() as stack:
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._assert_e2e_api_allowed")
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.bootstrap_e2e_context",
					return_value={
						"company": "_Test Company",
						"shift_name": "SHIFT-001",
						"workstation": "E2E Workstation",
					},
				)
			)
			stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api._get_or_create_e2e_employee",
					return_value="HR-EMP-001",
				)
			)
			get_doc = stack.enter_context(
				patch(
					"production_entry_app.production_entry_app.e2e_api.frappe.get_doc",
					side_effect=[shift, builder],
				)
			)
			stack.enter_context(
				patch("production_entry_app.production_entry_app.e2e_api._clear_timeline_cache_for_context")
			)
			stack.enter_context(patch("production_entry_app.production_entry_app.e2e_api.frappe.db.commit"))

			result = create_e2e_downtime_entry(prefix="E2E", stop_reason="Unsupported")

		self.assertEqual(
			result, {"name": "DT-001", "workstation": "E2E Workstation", "shift_name": "SHIFT-001"}
		)
		self.assertEqual(get_doc.call_args_list[1].args[0]["stop_reason"], "Other")
		builder.insert.assert_called_once_with(ignore_permissions=True)


def _ensure_user_with_exact_roles(email: str, roles: tuple[str, ...]) -> None:
	unique_roles = tuple(dict.fromkeys(roles))
	for role in unique_roles:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = email.split("@", 1)[0]
		user.user_type = "System User"
	user.set("roles", [])
	for role in unique_roles:
		user.append("roles", {"role": role})
	save_test_user(user)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed so permission checks see role changes
	frappe.clear_cache(user=email)


def _set_role_docperm(doctype: str, role: str, **permissions: int) -> None:
	from frappe.permissions import setup_custom_perms

	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)

	setup_custom_perms(doctype)
	existing_name = frappe.db.get_value(
		"Custom DocPerm",
		{"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0},
		"name",
	)
	if existing_name:
		docperm = frappe.get_doc("Custom DocPerm", existing_name)
	else:
		docperm = frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": doctype,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role,
				"permlevel": 0,
			}
		)

	for ptype in ("read", "write", "create", "delete", "submit", "cancel", "amend", "report"):
		setattr(docperm, ptype, int(permissions.get(ptype, 0)))

	docperm.save(ignore_permissions=True)

	frappe.clear_cache(doctype=doctype)
	frappe.clear_cache(user=frappe.session.user)


def _clear_role_docperm(doctype: str, role: str) -> None:
	for name in frappe.get_all(
		"Custom DocPerm",
		filters={"parent": doctype, "role": role, "permlevel": 0},
		pluck="name",
	):
		frappe.delete_doc("Custom DocPerm", name, ignore_permissions=True, force=True)
	frappe.clear_cache(doctype=doctype)
	frappe.clear_cache(user=frappe.session.user)


def _seed_die_tool_counter(item_code: str, *, current_stroke_count: float, stroke_capacity: float) -> None:
	if frappe.db.exists("Die Tool Counter", item_code):
		frappe.db.set_value(
			"Die Tool Counter",
			item_code,
			{
				"current_stroke_count": current_stroke_count,
				"stroke_capacity": stroke_capacity,
			},
			update_modified=False,
		)
		return
	frappe.get_doc(
		{
			"doctype": "Die Tool Counter",
			"die_tool_item": item_code,
			"current_stroke_count": current_stroke_count,
			"stroke_capacity": stroke_capacity,
		}
	).insert(ignore_permissions=True)
