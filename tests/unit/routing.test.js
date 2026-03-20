const test = require("node:test");
const assert = require("node:assert/strict");

test("getRouteRegex escapes literal path characters", async () => {
	process.env.PLAYWRIGHT_ROUTE_PREFIX = "desk";
	delete require.cache[require.resolve("../e2e/utils/routing")];
	const { getRouteRegex } = require("../e2e/utils/routing");

	const literalRegex = getRouteRegex("/stock-entry/ITEM-1.2");

	assert.equal(literalRegex.test("/desk/stock-entry/ITEM-1.2"), true);
	assert.equal(literalRegex.test("/desk/stock-entry/ITEM-1x2"), false);
});
