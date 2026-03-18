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

/**
 * Get the full route path with the correct prefix.
 * @param {string} path - Path starting with /, e.g., "/home" or "/shift/new"
 * @returns {string} Full URL path with prefix, e.g., "/app/shift/new"
 */
function getRoute(path) {
	return `/${ROUTE_PREFIX}${path}`;
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
 * @param {string} pathPattern - Path pattern starting with /, e.g., "/shift/"
 * @returns {RegExp} Regex that matches URLs with the current prefix
 */
function getRouteRegex(pathPattern) {
	return new RegExp(`\\/${ROUTE_PREFIX}${pathPattern}`);
}

module.exports = { getRoute, getRoutePrefix, getRouteRegex, ROUTE_PREFIX };
