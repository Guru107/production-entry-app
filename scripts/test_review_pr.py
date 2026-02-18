"""
Tests for PR review agent.
Run with: python -m pytest scripts/test_review_pr.py -v
"""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from scripts.review_pr import (
	PRReviewAgent,
	ReviewComment,
	build_review_prompt,
	parse_diff_files,
	post_pr_comment,
)

SAMPLE_DIFF_WITH_TESTS = """\
diff --git a/production_entry_app/production_entry_app/doctype/shift/shift.py b/production_entry_app/production_entry_app/doctype/shift/shift.py
index abc123..def456 100644
--- a/production_entry_app/production_entry_app/doctype/shift/shift.py
+++ b/production_entry_app/production_entry_app/doctype/shift/shift.py
@@ -100,6 +100,15 @@ class Shift(Document):
+	def new_feature(self):
+		\"\"\"New feature implementation.\"\"\"
+		frappe.throw(_("Validation error"))
+
diff --git a/production_entry_app/production_entry_app/doctype/shift/test_shift.py b/production_entry_app/production_entry_app/doctype/shift/test_shift.py
index abc123..def456 100644
--- a/production_entry_app/production_entry_app/doctype/shift/test_shift.py
+++ b/production_entry_app/production_entry_app/doctype/shift/test_shift.py
@@ -500,6 +500,12 @@ class TestShift(FrappeTestCase):
+	def test_new_feature(self):
+		\"\"\"Test new feature.\"\"\"
+		shift = make_shift()
+		self.assertRaises(frappe.ValidationError, shift.new_feature)
"""

SAMPLE_DIFF_MISSING_TESTS = """\
diff --git a/production_entry_app/production_entry_app/doctype/shift/shift.py b/production_entry_app/production_entry_app/doctype/shift/shift.py
index abc123..def456 100644
--- a/production_entry_app/production_entry_app/doctype/shift/shift.py
+++ b/production_entry_app/production_entry_app/doctype/shift/shift.py
@@ -100,6 +100,15 @@ class Shift(Document):
+	def new_feature_no_test(self):
+		\"\"\"New feature without tests.\"\"\"
+		return frappe.db.get_value("Shift", self.name, "status")
"""

SAMPLE_DIFF_WITH_RAW_SQL = """\
diff --git a/production_entry_app/production_entry_app/api.py b/production_entry_app/production_entry_app/api.py
index abc123..def456 100644
--- a/production_entry_app/production_entry_app/api.py
+++ b/production_entry_app/production_entry_app/api.py
@@ -50,6 +50,10 @@ def get_data():
+	result = frappe.db.sql("SELECT * FROM tabShift WHERE status = 'Running'")
+	return result
"""

SAMPLE_DIFF_RAISE_INSTEAD_OF_THROW = """\
diff --git a/production_entry_app/production_entry_app/doctype/shift/shift.py b/production_entry_app/production_entry_app/doctype/shift/shift.py
index abc123..def456 100644
--- a/production_entry_app/production_entry_app/doctype/shift/shift.py
+++ b/production_entry_app/production_entry_app/doctype/shift/shift.py
@@ -100,6 +100,10 @@ class Shift(Document):
+	def bad_validation(self):
+		if not self.name:
+			raise ValueError("Name is required")
"""


class TestParseDiffFiles(unittest.TestCase):
	def test_parse_returns_list_of_changed_files(self):
		files = parse_diff_files(SAMPLE_DIFF_WITH_TESTS)
		filenames = [f["filename"] for f in files]
		self.assertIn(
			"production_entry_app/production_entry_app/doctype/shift/shift.py",
			filenames,
		)
		self.assertIn(
			"production_entry_app/production_entry_app/doctype/shift/test_shift.py",
			filenames,
		)

	def test_parse_empty_diff_returns_empty_list(self):
		files = parse_diff_files("")
		self.assertEqual(files, [])

	def test_parse_captures_added_lines(self):
		files = parse_diff_files(SAMPLE_DIFF_WITH_TESTS)
		shift_file = next(
			f for f in files if f["filename"].endswith("shift.py") and "test_" not in f["filename"]
		)
		added = "\n".join(shift_file["added_lines"])
		self.assertIn("new_feature", added)

	def test_parse_identifies_test_files(self):
		files = parse_diff_files(SAMPLE_DIFF_WITH_TESTS)
		test_files = [f for f in files if f["is_test"]]
		self.assertEqual(len(test_files), 1)
		self.assertIn("test_shift.py", test_files[0]["filename"])


class TestStaticChecks(unittest.TestCase):
	def setUp(self):
		self.agent = PRReviewAgent(api_key="test-key", github_token="gh-test")

	def test_detects_missing_tests_for_new_code(self):
		files = parse_diff_files(SAMPLE_DIFF_MISSING_TESTS)
		comments = self.agent.run_static_checks(files)
		issues = [c for c in comments if "test" in c.body.lower()]
		self.assertTrue(len(issues) > 0, "Should flag missing tests")

	def test_no_missing_test_warning_when_tests_present(self):
		files = parse_diff_files(SAMPLE_DIFF_WITH_TESTS)
		comments = self.agent.run_static_checks(files)
		# Should not flag missing tests when test file is modified
		missing_test_issues = [
			c for c in comments if "no test" in c.body.lower() or "missing test" in c.body.lower()
		]
		self.assertEqual(len(missing_test_issues), 0)

	def test_detects_raw_sql_usage(self):
		files = parse_diff_files(SAMPLE_DIFF_WITH_RAW_SQL)
		comments = self.agent.run_static_checks(files)
		sql_issues = [c for c in comments if "sql" in c.body.lower()]
		self.assertTrue(len(sql_issues) > 0, "Should flag raw SQL usage")

	def test_detects_raise_instead_of_frappe_throw(self):
		files = parse_diff_files(SAMPLE_DIFF_RAISE_INSTEAD_OF_THROW)
		comments = self.agent.run_static_checks(files)
		raise_issues = [c for c in comments if "frappe.throw" in c.body.lower()]
		self.assertTrue(len(raise_issues) > 0, "Should flag bare raise instead of frappe.throw")

	def test_empty_diff_produces_no_static_issues(self):
		files = parse_diff_files("")
		comments = self.agent.run_static_checks(files)
		self.assertEqual(comments, [])


class TestBuildReviewPrompt(unittest.TestCase):
	def test_prompt_includes_diff(self):
		prompt = build_review_prompt(SAMPLE_DIFF_WITH_TESTS, pr_title="Add new feature", pr_number=42)
		self.assertIn("new_feature", prompt)

	def test_prompt_includes_frappe_guidelines(self):
		prompt = build_review_prompt(SAMPLE_DIFF_WITH_TESTS, pr_title="Add new feature", pr_number=42)
		self.assertIn("frappe.throw", prompt.lower())

	def test_prompt_includes_pr_title(self):
		prompt = build_review_prompt(SAMPLE_DIFF_MISSING_TESTS, pr_title="Fix shift validation", pr_number=7)
		self.assertIn("Fix shift validation", prompt)

	def test_prompt_includes_test_requirement(self):
		prompt = build_review_prompt(SAMPLE_DIFF_MISSING_TESTS, pr_title="Some fix", pr_number=3)
		self.assertIn("test", prompt.lower())


class TestPRReviewAgent(unittest.TestCase):
	def setUp(self):
		self.agent = PRReviewAgent(api_key="test-key", github_token="gh-test")

	@patch("scripts.review_pr.call_claude_api")
	def test_review_returns_review_comment(self, mock_api):
		mock_api.return_value = "This PR looks good. Tests are present. No issues found."
		result = self.agent.review(
			diff=SAMPLE_DIFF_WITH_TESTS,
			pr_title="Add new feature",
			pr_number=42,
		)
		self.assertIsInstance(result, str)
		self.assertTrue(len(result) > 0)
		mock_api.assert_called_once()

	@patch("scripts.review_pr.call_claude_api")
	def test_review_includes_static_check_results(self, mock_api):
		mock_api.return_value = "Code review analysis complete."
		result = self.agent.review(
			diff=SAMPLE_DIFF_MISSING_TESTS,
			pr_title="Feature without tests",
			pr_number=99,
		)
		# Static checks should flag missing tests and be included in output
		self.assertIn("test", result.lower())

	@patch("scripts.review_pr.call_claude_api")
	def test_review_handles_empty_diff(self, mock_api):
		mock_api.return_value = "No changes to review."
		result = self.agent.review(
			diff="",
			pr_title="Empty PR",
			pr_number=1,
		)
		self.assertIsInstance(result, str)

	@patch("scripts.review_pr.call_claude_api")
	def test_review_propagates_api_error(self, mock_api):
		mock_api.side_effect = RuntimeError("API rate limit exceeded")
		with self.assertRaises(RuntimeError):
			self.agent.review(
				diff=SAMPLE_DIFF_WITH_TESTS,
				pr_title="Some PR",
				pr_number=5,
			)


class TestPostPRComment(unittest.TestCase):
	@patch("urllib.request.urlopen")
	def test_post_comment_sends_correct_request(self, mock_urlopen):
		mock_response = MagicMock()
		mock_response.read.return_value = json.dumps({"id": 123}).encode()
		mock_response.__enter__ = lambda s: s
		mock_response.__exit__ = MagicMock(return_value=False)
		mock_urlopen.return_value = mock_response

		post_pr_comment(
			repo="Guru107/production_entry_app",
			pr_number=42,
			body="Test review comment",
			github_token="gh-test-token",
		)

		mock_urlopen.assert_called_once()
		request = mock_urlopen.call_args[0][0]
		self.assertIn("42", request.full_url)
		payload = json.loads(request.data.decode())
		self.assertEqual(payload["body"], "Test review comment")

	@patch("urllib.request.urlopen")
	def test_post_comment_raises_on_http_error(self, mock_urlopen):
		import urllib.error

		mock_urlopen.side_effect = urllib.error.HTTPError(
			url="http://test", code=403, msg="Forbidden", hdrs=None, fp=None
		)
		with self.assertRaises(urllib.error.HTTPError):
			post_pr_comment(
				repo="Guru107/production_entry_app",
				pr_number=1,
				body="Comment",
				github_token="bad-token",
			)


class TestReviewComment(unittest.TestCase):
	def test_review_comment_has_required_fields(self):
		comment = ReviewComment(
			severity="warning",
			category="testing",
			body="Missing tests for new feature",
			filename="shift.py",
		)
		self.assertEqual(comment.severity, "warning")
		self.assertEqual(comment.category, "testing")
		self.assertIn("Missing tests", comment.body)

	def test_review_comment_format_includes_severity_emoji(self):
		comment = ReviewComment(
			severity="error",
			category="frappe-practices",
			body="Use frappe.throw() instead of raise",
			filename="shift.py",
		)
		formatted = comment.format()
		self.assertIn("error", formatted.lower())

	def test_review_comment_warning_severity(self):
		comment = ReviewComment(
			severity="warning",
			category="performance",
			body="Consider using frappe.qb for this query",
			filename="api.py",
		)
		formatted = comment.format()
		self.assertIn("warning", formatted.lower())


if __name__ == "__main__":
	unittest.main()
