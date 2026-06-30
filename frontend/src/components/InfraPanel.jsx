import React, { useState, useEffect, useRef } from 'react';
import { GitBranch, RefreshCw, Terminal as TerminalIcon, ShieldAlert, Cpu, HardDrive, FileText, ChevronRight, Play, CheckCircle, AlertCircle, Trash2 } from 'lucide-react';

const InfraPanel = () => {
  // Состояние Git
  const [gitInfo, setGitInfo] = useState(null);
  const [gitLoading, setGitLoading] = useState(true);
  const [pullLoading, setPullLoading] = useState(false);
  const [gitOutput, setGitOutput] = useState('');

  // Состояние Логов
  const [selectedService, setSelectedService] = useState('backend');
  const [logsText, setLogsText] = useState('');
  const [logsLoading, setLogsLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);

  // Состояние Выполнения Команд
  const [command, setCommand] = useState('');
  const [cmdOutput, setCmdOutput] = useState('');
  const [cmdLoading, setCmdLoading] = useState(false);

  // Состояние ВМ для проброса портов
  const [vms, setVms] = useState([]);
  const [vmsLoading, setVmsLoading] = useState(false);

  const fetchVms = async () => {
    setVmsLoading(true);
    try {
      const response = await fetch('/api/vms');
      if (response.ok) {
        const data = await response.json();
        setVms(data);
      }
    } catch (err) {
      console.error('Failed to fetch VMs:', err);
    } finally {
      setVmsLoading(false);
    }
  };

  const getSshIp = (vm) => {
    if (!vm.ips || vm.ips.length === 0) return null;
    for (let ip of vm.ips) {
      if (!ip.startsWith('10.244.') && !ip.startsWith('10.42.') && !ip.startsWith('10.0.2.') && !ip.startsWith('127.0.') && !ip.includes(':')) {
        return ip;
      }
    }
    for (let ip of vm.ips) {
      if ((ip.startsWith('10.42.') || ip.startsWith('10.244.')) && !ip.includes(':')) {
        return ip;
      }
    }
    for (let ip of vm.ips) {
      if (!ip.includes(':')) return ip;
    }
    return vm.ips[0] || null;
  };

  const isPrivateIp = (ip) => {
    if (!ip) return false;
    return ip.startsWith('172.16.') || ip.startsWith('172.17.') || ip.startsWith('172.18.') || ip.startsWith('172.19.') || ip.startsWith('172.20.') || ip.startsWith('172.21.') || ip.startsWith('172.22.') || ip.startsWith('172.23.') || ip.startsWith('172.24.') || ip.startsWith('172.25.') || ip.startsWith('172.26.') || ip.startsWith('172.27.') || ip.startsWith('172.28.') || ip.startsWith('172.29.') || ip.startsWith('172.30.') || ip.startsWith('172.31.') || ip.startsWith('10.') || ip.startsWith('192.168.');
  };

  const logsEndRef = useRef(null);
  const cmdOutputEndRef = useRef(null);

  // Запрос статуса Git
  const fetchGitInfo = async () => {
    setGitLoading(true);
    try {
      const response = await fetch('/api/infra/git-info');
      if (!response.ok) throw new Error('Git info unavailable');
      const data = await response.json();
      setGitInfo(data);
    } catch (err) {
      console.error(err);
    } finally {
      setGitLoading(false);
    }
  };

  // Запуск git pull и пересборки контейнеров
  const handleGitPull = async () => {
    if (!window.confirm('Вы уверены, что хотите обновить код с GitHub и пересобрать все службы? Это пересоберет контейнеры с новым кодом без перезагрузки физического сервера.')) {
      return;
    }
    setPullLoading(true);
    setGitOutput('Инициализация обновления с GitHub...\n');
    try {
      const response = await fetch('/api/infra/git-pull', { method: 'POST' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Ошибка выполнения');
      setGitOutput(prev => prev + `[STATUS] ${data.status === 'success' ? 'Службы успешно пересобраны!' : 'Обновление выполнено частично.'}\n\nЛог сборки и перезапуска:\n${data.output}`);
      fetchGitInfo();
    } catch (err) {
      setGitOutput(prev => prev + `\n[ERROR] Критическая ошибка при обновлении: ${err.message}`);
    } finally {
      setPullLoading(false);
    }
  };

  // Запрос логов контейнера
  const fetchLogs = async () => {
    setLogsLoading(true);
    try {
      const response = await fetch(`/api/infra/logs?service=${selectedService}&tail=200`);
      if (!response.ok) throw new Error('Logs unavailable');
      const data = await response.json();
      setLogsText(data.logs || 'Логи пусты.');
    } catch (err) {
      setLogsText(`Ошибка загрузки логов: ${err.message}`);
    } finally {
      setLogsLoading(false);
    }
  };

  // Выполнение терминальной команды
  const executeCommand = async (cmdToRun = null) => {
    const finalCmd = cmdToRun !== null ? cmdToRun : command;
    if (!finalCmd.trim()) return;
    setCmdLoading(true);
    setCmdOutput(prev => prev + `\n$ ${finalCmd}\n`);
    try {
      const response = await fetch('/api/infra/execute-command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: finalCmd })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Ошибка выполнения');
      setCmdOutput(prev => prev + data.output + '\n');
      if (cmdToRun === null) setCommand('');
    } catch (err) {
      setCmdOutput(prev => prev + `Ошибка: ${err.message}\n`);
    } finally {
      setCmdLoading(false);
    }
  };

  // Первичная загрузка
  useEffect(() => {
    fetchGitInfo();
    fetchLogs();
    fetchVms();
  }, []);

  // Обновление логов при смене сервиса
  useEffect(() => {
    fetchLogs();
  }, [selectedService]);

  // Интервал автообновления логов
  useEffect(() => {
    let interval;
    if (autoRefresh) {
      interval = setInterval(fetchLogs, 4000);
    }
    return () => clearInterval(interval);
  }, [autoRefresh, selectedService]);

  // Автопрокрутка логов и терминала вниз
  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logsText]);

  useEffect(() => {
    if (cmdOutputEndRef.current) {
      cmdOutputEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [cmdOutput]);

  // Быстрые команды админа
  const quickCommands = [
    { name: 'Диски', cmd: 'df -h' },
    { name: 'Память', cmd: 'free -m' },
    { name: 'Контейнеры', cmd: 'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"' },
    { name: 'Сеть (IP)', cmd: 'ip -br addr' },
    { name: 'Аптайм', cmd: 'uptime' },
    { name: 'IPTables NAT', cmd: 'iptables -t nat -vnL --line-numbers' }
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div className="vms-section-header">
        <h2 style={{ fontSize: '1.4rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '10px' }}>
          <TerminalIcon className="logo-icon" size={22} />
          Управление инфраструктурой Aegis
        </h2>
        <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
          Версия системы: <strong style={{ color: 'var(--primary)' }}>KubeVirt + Docker stack</strong>
        </span>
      </div>

      {/* Верхний блок: Git статус и хост-обновление */}
      <div className="grid-2col" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
        <div className="card" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
          <div>
            <div className="card-title" style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '10px', marginBottom: '15px' }}>
              <GitBranch size={18} color="var(--primary)" />
              <span>Синхронизация с GitHub</span>
            </div>
            
            {gitLoading && !gitInfo ? (
              <div style={{ display: 'flex', justifyContent: 'center', padding: '30px' }}><div className="spinner"></div></div>
            ) : gitInfo ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '0.9rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text-secondary)' }}>Ветка репозитория:</span>
                  <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{gitInfo.branch}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text-secondary)' }}>Последний коммит:</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    {gitInfo.commit_hash ? gitInfo.commit_hash.slice(0, 8) : 'N/A'}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text-secondary)' }}>Автор коммита:</span>
                  <span style={{ fontWeight: 500 }}>{gitInfo.author}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text-secondary)' }}>Тема коммита:</span>
                  <span style={{ fontWeight: 500, color: 'var(--text-primary)', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={gitInfo.subject}>
                    {gitInfo.subject}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '5px', borderTop: '1px solid var(--border-color)', paddingTop: '10px' }}>
                  <span style={{ color: 'var(--text-secondary)' }}>Статус на сервере:</span>
                  <span className={`status-badge ${gitInfo.status_text === 'Up to date' ? 'running' : 'stopped'}`} style={{ textTransform: 'none' }}>
                    <span className="status-dot" />
                    {gitInfo.status_text}
                  </span>
                </div>
              </div>
            ) : (
              <div style={{ color: 'var(--danger)', fontSize: '0.85rem' }}>Не удалось получить сведения о репозитории.</div>
            )}

            {gitInfo && gitInfo.local_changes && (
              <div style={{ marginTop: '12px', padding: '8px 12px', background: 'var(--warning-glow)', border: '1px solid var(--warning)', borderRadius: '4px', fontSize: '0.75rem', color: 'var(--warning)' }}>
                <strong>Внимание:</strong> Есть локальные изменения на хост-сервере:<br />
                <pre style={{ fontFamily: 'var(--font-mono)', marginTop: '4px', overflowX: 'auto' }}>{gitInfo.local_changes}</pre>
              </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: '10px', marginTop: '20px' }}>
            <button className="btn btn-secondary btn-sm" onClick={fetchGitInfo} disabled={gitLoading || pullLoading}>
              <RefreshCw size={14} className={gitLoading ? 'spinner' : ''} /> Проверить
            </button>
            <button 
              className="btn btn-primary btn-sm" 
              onClick={handleGitPull} 
              disabled={pullLoading}
              style={{ flex: 1 }}
            >
              {pullLoading ? (
                <>
                  <span className="spinner" style={{ width: '12px', height: '12px', border: '2px solid #fff', borderTopColor: 'transparent', marginRight: '6px' }}></span>
                  Обновление...
                </>
              ) : (
                'Обновить код с GitHub (без перезагрузки сервера)'
              )}
            </button>
          </div>
        </div>

        {/* Терминал вывода логов Git обновления */}
        <div className="card" style={{ background: '#111216', border: '1px solid #20242d', color: '#abb2bf', display: 'flex', flexDirection: 'column', height: '260px', padding: '12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid #282c34', paddingBottom: '8px', marginBottom: '8px', fontSize: '0.8rem', color: '#5c6370', fontWeight: 'bold' }}>
            <span>ЛОГ СБОРКИ / ОБНОВЛЕНИЯ</span>
            <span>git pull & compose rebuild</span>
          </div>
          <div style={{ flex: 1, overflowY: 'auto', fontFamily: 'var(--font-mono)', fontSize: '0.75rem', whiteSpace: 'pre-wrap', lineHeight: '1.4' }}>
            {gitOutput || 'Лог пуст. Запустите обновление кода с GitHub для просмотра сборки.'}
          </div>
        </div>
      </div>

      {/* Средний блок: Логи Docker-контейнеров */}
      <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <FileText size={18} color="var(--primary)" />
            <span style={{ fontWeight: 600 }}>Логи контейнеров Aegis (Хост)</span>
          </div>
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            {/* Выбор контейнера */}
            <select 
              className="form-input form-select" 
              style={{ width: '180px', padding: '4px 10px', fontSize: '0.85rem', height: 'auto', margin: '0' }}
              value={selectedService}
              onChange={(e) => setSelectedService(e.target.value)}
            >
              <option value="backend">FastAPI Бэкенд</option>
              <option value="frontend">Админ Панель (Nginx)</option>
              <option value="orchestrator">Go-Оркестратор</option>
              <option value="vds-frontend">Клиент Панель (Nginx)</option>
              <option value="db">База данных Postgres</option>
            </select>

            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem', cursor: 'pointer', userSelect: 'none', color: 'var(--text-secondary)' }}>
              <input 
                type="checkbox" 
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              Автообновление (4с)
            </label>

            <button className="btn btn-secondary btn-sm btn-icon-only" onClick={fetchLogs} disabled={logsLoading} title="Обновить логи">
              <RefreshCw size={12} className={logsLoading ? 'spinner' : ''} />
            </button>
          </div>
        </div>

        {/* Терминал Логов */}
        <div style={{ background: '#0e1013', border: '1px solid #1a1e24', borderRadius: '4px', color: '#abb2bf', padding: '15px', height: '350px', overflowY: 'auto', fontFamily: 'var(--font-mono)', fontSize: '0.78rem', lineBreak: 'anywhere', whiteSpace: 'pre-wrap' }}>
          {logsText ? (
            <>
              {logsText}
              <div ref={logsEndRef} />
            </>
          ) : (
            <div style={{ color: '#5c6370', textAlign: 'center', paddingTop: '100px' }}>
              Нет доступных записей в логе.
            </div>
          )}
        </div>
      </div>

      {/* Нижний блок: Консоль выполнения команд на хосте */}
      <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
        <div style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <TerminalIcon size={18} color="var(--primary)" />
            <span style={{ fontWeight: 600 }}>Выполнение консольных команд на хост-сервере</span>
          </div>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '4px' }}>
            Команды будут выполнены напрямую в пространстве имен хоста (через Docker nsenter в namespace 1). Будьте осторожны!
          </p>
        </div>

        {/* Быстрые команды */}
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          {quickCommands.map((qc) => (
            <button 
              key={qc.name}
              className="btn btn-secondary btn-sm"
              style={{ fontSize: '0.75rem', padding: '4px 10px', borderRadius: '3px' }}
              onClick={() => executeCommand(qc.cmd)}
              disabled={cmdLoading}
            >
              {qc.name}
            </button>
          ))}
        </div>

        {/* Список ВМ для проброса портов */}
        {vms.filter(vm => vm.status === 'Running' && getSshIp(vm) && isPrivateIp(getSshIp(vm))).length > 0 && (
          <div style={{ background: 'rgba(245, 158, 11, 0.04)', border: '1px dashed rgba(245, 158, 11, 0.3)', padding: '12px', borderRadius: '4px', fontSize: '0.8rem' }}>
            <strong style={{ color: 'rgb(245, 158, 11)', display: 'block', marginBottom: '8px' }}>
              ⚠️ Обнаружены запущенные VM в приватной сети. Выберите VM для автоматической вставки команд проброса портов:
            </strong>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {vms.filter(vm => vm.status === 'Running' && getSshIp(vm) && isPrivateIp(getSshIp(vm))).map(vm => {
                const ip = getSshIp(vm);
              const port = vm.ssh_port || 2222;
              const cmd1 = `iptables -t nat -A PREROUTING -p tcp --dport ${port} -j DNAT --to-destination ${ip}:22`;
                const cmd2 = `iptables -A FORWARD -p tcp -d ${ip} --dport 22 -j ACCEPT`;
                return (
                  <div key={vm.name} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(0,0,0,0.02)', padding: '6px 10px', border: '1px solid var(--border-color)', flexWrap: 'wrap', gap: '10px' }}>
                    <span>
                      VM <strong>{vm.name}</strong> (IP: <code>{ip}</code>)
                    </span>
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                      <button 
                        className="btn btn-secondary btn-sm"
                        style={{ fontSize: '0.75rem', padding: '4px 8px', borderRadius: '0px' }}
                        onClick={() => {
                          setCommand(cmd1);
                          alert('Команда PREROUTING введена в поле ввода! Нажмите "Запуск" для выполнения.');
                        }}
                        type="button"
                      >
                        Заполнить шаг 1
                      </button>
                      <button 
                        className="btn btn-secondary btn-sm"
                        style={{ fontSize: '0.75rem', padding: '4px 8px', borderRadius: '0px' }}
                        onClick={() => {
                          setCommand(cmd2);
                          alert('Команда FORWARD введена в поле ввода! Нажмите "Запуск" для выполнения.');
                        }}
                        type="button"
                      >
                        Заполнить шаг 2
                      </button>
                      <button 
                        className="btn btn-warning btn-sm"
                        style={{ fontSize: '0.75rem', padding: '4px 8px', borderRadius: '0px', background: 'rgba(245, 158, 11, 0.15)', borderColor: 'rgba(245, 158, 11, 0.3)', color: 'rgb(245, 158, 11)' }}
                        onClick={async () => {
                          if (window.confirm(`Выполнить проброс портов на хосте для ${vm.name}?`)) {
                            setCmdLoading(true);
                            setCmdOutput(prev => prev + `\n$ ${cmd1}\n$ ${cmd2}\n`);
                            try {
                              let response = await fetch('/api/infra/execute-command', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ command: cmd1 })
                              });
                              let data = await response.json();
                              setCmdOutput(prev => prev + (data.output || '') + '\n');
                              
                              response = await fetch('/api/infra/execute-command', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ command: cmd2 })
                              });
                              data = await response.json();
                              setCmdOutput(prev => prev + (data.output || '') + '\nУспешно применены правила проброса!\n');
                            } catch (err) {
                              setCmdOutput(prev => prev + `Ошибка: ${err.message}\n`);
                            } finally {
                              setCmdLoading(false);
                            }
                          }
                        }}
                        type="button"
                      >
                        ⚡ Пробросить порт {vm.ssh_port || 2222}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Терминал вывода команд */}
        <div style={{ background: '#0b0c10', border: '1px solid #151821', borderRadius: '4px', color: '#33ff33', padding: '15px', height: '250px', overflowY: 'auto', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', whiteSpace: 'pre-wrap' }}>
          {cmdOutput ? (
            <>
              {cmdOutput}
              <div ref={cmdOutputEndRef} />
            </>
          ) : (
            <span style={{ color: '#555555' }}>Терминал готов. Введите команду или выберите быструю команду выше для выполнения.</span>
          )}
        </div>

        {/* Ввод команды */}
        <form 
          onSubmit={(e) => { e.preventDefault(); executeCommand(); }} 
          style={{ display: 'flex', gap: '10px', alignItems: 'center' }}
        >
          <input 
            type="text" 
            className="form-input" 
            placeholder="Введите команду (например: df -h, ip link show, iptables -S)..."
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            disabled={cmdLoading}
            style={{ margin: 0, fontFamily: 'var(--font-mono)' }}
          />
          <button type="submit" className="btn btn-primary" style={{ padding: '0 20px', height: '42px' }} disabled={cmdLoading || !command.trim()}>
            {cmdLoading ? <span className="spinner" style={{ width: '14px', height: '14px', border: '2px solid #fff', borderTopColor: 'transparent' }} /> : <Play size={14} />}
            Запуск
          </button>
          {cmdOutput && (
            <button 
              type="button" 
              className="btn btn-secondary" 
              style={{ height: '42px', padding: '0 12px' }} 
              onClick={() => setCmdOutput('')}
              title="Очистить терминал"
            >
              <Trash2 size={14} />
            </button>
          )}
        </form>
      </div>
    </div>
  );
};

export default InfraPanel;
