export function sshTerminalSupported(vm) {
  return Boolean(vm) && !['windows', 'truenas', 'proxmox'].includes(String(vm.os_type || '').toLowerCase());
}

export function webTerminalEnabled(vm) {
  return sshTerminalSupported(vm) && vm.ssh_access?.web_terminal_enabled !== false;
}

export function keyOnlyAccess(vm) {
  return vm?.ssh_access?.auth_mode === 'publickey';
}

// Same address preference as backend netutils.pick_external_ip. In particular,
// do not choose the Docker bridge inside the guest as the VM's SSH address.
export function sshIp(vm) {
  const ips = vm?.ips || [];
  const internal = ip => ['10.244.', '10.42.', '10.0.2.', '127.', '192.168.100.',
    ...Array.from({ length: 15 }, (_, i) => 17 + i).filter(i => i !== 20).map(i => `172.${i}.`)
  ].some(prefix => ip.startsWith(prefix));
  return ips.find(ip => !ip.includes(':') && !internal(ip))
    || ips.find(ip => ip.startsWith('10.42.') || ip.startsWith('10.244.'))
    || ips.find(ip => !ip.includes(':')) || ips[0] || null;
}

function shellArg(value) {
  const text = String(value);
  return /^[a-zA-Z0-9_./:@~-]+$/.test(text) ? text : `'${text.replaceAll("'", "'\"'\"'")}'`;
}

export function sshCommands(vm, serverHost, keyPath = '~/.ssh/id_ed25519') {
  if (!sshTerminalSupported(vm)) return { local: null, external: null, port: null };
  const user = vm.credentials?.username || 'root';
  const host = String(serverHost || '').trim();
  let validHost = /^[a-zA-Z0-9](?:[a-zA-Z0-9._-]*[a-zA-Z0-9])?$/.test(host);
  if (host.includes(':')) {
    try {
      const ipv6 = new URL(`http://${host.startsWith('[') ? host : `[${host}]`}`);
      validHost = ipv6.hostname.startsWith('[') && !ipv6.port;
    } catch {
      validHost = false;
    }
  }
  const localIp = sshIp(vm);
  const keyArgs = keyOnlyAccess(vm)
    ? ` -i ${shellArg(keyPath.trim() || 'ПУТЬ_К_ПРИВАТНОМУ_КЛЮЧУ')} -o IdentitiesOnly=yes -o PreferredAuthentications=publickey`
    : '';
  const destination = address => shellArg(`${user}@${address.includes(':') && !address.startsWith('[') ? `[${address}]` : address}`);
  // Explicit non-empty port configuration overrides the legacy/default port.
  const configured = vm.ports_config?.length
    ? vm.ports_config.find(rule => Number(rule.int_port) === 22 && (!rule.protocol || rule.protocol.toLowerCase() === 'tcp'))?.ext_port
    : vm.ssh_port;
  const port = Number(configured);
  const validPort = Number.isInteger(port) && port >= 1 && port <= 65535;
  return {
    local: localIp ? `ssh${keyArgs} ${destination(localIp)}` : null,
    external: validHost && validPort ? `ssh${keyArgs} -p ${port} ${destination(host)}` : null,
    port: validPort ? port : null,
  };
}
