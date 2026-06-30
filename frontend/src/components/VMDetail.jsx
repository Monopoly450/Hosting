import React, { useEffect, useState, useRef } from 'react';
import { X, RefreshCw, Cpu, HardDrive, ShieldAlert, Terminal, Activity, Layers, ListFilter, Play, Square, RotateCw, Monitor, Settings, Trash2, Copy, Check, Eye, EyeOff, AlertTriangle, Key, Shield, Network, Send } from 'lucide-react';
import VncConsole from './VncConsole';
import BackupList from './BackupList';

const VMDetail = ({ vmName, onClose, onActionSuccess }) => {
  const [vm, setVm] = useState(null);
  const [sshData, setSshData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sshLoading, setSshLoading] = useState(false);
  const [error, setError] = useState(null);
  const [sshError, setSshError] = useState(null);
  
  const [cpuCores, setCpuCores] = useState(2);
  const [memoryGb, setMemoryGb] = useState(2);
  const [diskGb, setDiskGb] = useState(20);
  const [hasInitializedResize, setHasInitializedResize] = useState(false);
  const [savingResize, setSavingResize] = useState(false);

  const [actionLoading, setActionLoading] = useState(null);
  const [showPassword, setShowPassword] = useState(false);
  const [copiedField, setCopiedField] = useState(null);

  // Terminal state
  const [command, setCommand] = useState('');
  const [executing, setExecuting] = useState(false);
  const [cwd, setCwd] = useState('~');
  const [terminalHistory, setTerminalHistory] = useState([]);
  const [applyingNat, setApplyingNat] = useState(false);
  const [activeTab, setActiveTab] = useState('overview'); // 'overview', 'vnc', 'backups'

  // Migration state
  const [showMigrateModal, setShowMigrateModal] = useState(false);
  const [externalServers, setExternalServers] = useState([]);
  const [selectedTargetServer, setSelectedTargetServer] = useState('');
  const [migrating, setMigrating] = useState(false);

  const fetchExternalServersForMigration = async () => {
    try {
      const response = await fetch('/api/external-servers');
      if (response.ok) {
        const data = await response.json();
        setExternalServers(data);
        if (data.length > 0) setSelectedTargetServer(data[0].id);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleMigrate = async () => {
    if (!selectedTargetServer) {
      alert("Выберите сервер назначения");
      return;
    }
    if (!window.confirm("Вы уверены? Виртуальная машина будет перенесена на внешний сервер и удалена из локального кластера. Процесс может занять несколько минут.")) {
      return;
    }
    setMigrating(true);
    try {
      const response = await fetch(`/api/vms/${vmName}/migrate?target_server_id=${selectedTargetServer}`, {
        method: 'POST'
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || "Ошибка миграции");
      }
      alert("Миграция успешно завершена! Машина теперь доступна в списке как внешний сервер.");
      setShowMigrateModal(false);
      onClose();
      if (onActionSuccess) onActionSuccess();
    } catch (err) {
      alert(`Ошибка: ${err.message}`);
    } finally {
      setMigrating(false);
    }
  };


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
      if (!response.ok) throw new Error('SSH недоступен');
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
      await fetchVmDetails();
      if (onActionSuccess) onActionSuccess();
    } catch (err) {
      alert(`Ошибка: ${err.message}`);
    } finally {
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
    return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '400px' }}><div className="spinner" /></div>;
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

  const sshIp = getSshIp();
  const bridgeIp = getBridgeIp();
  const currentDiskLimit = vm.disks && vm.disks[0] ? parseInt(vm.disks[0].size) || 20 : 20;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* HEADER SECTION */}
      <div className="glass-card" style={{ padding: '24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '20px' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '8px' }}>
              <h2 style={{ margin: 0, fontSize: '1.6rem', color: 'var(--text-heading)' }}>{vm.name}</h2>
              <span className={`badge badge-${vm.status === 'Running' ? 'success' : 'danger'}`} style={{ padding: '6px 12px', fontSize: '0.85rem' }}>
                <span className="status-dot"></span>
                {vm.status === 'Running' ? 'Active' : vm.status}
              </span>
            </div>
            <div style={{ display: 'flex', gap: '24px', fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><HardDrive size={16}/> {vm.os_type || 'Unknown OS'}</span>
              <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><Network size={16}/> {vm.node || 'Node-1'}</span>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '12px' }}>
            {vm.status !== 'Running' ? (
              <button className="btn btn-primary" onClick={() => handlePowerAction('start')} disabled={actionLoading !== null}>
                {actionLoading === 'start' ? <span className="spinner"/> : <><Play size={14} /> Start</>}
              </button>
            ) : (
              <>
                <button className="btn btn-secondary" onClick={() => handlePowerAction('stop')} disabled={actionLoading !== null}>
                  {actionLoading === 'stop' ? <span className="spinner"/> : <><Square size={14} /> Stop</>}
                </button>
                <button className="btn btn-secondary" onClick={() => handlePowerAction('restart')} disabled={actionLoading !== null}>
                  {actionLoading === 'restart' ? <span className="spinner"/> : <><RotateCw size={14} /> Reboot</>}
                </button>
              </>
            )}
            
            <div style={{ width: '1px', background: 'var(--border-subtle)', margin: '0 8px' }}></div>
            
            <button className={`btn ${activeTab === 'overview' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setActiveTab('overview')}>
              <Activity size={14} /> Обзор
            </button>
            <button className={`btn ${activeTab === 'vnc' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setActiveTab('vnc')} disabled={vm.status !== 'Running'}>
              <Monitor size={14} /> VNC
            </button>
            <button className={`btn ${activeTab === 'backups' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setActiveTab('backups')}>
              💾 Бэкапы
            </button>
            <div style={{ width: '1px', background: 'var(--border-subtle)', margin: '0 8px' }}></div>
            <button className="btn btn-secondary" onClick={() => { setShowMigrateModal(true); fetchExternalServersForMigration(); }}>
              <Send size={14} /> Перенести
            </button>
          </div>
        </div>
      </div>

      {activeTab === 'vnc' && (
        <div className="glass-card" style={{ padding: 0, overflow: 'hidden', background: '#000', borderRadius: 'var(--radius-lg)' }}>
          <VncConsole name={vmName} username={vm.credentials?.username} password={vm.credentials?.password} isInline={true} />
        </div>
      )}

      {activeTab === 'backups' && (
        <div className="glass-card">
          <BackupList vmName={vmName} vmStatus={vm.status} onRestoreStarted={fetchVmDetails} />
        </div>
      )}


      {showMigrateModal && (
        <div className="modal-overlay">
          <div className="modal-content" style={{ maxWidth: '500px' }}>
            <div className="modal-header">
              <h3>Миграция ВМ на Внешний сервер</h3>
              <button className="btn-icon-only" onClick={() => setShowMigrateModal(false)}><X size={20} /></button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ background: 'var(--status-warning-bg)', color: 'var(--status-warning)', padding: '16px', borderRadius: 'var(--radius-md)', fontSize: '0.9rem' }}>
                <AlertTriangle size={18} style={{ marginBottom: '8px' }} />
                <p style={{ margin: 0 }}>ВМ будет выключена, а её диск отправлен по SSH на выбранный внешний сервер. После миграции она продолжит работу там, а локальная копия будет удалена.</p>
              </div>
              
              <div className="input-group">
                <label className="input-label">Выберите внешний сервер (Target)</label>
                <select 
                  className="form-control" 
                  value={selectedTargetServer} 
                  onChange={e => setSelectedTargetServer(e.target.value)}
                  disabled={migrating}
                >
                  {externalServers.length === 0 && <option disabled value="">Нет доступных внешних серверов</option>}
                  {externalServers.map(s => (
                    <option key={s.id} value={s.id}>{s.name} ({s.ip})</option>
                  ))}
                </select>
              </div>
              
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setShowMigrateModal(false)} disabled={migrating}>Отмена</button>
              <button className="btn btn-primary" onClick={handleMigrate} disabled={migrating || externalServers.length === 0}>
                {migrating ? <span className="spinner" /> : <><Send size={16} /> Начать миграцию</>}
              </button>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'overview' && (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(450px, 1fr))', gap: '24px' }}>
        
        {/* LEFT COLUMN */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Details & Connectivity */}
          <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <h3 className="section-title" style={{ margin: 0 }}><Key size={18}/> Реквизиты подключения</h3>
            
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
              <tbody>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '12px 0', color: 'var(--text-secondary)' }}>Локальный IP (Bridge)</td>
                  <td style={{ padding: '12px 0', textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{bridgeIp || 'N/A'}</td>
                </tr>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '12px 0', color: 'var(--text-secondary)' }}>Pod IP (Internal)</td>
                  <td style={{ padding: '12px 0', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{sshIp || 'N/A'}</td>
                </tr>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '12px 0', color: 'var(--text-secondary)' }}>SSH Пользователь</td>
                  <td style={{ padding: '12px 0', textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{vm.credentials?.username || 'root'}</td>
                </tr>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '12px 0', color: 'var(--text-secondary)' }}>SSH Пароль</td>
                  <td style={{ padding: '12px 0', textAlign: 'right', display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{showPassword ? (vm.credentials?.password || 'N/A') : '••••••••'}</span>
                    <button className="btn-icon-only" onClick={() => setShowPassword(!showPassword)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0 }} title={showPassword ? 'Скрыть пароль' : 'Показать пароль'}>
                      {showPassword ? <EyeOff size={14} color="var(--text-muted)" /> : <Eye size={14} color="var(--text-muted)" />}
                    </button>
                    {showPassword && vm.credentials?.password && (
                      <button className="btn-icon-only" onClick={() => handleCopy(vm.credentials.password, 'tablePass')} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0 }} title="Копировать пароль">
                        {copiedField === 'tablePass' ? <Check size={14} color="var(--status-success)" /> : <Copy size={14} color="var(--text-muted)" />}
                      </button>
                    )}
                  </td>
                </tr>
              </tbody>
            </table>

            {/* Команды */}
            <div style={{ marginTop: '8px' }}>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '8px' }}>Команда локального SSH (внутри сети):</div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <input type="text" readOnly className="form-control" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }} value={sshIp ? `ssh ${vm.credentials?.username || 'root'}@${sshIp}` : 'Ожидание сети...'} />
                <button className="btn btn-secondary btn-icon" onClick={() => handleCopy(`ssh ${vm.credentials?.username || 'root'}@${sshIp}`, 'localSsh')} disabled={!sshIp}>
                  {copiedField === 'localSsh' ? <Check size={14} color="var(--status-success)" /> : <Copy size={14} />}
                </button>
              </div>
            </div>

            <div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '8px' }}>Команда внешнего SSH:</div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <input type="text" readOnly className="form-control" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }} value={vm.ssh_port ? `ssh ${vm.credentials?.username || 'root'}@${window.location.hostname} -p ${vm.ssh_port}` : 'Ожидание порта...'} />
                <button className="btn btn-secondary btn-icon" onClick={() => handleCopy(`ssh ${vm.credentials?.username || 'root'}@${window.location.hostname} -p ${vm.ssh_port}`, 'extSsh')} disabled={!vm.ssh_port}>
                  {copiedField === 'extSsh' ? <Check size={14} color="var(--status-success)" /> : <Copy size={14} />}
                </button>
              </div>
            </div>
          </div>

          {/* Usage Monitoring */}
          <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <h3 className="section-title" style={{ margin: 0 }}><Activity size={18}/> Показатели системы (Гостевая ОС)</h3>
            {!sshData ? (
              <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
                {vm.status === 'Running' ? <><span className="spinner" style={{ marginBottom: '12px' }}/> <br/> Ожидание агента SSH...</> : 'ВМ выключена'}
              </div>
            ) : sshData.error ? (
              <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
                <span className="spinner" style={{ marginBottom: '12px' }}/> <br/> 
                <span style={{ fontSize: '0.85rem' }}>Ожидание загрузки гостевой ОС...</span>
                <p style={{ fontSize: '0.75rem', opacity: 0.6, marginTop: '8px' }}>{sshData.error}</p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: '8px' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>CPU Usage ({sshData.cpu?.cores || 1} cores)</span>
                    <span style={{ fontWeight: 600 }}>{sshData.cpu?.usage_percent || 0}%</span>
                  </div>
                  <div className="progress-track"><div className="progress-fill primary" style={{ width: `${sshData.cpu?.usage_percent || 0}%` }} /></div>
                </div>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: '8px' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>RAM Usage ({sshData.memory?.total_mb || 0} MB)</span>
                    <span style={{ fontWeight: 600 }}>{sshData.memory?.usage_percent || 0}%</span>
                  </div>
                  <div className="progress-track"><div className="progress-fill" style={{ width: `${sshData.memory?.usage_percent || 0}%`, background: 'var(--accent-secondary)' }} /></div>
                </div>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: '8px' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>Disk (/) Usage</span>
                    <span style={{ fontWeight: 600 }}>{sshData.disk?.usage_percent || 0}%</span>
                  </div>
                  <div className="progress-track"><div className="progress-fill warning" style={{ width: `${sshData.disk?.usage_percent || 0}%` }} /></div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* RIGHT COLUMN */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Resource Allocation */}
          <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <h3 className="section-title" style={{ margin: 0 }}><Cpu size={18}/> Выделение ресурсов</h3>
            <form onSubmit={handleResize} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '0.85rem' }}>
                  <span className="text-muted">CPU Cores</span>
                  <span style={{ fontWeight: 600 }}>{cpuCores} vCPUs</span>
                </div>
                <input type="range" min="1" max="16" value={cpuCores} onChange={(e) => setCpuCores(parseInt(e.target.value))} style={{ width: '100%' }} disabled={savingResize} />
              </div>

              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '0.85rem' }}>
                  <span className="text-muted">Memory (RAM)</span>
                  <span style={{ fontWeight: 600 }}>{memoryGb} GB</span>
                </div>
                <input type="range" min="1" max="64" value={memoryGb} onChange={(e) => setMemoryGb(parseInt(e.target.value))} style={{ width: '100%' }} disabled={savingResize} />
              </div>

              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '0.85rem' }}>
                  <span className="text-muted">Storage Disk</span>
                  <span style={{ fontWeight: 600 }}>{diskGb} GB</span>
                </div>
                <input type="range" min={currentDiskLimit} max="500" step="10" value={diskGb} onChange={(e) => setDiskGb(parseInt(e.target.value))} style={{ width: '100%' }} disabled={savingResize} />
              </div>

              <button type="submit" className="btn btn-primary" style={{ marginTop: '8px' }} disabled={savingResize}>
                {savingResize ? <span className="spinner" /> : 'Применить изменения (после Reboot)'}
              </button>
            </form>
          </div>

          {/* Network & Access */}
          <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 className="section-title" style={{ margin: 0 }}><Network size={18}/> Сеть и доступ</h3>
            </div>

            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem', textAlign: 'left' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <th style={{ padding: '8px 0', color: 'var(--text-secondary)', fontWeight: 500 }}>Действие</th>
                  <th style={{ padding: '8px 0', color: 'var(--text-secondary)', fontWeight: 500 }}>Внешний порт</th>
                  <th style={{ padding: '8px 0', color: 'var(--text-secondary)', fontWeight: 500 }}>Внутренний порт</th>
                  <th style={{ padding: '8px 0', color: 'var(--text-secondary)', fontWeight: 500 }}>Протокол</th>
                </tr>
              </thead>
              <tbody>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '12px 0', fontWeight: 500 }}>SSH ВМ</td>
                  <td style={{ padding: '12px 0' }}>{vm.ssh_port || 'N/A'}</td>
                  <td style={{ padding: '12px 0' }}>22</td>
                  <td style={{ padding: '12px 0', color: 'var(--text-muted)' }}>TCP</td>
                </tr>
                {/* Здесь можно добавить другие порты, если они будут прокидываться в будущем */}
              </tbody>
            </table>
          </div>

          {/* Terminal */}
          {vm.status === 'Running' && vm.os_type !== 'windows' && (
            <div style={{ display: 'flex', flexDirection: 'column', height: '300px', background: '#0f172a', borderRadius: 'var(--radius-md)', overflow: 'hidden', padding: '16px', boxShadow: 'var(--shadow-md)' }}>
              <div style={{ color: '#94a3b8', fontSize: '0.8rem', fontWeight: 600, borderBottom: '1px solid #1e293b', paddingBottom: '8px', marginBottom: '8px', display: 'flex', justifyContent: 'space-between' }}>
                <span>user@{vmName} ~</span>
                <Terminal size={14} />
              </div>
              
              <div style={{ flex: 1, color: '#f8fafc', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', overflowY: 'auto', marginBottom: '12px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {terminalHistory.map((line, idx) => (
                  <div key={idx} style={{ color: line.type === 'prompt' ? '#38bdf8' : line.type === 'stderr' ? '#f87171' : line.type === 'info' ? '#94a3b8' : 'inherit', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                    {line.text}
                  </div>
                ))}
                <div ref={terminalEndRef} />
              </div>
              
              <form onSubmit={handleExecuteCommand} style={{ display: 'flex', gap: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', color: '#38bdf8', fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>
                  $
                </div>
                <input 
                  type="text" 
                  value={command} 
                  onChange={(e) => setCommand(e.target.value)} 
                  disabled={executing || !sshData} 
                  placeholder={sshData ? "Enter command..." : "Waiting for SSH connection..."}
                  style={{ flex: 1, background: 'transparent', border: 'none', color: '#fff', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', outline: 'none' }} 
                />
              </form>
            </div>
          )}

        </div>
      </div>
      )}
    </div>
  );
};

export default VMDetail;
