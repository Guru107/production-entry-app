function e2ePrefix(testInfo) {
	const worker = String(testInfo.workerIndex ?? 0);
	const file = testInfo.titlePath[1] || "spec";
	const slug = file
		.toUpperCase()
		.replace(/[^A-Z0-9]+/g, "_")
		.replace(/^_+|_+$/g, "")
		.slice(0, 24);
	return `E2E_${slug}_W${worker}`;
}

module.exports = { e2ePrefix };
