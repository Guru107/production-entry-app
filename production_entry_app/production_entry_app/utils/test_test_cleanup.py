from __future__ import annotations

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.utils import test_cleanup


class TestTestCleanup(FrappeTestCase):
	def test_install_test_run_cleanup_wraps_frappe_test_case_once(self) -> None:
		original_run = FrappeTestCase.run
		original_flag = getattr(FrappeTestCase, "_pea_cleanup_installed", None)
		self.addCleanup(setattr, FrappeTestCase, "run", original_run)
		if original_flag is None:
			self.addCleanup(lambda: delattr(FrappeTestCase, "_pea_cleanup_installed"))
		else:
			self.addCleanup(setattr, FrappeTestCase, "_pea_cleanup_installed", original_flag)

		with patch("frappe.tests.utils.FrappeTestCase.run", autospec=True) as original_run:
			if hasattr(FrappeTestCase, "_pea_cleanup_installed"):
				delattr(FrappeTestCase, "_pea_cleanup_installed")
			test_cleanup._ORIGINAL_FRAPPE_TEST_CASE_RUN = None

			test_cleanup.install_test_run_cleanup()
			test_cleanup.install_test_run_cleanup()

		self.assertTrue(getattr(FrappeTestCase, "_pea_cleanup_installed", False))
		self.assertIs(test_cleanup._ORIGINAL_FRAPPE_TEST_CASE_RUN, original_run)
		self.assertNotEqual(FrappeTestCase.run, original_run)

	def test_cleanup_after_python_test_retries_and_logs(self) -> None:
		with (
			patch("production_entry_app.production_entry_app.utils.test_cleanup.frappe.db.rollback"),
			patch("production_entry_app.production_entry_app.utils.test_cleanup.frappe.db.commit"),
			patch(
				"production_entry_app.production_entry_app.utils.test_cleanup.restore_manufacturing_settings_snapshot"
			),
			patch(
				"production_entry_app.production_entry_app.utils.test_cleanup.cleanup_reserved_test_data",
				side_effect=[Exception("boom"), Exception("boom")],
			),
			patch("production_entry_app.production_entry_app.utils.test_cleanup.frappe.log_error") as log_error,
		):
			test_cleanup.cleanup_after_python_test({"shift_wip_warehouse": "WIP"})

		log_error.assert_called_once()
