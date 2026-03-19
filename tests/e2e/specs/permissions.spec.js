const { test, expect } = require("@playwright/test");
const { deleteRoleIfExists, deleteUserIfExists, ensureUser } = require("../fixtures/users");
const { callFrappeMethod, getDoc, saveForm, setFieldValue } = require("../fixtures/frappe");
const { ShiftPage } = require("../pages/shift-page");
const { getRoute, getRouteRegex } = require("../utils/routing");

const ADMIN_USERNAME = process.env.PLAYWRIGHT_USERNAME || "Administrator";
const ADMIN_PASSWORD = process.env.PLAYWRIGHT_PASSWORD || "123";
const TEST_PASSWORD = process.env.PLAYWRIGHT_TEST_USER_PASSWORD || "E2eT3st!Pass#2026";

function uniqueSuffix() {
	return `${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

function reservedUserEmail(label, suffix) {
	return `e2e-user-${label}-${suffix}@example.com`;
}

function reservedRoleName(label, suffix) {
	return `E2E ROLE ${label.toUpperCase()} ${suffix}`;
}

function futureDate(daysAhead = 45) {
	const date = new Date();
	date.setDate(date.getDate() + daysAhead);
	return date.toISOString().slice(0, 10);
}

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

async function ensureBranch(page, branchName = "_Test Branch") {
	const rows = await callFrappeMethod(page, "frappe.client.get_list", {
		doctype: "Branch",
		fields: JSON.stringify(["name"]),
		filters: JSON.stringify([["name", "=", branchName]]),
		limit_page_length: 1,
	});
	if (rows?.[0]?.name) {
		return rows[0].name;
	}
	const doc = await callFrappeMethod(page, "frappe.client.insert", {
		doc: JSON.stringify({
			doctype: "Branch",
			branch: branchName,
		}),
	});
	return doc.name;
}

async function ensureDepartment(page, departmentName = "E2E Department") {
	const rows = await callFrappeMethod(page, "frappe.client.get_list", {
		doctype: "Department",
		fields: JSON.stringify(["name"]),
		filters: JSON.stringify([["department_name", "=", departmentName]]),
		limit_page_length: 1,
	});
	if (rows?.[0]?.name) {
		return rows[0].name;
	}
	const doc = await callFrappeMethod(page, "frappe.client.insert", {
		doc: JSON.stringify({
			doctype: "Department",
			department_name: departmentName,
		}),
	});
	return doc.name;
}

async function getShiftSeedFields(page) {
	return {
		department: await ensureDepartment(page),
		branch: await ensureBranch(page),
	};
}

async function runShiftCrudAsRole(page, { email, role, dayOffset }) {
	const shiftFields = await getShiftSeedFields(page);
	await ensureUser(page, {
		email,
		firstName: role.replace(/\s+/g, ""),
		password: TEST_PASSWORD,
		roles: [role],
	});

	await loginAs(page, email, TEST_PASSWORD);

	const shiftDate = futureDate(dayOffset + Math.floor(Math.random() * 3650));
	const shiftPage = new ShiftPage(page);
	const createdDoc = await callFrappeMethod(page, "frappe.client.insert", {
		doc: JSON.stringify({
			doctype: "Shift",
			department: shiftFields.department,
			branch: shiftFields.branch,
			shift_label: "1",
			shift_duration: "8",
			shift_date: shiftDate,
			planned_start_time: "06:00:00",
		}),
	});

	const createdShiftName = createdDoc?.name || "";
	expect(createdShiftName).toContain("SHIFT-");

	await shiftPage.open(createdShiftName);
	const fetchedCreatedDoc = await getDoc(page, "Shift", createdShiftName);
	expect(fetchedCreatedDoc.name).toBe(createdShiftName);

	await callFrappeMethod(page, "frappe.client.set_value", {
		doctype: "Shift",
		name: createdShiftName,
		fieldname: "shift_duration",
		value: "10",
	});
	const updatedDoc = await getDoc(page, "Shift", createdShiftName);
	expect(String(updatedDoc.shift_duration)).toBe("10");

	await callFrappeMethod(page, "frappe.client.delete", {
		doctype: "Shift",
		name: createdShiftName,
	});

	const afterDelete = await callFrappeMethod(page, "frappe.client.get_list", {
		doctype: "Shift",
		filters: JSON.stringify([["name", "=", createdShiftName]]),
		fields: JSON.stringify(["name"]),
		limit_page_length: 1,
	});
	expect(afterDelete).toEqual([]);
}

test.describe("Permissions", () => {
	const createdUsers = new Set();
	const createdRoles = new Set();

	test.afterEach(async ({ page }) => {
		await loginAsAdmin(page);
		for (const email of createdUsers) {
			await deleteUserIfExists(page, email);
		}
		for (const roleName of createdRoles) {
			await deleteRoleIfExists(page, roleName);
		}
		createdUsers.clear();
		createdRoles.clear();
	});

	test("@regression manufacturing user can create read update delete Shift in UI", async ({
		page,
	}) => {
		await loginAsAdmin(page);
		const suffix = uniqueSuffix();
		const email = reservedUserEmail("mfg-user", suffix);
		createdUsers.add(email);

		await runShiftCrudAsRole(page, {
			email,
			role: "Manufacturing User",
			dayOffset: 46,
		});

		await loginAsAdmin(page);
	});

	test("@regression manufacturing manager can create read update delete Shift in UI", async ({
		page,
	}) => {
		await loginAsAdmin(page);
		const suffix = uniqueSuffix();
		const email = reservedUserEmail("mfg-manager", suffix);
		createdUsers.add(email);

		await runShiftCrudAsRole(page, {
			email,
			role: "Manufacturing Manager",
			dayOffset: 47,
		});

		await loginAsAdmin(page);
	});

	test("@regression non-manufacturing user cannot access Shift list or form", async ({
		page,
	}) => {
		await loginAsAdmin(page);
		const suffix = uniqueSuffix();
		const email = reservedUserEmail("non-mfg", suffix);
		const noManufacturingRole = reservedRoleName("no-manufacturing", suffix);
		createdUsers.add(email);
		createdRoles.add(noManufacturingRole);

		await ensureUser(page, {
			email,
			firstName: "NonMfg",
			password: TEST_PASSWORD,
			roles: [noManufacturingRole],
		});

		await loginAs(page, email, TEST_PASSWORD);

		await page.goto(getRoute("/shift"));
		await page.goto(getRoute("/shift/new"));

		await expect(
			callFrappeMethod(page, "frappe.client.get_list", {
				doctype: "Shift",
				fields: JSON.stringify(["name"]),
				limit_page_length: 1,
			})
		).rejects.toThrow(/not permitted|permission/i);

		await expect(
			callFrappeMethod(page, "frappe.client.insert", {
				doc: JSON.stringify({
					doctype: "Shift",
					...(await getShiftSeedFields(page)),
					shift_label: "1",
					shift_duration: "8",
					shift_date: futureDate(49),
					planned_start_time: "08:00:00",
				}),
			})
		).rejects.toThrow(/not permitted|permission/i);

		await loginAsAdmin(page);
	});

	test("@regression manufacturing user can create read update delete Downtime Reason", async ({
		page,
	}) => {
		await loginAsAdmin(page);
		const suffix = uniqueSuffix();
		const email = reservedUserEmail("downtime-user", suffix);
		createdUsers.add(email);

		await ensureUser(page, {
			email,
			firstName: "DownUser",
			password: TEST_PASSWORD,
			roles: ["Manufacturing User"],
		});

		await loginAs(page, email, TEST_PASSWORD);

		await page.goto(getRoute("/downtime-reason/new"));
		await page.waitForLoadState("domcontentloaded");

		await expect
			.poll(async () => await page.evaluate(() => window.cur_frm?.doctype || ""))
			.toBe("Downtime Reason");

		const reasonName = `E2E-DOWNTIME-${suffix}`;
		await setFieldValue(page, "downtime_reason_name", reasonName);
		await saveForm(page, "Save");

		let docName = await page.evaluate(() => window.cur_frm?.doc?.name || "");
		expect(docName).toBe(reasonName);

		await page.goto(getRoute(`/downtime-reason/${encodeURIComponent(docName)}`));
		await page.waitForFunction((name) => window.cur_frm?.doc?.name === name, docName);

		const renamedReason = `${reasonName}-UPDATED`;
		await callFrappeMethod(page, "frappe.rename_doc", {
			doctype: "Downtime Reason",
			old: docName,
			new: renamedReason,
			merge: 0,
		});
		docName = renamedReason;
		const updatedReason = await getDoc(page, "Downtime Reason", docName);
		expect(updatedReason.name).toBe(renamedReason);
		expect(updatedReason.downtime_reason_name).toBe(renamedReason);

		await page.goto(getRoute(`/downtime-reason/${encodeURIComponent(docName)}`));
		await page.waitForFunction((name) => window.cur_frm?.doc?.name === name, docName);

		await callFrappeMethod(page, "frappe.client.delete", {
			doctype: "Downtime Reason",
			name: docName,
		});

		const list = await callFrappeMethod(page, "frappe.client.get_list", {
			doctype: "Downtime Reason",
			filters: JSON.stringify([["name", "=", docName]]),
			fields: JSON.stringify(["name"]),
			limit_page_length: 1,
		});
		expect(list).toEqual([]);

		await loginAsAdmin(page);
	});
});
