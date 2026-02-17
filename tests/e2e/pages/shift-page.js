const { expect } = require('@playwright/test');
const { callFrappeMethod, saveForm, setFieldValue } = require('../fixtures/frappe');

class ShiftPage {
  constructor(page) {
    this.page = page;
  }

  async runDocAction(methodName) {
    await this.page.evaluate(
      ({ action }) =>
        new Promise((resolve, reject) => {
          frappe.call({
            doc: cur_frm.doc,
            method: action,
            callback: () => resolve(true),
            error: (err) => reject(new Error(err?.message || `Failed doc action: ${action}`)),
          });
        }),
      { action: methodName }
    );
  }

  async open(name) {
    const encodedName = encodeURIComponent(name);
    await this.page.goto(`/app/shift/${encodedName}`);
    await expect(this.page).toHaveURL(new RegExp(`/app/shift/${encodedName}$`));
    await this.page.waitForFunction((docname) => window.cur_frm?.doc?.name === docname, name);
  }

  async openNew() {
    await this.page.goto('/app/shift/new');
    await expect(this.page).toHaveURL(/\/app\/shift\/new-shift-/);
    await this.page.waitForFunction(() => window.cur_frm?.doctype === 'Shift' && window.cur_frm?.is_new?.());
  }

  async createDraftViaApi({ date, label = '2', duration = '8', startTime = '10:00:00' }) {
    return await callFrappeMethod(this.page, 'frappe.client.insert', {
      doc: JSON.stringify({
        doctype: 'Shift',
        shift_label: label,
        shift_duration: duration,
        shift_date: date,
        planned_start_time: startTime,
      }),
    });
  }

  async setDraftFields({ date, label, duration, startTime }) {
    if (label != null) {
      await setFieldValue(this.page, 'shift_label', String(label));
    }
    if (duration != null) {
      await setFieldValue(this.page, 'shift_duration', String(duration));
    }
    if (date != null) {
      await setFieldValue(this.page, 'shift_date', date);
    }
    if (startTime != null) {
      await setFieldValue(this.page, 'planned_start_time', startTime);
    }
  }

  async saveDraft() {
    await saveForm(this.page, 'Save');
  }

  async attemptSaveDraft() {
    try {
      await this.saveDraft();
    } catch (error) {
      // Validation errors can reject save in-browser; assertions read UI message.
    }
  }

  async startShift() {
    await this.runDocAction('start_shift');
    await this.page.waitForFunction(() => window.cur_frm?.doc?.status === 'Running');
  }

  async cancelShift() {
    await this.runDocAction('cancel_shift');
    await this.page.waitForFunction(() => window.cur_frm?.doc?.status === 'Cancelled');
  }

  async createProductionEntryFromShift() {
    await this.page.evaluate(() => {
      const label = __('Production Entry');
      const button = window.cur_frm?.custom_buttons?.[label];
      if (!button) {
        throw new Error('Production Entry action button not found on Shift form.');
      }
      button.trigger('click');
    });
    await expect(this.page).toHaveURL(/\/app\/stock-entry\/new-stock-entry-/);
    await this.page.waitForFunction(
      () => window.cur_frm?.doctype === 'Stock Entry' && window.cur_frm?.is_new?.()
    );
  }

  async endShift() {
    await this.runDocAction('end_shift');
    await this.page.waitForFunction(() => window.cur_frm?.doc?.status === 'Completed');
  }

  async waitForPlannedLossRows(count) {
    await this.page.waitForFunction((rowCount) => (window.cur_frm?.doc?.planned_losses || []).length === rowCount, count);
  }

  async getPlannedLosses() {
    return await this.page.evaluate(() =>
      (window.cur_frm?.doc?.planned_losses || []).map((row) => ({
        downtime_reason: row.downtime_reason,
        start_time: row.start_time,
        end_time: row.end_time,
      }))
    );
  }

  async isPlannedLossesReadOnly() {
    return await this.page.evaluate(() => Boolean(window.cur_frm?.fields_dict?.planned_losses?.df?.read_only));
  }
}

module.exports = { ShiftPage };
