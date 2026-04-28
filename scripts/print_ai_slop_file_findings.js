#!/usr/bin/env node
const fs = require("fs");
const target = process.argv[2];
if (!target) {
	console.error("Usage: node scripts/print_ai_slop_file_findings.js <path-fragment>");
	process.exit(2);
}
const raw = fs.readFileSync("reports/ai-slop-report.json", "utf8");
const end = raw.lastIndexOf("\n[JS/TS Analysis]");
const report = JSON.parse((end >= 0 ? raw.slice(0, end) : raw).trim());
const files = [...(report.file_results || []), ...(report.js_file_results || [])];
const match = files.find((file) => String(file.file_path || file.file || "").includes(target));
if (!match) {
	console.log(JSON.stringify({ found: false, target }, null, 2));
	process.exit(0);
}
console.log(JSON.stringify(match, null, 2));
