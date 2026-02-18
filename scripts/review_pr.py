"""
PR Review Agent for production_entry_app.

Reviews pull request diffs against project standards defined in CLAUDE.md:
- TDD compliance (tests required for all new features)
- Frappe best practices (frappe.throw, frappe.db, frappe.qb)
- No raw SQL
- Code style (tabs, 110-char lines)
- Security hygiene

Usage (standalone):
    python scripts/review_pr.py \
        --repo Guru107/production_entry_app \
        --pr-number 42 \
        --diff-file /tmp/pr.diff \
        --pr-title "Add new feature"

Environment variables:
    ANTHROPIC_API_KEY  - Claude API key (required)
    GITHUB_TOKEN       - GitHub token for posting comments (required for posting)
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import ClassVar

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ReviewComment:
	"""A single review comment produced by the agent."""

	severity: str  # "error" | "warning" | "info"
	category: str  # e.g. "testing", "frappe-practices", "performance"
	body: str
	filename: str = ""

	_SEVERITY_LABELS: ClassVar[dict[str, str]] = {
		"error": "🔴 Error",
		"warning": "🟡 Warning",
		"info": "🔵 Info",
	}

	def format(self) -> str:
		label = self._SEVERITY_LABELS.get(self.severity, f"[{self.severity}]")
		parts = [f"**{label}** ({self.category})"]
		if self.filename:
			parts.append(f"`{self.filename}`")
		parts.append(self.body)
		return " — ".join(parts)


@dataclass
class ParsedFile:
	"""Represents one file extracted from a unified diff."""

	filename: str
	added_lines: list[str] = field(default_factory=list)
	removed_lines: list[str] = field(default_factory=list)
	is_test: bool = False


# ---------------------------------------------------------------------------
# Diff parsing
# ---------------------------------------------------------------------------


def parse_diff_files(diff: str) -> list[dict]:
	"""
	Parse a unified diff string and return a list of file dicts.

	Each dict has:
	    filename   str
	    added_lines list[str]
	    removed_lines list[str]
	    is_test    bool
	"""
	if not diff or not diff.strip():
		return []

	files: list[dict] = []
	current: dict | None = None

	for line in diff.splitlines():
		if line.startswith("diff --git "):
			# Commit current file
			if current is not None:
				files.append(current)
			# Extract filename from "diff --git a/foo b/foo"
			match = re.search(r" b/(.+)$", line)
			filename = match.group(1) if match else ""
			is_test = (
				os.path.basename(filename).startswith("test_")
				or os.path.basename(filename).endswith("_test.py")
				or "/test" in filename
			)
			current = {
				"filename": filename,
				"added_lines": [],
				"removed_lines": [],
				"is_test": is_test,
			}
		elif current is not None:
			if line.startswith("+") and not line.startswith("+++"):
				current["added_lines"].append(line[1:])
			elif line.startswith("-") and not line.startswith("---"):
				current["removed_lines"].append(line[1:])

	if current is not None:
		files.append(current)

	return files


# ---------------------------------------------------------------------------
# Static checks (rule-based, no API required)
# ---------------------------------------------------------------------------


class PRReviewAgent:
	"""Agent that reviews a PR diff using static checks and the Claude API."""

	def __init__(self, api_key: str, github_token: str = ""):
		self.api_key = api_key
		self.github_token = github_token

	# ------------------------------------------------------------------
	# Public interface
	# ------------------------------------------------------------------

	def review(self, diff: str, pr_title: str, pr_number: int) -> str:
		"""
		Review a PR diff and return a formatted review body (Markdown string).

		Raises RuntimeError/HTTPError if the Claude API call fails.
		"""
		files = parse_diff_files(diff)
		static_comments = self.run_static_checks(files)

		prompt = build_review_prompt(diff, pr_title=pr_title, pr_number=pr_number)
		ai_review = call_claude_api(prompt=prompt, api_key=self.api_key)

		return _format_full_review(ai_review=ai_review, static_comments=static_comments, pr_number=pr_number)

	# ------------------------------------------------------------------
	# Static analysis
	# ------------------------------------------------------------------

	def run_static_checks(self, files: list[dict]) -> list[ReviewComment]:
		"""Run rule-based checks; return list of ReviewComment objects."""
		if not files:
			return []

		comments: list[ReviewComment] = []
		source_files = [f for f in files if not f["is_test"]]
		test_files = [f for f in files if f["is_test"]]
		test_filenames = {f["filename"] for f in test_files}

		for f in source_files:
			added = f["added_lines"]
			if not added:
				continue

			filename = f["filename"]

			# 1. Detect new method/function definitions without corresponding test changes
			new_defs = [
				line.strip()
				for line in added
				if re.match(r"\s*def \w+", line) and not line.strip().startswith("#")
			]
			if new_defs and not test_filenames:
				comments.append(
					ReviewComment(
						severity="error",
						category="testing",
						body=(
							"This PR adds new code but includes no test file changes. "
							"Per project guidelines, **all features must have tests** and "
							"coverage must remain above 90%. Please add or update tests."
						),
						filename=filename,
					)
				)

			# 2. Detect raw SQL via frappe.db.sql
			raw_sql_lines = [line for line in added if "frappe.db.sql(" in line]
			if raw_sql_lines:
				comments.append(
					ReviewComment(
						severity="warning",
						category="frappe-practices",
						body=(
							"Avoid raw SQL (`frappe.db.sql`). "
							"Use `frappe.get_list()`, `frappe.db.get_value()`, or `frappe.qb` "
							"(Query Builder) for complex queries as per project conventions."
						),
						filename=filename,
					)
				)

			# 3. Detect bare raise instead of frappe.throw
			bare_raise_lines = [
				line
				for line in added
				if re.search(r"\braise\s+(ValueError|Exception|RuntimeError|TypeError|AssertionError)", line)
			]
			if bare_raise_lines:
				comments.append(
					ReviewComment(
						severity="error",
						category="frappe-practices",
						body=(
							"Use `frappe.throw(_('...'))` for validation errors instead of bare `raise`. "
							"This ensures proper localisation and user-friendly error messages."
						),
						filename=filename,
					)
				)

			# 4. Detect direct status field assignment (Shift status machine violation)
			if "shift" in filename.lower() and "test" not in filename.lower():
				direct_status = [
					line
					for line in added
					if re.search(r'self\.status\s*=\s*["\']', line)
					and "flags.allow_status_change" not in line
				]
				if direct_status:
					comments.append(
						ReviewComment(
							severity="error",
							category="architecture",
							body=(
								"Direct assignment to `self.status` bypasses the state-machine guard. "
								"Use `_transition_status()` which sets `flags.allow_status_change = True` "
								"before saving."
							),
							filename=filename,
						)
					)

		return comments


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_REVIEW_SYSTEM_PROMPT = """\
You are a senior code reviewer for a Frappe Framework v15 / ERPNext application
called production_entry_app. Your role is to review pull request diffs and provide
clear, actionable feedback that helps the author ship high-quality, maintainable code.

Project standards (from CLAUDE.md):
- Test-Driven Development: tests must be written FIRST; coverage must stay above 90%.
- Every feature or bug fix must include test cases.
- Use frappe.throw(_("...")) for validation errors — never bare raise.
- Use frappe.get_list(), frappe.db.get_value(), frappe.qb for DB access — no raw SQL.
- Tabs for indentation; Python line length 110 chars; Python 3.10+ syntax.
- Status transitions on the Shift document must go through _transition_status(), not
  direct field assignment.
- All user-facing strings must be wrapped with _() / __() for translation.
- Tests extend FrappeTestCase; use frappe.tests.utils helpers.

Review format:
1. Start with a one-paragraph summary of what the PR does.
2. List any REQUIRED changes (blocking issues) as a numbered list.
3. List any SUGGESTED improvements (non-blocking) as a numbered list.
4. End with an overall assessment: APPROVED, APPROVED_WITH_SUGGESTIONS, or CHANGES_REQUIRED.

Be concise. Reference specific file names and line content when possible.
Do not repeat issues already flagged in the static analysis section.
"""


def build_review_prompt(diff: str, pr_title: str, pr_number: int) -> str:
	"""Build the user-turn prompt for the Claude API call."""
	diff_section = diff[:12000] if len(diff) > 12000 else diff  # Stay within context
	return (
		f"Please review PR #{pr_number}: **{pr_title}**\n\n"
		"The following static checks have already been applied (do not duplicate them).\n"
		"Focus on logic correctness, architecture quality, test adequacy, and "
		"adherence to Frappe best practices.\n\n"
		f"## Diff\n\n```diff\n{diff_section}\n```"
	)


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------


def call_claude_api(prompt: str, api_key: str, model: str = "claude-opus-4-6") -> str:
	"""
	Call the Anthropic Messages API and return the assistant's text response.

	Raises RuntimeError on non-2xx responses.
	"""
	url = "https://api.anthropic.com/v1/messages"
	payload = {
		"model": model,
		"max_tokens": 1024,
		"system": _REVIEW_SYSTEM_PROMPT,
		"messages": [{"role": "user", "content": prompt}],
	}
	data = json.dumps(payload).encode()
	req = urllib.request.Request(
		url,
		data=data,
		headers={
			"Content-Type": "application/json",
			"x-api-key": api_key,
			"anthropic-version": "2023-06-01",
		},
		method="POST",
	)
	try:
		with urllib.request.urlopen(req) as resp:
			body = json.loads(resp.read().decode())
			return body["content"][0]["text"]
	except urllib.error.HTTPError as exc:
		error_body = exc.read().decode() if exc.fp else ""
		raise RuntimeError(f"Anthropic API error {exc.code}: {error_body}") from exc


# ---------------------------------------------------------------------------
# Comment posting
# ---------------------------------------------------------------------------


def post_pr_comment(repo: str, pr_number: int, body: str, github_token: str) -> None:
	"""Post a comment on a GitHub/Gitea pull request via the API."""
	# Support both GitHub and local Gitea proxy
	base_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
	url = f"{base_url}/repos/{repo}/issues/{pr_number}/comments"
	payload = json.dumps({"body": body}).encode()
	req = urllib.request.Request(
		url,
		data=payload,
		headers={
			"Content-Type": "application/json",
			"Authorization": f"Bearer {github_token}",
			"Accept": "application/vnd.github+json",
			"X-GitHub-Api-Version": "2022-11-28",
		},
		method="POST",
	)
	with urllib.request.urlopen(req) as resp:
		resp.read()  # consume response


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_full_review(ai_review: str, static_comments: list[ReviewComment], pr_number: int) -> str:
	"""Combine static-check results and AI review into a single Markdown body."""
	parts: list[str] = [
		"## 🤖 Automated PR Review",
		f"_Review for PR #{pr_number} — generated by the production_entry_app review agent_",
		"",
	]

	if static_comments:
		parts.append("### Static Analysis Findings")
		parts.append("")
		for comment in static_comments:
			parts.append(f"- {comment.format()}")
		parts.append("")

	parts.append("### AI Review")
	parts.append("")
	parts.append(ai_review)

	return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="PR Review Agent for production_entry_app")
	parser.add_argument("--repo", required=True, help="GitHub repo in owner/name format")
	parser.add_argument("--pr-number", required=True, type=int, help="Pull request number")
	parser.add_argument("--pr-title", required=True, help="Pull request title")
	parser.add_argument("--diff-file", required=True, help="Path to unified diff file")
	parser.add_argument("--no-post", action="store_true", help="Print review instead of posting")
	return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
	args = _parse_args(argv)

	api_key = os.environ.get("ANTHROPIC_API_KEY", "")
	github_token = os.environ.get("GITHUB_TOKEN", "")

	if not api_key:
		print("ERROR: ANTHROPIC_API_KEY environment variable is not set.", file=sys.stderr)
		return 1

	try:
		with open(args.diff_file) as fh:
			diff = fh.read()
	except OSError as exc:
		print(f"ERROR: Cannot read diff file: {exc}", file=sys.stderr)
		return 1

	agent = PRReviewAgent(api_key=api_key, github_token=github_token)

	try:
		review_body = agent.review(diff=diff, pr_title=args.pr_title, pr_number=args.pr_number)
	except RuntimeError as exc:
		print(f"ERROR: Review failed: {exc}", file=sys.stderr)
		return 1

	if args.no_post or not github_token:
		print(review_body)
		return 0

	try:
		post_pr_comment(
			repo=args.repo,
			pr_number=args.pr_number,
			body=review_body,
			github_token=github_token,
		)
		print(f"✓ Review posted to PR #{args.pr_number}")
	except urllib.error.HTTPError as exc:
		print(f"ERROR: Failed to post comment: HTTP {exc.code}", file=sys.stderr)
		return 1

	return 0


if __name__ == "__main__":
	sys.exit(main())
