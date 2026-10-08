import test from 'node:test';
import assert from 'node:assert/strict';
import { initializeVmSettings, quantityGi, settingsError } from '../src/utils/vmSettings.js';

test('polling never resets unsaved slider edits through an old closure', () => {
  const ref = { current: null };
  let value = 0;
  const poll = () => initializeVmSettings(ref, 'vm1', { cpu: 2 }, data => { value = data.cpu; });
  assert.equal(poll(), true);
  value = 4;
  assert.equal(poll(), false);
  assert.equal(value, 4);
  initializeVmSettings(ref, 'vm2', { cpu: 8 }, data => { value = data.cpu; });
  assert.equal(value, 8);
});

test('a new page initializes from persisted settings again', () => {
  let value;
  initializeVmSettings({ current: null }, 'vm1', { cpu: 4 }, data => { value = data.cpu; });
  assert.equal(value, 4);
});

test('memory and disk quantities are converted to GiB, not parsed as plain integers', () => {
  assert.equal(quantityGi('2048Mi', 2), 2);
  assert.equal(quantityGi('4Gi', 2), 4);
  assert.equal(quantityGi('21474836480', 20), 20);
  assert.equal(quantityGi('invalid', 20), 20);
});

test('API validation and storage errors remain visible instead of generic failure', async () => {
  assert.equal(await settingsError({ json: async () => ({ detail: 'local-path не поддерживает расширение' }) }, 'Ошибка'),
    'local-path не поддерживает расширение');
  assert.equal(await settingsError({ json: async () => ({ detail: [{ msg: 'Invalid memory' }] }) }, 'Ошибка'), 'Invalid memory');
  assert.equal(await settingsError({ json: async () => { throw new Error('HTML'); } }, 'Ошибка'), 'Ошибка');
});
