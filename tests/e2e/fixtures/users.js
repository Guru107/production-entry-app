const { callFrappeMethod } = require("./frappe");

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
};
