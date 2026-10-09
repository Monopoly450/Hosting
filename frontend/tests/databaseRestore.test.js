import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components/DatabasesPanel.jsx', import.meta.url), 'utf8');
const body = source.split('const handleRestoreBackup = async (filename) => {')[1].split('\n    };')[0];
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const params = ['filename', 'connectDb', 'backupRestoring', 'backupCreating', 'window', 'fetch', 'getHeaders',
  'setBackupRestoring', 'setQueryResult', 'setQueryError', 'alert', 'fetchDbTables', 'fetchDbMetrics'];
const restore = new AsyncFunction(...params, body);

async function simulate({ ok = true, status = 'Success', busy = null, creating = false, cancelled = false, throws = false } = {}) {
  const events = [];
  await restore('backup.sql', { id: 8 }, busy, creating, { confirm: () => !cancelled },
    async () => {
      events.push('request');
      if (throws) throw new Error('connection lost');
      return { ok, json: async () => ({ status, detail: 'restore failed' }) };
    }, () => ({}), value => events.push(['restoring', value]), value => events.push(['result', value]),
    value => events.push(['error', value]), value => events.push(['alert', value]),
    () => events.push('tables'), () => events.push('metrics'));
  return events;
}

test('confirmed restore clears stale SQL data and refreshes tables and metrics', async () => {
  const events = await simulate();
  assert.deepEqual(events[0], ['restoring', 'backup.sql']);
  assert.ok(events.some(e => Array.isArray(e) && e[0] === 'result' && e[1] === null));
  assert.ok(events.includes('tables'));
  assert.ok(events.includes('metrics'));
  assert.deepEqual(events.at(-1), ['restoring', null]);
  assert.ok(events.some(e => Array.isArray(e) && e[0] === 'alert' && e[1].includes('успешно')));
  assert.doesNotMatch(body, /executeQuery|handleExecuteQuery/);
});

test('HTTP failures, unconfirmed HTTP 200 and connection loss never show success', async () => {
  for (const config of [{ ok: false }, { status: 'Failed' }, { throws: true }]) {
    const events = await simulate(config);
    assert.equal(events.filter(e => Array.isArray(e) && e[0] === 'alert' && e[1].includes('успешно')).length, 0);
    assert.ok(!events.includes('tables'));
    assert.deepEqual(events.at(-1), ['restoring', null]);
  }
});

test('busy or cancelled operations do not submit another request', async () => {
  for (const config of [{ busy: 'other.sql' }, { creating: true }, { cancelled: true }]) {
    assert.deepEqual(await simulate(config), []);
  }
});

test('backup UI warns about replacement and blocks restore and deletion while busy', () => {
  assert.match(source, /На время восстановления остановите приложения/);
  assert.match(source, /role="status"/);
  assert.match(source, /onClick=\{\(\) => handleRestoreBackup\(b.filename\)\}\s+disabled=\{!!backupRestoring \|\| backupCreating\}/);
  assert.match(source, /onClick=\{\(\) => handleDeleteBackup\(b.filename\)\}\s+disabled=\{!!backupRestoring \|\| backupCreating\}/);
});
