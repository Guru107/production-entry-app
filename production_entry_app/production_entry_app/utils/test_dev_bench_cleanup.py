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
			patch.dict("os.environ", {}, clear=False),
			patch.dict(dev_bench_cleanup.frappe.conf, {"allow_e2e_tests": 1}, clear=False),
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
