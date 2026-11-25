"""Create or update the "RM Batch Trace" Script Report on a host site through the REST API.

Usage (from the repo root):
    python host_reports/rm_batch_trace/publish.py --target staging
    python host_reports/rm_batch_trace/publish.py --target production

Credentials come from ERPNEXT_STAGING_BASE_URL / _API_KEY / _API_SECRET (staging) or
ERPNEXT_BASE_URL / ERPNEXT_API_KEY / ERPNEXT_API_SECRET (production). The API user needs
the Script Manager role. There is no default target, so production is never hit by accident.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_PREFIX: dict[str, str] = {"staging": "ERPNEXT_STAGING_", "production": "ERPNEXT_"}


def build_report_payload() -> dict:
	"""Report document fields: report.json plus the server script and the filter JavaScript."""
	payload = json.loads((HERE / "report.json").read_text())
	payload["report_script"] = (HERE / "rm_batch_trace.py").read_text()
	payload["javascript"] = (HERE / "rm_batch_trace.js").read_text()
	return payload


def _request(method: str, url: str, token: str, body: dict | None = None) -> tuple[int, dict]:
	data = json.dumps(body).encode() if body is not None else None
	request = urllib.request.Request(
		url,
		data=data,
		method=method,
		headers={"Authorization": f"token {token}", "Content-Type": "application/json"},
	)
	try:
		with urllib.request.urlopen(request, timeout=60) as response:
			return response.status, json.loads(response.read() or b"{}")
	except urllib.error.HTTPError as error:
		return error.code, json.loads(error.read() or b"{}")


def publish(target: str) -> str:
	prefix = ENV_PREFIX[target]
	try:
		base_url = os.environ[f"{prefix}BASE_URL"].rstrip("/")
		token = f"{os.environ[prefix + 'API_KEY']}:{os.environ[prefix + 'API_SECRET']}"
	except KeyError as missing:
		sys.exit(f"Missing environment variable {missing} for target {target}.")

	payload = build_report_payload()
	name = urllib.parse.quote(payload["report_name"])
	status, _body = _request("GET", f"{base_url}/api/resource/Report/{name}", token)
	if status == 200:
		status, body = _request("PUT", f"{base_url}/api/resource/Report/{name}", token, payload)
		action = "updated"
	elif status == 404:
		status, body = _request("POST", f"{base_url}/api/resource/Report", token, payload)
		action = "created"
	else:
		sys.exit(f"Could not read Report on {target}: HTTP {status}")
	if status != 200:
		sys.exit(f"Publishing to {target} failed: HTTP {status} {json.dumps(body)[:1000]}")
	return f"Report '{payload['report_name']}' {action} on {target} ({base_url})."


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	parser.add_argument("--target", required=True, choices=sorted(ENV_PREFIX))
	print(publish(parser.parse_args().target))


if __name__ == "__main__":
	main()
