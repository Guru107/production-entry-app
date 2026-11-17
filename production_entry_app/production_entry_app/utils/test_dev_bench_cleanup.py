from __future__ import annotations

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.utils import dev_bench_cleanup


class TestDevBenchCleanup(FrappeTestCase):
	def test_should_run_false_for_ephemeral_site(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.utils.dev_bench_cleanup.is_ephemeral_site_name",
				return_value=True,
			),
			patch.dict("os.environ", {}, clear=False),
			patch.dict(dev_bench_cleanup.frappe.conf, {"allow_e2e_tests": 1}, clear=False),
		):
			self.assertFalse(dev_bench_cleanup.should_run_persistent_dev_cleanup())

	def test_should_run_false_in_ci(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.utils.dev_bench_cleanup.is_ephemeral_site_name",
				return_value=False,
			),
			patch.dict("os.environ", {"CI": "true"}, clear=False),
			patch.dict(dev_bench_cleanup.frappe.conf, {"allow_e2e_tests": 1}, clear=False),
		):
			self.assertFalse(dev_bench_cleanup.should_run_persistent_dev_cleanup())

	def test_should_run_true_on_local_persistent_dev_site(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.utils.dev_bench_cleanup.is_ephemeral_site_name",
				return_value=False,
			),
			patch.dict("os.environ", {"CI": ""}, clear=False),
			patch.dict(
				dev_bench_cleanup.frappe.conf, {"allow_e2e_tests": 1, "developer_mode": 1}, clear=False
			),
		):
			self.assertTrue(dev_bench_cleanup.should_run_persistent_dev_cleanup())

	def test_should_run_false_without_allow_e2e_tests(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.utils.dev_bench_cleanup.is_ephemeral_site_name",
				return_value=False,
			),
			patch.dict("os.environ", {}, clear=False),
			patch.dict(dev_bench_cleanup.frappe.conf, {"allow_e2e_tests": 0}, clear=False),
		):
			self.assertFalse(dev_bench_cleanup.should_run_persistent_dev_cleanup())

	def test_cleanup_if_applicable_skips_when_not_persistent_dev(self) -> None:
		with (
			patch.object(dev_bench_cleanup, "should_run_persistent_dev_cleanup", return_value=False),
			patch.object(dev_bench_cleanup, "cleanup_persistent_dev_site_test_data") as cleanup,
		):
			result = dev_bench_cleanup.cleanup_persistent_dev_site_if_applicable()
		self.assertIsNone(result)
		cleanup.assert_not_called()

	def test_cleanup_if_applicable_runs_full_cleanup(self) -> None:
		expected = {"deleted_users": 3}
		with (
			patch.object(dev_bench_cleanup, "should_run_persistent_dev_cleanup", return_value=True),
			patch.object(
				dev_bench_cleanup,
				"cleanup_persistent_dev_site_test_data",
				return_value=expected,
			) as cleanup,
		):
			result = dev_bench_cleanup.cleanup_persistent_dev_site_if_applicable()
		self.assertEqual(result, expected)
		cleanup.assert_called_once_with()

	def test_should_run_false_without_developer_mode(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.utils.dev_bench_cleanup.is_ephemeral_site_name",
				return_value=False,
			),
			patch.dict("os.environ", {"CI": ""}, clear=False),
			patch.dict(
				dev_bench_cleanup.frappe.conf, {"allow_e2e_tests": 1, "developer_mode": 0}, clear=False
			),
		):
			self.assertFalse(dev_bench_cleanup.should_run_persistent_dev_cleanup())

	def test_failed_cancel_never_raw_deletes_a_submitted_stock_entry(self) -> None:
		with (
			patch.object(dev_bench_cleanup.frappe.db, "exists", return_value=True),
			patch.object(dev_bench_cleanup.frappe.db, "get_value", return_value=1),
			patch.object(dev_bench_cleanup.frappe, "log_error") as log_error,
			patch.object(
				dev_bench_cleanup.e2e_api,
				"_safe_cancel_and_delete",
				side_effect=RuntimeError("negative stock"),
			),
			patch.object(dev_bench_cleanup.e2e_api, "_delete_e2e_stock_entry_rows") as raw_delete,
		):
			dev_bench_cleanup._cancel_delete_stock_entries(["MAT-STE-1"])

		raw_delete.assert_not_called()
		log_error.assert_called_once()

	def test_failed_cancel_raw_deletes_a_non_submitted_stock_entry(self) -> None:
		with (
			patch.object(dev_bench_cleanup.frappe.db, "exists", return_value=True),
			patch.object(dev_bench_cleanup.frappe.db, "get_value", return_value=0),
			patch.object(
				dev_bench_cleanup.e2e_api, "_safe_cancel_and_delete", side_effect=RuntimeError("boom")
			),
			patch.object(dev_bench_cleanup.e2e_api, "_delete_e2e_stock_entry_rows") as raw_delete,
		):
			dev_bench_cleanup._cancel_delete_stock_entries(["MAT-STE-1"])

		raw_delete.assert_called_once_with("MAT-STE-1")

	def test_purge_scopes_downtime_entries_to_e2e_workstations_or_future_dates(self) -> None:
		captured: dict[str, object] = {}

		def fake_get_all(doctype: str, *args: object, **kwargs: object) -> list[str]:
			if doctype == "Downtime Entry":
				captured.update(kwargs)
				return []
			return []

		with (
			patch.object(dev_bench_cleanup, "_ensure_fiscal_years_for_test_stock_entries"),
			patch.object(dev_bench_cleanup, "_cancel_delete_stock_entries"),
			patch.object(dev_bench_cleanup, "_stock_entries_with_test_items", return_value=[]),
			patch.object(dev_bench_cleanup.frappe, "get_all", side_effect=fake_get_all),
		):
			dev_bench_cleanup._purge_future_transactional_data()

		self.assertEqual(
			captured["or_filters"],
			{
				"workstation": ["like", "E2E%"],
				"from_time": [">=", dev_bench_cleanup._PERSISTENT_DEV_TEST_DATE_CUTOFF],
			},
		)
