import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import Module, { createRequire } from 'node:module';
import { buildSync } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { keyOnlyAccess, sshCommands, sshIp, sshTerminalSupported, webTerminalEnabled } from '../src/utils/sshAccess.js';

const vm = { name: 'all-fields-test', os_type: 'ubuntu', status: 'Running', ips: ['10.0.2.2', '172.20.0.38'],
  ssh_port: 22009, credentials: { username: 'ubuntu' },
  ssh_access: { auth_mode: 'publickey', web_terminal_enabled: false } };

test('key-only guests offer instructions instead of password terminal; OS exclusions apply', () => {
  for (const os_type of ['ubuntu', 'debian', 'alpine', 'arch', 'custom', 'fedora', 'almalinux', 'rocky', 'opensuse']) {
    const guest = { ...vm, os_type };
    assert.ok(sshTerminalSupported(guest));
    assert.ok(keyOnlyAccess(guest));
    assert.equal(webTerminalEnabled(guest), false);
  }
  for (const os_type of ['windows', 'truenas', 'TrueNAS', 'proxmox', 'Proxmox']) {
    const guest = { ...vm, os_type };
    assert.equal(sshTerminalSupported(guest), false);
    assert.equal(webTerminalEnabled(guest), false);
    assert.equal(sshCommands(guest, 'hosting.example').external, null);
  }
  assert.equal(webTerminalEnabled(null), false);
  assert.ok(webTerminalEnabled({ os_type: 'ubuntu' }));
});

test('local and external commands use a key, actual guest address and forwarded port', () => {
  const commands = sshCommands(vm, 'hosting.example', '/root/test key/id_ed25519');
  assert.equal(commands.local, "ssh -i '/root/test key/id_ed25519' -o IdentitiesOnly=yes -o PreferredAuthentications=publickey ubuntu@172.20.0.38");
  assert.equal(commands.external, "ssh -i '/root/test key/id_ed25519' -o IdentitiesOnly=yes -o PreferredAuthentications=publickey -p 22009 ubuntu@hosting.example");
  assert.doesNotMatch(commands.external, /172\.20\.0\.38/);
  assert.equal(sshIp({ ips: ['172.17.0.1', '172.20.0.38'] }), '172.20.0.38');
  assert.equal(sshIp({ ips: ['10.0.2.2', '10.42.0.5'] }), '10.42.0.5');
});

test('password commands retain normal SSH; edited port config overrides stale default', () => {
  const guest = { ...vm, ssh_access: { auth_mode: 'password', web_terminal_enabled: true },
    ports_config: [{ int_port: 22, ext_port: 23456 }] };
  assert.equal(sshCommands(guest, '203.0.113.10').external, 'ssh -p 23456 ubuntu@203.0.113.10');
  guest.ports_config = [{ int_port: 80, ext_port: 28009 }];
  assert.equal(sshCommands(guest, '203.0.113.10').external, null);
});

test('missing network/port and invalid host never produce a misleading external command', () => {
  assert.equal(sshCommands({ ...vm, ips: [] }, 'hosting.example').local, null);
  assert.equal(sshCommands({ ...vm, ssh_port: null }, 'hosting.example').external, null);
  for (const host of ['https://hosting.example', 'host; echo secret', 'host:22/path', 'host:22', '[::1]:22', '-oProxyCommand=evil', '']) {
    assert.equal(sshCommands(vm, host).external, null);
  }
  assert.match(sshCommands(vm, '2001:db8::1').external, /'ubuntu@\[2001:db8::1\]'$/);
});

test('private key path is shell-quoted rather than executed, and not uploaded', () => {
  const command = sshCommands(vm, 'hosting.example', "/tmp/key'; touch /tmp/pwn; '").local;
  assert.match(command, /-i '\/tmp\/key'"'"'; touch \/tmp\/pwn; '"'"''/);
  const source = readFileSync(new URL('../src/components/SshConnectionGuide.jsx', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /fetch\(|localStorage|type="file"/);
});

function guide(props) {
  const filename = fileURLToPath(new URL('../src/components/SshConnectionGuide.jsx', import.meta.url));
  const { outputFiles } = buildSync({ entryPoints: [filename], bundle: true, write: false,
    platform: 'node', format: 'cjs', packages: 'external' });
  const mod = new Module(filename);
  mod.require = createRequire(filename);
  mod._compile(outputFiles[0].text, filename);
  return renderToStaticMarkup(React.createElement(mod.exports.default, {
    vm, serverHost: 'hosting.example', keyPath: '~/.ssh/id_ed25519', ...props,
  }));
}

test('guide explains disabled terminal and external access without requesting key contents', () => {
  const html = guide();
  assert.match(html, /Веб-терминал отключён/);
  assert.match(html, /Панель не получает и не хранит ваш приватный ключ/);
  assert.match(html, /Путь к приватному ключу/);
  assert.match(html, /hosting\.example/);
  assert.match(html, /-p 22009/);
  assert.match(html, /Открыть VNC/);
  assert.match(html, /Настройки портов/);
  assert.match(html, /не гарантирует доступность порта извне/);
  assert.equal(guide({ vm: { ...vm, os_type: 'truenas' } }), '');
  assert.equal(guide({ vm: { ...vm, os_type: 'proxmox' } }), '');
});

test('parent never mounts socket terminal or polls password SSH for key-only guests', () => {
  const source = readFileSync(new URL('../src/components/VMDetail.jsx', import.meta.url), 'utf8');
  assert.match(source, /if \(!webTerminalEnabled\(vm\) \|\| vm.status !== 'Running'\)/);
  assert.match(source, /webTerminalEnabled\(vm\) && vm.status === 'Running' && \(/);
  assert.match(source, /vm\?\.ssh_access\?\.web_terminal_enabled/);
  assert.match(source, /<SshConnectionGuide \{\.\.\.sshGuideProps\} \/>/);
  for (const file of ['../src/App.jsx', '../src/components/ClusterPanel.jsx']) {
    const form = readFileSync(new URL(file, import.meta.url), 'utf8');
    assert.match(form, /Вместо веб-терминала панель покажет инструкции подключения по ключу/);
  }
});
