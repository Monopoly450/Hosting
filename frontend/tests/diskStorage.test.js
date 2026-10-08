import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import Module, { createRequire } from 'node:module';
import { buildSync } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

function loadComponent(name) {
  const filename = fileURLToPath(new URL(`../src/components/${name}.jsx`, import.meta.url));
  const { outputFiles } = buildSync({ entryPoints: [filename], bundle: true, write: false,
    platform: 'node', format: 'cjs', packages: 'external' });
  const mod = new Module(filename);
  mod.require = createRequire(filename);
  mod._compile(outputFiles[0].text, filename);
  return mod.exports.default;
}

test('disk hint explains network disk creation and does not promise system disk expansion', () => {
  const html = renderToStaticMarkup(React.createElement(loadComponent('DiskStorageNotice')));
  assert.match(html, /«Сетевые диски»/);
  assert.match(html, /создайте диск/);
  assert.match(html, /подключите его к этой ВМ/);
  assert.match(html, /размер системного диска не изменится/);
});

test('resource modal has only CPU and RAM sliders and displays persisted disk size after restore', () => {
  const html = renderToStaticMarkup(React.createElement(loadComponent('VMEditModal'), {
    vm: { name: 'vm1', cpu_cores: 2, memory: '2Gi', disk_gb: 20,
      disks: [{ size: '22763326669' }] }, onClose() {}, onSaveSuccess() {},
  }));
  assert.equal((html.match(/type="range"/g) || []).length, 2);
  assert.match(html, /20 GB/);
  assert.match(html, /«Сетевые диски»/);
});

test('all disk forms include the same hint and VM settings have no throttle or disk size controls', () => {
  const detail = readFileSync(new URL('../src/components/VMDetail.jsx', import.meta.url), 'utf8');
  assert.match(detail, /<DiskStorageNotice\s*\/>/);
  assert.doesNotMatch(detail, /Ограничения скорости диска|Лимит IOPS|disk_read_mbs|disk_write_mbs|setDiskGb/);
  assert.match(detail, /disk_gb: currentDiskGb/);
  const app = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');
  assert.match(app, /<DiskStorageNotice\s*\/>/);
});

test('network pool card and settings do not attribute all VM backups and databases to network disks', () => {
  const stats = readFileSync(new URL('../src/components/HostStats.jsx', import.meta.url), 'utf8');
  assert.match(stats, /Сетевые диски \(LVM\)/);
  assert.match(stats, /Выделено сетевым дискам/);
  assert.match(stats, /network_reserved_gb/);
  assert.doesNotMatch(stats, /диски ВМ, бэкапы, базы данных, сетевые диски|Зарезервировано ВМ:|суммарный объем дисков созданных ВМ/);
});
