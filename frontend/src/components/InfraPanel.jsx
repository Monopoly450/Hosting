import React, { useState, useEffect, useRef } from 'react';
import { GitBranch, RefreshCw, Terminal as TerminalIcon, ShieldAlert, Cpu, HardDrive, FileText, ChevronRight, Play, CheckCircle, AlertCircle, Trash2 } from 'lucide-react';

const InfraPanel = () => {
  const [gitInfo, setGitInfo] = useState(null);
  const [gitLoading, setGitLoading] = useState(true);
  const [pullLoading, setPullLoading] = useState(false);
  const [gitOutput, setGitOutput] = useState('');

  const [selectedService, setSelectedService] = useState('backend');
  const [logsText, setLogsText] = useState('');
  const [logsLoading, setLogsLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);

  const [command, setCommand] = useState('');
  const [cmdOutput, setCmdOutput] = useState('');
  const [cmdLoading, setCmdLoading] = useState(false);

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
    return ip.startsWith('172.') || ip.startsWith('10.') || ip.startsWith('192.168.');
  };

  const logsEndRef = useRef(null);
  const cmdOutputEndRef = useRef(null);

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

  const handleGitPull = async () => {
    if (!window.confirm('Вы уверены, что хотите обновить код с GitHub и пересобрать все службы?')) {
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

  useEffect(() => {
    fetchGitInfo();
    fetchLogs();
    fetchVms();
  }, []);

  useEffect(() => {
    fetchLogs();
  }, [selectedService]);

  useEffect(() => {
    let interval;
    if (autoRefresh) {
      interval = setInterval(fetchLogs, 4000);
    }
    return () => clearInterval(interval);
  }, [autoRefresh, selectedService]);

  useEffect(() => {
    if (logsEndRef.current) logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
  }, [logsText]);

  useEffect(() => {
    if (cmdOutputEndRef.current) cmdOutputEndRef.current.scrollIntoView({ behavior: 'smooth' });
  }, [cmdOutput]);

  const quickCommands = [
    { name: 'Диски', cmd: 'df -h' },
    { name: 'Память', cmd: 'free -m' },
    { name: 'Контейнеры', cmd: 'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"' },
    { name: 'Сеть (IP)', cmd: 'ip -br addr' },
    { name: 'Аптайм', cmd: 'uptime' },
    { name: 'IPTables NAT', cmd: 'iptables -t nat -vnL --line-numbers' }
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      <div>
        <h2 className="section-title" style={{ margin: 0 }}>
          <TerminalIcon size={22} color="var(--accent-primary)" />
          Инфраструктура и Логи
        </h2>
        <p className="text-muted" style={{ margin: '4px 0 0', fontSize: '0.9rem' }}>Хостовый уровень (KubeVirt + Docker)</p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: '24px' }}>
        
        {/* Git Card */}
        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <h3 className="section-title" style={{ margin: 0, borderBottom: '1px solid var(--border-subtle)', paddingBottom: '16px' }}>
            <GitBranch size={18} /> Синхронизация с GitHub
          </h3>
          
          {gitLoading && !gitInfo ? (
            <div style={{ padding: '32px', textAlign: 'center' }}><span className="spinner" /></div>
          ) : gitInfo ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', fontSize: '0.85rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span className="text-muted">Ветка:</span>
                <span style={{ fontWeight: 600 }}>{gitInfo.branch}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span className="text-muted">Последний коммит:</span>
                <span style={{ fontFamily: 'var(--font-mono)' }}>{gitInfo.commit_hash?.slice(0, 8) || 'N/A'}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span className="text-muted">Автор:</span>
                <span style={{ fontWeight: 500 }}>{gitInfo.author}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span className="text-muted">Статус:</span>
                <span className={`badge badge-${gitInfo.status_text === 'Up to date' ? 'success' : 'warning'}`}>
                  {gitInfo.status_text}
                </span>
              </div>

              {gitInfo.local_changes && (
                <div style={{ marginTop: '8px', padding: '12px', background: 'var(--status-warning-bg)', color: 'var(--status-warning)', borderRadius: 'var(--radius-md)', fontSize: '0.8rem' }}>
                  <strong>Внимание: есть локальные изменения!</strong>
                  <pre style={{ margin: '4px 0 0', fontFamily: 'var(--font-mono)', overflowX: 'auto' }}>{gitInfo.local_changes}</pre>
                </div>
              )}
            </div>
          ) : (
            <div className="text-muted">Не удалось получить данные Git.</div>
          )}

          <div style={{ display: 'flex', gap: '8px', marginTop: 'auto', paddingTop: '16px' }}>
            <button className="btn btn-secondary" onClick={fetchGitInfo} disabled={gitLoading || pullLoading}>
              <RefreshCw size={14} className={gitLoading ? 'spinner' : ''} /> Проверить
            </button>
            <button className="btn btn-primary" onClick={handleGitPull} disabled={pullLoading} style={{ flex: 1 }}>
              {pullLoading ? <span className="spinner"/> : 'Обновить с GitHub'}
            </button>
          </div>
        </div>

        {/* Git Output Terminal */}
        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '12px', padding: 0, overflow: 'hidden' }}>
          <div style={{ background: '#0f172a', padding: '12px 16px', borderBottom: '1px solid #1e293b', color: '#94a3b8', fontSize: '0.8rem', fontWeight: 600, display: 'flex', justifyContent: 'space-between' }}>
            <span>ЛОГ СБОРКИ / ОБНОВЛЕНИЯ</span>
            <span>git pull & build</span>
          </div>
          <div style={{ flex: 1, background: '#0f172a', padding: '0 16px 16px', color: '#f8fafc', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', overflowY: 'auto', whiteSpace: 'pre-wrap' }}>
            {gitOutput || 'Ожидание запуска...'}
          </div>
        </div>
      </div>

      {/* Docker Logs */}
      <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
          <h3 className="section-title" style={{ margin: 0 }}>
            <FileText size={18} /> Логи контейнеров Aegis
          </h3>
          <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
            <select 
              className="form-control" 
              value={selectedService}
              onChange={(e) => setSelectedService(e.target.value)}
            >
              <option value="backend">FastAPI Бэкенд</option>
              <option value="frontend">Админ Панель (Nginx)</option>
              <option value="orchestrator">Go-Оркестратор</option>
              <option value="db">База данных Postgres</option>
            </select>
            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.85rem', cursor: 'pointer', color: 'var(--text-secondary)' }}>
              <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
              Автообновление (4с)
            </label>
            <button className="btn btn-secondary btn-icon" onClick={fetchLogs} disabled={logsLoading}>
              <RefreshCw size={14} className={logsLoading ? 'spinner' : ''} />
            </button>
          </div>
        </div>

        <div style={{ height: '350px', background: '#0f172a', borderRadius: 'var(--radius-md)', padding: '16px', color: '#f8fafc', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', overflowY: 'auto', whiteSpace: 'pre-wrap' }}>
          {logsText ? (
            <>
              {logsText}
              <div ref={logsEndRef} />
            </>
          ) : (
            <div style={{ color: '#64748b', textAlign: 'center', marginTop: '100px' }}>Нет логов</div>
          )}
        </div>
      </div>

      {/* Host Terminal */}
      <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div>
          <h3 className="section-title" style={{ margin: 0 }}>
            <TerminalIcon size={18} /> Консоль хост-сервера
          </h3>
          <p className="text-muted" style={{ margin: '4px 0 0', fontSize: '0.85rem' }}>Команды выполняются на хосте с root правами.</p>
        </div>

        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          {quickCommands.map((qc) => (
            <button key={qc.name} className="btn btn-secondary" style={{ fontSize: '0.8rem' }} onClick={() => executeCommand(qc.cmd)} disabled={cmdLoading}>
              {qc.name}
            </button>
          ))}
        </div>

        {vms.filter(vm => vm.status === 'Running' && getSshIp(vm) && isPrivateIp(getSshIp(vm))).length > 0 && (
          <div style={{ background: 'var(--status-warning-bg)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--status-warning)' }}>
            <strong style={{ color: 'var(--status-warning)', display: 'block', marginBottom: '8px', fontSize: '0.9rem' }}>⚠️ Найдена ВМ в приватной сети (требуется NAT)</strong>
            {vms.filter(vm => vm.status === 'Running' && getSshIp(vm) && isPrivateIp(getSshIp(vm))).map(vm => {
              const ip = getSshIp(vm);
              const port = vm.ssh_port || 2222;
              const cmd1 = `iptables -t nat -A PREROUTING -p tcp --dport ${port} -j DNAT --to-destination ${ip}:22`;
              const cmd2 = `iptables -A FORWARD -p tcp -d ${ip} --dport 22 -j ACCEPT`;
              return (
                <div key={vm.name} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'var(--bg-surface)', padding: '12px', borderRadius: 'var(--radius-sm)', marginTop: '8px' }}>
                  <span style={{ fontSize: '0.85rem' }}>{vm.name} (IP: <code>{ip}</code>)</span>
                  <button className="btn btn-primary btn-sm" onClick={async () => {
                    if (window.confirm(`Выполнить проброс портов на хосте для ${vm.name}?`)) {
                      setCmdLoading(true);
                      setCmdOutput(prev => prev + `\n$ ${cmd1}\n$ ${cmd2}\n`);
                      try {
                        let response = await fetch('/api/infra/execute-command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command: cmd1 }) });
                        let data = await response.json();
                        setCmdOutput(prev => prev + (data.output || '') + '\n');
                        response = await fetch('/api/infra/execute-command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command: cmd2 }) });
                        data = await response.json();
                        setCmdOutput(prev => prev + (data.output || '') + '\nУспешно применены правила проброса!\n');
                      } catch (err) {
                        setCmdOutput(prev => prev + `Ошибка: ${err.message}\n`);
                      } finally {
                        setCmdLoading(false);
                      }
                    }
                  }}>⚡ NAT Порт {port}</button>
                </div>
              );
            })}
          </div>
        )}

        <div style={{ height: '250px', background: '#0f172a', borderRadius: 'var(--radius-md)', padding: '16px', color: '#10b981', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', overflowY: 'auto', whiteSpace: 'pre-wrap' }}>
          {cmdOutput ? (
            <>
              {cmdOutput}
              <div ref={cmdOutputEndRef} />
            </>
          ) : (
            <span style={{ color: '#64748b' }}>Терминал готов...</span>
          )}
        </div>

        <form onSubmit={(e) => { e.preventDefault(); executeCommand(); }} style={{ display: 'flex', gap: '8px' }}>
          <input 
            type="text" 
            className="form-control" 
            placeholder="Введите команду..."
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            disabled={cmdLoading}
            style={{ fontFamily: 'var(--font-mono)' }}
          />
          <button type="submit" className="btn btn-primary" disabled={cmdLoading || !command.trim()}>
            {cmdLoading ? <span className="spinner"/> : <Play size={14} />} Запуск
          </button>
          {cmdOutput && (
            <button type="button" className="btn btn-secondary btn-icon" onClick={() => setCmdOutput('')}>
              <Trash2 size={14} />
            </button>
          )}
        </form>
      </div>

    </div>
  );
};

export default InfraPanel;
