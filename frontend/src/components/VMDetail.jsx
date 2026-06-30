import React, { useEffect, useState, useRef } from 'react';
import { X, RefreshCw, Cpu, HardDrive, ShieldAlert, Terminal, Activity, Layers, ListFilter, Play, Square, RotateCw, Monitor, Settings, Trash2, Copy, Check, Eye, EyeOff, AlertTriangle, Key, Shield } from 'lucide-react';
import VncConsole from './VncConsole';
import BackupList from './BackupList';

const VMDetail = ({ vmName, onClose, onActionSuccess }) => {
  const [vm, setVm] = useState(null);
  const [sshData, setSshData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sshLoading, setSshLoading] = useState(false);
  const [error, setError] = useState(null);
  const [sshError, setSshError] = useState(null);
  
  const [activeTab, setActiveTab] = useState('vnc');
  const [bypassVncProgress, setBypassVncProgress] = useState(false);
  const [activeSubTab, setActiveSubTab] = useState('processes');
  
  const [cpuCores, setCpuCores] = useState(2);
  const [memoryGb, setMemoryGb] = useState(2);
  const [diskGb, setDiskGb] = useState(20);
  const [hasInitializedResize, setHasInitializedResize] = useState(false);
  const [savingResize, setSavingResize] = useState(false);

  const [actionLoading, setActionLoading] = useState(null);
  const [showPassword, setShowPassword] = useState(false);
  const [copiedField, setCopiedField] = useState(null);

  const [command, setCommand] = useState('');
  const [executing, setExecuting] = useState(false);
  const [cwd, setCwd] = useState('~');
  const [terminalHistory, setTerminalHistory] = useState([]);
  const [applyingNat, setApplyingNat] = useState(false);

  const terminalEndRef = useRef(null);

  const isPrivateIp = (ip) => {
    if (!ip) return false;
    return ip.startsWith('172.') || ip.startsWith('10.') || ip.startsWith('192.168.');
  };

  const handleApplyNat = async () => {
    const ip = getSshIp();
    if (!ip) return;
    setApplyingNat(true);
    const port = vm.ssh_port || 2222;
    const cmd1 = `iptables -t nat -A PREROUTING -p tcp --dport ${port} -j DNAT --to-destination ${ip}:22`;
    const cmd2 = `iptables -A FORWARD -p tcp -d ${ip} --dport 22 -j ACCEPT`;
    try {
      let response = await fetch('/api/infra/execute-command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command: cmd1 }) });
      if (!response.ok) throw new Error('Ошибка при пробросе PREROUTING');
      response = await fetch('/api/infra/execute-command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command: cmd2 }) });
      if (!response.ok) throw new Error('Ошибка при пробросе FORWARD');
      alert(`Проброс портов на хосте успешно настроен!`);
    } catch (err) {
      alert(`Ошибка настройки проброса портов: ${err.message}`);
    } finally {
      setApplyingNat(false);
    }
  };
  
  const fetchVmDetails = async () => {
    try {
      const response = await fetch(`/api/vms/${vmName}`);
      if (!response.ok) throw new Error('Не удалось получить статус виртуальной машины.');
      const data = await response.json();
      setVm(data);
      setError(null);

      if (data && !hasInitializedResize) {
        setCpuCores(data.cpu_cores || 2);
        const currentRam = parseInt(data.memory) || 2;
        const currentDisk = data.disks && data.disks[0] ? parseInt(data.disks[0].size) || 20 : 20;
        setMemoryGb(currentRam);
        setDiskGb(currentDisk);
        setHasInitializedResize(true);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchSshDetails = async () => {
    if (!vm || vm.status !== 'Running') {
      setSshData(null);
      setSshLoading(false);
      return;
    }
    setSshLoading(true);
    try {
      const response = await fetch(`/api/vms/${vmName}/ssh-details`);
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'SSH соединение недоступно.');
      }
      const data = await response.json();
      setSshData(data);
      setSshError(null);
    } catch (err) {
      setSshError(err.message);
    } finally {
      setSshLoading(false);
    }
  };

  useEffect(() => {
    fetchVmDetails();
    const interval = setInterval(fetchVmDetails, 4000);
    return () => clearInterval(interval);
  }, [vmName]);

  useEffect(() => {
    fetchSshDetails();
    const interval = setInterval(fetchSshDetails, 6000);
    return () => clearInterval(interval);
  }, [vmName, vm?.status]);

  useEffect(() => {
    if (sshData && terminalHistory.length === 0) {
      setTerminalHistory([
        { type: 'info', text: `Welcome to ${sshData.name} SSH session.` },
        { type: 'info', text: `OS: ${sshData.os_name} | Kernel: ${sshData.kernel}` },
        { type: 'info', text: `Type your bash commands below.` },
        { type: 'info', text: '' }
      ]);
    }
  }, [sshData]);

  useEffect(() => {
    if (terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [terminalHistory]);

  const handleCopy = (text, field) => {
    navigator.clipboard.writeText(text);
    setCopiedField(field);
    setTimeout(() => setCopiedField(null), 2000);
  };

  const handlePowerAction = async (action) => {
    setActionLoading(action);
    try {
      const response = await fetch(`/api/vms/${vmName}/${action}`, { method: 'POST' });
      if (!response.ok) throw new Error(`Действие ${action} завершилось ошибкой.`);
      if (action === 'start' || action === 'restart') setBypassVncProgress(false);
      await fetchVmDetails();
      if (onActionSuccess) onActionSuccess();
    } catch (err) {
      alert(`Ошибка: ${err.message}`);
    } finally {
      setActionLoading(null);
    }
  };

  const handleDeleteVM = async () => {
    if (!confirm(`Вы действительно хотите безвозвратно удалить виртуальную машину "${vmName}" и все ее диски?`)) return;
    setActionLoading('delete');
    try {
      const response = await fetch(`/api/vms/${vmName}`, { method: 'DELETE' });
      if (!response.ok) throw new Error('Не удалось удалить ВМ.');
      if (onActionSuccess) onActionSuccess();
      onClose();
    } catch (err) {
      alert(`Ошибка: ${err.message}`);
      setActionLoading(null);
    }
  };

  const handleResize = async (e) => {
    e.preventDefault();
    setSavingResize(true);
    try {
      const response = await fetch(`/api/vms/${vmName}/resize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cpu_cores: parseInt(cpuCores), memory_gb: parseInt(memoryGb), disk_gb: parseInt(diskGb) })
      });
      if (!response.ok) throw new Error('Не удалось обновить ресурсы.');
      alert('Настройки успешно обновлены! Изменения вступят в силу после перезапуска виртуалки.');
      fetchVmDetails();
      if (onActionSuccess) onActionSuccess();
    } catch (err) {
      alert(`Ошибка: ${err.message}`);
    } finally {
      setSavingResize(false);
    }
  };

  const handleExecuteCommand = async (e) => {
    e.preventDefault();
    const cmdText = command.trim();
    if (!cmdText || executing) return;
    setExecuting(true);
    setCommand('');
    const promptText = `${sshData?.username || 'root'}@${sshData?.host || 'vm'}:${cwd}$ ${cmdText}`;
    setTerminalHistory(prev => [...prev, { type: 'prompt', text: promptText }]);
    try {
      const response = await fetch(`/api/vms/${vmName}/execute`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command: cmdText, cwd: cwd })
      });
      if (!response.ok) throw new Error('Ошибка связи с API');
      const resData = await response.json();
      if (resData.cwd) setCwd(resData.cwd);
      setTerminalHistory(prev => {
        const next = [...prev];
        if (resData.stdout) next.push({ type: 'stdout', text: resData.stdout });
        if (resData.stderr) next.push({ type: 'stderr', text: resData.stderr });
        if (!resData.stdout && !resData.stderr && resData.exit_status !== 0) {
          next.push({ type: 'stderr', text: `Exited with status ${resData.exit_status}` });
        }
        return next;
      });
    } catch (err) {
      setTerminalHistory(prev => [...prev, { type: 'stderr', text: `Error: ${err.message}` }]);
    } finally {
      setExecuting(false);
    }
  };

  const getSshIp = () => {
    if (!vm || !vm.ips || vm.ips.length === 0) return null;
    const bridgeIp = vm.ips.find(ip => !ip.startsWith('10.244.') && !ip.startsWith('10.42.') && !ip.startsWith('10.0.2.') && !ip.startsWith('127.0.') && !ip.includes(':'));
    if (bridgeIp) return bridgeIp;
    const podIp = vm.ips.find(ip => (ip.startsWith('10.42.') || ip.startsWith('10.244.')) && !ip.includes(':'));
    if (podIp) return podIp;
    return vm.ips.find(ip => !ip.includes(':')) || vm.ips[0];
  };

  const getBridgeIp = () => {
    if (!vm || !vm.ips || vm.ips.length === 0) return null;
    return vm.ips.find(ip => !ip.startsWith('10.244.') && !ip.startsWith('10.42.') && !ip.startsWith('10.0.2.') && !ip.startsWith('127.0.') && !ip.includes(':')) || null;
  };

  if (loading && !vm) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '400px' }}>
        <div className="spinner" />
      </div>
    );
  }

  if (error && !vm) {
    return (
      <div className="glass-card" style={{ textAlign: 'center', padding: '40px' }}>
        <ShieldAlert size={48} color="var(--status-danger)" />
        <h3 className="section-title" style={{ justifyContent: 'center', marginTop: '16px' }}>Ошибка загрузки ВМ</h3>
        <p className="text-muted">{error}</p>
      </div>
    );
  }

  const isNetworkConfigured = vm && (vm.status === 'Stopped' || getBridgeIp() !== null);
  const canClickTab = vm && (vm.status === 'Running' || isNetworkConfigured);
  const sshIp = getSshIp();
  const currentDiskLimit = vm.disks && vm.disks[0] ? parseInt(vm.disks[0].size) || 20 : 20;

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: '32px', alignItems: 'start' }}>
      
      {/* Левая панель - Управление и статус */}
      <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
        
        {/* Базовая инфа */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 600 }}>{vm.name}</h3>
            <span className={`badge badge-${vm.status === 'Running' ? 'success' : 'danger'}`}>
              <span className="status-dot"></span>
              {vm.status === 'Running' ? 'Active' : vm.status}
            </span>
          </div>
          
          <div style={{ display: 'flex', gap: '8px' }}>
            {vm.status !== 'Running' ? (
              <button className="btn btn-primary" style={{ flex: 1 }} onClick={() => handlePowerAction('start')} disabled={actionLoading !== null}>
                {actionLoading === 'start' ? <span className="spinner"/> : <><Play size={14} /> Запуск</>}
              </button>
            ) : (
              <>
                <button className="btn btn-secondary" style={{ flex: 1 }} onClick={() => handlePowerAction('stop')} disabled={actionLoading !== null}>
                  {actionLoading === 'stop' ? <span className="spinner"/> : <><Square size={14} /> Стоп</>}
                </button>
                <button className="btn btn-secondary btn-icon" onClick={() => handlePowerAction('restart')} disabled={actionLoading !== null}>
                  {actionLoading === 'restart' ? <span className="spinner"/> : <RotateCw size={14} />}
                </button>
              </>
            )}
          </div>
        </div>

        {/* Выделенные спецификации */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', textAlign: 'center', background: 'var(--bg-body)', padding: '12px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
          <div>
            <div className="text-muted" style={{ fontSize: '0.75rem' }}>CPU</div>
            <div style={{ fontWeight: 600 }}>{vm.cpu_cores}</div>
          </div>
          <div>
            <div className="text-muted" style={{ fontSize: '0.75rem' }}>RAM</div>
            <div style={{ fontWeight: 600 }}>{vm.memory}</div>
          </div>
          <div>
            <div className="text-muted" style={{ fontSize: '0.75rem' }}>Disk</div>
            <div style={{ fontWeight: 600 }}>{vm.disks?.[0]?.size || 'N/A'}</div>
          </div>
        </div>

        {/* Реквизиты */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <h4 style={{ fontSize: '0.9rem', fontWeight: 600, margin: 0 }}>Подключение</h4>
          
          <div className="input-group" style={{ margin: 0 }}>
            <label className="input-label">IP Address</label>
            <div style={{ display: 'flex', gap: '8px' }}>
              <input type="text" readOnly className="form-control" style={{ fontFamily: 'var(--font-mono)' }} value={sshIp || 'Ожидание...'} />
              <button className="btn btn-secondary btn-icon" onClick={() => handleCopy(sshIp, 'ip')} disabled={!sshIp}>
                {copiedField === 'ip' ? <Check size={14} color="var(--status-success)" /> : <Copy size={14} />}
              </button>
            </div>
          </div>

          {vm.os_type !== 'windows' && (
            <div style={{ padding: '12px', background: 'var(--bg-body)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)', fontSize: '0.85rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                <span className="text-muted">Пользователь:</span>
                <strong style={{ fontFamily: 'var(--font-mono)' }}>{vm.credentials?.username || 'root'}</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="text-muted">Пароль:</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <strong style={{ fontFamily: 'var(--font-mono)' }}>{showPassword ? (vm.credentials?.password || 'N/A') : '••••••••'}</strong>
                  <button className="btn-icon-only" onClick={() => setShowPassword(!showPassword)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}>
                    {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Опасная зона */}
        <div style={{ marginTop: 'auto', paddingTop: '24px', borderTop: '1px solid var(--border-subtle)' }}>
          <button className="btn btn-danger" style={{ width: '100%' }} onClick={handleDeleteVM} disabled={actionLoading !== null}>
            {actionLoading === 'delete' ? <span className="spinner"/> : <><Trash2 size={14} /> Удалить виртуалку</>}
          </button>
        </div>
      </div>

      {/* Правая панель - Вкладки контента */}
      <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', minHeight: '600px', padding: '0' }}>
        
        {/* Навигация */}
        <div style={{ display: 'flex', gap: '8px', padding: '16px 24px', borderBottom: '1px solid var(--border-subtle)' }}>
          {vm.status === 'Running' && (
            <>
              <button className={`btn ${activeTab === 'vnc' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setActiveTab('vnc')}>
                <Monitor size={14} /> Экран
              </button>
              {vm.os_type !== 'windows' && (
                <>
                  <button className={`btn ${activeTab === 'terminal' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => canClickTab && setActiveTab('terminal')} disabled={!canClickTab}>
                    <Terminal size={14} /> SSH Терминал
                  </button>
                  <button className={`btn ${activeTab === 'monitoring' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => canClickTab && setActiveTab('monitoring')} disabled={!canClickTab}>
                    <Activity size={14} /> Метрики
                  </button>
                </>
              )}
            </>
          )}
          <button className={`btn ${activeTab === 'backups' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => canClickTab && setActiveTab('backups')} disabled={!canClickTab}>
            💾 Бэкапы
          </button>
          <button className={`btn ${activeTab === 'resize' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => canClickTab && setActiveTab('resize')} disabled={!canClickTab}>
            <Settings size={14} /> Настройки
          </button>
        </div>

        {/* Контент вкладок */}
        <div style={{ padding: '24px', flex: 1, display: 'flex', flexDirection: 'column' }}>
          
          {/* VNC */}
          {activeTab === 'vnc' && (
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#000', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
              {vm.status !== 'Running' ? (
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
                  <Monitor size={48} />
                  <p style={{ marginTop: '16px' }}>ВМ выключена</p>
                </div>
              ) : (
                <VncConsole name={vmName} username={vm.credentials?.username} password={vm.credentials?.password} isInline={true} onClose={() => {}} />
              )}
            </div>
          )}

          {/* SSH */}
          {activeTab === 'terminal' && (
            <div style={{ display: 'flex', flexDirection: 'column', flex: 1, background: '#0f172a', borderRadius: 'var(--radius-md)', overflow: 'hidden', padding: '16px' }}>
              {sshError && !sshData ? (
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--status-danger)' }}>
                  <ShieldAlert size={32} />
                  <p style={{ marginTop: '16px' }}>{sshError}</p>
                </div>
              ) : (
                <>
                  <div style={{ flex: 1, color: '#f8fafc', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', overflowY: 'auto', marginBottom: '16px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {terminalHistory.map((line, idx) => (
                      <div key={idx} style={{ color: line.type === 'prompt' ? '#38bdf8' : line.type === 'stderr' ? '#f87171' : line.type === 'info' ? '#94a3b8' : 'inherit', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                        {line.text}
                      </div>
                    ))}
                    <div ref={terminalEndRef} />
                  </div>
                  <form onSubmit={handleExecuteCommand} style={{ display: 'flex', gap: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', background: 'rgba(255,255,255,0.1)', padding: '0 12px', color: '#94a3b8', borderRadius: 'var(--radius-md)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem' }}>
                      {sshData?.username || 'root'}@{sshData?.host || 'vm'}:{cwd}$
                    </div>
                    <input type="text" value={command} onChange={(e) => setCommand(e.target.value)} disabled={executing} autoFocus className="form-control" style={{ background: 'rgba(255,255,255,0.05)', color: '#fff', border: '1px solid rgba(255,255,255,0.1)' }} />
                    <button type="submit" className="btn btn-primary" disabled={executing || !command.trim()}>Выполнить</button>
                  </form>
                </>
              )}
            </div>
          )}

          {/* Monitoring */}
          {activeTab === 'monitoring' && (
            <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
              {!sshData ? (
                <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', flex: 1 }}><span className="spinner" /></div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                  <div className="grid-cols-3">
                    <div className="stat-box">
                      <span className="stat-box-title">CPU Usage</span>
                      <span className="stat-box-value">{sshData.cpu.usage_percent}%</span>
                      <div className="progress-track"><div className="progress-fill primary" style={{ width: `${sshData.cpu.usage_percent}%` }} /></div>
                    </div>
                    <div className="stat-box">
                      <span className="stat-box-title">Memory</span>
                      <span className="stat-box-value">{sshData.memory.usage_percent}%</span>
                      <div className="progress-track"><div className="progress-fill success" style={{ width: `${sshData.memory.usage_percent}%` }} /></div>
                    </div>
                    <div className="stat-box">
                      <span className="stat-box-title">Disk (/)</span>
                      <span className="stat-box-value">{sshData.disk.usage_percent}%</span>
                      <div className="progress-track"><div className="progress-fill warning" style={{ width: `${sshData.disk.usage_percent}%` }} /></div>
                    </div>
                  </div>

                  <div>
                    <h4 className="section-title">Топ процессов</h4>
                    <div style={{ overflowX: 'auto', background: 'var(--bg-body)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                      <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
                        <thead>
                          <tr style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)' }}>
                            <th style={{ padding: '12px' }}>PID</th>
                            <th style={{ padding: '12px' }}>User</th>
                            <th style={{ padding: '12px' }}>CPU%</th>
                            <th style={{ padding: '12px' }}>MEM%</th>
                            <th style={{ padding: '12px' }}>Command</th>
                          </tr>
                        </thead>
                        <tbody>
                          {sshData.processes?.slice(0, 8).map((p, i) => (
                            <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                              <td style={{ padding: '12px', fontFamily: 'var(--font-mono)' }}>{p.pid}</td>
                              <td style={{ padding: '12px' }}>{p.user}</td>
                              <td style={{ padding: '12px', color: 'var(--accent-primary)', fontWeight: 600 }}>{p.cpu}%</td>
                              <td style={{ padding: '12px' }}>{p.mem}%</td>
                              <td style={{ padding: '12px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>{p.command.substring(0, 50)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Backups */}
          {activeTab === 'backups' && <BackupList vmName={vmName} vmStatus={vm.status} onRestoreStarted={fetchVmDetails} />}

          {/* Resize */}
          {activeTab === 'resize' && (
            <div style={{ maxWidth: '600px' }}>
              <form onSubmit={handleResize} style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                <div style={{ padding: '16px', background: 'var(--status-warning-bg)', borderRadius: 'var(--radius-md)', color: 'var(--status-warning)', display: 'flex', gap: '12px' }}>
                  <AlertTriangle size={20} style={{ flexShrink: 0 }} />
                  <p style={{ fontSize: '0.9rem', margin: 0 }}>Изменение CPU/RAM применится после перезапуска ВМ. Диск можно только увеличивать.</p>
                </div>

                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <span className="input-label">CPU Cores</span>
                    <span style={{ fontWeight: 600, color: 'var(--accent-primary)' }}>{cpuCores} Cores</span>
                  </div>
                  <input type="range" min="1" max="16" value={cpuCores} onChange={(e) => setCpuCores(parseInt(e.target.value))} style={{ width: '100%' }} disabled={savingResize} />
                </div>

                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <span className="input-label">Memory (RAM)</span>
                    <span style={{ fontWeight: 600, color: 'var(--accent-primary)' }}>{memoryGb} GB</span>
                  </div>
                  <input type="range" min="1" max="64" value={memoryGb} onChange={(e) => setMemoryGb(parseInt(e.target.value))} style={{ width: '100%' }} disabled={savingResize} />
                </div>

                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <span className="input-label">Storage Disk</span>
                    <span style={{ fontWeight: 600, color: 'var(--accent-primary)' }}>{diskGb} GB</span>
                  </div>
                  <input type="range" min={currentDiskLimit} max="500" step="10" value={diskGb} onChange={(e) => setDiskGb(parseInt(e.target.value))} style={{ width: '100%' }} disabled={savingResize} />
                </div>

                <button type="submit" className="btn btn-primary" disabled={savingResize}>
                  {savingResize ? <span className="spinner" /> : 'Сохранить параметры ВМ'}
                </button>
              </form>
            </div>
          )}

        </div>
      </div>
    </div>
  );
};

export default VMDetail;
