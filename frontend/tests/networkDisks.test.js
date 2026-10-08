import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import Module, { createRequire } from 'node:module';
import { buildSync } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { networkDiskState } from '../src/utils/networkDisks.js';

function status(volume) {
    const filename = fileURLToPath(new URL('../src/components/NetworkDiskStatus.jsx', import.meta.url));
    const { outputFiles } = buildSync({ entryPoints: [filename], bundle: true, write: false,
        platform: 'node', format: 'cjs', packages: 'external' });
    const mod = new Module(filename);
    mod.require = createRequire(filename);
    mod._compile(outputFiles[0].text, filename);
    return renderToStaticMarkup(React.createElement(mod.exports.default, { volume }));
}

test('a disk connected at VM creation shows connected, not free, and explains the attachment', () => {
    const disk = { status: 'Attached', attached_vm_name: 'all-fields-test',
        attachment_type: 'creation', can_detach: false, can_delete: false };
    const state = networkDiskState(disk);
    assert.equal(state.label, 'Подключён');
    assert.ok(state.active && state.busy);
    assert.equal(state.canDetach, false);
    assert.equal(state.canDelete, false);
    const html = status(disk);
    assert.match(html, /Подключён при создании ВМ/);
    assert.match(html, /status-active/);
    assert.doesNotMatch(html, /Свободен/);
});

test('a reserved disk is connecting, with attach/delete actions blocked', () => {
    const disk = { status: 'Reserved', attached_vm_name: 'new-vm', can_detach: false, can_delete: false };
    const state = networkDiskState(disk);
    assert.equal(state.label, 'Подключается');
    assert.ok(state.busy && !state.active);
    assert.equal(state.canDetach, false);
    assert.equal(state.canDelete, false);
    assert.match(status(disk), /Ожидается подключение к ВМ/);
});

test('hotplug and free disks retain their existing actions', () => {
    const attached = networkDiskState({ status: 'Attached', attachment_type: 'hotplug', can_detach: true, can_delete: true });
    assert.ok(attached.canDetach && attached.canDelete);
    const free = networkDiskState({ status: 'Available' });
    assert.equal(free.label, 'Свободен');
    assert.equal(free.busy, false);
    assert.ok(free.canDelete);
});

test('the table shows the VM name and uses connection permissions for actions', () => {
    const source = readFileSync(new URL('../src/components/VolumesPanel.jsx', import.meta.url), 'utf8');
    assert.match(source, /<NetworkDiskStatus volume=\{v\}/);
    assert.match(source, /\{v\.attached_vm_name\}/);
    assert.match(source, /diskState\.busy \?/);
    assert.match(source, /disabled=\{!diskState\.canDetach\}/);
    assert.match(source, /disabled=\{!diskState\.canDelete\}/);
});
