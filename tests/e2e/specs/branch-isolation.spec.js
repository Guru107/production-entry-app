const { test, expect } = require("@playwright/test");
const { registerE2ELifecycle } = require("../fixtures/lifecycle");
const { bootstrapE2E, cleanupE2E } = require("../fixtures/test-data");
const { callFrappeMethod } = require("../fixtures/frappe");
const { ensureUser, deleteUserIfExists } = require("../fixtures/users");
const { getRoute, getRouteRegex } = require("../utils/routing");

const ADMIN_USERNAME = process.env.PLAYWRIGHT_USERNAME || "Administrator";
const ADMIN_PASSWORD = process.env.PLAYWRIGHT_PASSWORD || "123";
const TEST_PASSWORD = process.env.PLAYWRIGHT_TEST_USER_PASSWORD || "E2eT3st!Pass#2026";

async function loginAs(page, username, password) {
	const response = await page.request.post("/api/method/login", {
		form: {
			usr: username,
			pwd: password,
		},
	});
	expect(response.ok()).toBeTruthy();
	await page.goto(getRoute("/home"));
	await expect(page).toHaveURL(getRouteRegex("/home"));
}

async function loginAsAdmin(page) {
	await loginAs(page, ADMIN_USERNAME, ADMIN_PASSWORD);
}

async function deleteDocIfExists(page, doctype, name) {
	try {
		await callFrappeMethod(page, "frappe.client.get", {
			doctype,
			name,
		});
		await callFrappeMethod(page, "frappe.client.delete", {
			doctype,
			name,
		});
	} catch (error) {
		const message = String(error?.message || error);
		if (
			!message.includes("DoesNotExistError") &&
			!message.includes("Resource is not available") &&
			!message.includes("not found")
		) {
			throw error;
		}
	}
}

test.describe("Branch isolation", () => {
	const lifecycle = registerE2ELifecycle(test);
	const createdUsers = new Set();

	test.afterEach(async ({ page }) => {
		await loginAsAdmin(page);
		for (const email of createdUsers) {
			await deleteUserIfExists(page, email);
		}
		createdUsers.clear();
	});

	test("@smoke non-admin PEA user only sees shifts from assigned branch", async ({ page }) => {
		await loginAsAdmin(page);
		const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
		const seedShift = await callFrappeMethod(page, "frappe.client.get", {
			doctype: "Shift",
			name: ctx.shift_name,
		});
		const branchA = seedShift.branch || ctx.branch;
		const branchB = `${branchA}-${lifecycle.getPrefix()}-B-${Date.now()}`;
		const shiftDate = seedShift.shift_date || ctx.shift_date;
		const department = seedShift.department;
		let branchBShiftName;
		let branchPermission;
		const stockEntries = [];
		const seededFields = {
			department,
			company: seedShift.company,
			raw_material_warehouse: seedShift.raw_material_warehouse,
			work_in_progress_warehouse: seedShift.work_in_progress_warehouse,
			rejection_warehouse: seedShift.rejection_warehouse,
		};

		try {
			await callFrappeMethod(page, "frappe.client.insert", {
				doc: JSON.stringify({
					doctype: "Branch",
					branch: branchB,
				}),
			});

			const branchBShift = await callFrappeMethod(page, "frappe.client.insert", {
				doc: JSON.stringify({
					doctype: "Shift",
					shift_label: "2",
					shift_duration: "8",
					shift_date: shiftDate,
					planned_start_time: "06:00:00",
					branch: branchB,
					...seededFields,
				}),
			});
			branchBShiftName = branchBShift?.name;
			expect(branchBShiftName).toContain("SHIFT-");

			await callFrappeMethod(page, "run_doc_method", {
				dt: "Shift",
				dn: branchBShiftName,
				method: "start_shift",
			});

			const branchAStockEntry = await callFrappeMethod(
				page,
				"production_entry_app.production_entry_app.e2e_api.create_e2e_submitted_stock_entry",
				{
					prefix: lifecycle.getPrefix(),
					shift_name: ctx.shift_name,
				}
			);
			const branchBStockEntry = await callFrappeMethod(
				page,
				"production_entry_app.production_entry_app.e2e_api.create_e2e_submitted_stock_entry",
				{
					prefix: lifecycle.getPrefix(),
					shift_name: branchBShiftName,
					actual_start_time: "10:00:00",
					actual_end_time: "11:00:00",
					posting_time: "11:00:00",
				}
			);
			stockEntries.push(branchAStockEntry.name, branchBStockEntry.name);
			expect(branchAStockEntry.branch).toBe(branchA);
			expect(branchBStockEntry.branch).toBe(branchB);

			const email = `e2e-user-branch-isolation-${lifecycle.getPrefix()}-${Date.now()}-${Math.floor(
				Math.random() * 1000
			)}@example.com`;
			createdUsers.add(email);
			await ensureUser(page, {
				email,
				firstName: "BranchIsolation",
				password: TEST_PASSWORD,
				roles: ["PEA User", "Manufacturing User", "Stock User"],
			});

			const permissionResult = await callFrappeMethod(
				page,
				"production_entry_app.production_entry_app.e2e_api.set_e2e_branch_user_permission",
				{
					user: email,
					branch: branchA,
				}
			);
			branchPermission = permissionResult?.permission_name;

			await loginAs(page, email, TEST_PASSWORD);
			await page.goto(getRoute("/shift"));
			await expect(page).toHaveURL(getRouteRegex("/shift"));

			// API list call here intentionally runs after opening Shift list so it exercises
			// Desk's permission-filtered list endpoint for the logged-in user.
			const visibleShifts = await callFrappeMethod(page, "frappe.client.get_list", {
				doctype: "Shift",
				fields: JSON.stringify(["name", "branch"]),
				filters: JSON.stringify([
					["shift_date", "=", shiftDate],
					["department", "=", department],
					["shift_label", "in", ["1", "2"]],
				]),
				limit_page_length: 50,
			});
			const visibleBranches = new Set((visibleShifts || []).map((row) => row.branch));
			expect(visibleBranches.has(branchB)).toBe(false);
			expect(visibleBranches.has(branchA)).toBe(true);
			expect(visibleShifts.length).toBe(1);
			expect(visibleShifts[0].branch).toBe(branchA);

			await page.goto(getRoute("/stock-entry"));
			await expect(page).toHaveURL(getRouteRegex("/stock-entry"));

			// API list call here intentionally runs after opening Stock Entry list so it exercises
			// Desk's permission-filtered list endpoint for the logged-in user.
			const visibleStockEntries = await callFrappeMethod(page, "frappe.client.get_list", {
				doctype: "Stock Entry",
				fields: JSON.stringify(["name", "branch", "custom_pea_shift"]),
				filters: JSON.stringify([["name", "in", stockEntries]]),
				limit_page_length: 50,
			});
			const visibleStockEntryNames = new Set(
				(visibleStockEntries || []).map((row) => row.name)
			);
			expect(visibleStockEntryNames.has(branchBStockEntry.name)).toBe(false);
			expect(visibleStockEntryNames.has(branchAStockEntry.name)).toBe(true);
			expect(visibleStockEntries.length).toBe(1);
			expect(visibleStockEntries[0].branch).toBe(branchA);
			expect(visibleStockEntries[0].custom_pea_shift).toBe(ctx.shift_name);
		} finally {
			await loginAsAdmin(page);
			if (branchPermission) {
				await deleteDocIfExists(page, "User Permission", branchPermission);
			}
			await cleanupE2E(page, lifecycle.getPrefix());
			await deleteDocIfExists(page, "Branch", branchB);
		}
	});
});
