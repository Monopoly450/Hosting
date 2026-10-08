import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import Module, { createRequire } from 'node:module';
import { buildSync } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { creationName, creationError, supportsCreationCloudInit, vmCreationPayload } from '../src/utils/vmCreation.js';

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

const linuxDraft = {
  name: 'test-vm', os_type: 'ubuntu', cpu_cores: 2, memory_gb: 8, disk_gb: 40,
  packages: 'curl', network_drives: 'vol-1-test', ssh_key: 'public-key-draft',
  custom_user_data: '#cloud-config\ntimezone: UTC', cloud_init_template: 'docker',
};
const cloudInitKeys = ['packages', 'network_drives', 'ssh_key', 'custom_user_data', 'cloud_init_template'];

test('TrueNAS and other ISO installations do not support cloud-init creation fields', () => {
  for (const osType of ['truenas', 'windows', 'proxmox', ' TrueNAS ']) {
    assert.equal(supportsCreationCloudInit(osType), false);
  }
  for (const osType of ['ubuntu', 'debian', 'centos', 'almalinux', 'rocky', 'fedora', 'opensuse', 'arch', 'alpine', 'bitrix', 'custom']) {
    assert.equal(supportsCreationCloudInit(osType), true);
  }
});

test('switching from Linux to ISO omits hidden drafts without changing ISO or resource settings', () => {
  for (const os_type of ['truenas', 'windows', 'proxmox']) {
    const draft = { ...linuxDraft, os_type, iso_url: 'https://example.com/install.iso' };
    const payload = vmCreationPayload(draft);
    assert.deepEqual(payload, { name: 'test-vm', os_type, cpu_cores: 2, memory_gb: 8,
      disk_gb: 40, iso_url: draft.iso_url });
    for (const key of cloudInitKeys) {
      assert.equal(Object.hasOwn(payload, key), false);
      assert.equal(draft[key], linuxDraft[key]);
    }
  }
});

test('switching back to Linux preserves all advanced field drafts', () => {
  const iso = vmCreationPayload({ ...linuxDraft, os_type: 'truenas' });
  assert.equal(iso.packages, undefined);
  assert.deepEqual(vmCreationPayload(linuxDraft), linuxDraft);
  assert.notEqual(vmCreationPayload(linuxDraft), linuxDraft);
});

function advancedFields(osType) {
  const filename = fileURLToPath(new URL('../src/components/CreationCloudInitFields.jsx', import.meta.url));
  const { outputFiles } = buildSync({ entryPoints: [filename], bundle: true, write: false,
    platform: 'node', format: 'cjs', packages: 'external' });
  const mod = new Module(filename);
  mod.require = createRequire(filename);
  mod._compile(outputFiles[0].text, filename);
  return renderToStaticMarkup(React.createElement(mod.exports.default, { osType },
    React.createElement('div', { 'data-test': 'advanced-inputs' },
      'Пакеты для установки; Сетевые диски (NFS / PVC); Публичный SSH-ключ; Кастомный скрипт Cloud-Init')));
}

test('TrueNAS renders installation guidance instead of unsupported input controls', () => {
  const html = advancedFields('truenas');
  assert.match(html, /TrueNAS устанавливается из ISO через VNC/);
  assert.doesNotMatch(html, /advanced-inputs|Пакеты для установки|Сетевые диски \(NFS|Публичный SSH-ключ|Кастомный скрипт/);
  assert.equal(advancedFields('windows'), '');
  assert.equal(advancedFields('proxmox'), '');
  assert.match(advancedFields('ubuntu'), /advanced-inputs/);
});

test('single-VM and cluster forms wrap every advanced field and sanitize submitted payloads', () => {
  for (const path of ['../src/App.jsx', '../src/components/ClusterPanel.jsx']) {
    const source = readFileSync(new URL(path, import.meta.url), 'utf8');
    const fields = source.match(/<CreationCloudInitFields osType=\{[^}]+\}>([\s\S]*?)<\/CreationCloudInitFields>/);
    assert.ok(fields, path);
    for (const label of ['Пакеты для установки', 'Сетевые диски (NFS / PVC)', 'Публичный SSH-ключ', 'Кастомный скрипт Cloud-Init']) {
      assert.ok(fields[1].includes(label), `${path}: ${label}`);
    }
    assert.match(source, /vmCreationPayload\(\{/);
  }
});

test('mixed-OS cluster drops cloud-init fields only for ISO guests', () => {
  const payloads = [linuxDraft, { ...linuxDraft, name: 'nas', os_type: 'truenas' }].map(vmCreationPayload);
  assert.equal(payloads[0].network_drives, 'vol-1-test');
  assert.equal(Object.hasOwn(payloads[1], 'network_drives'), false);
  assert.equal(payloads[1].name, 'nas');
});
