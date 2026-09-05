const { callFrappeMethod } = require("./frappe");
const { getRoute } = require("../utils/routing");

async function loginAs(page, username, password) {
	const response = await page.request.post("/api/method/login", {
		form: { usr: username, pwd: password },
	});
	if (!response.ok()) {
		throw new Error(`Unable to login as ${username}.`);
	}
	await page.goto(getRoute("/home"));
	await page.waitForFunction(() => Boolean(window.frappe?.csrf_token));
}

async function ensureRole(page, roleName) {
	try {
		await callFrappeMethod(page, "frappe.client.get", { doctype: "Role", name: roleName });
	} catch (error) {
		await callFrappeMethod(page, "frappe.client.insert", {
			doc: JSON.stringify({
				doctype: "Role",
				role_name: roleName,
			}),
		});
	}
}

async function getUserIfExists(page, email) {
	try {
		return await callFrappeMethod(page, "frappe.client.get", { doctype: "User", name: email });
	} catch (error) {
		return null;
	}
}

function buildRolesRows(existingRows = [], roles = []) {
	const all = new Set([
		...existingRows.map((row) => row.role).filter(Boolean),
		...roles.filter(Boolean),
	]);
	return Array.from(all).map((role) => ({
		doctype: "Has Role",
		role,
	}));
}

async function ensureUser(page, { email, firstName, password = "123", roles = [] }) {
	for (const roleName of roles) {
		await ensureRole(page, roleName);
	}
	if (email.startsWith("e2e-user-") && email.endsWith("@example.com")) {
		return await callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.e2e_api.ensure_e2e_user",
			{
				email,
				first_name: firstName || email.split("@", 1)[0],
				password,
				roles: JSON.stringify(roles),
			}
		);
	}

	let user = await getUserIfExists(page, email);
	if (!user) {
		user = await callFrappeMethod(page, "frappe.client.insert", {
			doc: JSON.stringify({
				doctype: "User",
				email,
				first_name: firstName || email.split("@", 1)[0],
				enabled: 1,
				user_type: "System User",
				send_welcome_email: 0,
				new_password: password,
				roles: buildRolesRows([], roles),
			}),
		});
		return user;
	}

	user.enabled = 1;
	user.user_type = "System User";
	user.roles = buildRolesRows(user.roles || [], roles);
	await callFrappeMethod(page, "frappe.client.save", { doc: JSON.stringify(user) });
	return user;
}

async function deleteUserIfExists(page, email) {
	const user = await getUserIfExists(page, email);
	if (!user) {
		return false;
	}
	await callFrappeMethod(page, "frappe.client.delete", {
		doctype: "User",
		name: email,
	});
	return true;
}

async function deleteRoleIfExists(page, roleName) {
	try {
		await callFrappeMethod(page, "frappe.client.get", { doctype: "Role", name: roleName });
	} catch (error) {
		return false;
	}
	await callFrappeMethod(page, "frappe.client.delete", {
		doctype: "Role",
		name: roleName,
	});
	return true;
}

module.exports = {
	deleteRoleIfExists,
	deleteUserIfExists,
	ensureRole,
	ensureUser,
	loginAs,
};
