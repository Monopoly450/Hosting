import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import Module, { createRequire } from 'node:module';
import { buildSync } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const filename = fileURLToPath(new URL('../src/components/ProxmoxAccessGuide.jsx', import.meta.url));
const { outputFiles } = buildSync({ entryPoints: [filename], bundle: true, write: false,
  platform: 'node', format: 'cjs', packages: 'external' });
const mod = new Module(filename);
mod.require = createRequire(filename);
mod._compile(outputFiles[0].text, filename);
const { default: Guide, proxmoxUrl } = mod.exports;
const vm = { os_type: 'proxmox', status: 'Running', ports_config: [{ int_port: 8006, ext_port: 28010 }] };
const render = guest => renderToStaticMarkup(React.createElement(Guide, { vm: guest, serverHost: 'hosting.example', onCopy: () => {} }));

test('Proxmox URL uses configured external port and HTTPS', () => {
  assert.equal(proxmoxUrl(vm, 'hosting.example'), 'https://hosting.example:28010');
  assert.equal(proxmoxUrl({ ...vm, ports_config: [{ int_port: 8006, ext_port: 30000 }] }, 'hosting.example'), 'https://hosting.example:30000');
  for (const ports_config of [[], [{ int_port: 80, ext_port: 28010 }], [{ int_port: 8006, ext_port: 28010, protocol: 'udp' }], [{ int_port: 8006, ext_port: 70000 }]]) {
    assert.equal(proxmoxUrl({ ...vm, ports_config }, 'hosting.example'), null);
  }
});

test('guide distinguishes running VM from completed ISO installation and uses installer credentials', () => {
  const html = render(vm);
  for (const text of ['https://hosting.example:28010', 'Открыть Proxmox', 'VNC', 'root', 'Linux PAM', 'пароль, заданный вами', 'Веб-терминал панели для Proxmox отключён', 'роутере']) assert.ok(html.includes(text), text);
  assert.doesNotMatch(html, /Administrator|Терминал \/ SSH/);
  assert.match(render({ ...vm, proxmox_available: false }), /пока не отвечает/);
  assert.match(render({ ...vm, proxmox_available: true }), /внутри ВМ отвечает/);
  assert.match(render({ ...vm, ports_config: [] }), /Нет проброса TCP/);
  assert.equal(render({ ...vm, os_type: 'ubuntu' }), '');
});

test('VM detail uses applied configuration in Proxmox guide, not draft rules', () => {
  const source = readFileSync(new URL('../src/components/VMDetail.jsx', import.meta.url), 'utf8');
  assert.match(source, /<ProxmoxAccessGuide vm=\{vm\}/);
  assert.match(source, /sshTerminalSupported\(vm\) && \(/);
});
