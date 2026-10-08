import React from 'react';

export function proxmoxUrl(vm, host) {
  const rule = vm?.ports_config?.find(p => Number(p.int_port) === 8006
    && (!p.protocol || p.protocol.toLowerCase() === 'tcp'));
  const port = Number(rule?.ext_port);
  if (!host || !Number.isInteger(port) || port < 1 || port > 65535) return null;
  return `https://${host}:${port}`;
}

export default function ProxmoxAccessGuide({ vm, serverHost, onCopy, copiedField }) {
  if (vm?.os_type !== 'proxmox') return null;
  // Use applied server configuration, not unsaved changes in Settings.
  const url = proxmoxUrl(vm, serverHost);
  return (
    <div style={{ marginTop: '8px', fontSize: '0.8rem' }}>
      <div style={{ color: 'var(--text-secondary)', marginBottom: '8px' }}>Панель Proxmox (HTTPS, порт 8006 внутри ВМ):</div>
      {url ? <>
        <input readOnly className="form-control" value={url} style={{ fontFamily: 'var(--font-mono)' }} />
        <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
          <a className="btn btn-secondary" href={url} target="_blank" rel="noopener noreferrer">Открыть Proxmox</a>
          <button className="btn btn-secondary" onClick={() => onCopy(url, 'extProxmox')}>
            {copiedField === 'extProxmox' ? 'Скопировано' : 'Копировать адрес'}
          </button>
        </div>
      </> : <div>Нет проброса TCP → 8006. Укажите свободный внешний порт в «Настройках» и примените правила.</div>}
      {vm.proxmox_available !== undefined && (
        <div style={{ marginTop: '8px', color: vm.proxmox_available ? 'var(--status-success)' : 'var(--text-secondary)' }}>
          {vm.proxmox_available ? 'Порт 8006 внутри ВМ отвечает.' : 'Порт 8006 внутри ВМ пока не отвечает. Проверьте установку, сеть и службу pveproxy через VNC.'}
        </div>
      )}
      <p style={{ color: 'var(--text-secondary)', marginTop: '10px' }}>
        Сначала завершите установку Proxmox с ISO через VNC и загрузитесь с установленного диска.
        Статус «Запущена» означает работу ВМ, а не готовность Proxmox.
        Вход: пользователь root, область Linux PAM, пароль, заданный вами в установщике.
      </p>
      <p style={{ color: 'var(--text-secondary)' }}>
        Веб-терминал панели для Proxmox отключён; используйте VNC или консоль в самом Proxmox.
        Для доступа из интернета внешний TCP-порт также должен быть открыт на роутере и в сетевом фаерволе.
      </p>
    </div>
  );
}
