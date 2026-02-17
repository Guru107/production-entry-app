const { test, expect } = require('@playwright/test');
const { ensureUser } = require('../fixtures/users');
const { callFrappeMethod, getDoc, saveForm, setFieldValue } = require('../fixtures/frappe');
const { ShiftPage } = require('../pages/shift-page');

const ADMIN_USERNAME = process.env.PLAYWRIGHT_USERNAME || 'Administrator';
const ADMIN_PASSWORD = process.env.PLAYWRIGHT_PASSWORD || '123';
const TEST_PASSWORD = process.env.PLAYWRIGHT_TEST_USER_PASSWORD || 'E2eT3st!Pass#2026';

function uniqueSuffix() {
  return `${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

function futureDate(daysAhead = 45) {
  const date = new Date();
  date.setDate(date.getDate() + daysAhead);
  return date.toISOString().slice(0, 10);
}

async function loginAs(page, username, password) {
  const response = await page.request.post('/api/method/login', {
    form: {
      usr: username,
      pwd: password,
    },
  });
  expect(response.ok()).toBeTruthy();
  await page.goto('/app/home');
  await expect(page).toHaveURL(/\/app\//);
}

async function loginAsAdmin(page) {
  await loginAs(page, ADMIN_USERNAME, ADMIN_PASSWORD);
}

async function runShiftCrudAsRole(page, { email, role, dayOffset }) {
  await ensureUser(page, {
    email,
    firstName: role.replace(/\s+/g, ''),
    password: TEST_PASSWORD,
    roles: [role],
  });

  await loginAs(page, email, TEST_PASSWORD);

  const shiftPage = new ShiftPage(page);
  await shiftPage.openNew();
  await shiftPage.setDraftFields({
    date: futureDate(dayOffset),
    label: '1',
    duration: '8',
    startTime: '06:00:00',
  });
  await shiftPage.saveDraft();

  const createdShiftName = await page.evaluate(() => window.cur_frm?.doc?.name || '');
  expect(createdShiftName).toContain('SHIFT-');

  await shiftPage.open(createdShiftName);
  const createdDoc = await getDoc(page, 'Shift', createdShiftName);
  expect(createdDoc.name).toBe(createdShiftName);

  await shiftPage.setDraftFields({ duration: '10' });
  await shiftPage.saveDraft();
  const updatedDoc = await getDoc(page, 'Shift', createdShiftName);
  expect(String(updatedDoc.shift_duration)).toBe('10');

  await callFrappeMethod(page, 'frappe.client.delete', {
    doctype: 'Shift',
    name: createdShiftName,
  });

  const afterDelete = await callFrappeMethod(page, 'frappe.client.get_list', {
    doctype: 'Shift',
    filters: JSON.stringify([['name', '=', createdShiftName]]),
    fields: JSON.stringify(['name']),
    limit_page_length: 1,
  });
  expect(afterDelete).toEqual([]);
}

test.describe('Permissions', () => {
  test('@regression manufacturing user can create read update delete Shift in UI', async ({ page }) => {
    await loginAsAdmin(page);
    const suffix = uniqueSuffix();
    const email = `e2e-mfg-user-${suffix}@example.com`;

    await runShiftCrudAsRole(page, {
      email,
      role: 'Manufacturing User',
      dayOffset: 46,
    });

    await loginAsAdmin(page);
  });

  test('@regression manufacturing manager can create read update delete Shift in UI', async ({ page }) => {
    await loginAsAdmin(page);
    const suffix = uniqueSuffix();
    const email = `e2e-mfg-manager-${suffix}@example.com`;

    await runShiftCrudAsRole(page, {
      email,
      role: 'Manufacturing Manager',
      dayOffset: 47,
    });

    await loginAsAdmin(page);
  });

  test('@regression non-manufacturing user cannot access Shift list or form', async ({ page }) => {
    await loginAsAdmin(page);
    const suffix = uniqueSuffix();
    const email = `e2e-non-mfg-${suffix}@example.com`;

    await ensureUser(page, {
      email,
      firstName: 'NonMfg',
      password: TEST_PASSWORD,
      roles: [`E2E No Manufacturing ${suffix}`],
    });

    await loginAs(page, email, TEST_PASSWORD);

    await page.goto('/app/shift');
    await page.goto('/app/shift/new');

    await expect(
      callFrappeMethod(page, 'frappe.client.get_list', {
        doctype: 'Shift',
        fields: JSON.stringify(['name']),
        limit_page_length: 1,
      })
    ).rejects.toThrow(/not permitted|permission/i);

    await expect(
      callFrappeMethod(page, 'frappe.client.insert', {
        doc: JSON.stringify({
          doctype: 'Shift',
          shift_label: '1',
          shift_duration: '8',
          shift_date: futureDate(49),
          planned_start_time: '08:00:00',
        }),
      })
    ).rejects.toThrow(/not permitted|permission/i);

    await loginAsAdmin(page);
  });

  test('@regression manufacturing user can create read update delete Downtime Reason', async ({ page }) => {
    await loginAsAdmin(page);
    const suffix = uniqueSuffix();
    const email = `e2e-downtime-user-${suffix}@example.com`;

    await ensureUser(page, {
      email,
      firstName: 'DownUser',
      password: TEST_PASSWORD,
      roles: ['Manufacturing User'],
    });

    await loginAs(page, email, TEST_PASSWORD);

    await page.goto('/app/downtime-reason/new');
    await page.waitForLoadState('domcontentloaded');

    await expect.poll(async () => await page.evaluate(() => window.cur_frm?.doctype || '')).toBe(
      'Downtime Reason'
    );

    const reasonName = `E2E-DOWNTIME-${suffix}`;
    await setFieldValue(page, 'downtime_reason_name', reasonName);
    await saveForm(page, 'Save');

    let docName = await page.evaluate(() => window.cur_frm?.doc?.name || '');
    expect(docName).toBe(reasonName);

    await page.goto(`/app/downtime-reason/${encodeURIComponent(docName)}`);
    await page.waitForFunction((name) => window.cur_frm?.doc?.name === name, docName);

    const renamedReason = `${reasonName}-UPDATED`;
    await callFrappeMethod(page, 'frappe.rename_doc', {
      doctype: 'Downtime Reason',
      old: docName,
      new: renamedReason,
      merge: 0,
    });
    docName = renamedReason;
    const updatedReason = await getDoc(page, 'Downtime Reason', docName);
    expect(updatedReason.name).toBe(renamedReason);
    expect(updatedReason.downtime_reason_name).toBe(renamedReason);

    await page.goto(`/app/downtime-reason/${encodeURIComponent(docName)}`);
    await page.waitForFunction((name) => window.cur_frm?.doc?.name === name, docName);

    await callFrappeMethod(page, 'frappe.client.delete', {
      doctype: 'Downtime Reason',
      name: docName,
    });

    const list = await callFrappeMethod(page, 'frappe.client.get_list', {
      doctype: 'Downtime Reason',
      filters: JSON.stringify([['name', '=', docName]]),
      fields: JSON.stringify(['name']),
      limit_page_length: 1,
    });
    expect(list).toEqual([]);

    await loginAsAdmin(page);
  });
});
