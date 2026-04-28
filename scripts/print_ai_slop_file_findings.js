#!/usr/bin/env node
const path = require("path");
const fs = require("fs");
const target = process.argv[2];
if (!target) {
	console.error("Usage: node scripts/print_ai_slop_file_findings.js <path-fragment>");
	process.exit(2);
}
const reportPath = path.resolve(__dirname, "..", "reports", "ai-slop-report.json");
let report;
try {
	if (!fs.existsSync(reportPath)) {
		throw new Error("file does not exist");
	}
	const raw = fs.readFileSync(reportPath, "utf8");
	const end = raw.lastIndexOf("\n[JS/TS Analysis]");
	report = JSON.parse((end >= 0 ? raw.slice(0, end) : raw).trim());
} catch (error) {
	console.error(`Failed to read/parse ${reportPath}: ${error.message}`);
	process.exit(1);
}
const fileResults = Array.isArray(report?.file_results) ? report.file_results : [];
const jsFileResults = Array.isArray(report?.js_file_results) ? report.js_file_results : [];
const files = [...fileResults, ...jsFileResults];
const match = files.find((file) => String(file?.file_path ?? file?.file ?? "").includes(target));
if (!match) {
	console.log(JSON.stringify({ found: false, target }, null, 2));
	process.exit(0);
}
console.log(JSON.stringify(match, null, 2));
