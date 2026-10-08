import React, { useState } from 'react';
import { Key, Copy, Check, Monitor, Settings } from 'lucide-react';
import { keyOnlyAccess, sshCommands, sshTerminalSupported } from '../utils/sshAccess';

export default function SshConnectionGuide({ vm, serverHost, onServerHostChange,
  keyPath, onKeyPathChange, onOpenVnc, onOpenSettings, compact = false }) {
  const [copied, setCopied] = useState(null);
  const [copyError, setCopyError] = useState('');
  if (!sshTerminalSupported(vm)) return null;
  const keyOnly = keyOnlyAccess(vm);
  const commands = sshCommands(vm, serverHost, keyPath);
  const copy = async command => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(command);
      setCopyError('');
    } catch {
      setCopyError('Не удалось скопировать автоматически. Выделите команду и скопируйте вручную.');
    }
  };
  const commandRow = (label, command, name, waiting) => (
    <div>
      <label style={{ display: 'block', marginBottom: '8px', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>{label}</label>
      <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
        <code data-ssh-command={name} style={{ flex: 1, minWidth: 0, padding: '12px', background: 'var(--bg-surface-hover)',
          border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', overflowWrap: 'anywhere', fontSize: '0.8rem' }}>{command || waiting}</code>
        <button type="button" className="btn btn-secondary btn-icon" disabled={!command}
          title="Копировать команду" aria-label={`Копировать: ${label}`}
          onClick={() => copy(command)}>
          {command && copied === command ? <Check size={16} /> : <Copy size={16} />}
        </button>
      </div>
    </div>
  );
  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {!compact && <div>
        <h3 className="section-title" style={{ margin: '0 0 10px' }}><Key size={20} /> {keyOnly ? 'Подключение по SSH-ключу' : 'Подключение из своего терминала'}</h3>
        <p style={{ margin: 0, lineHeight: 1.6, color: 'var(--text-secondary)' }}>
          {keyOnly ? 'Веб-терминал отключён: он использует пароль, а эта ВМ принимает только SSH-ключ. Подключайтесь со своего компьютера или с сервера hosting.'
            : 'Можно использовать веб-терминал выше или подключиться по SSH со своего компьютера.'}
        </p>
      </div>}
      {vm.status !== 'Running' && <div className="alert alert-info" style={{ margin: 0 }}>Сначала запустите ВМ. Команды подключения доступны после появления сети.</div>}
      {keyOnly && <div>
        <label htmlFor={`ssh-key-path-${compact ? 'overview' : 'terminal'}`} style={{ display: 'block', marginBottom: '8px' }}>Путь к приватному ключу на компьютере, где выполняется команда</label>
        <input id={`ssh-key-path-${compact ? 'overview' : 'terminal'}`} className="form-control" value={keyPath}
          onChange={e => onKeyPathChange(e.target.value)} placeholder="~/.ssh/id_ed25519" autoComplete="off" spellCheck={false} />
        <small className="text-muted">Нужен файл без .pub, соответствующий публичному ключу ВМ. Для подключения со своего компьютера ключ должен находиться на нём, а не только на hosting. Указывайте только путь — не вставляйте содержимое ключа. Панель не получает и не хранит ваш приватный ключ.</small>
      </div>}
      {commandRow('С сервера hosting или из сети ВМ', commands.local, 'local', 'Ожидание IP-адреса ВМ…')}
      <small className="text-muted">Внутренний IP ВМ обычно недоступен напрямую из Интернета.</small>
      <div>
        <label htmlFor={`ssh-server-host-${compact ? 'overview' : 'terminal'}`} style={{ display: 'block', marginBottom: '8px' }}>Адрес сервера hosting для подключения извне</label>
        <input id={`ssh-server-host-${compact ? 'overview' : 'terminal'}`} className="form-control" value={serverHost}
          onChange={e => onServerHostChange(e.target.value)} placeholder="Публичный IP или домен сервера, без https://" autoComplete="off" spellCheck={false} />
      </div>
      {commandRow('Со своего компьютера — через проброшенный SSH-порт', commands.external, 'external',
        commands.port ? 'Укажите IP или домен сервера без https:// и номера порта.' : 'Проброс TCP-порта 22 не настроен или ещё не определён.')}
      <small className="text-muted">Проверьте проброс TCP → 22 в настройках ВМ и разрешение внешнего порта в firewall сервера/роутера. Если домен панели работает через HTTP-прокси/CDN, укажите настоящий IP hosting или отдельный SSH-домен. Команда не гарантирует доступность порта извне.</small>
      {!compact && <>
        <small className="text-muted">При первом подключении сверяйте отпечаток ключа сервера. В VNC его показывает команда <code>sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub</code>. Если SSH недоступен, откройте VNC — он не использует SSH.</small>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <button type="button" className="btn btn-secondary" onClick={onOpenVnc} disabled={vm.status !== 'Running'}><Monitor size={16} /> Открыть VNC</button>
          <button type="button" className="btn btn-secondary" onClick={onOpenSettings}><Settings size={16} /> Настройки портов</button>
        </div>
      </>}
      {copyError && <small role="alert" style={{ color: 'var(--status-danger)' }}>{copyError}</small>}
    </section>
  );
}
