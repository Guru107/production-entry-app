/**
 * Centralized routing utility for Frappe v15/v16 compatibility.
 *
 * Frappe v15 uses /app/ route prefix (e.g., /app/shift/new)
 * Frappe v16 uses /desk/ route prefix (e.g., /desk/shift/new)
 *
 * Usage:
 *   const { getRoute, getRoutePrefix } = require("./utils/routing");
 *   await page.goto(getRoute("/shift/new"));
 *   await expect(page).toHaveURL(getRouteRegex("/shift/"));
 *
 * Environment variable PLAYWRIGHT_ROUTE_PREFIX controls the prefix:
 *   - Set to "app" for Frappe v15 (default)
 *   - Set to "desk" for Frappe v16
 */

const ROUTE_PREFIX = process.env.PLAYWRIGHT_ROUTE_PREFIX || "app";
// v15's desk has a Home workspace at /home; v16 replaced it with Setup > Home.
const HOME_PATH = ROUTE_PREFIX === "desk" ? "/setup/home" : "/home";

function escapeRegexLiteral(value) {
	return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Get the full route path with the correct prefix.
 * @param {string} path - Path starting with /, e.g., "/home" or "/shift/new"
 * @returns {string} Full URL path with prefix, e.g., "/app/shift/new"
 */
function getRoute(path) {
	return `/${ROUTE_PREFIX}${path === "/home" ? HOME_PATH : path}`;
}

/**
 * Get the current route prefix (app or desk).
 * @returns {string} The route prefix
 */
function getRoutePrefix() {
	return ROUTE_PREFIX;
}

/**
 * Create a regex pattern for URL matching with the correct prefix.
 *
 * v16 nests list pages inside their module workspace (e.g. /desk/production-entry-app/shift
 * instead of /app/shift), so on v16 an optional single module segment is accepted. Form
 * routes stay flat on both versions (/app/shift/<name>, /desk/shift/<name>).
 *
 * @param {string} pathPattern - Path pattern starting with /, e.g., "/shift/"
 * @returns {RegExp} Regex that matches URLs with the current prefix
 */
function getRouteRegex(pathPattern) {
	const path = escapeRegexLiteral(pathPattern);
	if (ROUTE_PREFIX === "desk") {
		return new RegExp(`\\/${ROUTE_PREFIX}(\\/[a-z0-9-]+)*${path}`);
	}
	return new RegExp(`\\/${ROUTE_PREFIX}${path}`);
}

module.exports = {
	escapeRegexLiteral,
	getRoute,
	getRoutePrefix,
	getRouteRegex,
	HOME_PATH,
	ROUTE_PREFIX,
};
