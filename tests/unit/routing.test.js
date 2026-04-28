const test = require("node:test");
const assert = require("node:assert/strict");

function loadRouting(prefix) {
	if (prefix === null || prefix === undefined) {
		delete process.env.PLAYWRIGHT_ROUTE_PREFIX;
	} else {
		process.env.PLAYWRIGHT_ROUTE_PREFIX = prefix;
	}
	delete require.cache[require.resolve("../e2e/utils/routing")];
	return require("../e2e/utils/routing");
}

test("getRoute uses the default app prefix", async () => {
	const { getRoute } = loadRouting(null);

	assert.equal(getRoute("/home"), "/app/home");
});

test("getRouteRegex escapes literal path characters", async () => {
	const { getRouteRegex } = loadRouting("desk");

	const literalRegex = getRouteRegex("/stock-entry/ITEM-1.2");

	assert.equal(literalRegex.test("/desk/stock-entry/ITEM-1.2"), true);
	assert.equal(literalRegex.test("/desk/stock-entry/ITEM-1x2"), false);
});

test("escapeRegexLiteral escapes multiple regex metacharacters", async () => {
	const { escapeRegexLiteral } = loadRouting("desk");

	const escaped = escapeRegexLiteral("SHIFT-1.2+$");
	const literalRegex = new RegExp(escaped);

	assert.equal(literalRegex.test("SHIFT-1.2+$"), true);
	assert.equal(literalRegex.test("SHIFT-1x2++"), false);
});
