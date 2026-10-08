import test from 'node:test';
import assert from 'node:assert/strict';
import { creationName, creationError } from '../src/utils/vmCreation.js';

test('names are trimmed and lowercased, never silently replaced by hyphens', () => {
  assert.equal(creationName(' Test-1 '), 'test-1');
  for (const value of ['сервер', 'test vm', '-vm', 'vm-', '', 'a'.repeat(64)]) {
    assert.throws(() => creationName(value), /латинские/);
  }
});

test('validation errors identify fields and preserve all returned messages', () => {
  assert.equal(creationError([{ loc: ['body', 'packages'], msg: 'Value error, Неверные пакеты' },
    { loc: ['body', 'ssh_key'], msg: 'Value error, Неверный ключ' }]),
  'Пакеты: Неверные пакеты\nSSH-ключ: Неверный ключ');
  assert.equal(creationError([{ loc: ['body', 'vms', 1, 'name'], msg: 'Неверное имя' }]),
    'ВМ 2 · Имя: Неверное имя');
  assert.equal(creationError('Диск занят'), 'Диск занят');
  assert.equal(creationError(null), 'Не удалось создать ВМ.');
});
