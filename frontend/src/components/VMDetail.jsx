import React, { useEffect, useState, useRef } from 'react';
import { X, RefreshCw, Cpu, HardDrive, ShieldAlert, Terminal, Activity, Layers, ListFilter, Play, Square, RotateCw, Monitor, Settings, Trash2, Copy, Check, Eye, EyeOff, AlertTriangle, Key, Shield, Network, Send } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, ResponsiveContainer, Tooltip as RechartsTooltip } from 'recharts';
import VncConsole from './VncConsole';
import BackupList from './BackupList';
import CustomSelect from './CustomSelect';

const VMDetail = ({ vmName, onClose, onActionSuccess }) => {
  const [vm, setVm] = useState(null);
  const [sshData, setSshData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sshLoading, setSshLoading] = useState(false);
  const [error, setError] = useState(null);
  const [sshError, setSshError] = useState(null);
  const [startProgress, setStartProgress] = useState(0);
  
  const [cpuCores, setCpuCores] = useState(2);
  const [memoryGb, setMemoryGb] = useState(2);
  const [diskGb, setDiskGb] = useState(20);
  const [hasInitializedResize, setHasInitializedResize] = useState(false);
  const [savingResize, setSavingResize] = useState(false);

  const [diskReadMbs, setDiskReadMbs] = useState(0);
  const [diskWriteMbs, setDiskWriteMbs] = useState(0);
  const [diskReadIops, setDiskReadIops] = useState(0);
  const [diskWriteIops, setDiskWriteIops] = useState(0);
  const [portsConfig, setPortsConfig] = useState([]);
  const [firewallRules, setFirewallRules] = useState([]);
  const [savingSettings, setSavingSettings] = useState(false);
  const [metricsHistory, setMetricsHistory] = useState([]);
  const [historyRange, setHistoryRange] = useState(1); // Hours
  const [historyLoading, setHistoryLoading] = useState(true);

  const [actionLoading, setActionLoading] = useState(null);
  const [showPassword, setShowPassword] = useState(false);
  const [copiedField, setCopiedField] = useState(null);

  // Terminal state
  const [command, setCommand] = useState('');
  const [executing, setExecuting] = useState(false);
  const [cwd, setCwd] = useState('~');
  const [terminalHistory, setTerminalHistory] = useState([]);
  const [applyingNat, setApplyingNat] = useState(false);
  const [activeTab, setActiveTab] = useState('overview'); // 'overview', 'vnc', 'backups', 'settings'

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
        setDiskReadMbs(data.disk_read_mbs || 0);
        setDiskWriteMbs(data.disk_write_mbs || 0);
        setDiskReadIops(data.disk_read_iops || 0);
        setDiskWriteIops(data.disk_write_iops || 0);
        setPortsConfig(data.ports_config || []);
        setFirewallRules(data.firewall_rules || []);
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
    if (vm?.status === 'Running') {
      fetchMetricsHistory();
      const interval = setInterval(fetchMetricsHistory, 15000);
      return () => clearInterval(interval);
    }
  }, [vmName, historyRange, vm?.status, vm?.memory_gb]);

  useEffect(() => {
    fetchSshDetails();
    const interval = setInterval(fetchSshDetails, 6000);
    return () => clearInterval(interval);
  }, [vmName, vm?.status]);

  useEffect(() => {
    let timer;
    if (vm?.status === 'Starting') {
      timer = setInterval(() => {
        setStartProgress(prev => {
          if (prev >= 99) return 99;
          return prev + Math.floor(Math.random() * 8) + 2; // + 2..9% each second
        });
      }, 1000);
    } else {
      setStartProgress(0);
    }
    return () => clearInterval(timer);
  }, [vm?.status]);

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

  const fetchMetricsHistory = async () => {
    try {
      const response = await fetch(`/api/vms/${vmName}/metrics/history?range_hours=${historyRange}`);
      if (response.ok) {
        const data = await response.json();
        const ramTotalMb = (vm?.memory_gb || 2) * 1024;
        const formatted = data.map(pt => {
          const timeStr = new Date(pt.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
          const memUsagePct = ramTotalMb > 0 ? Math.round((pt.memory_mb / ramTotalMb) * 100 * 10) / 10 : 0;
          return {
            time: timeStr,
            cpu: pt.cpu,
            memory: memUsagePct,
            rawMemoryMb: pt.memory_mb
          };
        });
        setMetricsHistory(formatted);
      }
    } catch (e) {
      console.error("Error fetching metrics history:", e);
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleSaveSettings = async (e) => {
    if (e) e.preventDefault();
    setSavingSettings(true);
    try {
      const response = await fetch(`/api/vms/${vmName}/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cpu_cores: parseInt(cpuCores),
          memory_gb: parseInt(memoryGb),
          disk_gb: parseInt(diskGb),
          disk_read_mbs: parseInt(diskReadMbs),
          disk_write_mbs: parseInt(diskWriteMbs),
          disk_read_iops: parseInt(diskReadIops),
          disk_write_iops: parseInt(diskWriteIops),
          ports_config: portsConfig,
          firewall_rules: firewallRules
        })
      });
      if (!response.ok) throw new Error('Не удалось сохранить настройки.');
      alert('Настройки успешно сохранены! Изменения CPU/RAM/Диска вступят в силу после перезапуска ВМ, лимиты диска и фаервол применились мгновенно.');
      fetchVmDetails();
      if (onActionSuccess) onActionSuccess();
    } catch (err) {
      alert(`Ошибка: ${err.message}`);
    } finally {
      setSavingSettings(false);
    }
  };

  const handleAddPortForwardRule = () => {
    const nameInput = document.getElementById('new_port_name');
    const extInput = document.getElementById('new_ext_port');
    const intInput = document.getElementById('new_int_port');
    
    const name = nameInput?.value?.trim() || 'PortForward';
    const ext_port = parseInt(extInput?.value);
    const int_port = parseInt(intInput?.value);
    
    if (!ext_port || !int_port) {
      alert('Пожалуйста, введите корректные порты.');
      return;
    }
    
    // Проверяем дубли
    if (portsConfig.some(p => p.int_port === int_port || p.ext_port === ext_port)) {
      alert('Порт уже используется в других правилах.');
      return;
    }
    
    const newPort = { ext_port, int_port, name };
    setPortsConfig(prev => [...prev, newPort]);
    setFirewallRules(prev => [...prev, { port: int_port, allowed_ips: ["0.0.0.0/0"] }]);
    
    if (nameInput) nameInput.value = '';
    if (extInput) extInput.value = '';
    if (intInput) intInput.value = '';
  };

  const handleDeletePortRule = (int_port) => {
    setPortsConfig(prev => prev.filter(p => p.int_port !== int_port));
    setFirewallRules(prev => prev.filter(r => r.port !== int_port));
  };

  const handleUpdatePortWhitelist = (int_port, value) => {
    const ips = value.split(',').map(ip => ip.trim());
    setFirewallRules(prev => {
      const idx = prev.findIndex(r => r.port === int_port);
      if (idx !== -1) {
        const next = [...prev];
        next[idx] = { port: int_port, allowed_ips: ips };
        return next;
      }
      return [...prev, { port: int_port, allowed_ips: ips }];
    });
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
              <span className={`badge badge-${vm.status === 'Running' ? 'success' : (['starting', 'importing', 'stopping', 'scheduled', 'pending', 'provisioning'].includes(vm.status?.toLowerCase()) ? 'warning' : 'danger')}`} style={{ padding: '6px 12px', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span className="status-dot"></span>
                {(() => {
                  const norm = vm.status?.toLowerCase();
                  if (norm === 'running') return 'Запущена';
                  if (norm === 'stopped') return 'Остановлена';
                  if (norm === 'starting') return 'Запуск...';
                  if (norm === 'stopping') return 'Выключение...';
                  if (norm === 'scheduled') return 'Планирование...';
                  if (norm === 'pending') return 'В очереди...';
                  if (norm === 'provisioning') return 'Создание...';
                  if (norm === 'importing') return 'Импорт...';
                  if (norm === 'error') return 'Ошибка';
                  return vm.status;
                })()}
                {(vm.status === 'Starting' || vm.status === 'Importing') && (
                  <span style={{ marginLeft: '4px', fontWeight: 'bold' }}>
                    {vm.status === 'Importing' ? (vm.import_progress || '0%') : `${startProgress}%`}
                  </span>
                )}
              </span>
            </div>
            <div style={{ display: 'flex', gap: '24px', fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><HardDrive size={16}/> {vm.os_type || 'Unknown OS'}</span>
              <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><Network size={16}/> {vm.node || 'Node-1'}</span>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
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
            <button className={`btn ${activeTab === 'snapshots' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setActiveTab('snapshots')}>
              📸 Снимки
            </button>
            <button className={`btn ${activeTab === 'settings' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setActiveTab('settings')}>
              <Settings size={14} /> Настройки
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

      {activeTab === 'snapshots' && (
        <div className="glass-card">
          <VMSnapshotsList vmName={vmName} vmStatus={vm.status} />
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
                <CustomSelect 
                  value={selectedTargetServer} 
                  onChange={e => setSelectedTargetServer(e.target.value)}
                  disabled={migrating}
                  placeholder="Выберите внешний сервер"
                  options={externalServers.map(s => ({
                    value: s.id,
                    label: `${s.name} (${s.ip})`
                  }))}
                />
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
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(290px, 1fr))', gap: '24px' }}>
        
        {/* LEFT COLUMN */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Details & Connectivity */}
          <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <h3 className="section-title" style={{ margin: 0 }}><Key size={18}/> Реквизиты подключения</h3>
            
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
              <tbody>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '12px 0', color: 'var(--text-secondary)' }}>Локальный IP (Bridge)</td>
                  <td style={{ padding: '12px 0', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>
                    {(() => {
                      if (bridgeIp) return bridgeIp;
                      const hasAgent = vm.ips && vm.ips.some(ip => ip.startsWith('10.0.2.'));
                      if (['windows', 'proxmox', 'custom'].includes(vm.os_type)) {
                        return hasAgent ? 'N/A' : <span style={{fontSize:'0.75rem', color:'var(--text-muted)'}}>Ожидание QEMU Guest Agent</span>;
                      }
                      return 'N/A';
                    })()}
                  </td>
                </tr>
                {!['windows', 'proxmox', 'custom'].includes(vm.os_type) && (
                  <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <td style={{ padding: '12px 0', color: 'var(--text-secondary)' }}>Pod IP (Internal)</td>
                    <td style={{ padding: '12px 0', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{sshIp || 'N/A'}</td>
                  </tr>
                )}
                {!['windows', 'proxmox', 'custom'].includes(vm.os_type) && (
                  <>
                    <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={{ padding: '12px 0', color: 'var(--text-secondary)' }}>Пользователь</td>
                      <td style={{ padding: '12px 0', textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                        {vm.credentials?.username || 'root'}
                      </td>
                    </tr>
                    <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={{ padding: '12px 0', color: 'var(--text-secondary)' }}>Пароль</td>
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
                  </>
                )}
              </tbody>
            </table>

            {/* Команды */}
            {/* RDP Commands */}
            {(vm.os_type === 'windows' || (vm.os_type === 'custom' && portsConfig.some(p => p.int_port === 3389))) && (
              <>
                <div style={{ marginTop: '8px' }}>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '8px' }}>Адрес локального RDP (внутри сети):</div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <input type="text" readOnly className="form-control" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }} value={sshIp ? `${sshIp}:3389` : 'Ожидание сети...'} />
                    <button className="btn btn-secondary btn-icon" onClick={() => handleCopy(sshIp ? `${sshIp}:3389` : '', 'localRdp')} disabled={!sshIp}>
                      {copiedField === 'localRdp' ? <Check size={14} color="var(--status-success)" /> : <Copy size={14} />}
                    </button>
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '8px' }}>Адрес внешнего RDP (для подключения извне):</div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <input type="text" readOnly className="form-control" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }} value={vm.rdp_port ? `${window.location.hostname}:${vm.rdp_port}` : 'Ожидание порта...'} />
                    <button className="btn btn-secondary btn-icon" onClick={() => handleCopy(vm.rdp_port ? `${window.location.hostname}:${vm.rdp_port}` : '', 'extRdp')} disabled={!vm.rdp_port}>
                      {copiedField === 'extRdp' ? <Check size={14} color="var(--status-success)" /> : <Copy size={14} />}
                    </button>
                  </div>
                </div>
              </>
            )}

            {/* SSH Commands */}
            {!['windows', 'proxmox'].includes(vm.os_type) && !portsConfig.some(p => p.int_port === 3389) && (
              <>
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
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '8px' }}>Команда внешнего SSH (через проброс):</div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <input type="text" readOnly className="form-control" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }} value={vm.ssh_port ? `ssh ${vm.credentials?.username || 'root'}@${window.location.hostname} -p ${vm.ssh_port}` : 'Ожидание порта...'} />
                    <button className="btn btn-secondary btn-icon" onClick={() => handleCopy(`ssh ${vm.credentials?.username || 'root'}@${window.location.hostname} -p ${vm.ssh_port}`, 'extSsh')} disabled={!vm.ssh_port}>
                      {copiedField === 'extSsh' ? <Check size={14} color="var(--status-success)" /> : <Copy size={14} />}
                    </button>
                  </div>
                </div>

                <div style={{ marginTop: '8px' }}>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '8px' }}>Команда SSH через бастион (Jump Host):</div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <input type="text" readOnly className="form-control" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }} value={sshIp ? `ssh -J root@${window.location.hostname} ${vm.credentials?.username || 'root'}@${sshIp}` : 'Ожидание сети...'} />
                    <button className="btn btn-secondary btn-icon" onClick={() => handleCopy(`ssh -J root@${window.location.hostname} ${vm.credentials?.username || 'root'}@${sshIp}`, 'bastionSsh')} disabled={!sshIp}>
                      {copiedField === 'bastionSsh' ? <Check size={14} color="var(--status-success)" /> : <Copy size={14} />}
                    </button>
                  </div>
                </div>
              </>
            )}

            {/* Proxmox Web UI Link */}
            {vm.os_type === 'proxmox' && (
              <div style={{ marginTop: '8px' }}>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '8px' }}>Доступ к панели Proxmox (HTTPS):</div>
                {(() => {
                  const pObj = portsConfig.find(p => p.int_port === 8006);
                  const pUrl = pObj ? `https://${window.location.hostname}:${pObj.ext_port}` : null;
                  return (
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <input type="text" readOnly className="form-control" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }} value={pUrl || 'Добавьте проброс порта 8006 внизу...'} />
                      <button className="btn btn-secondary btn-icon" onClick={() => handleCopy(pUrl || '', 'extProxmox')} disabled={!pUrl}>
                        {copiedField === 'extProxmox' ? <Check size={14} color="var(--status-success)" /> : <Copy size={14} />}
                      </button>
                    </div>
                  );
                })()}
              </div>
            )}

            {/* Default HTTP/HTTPS Web Server Links (not for Proxmox) */}
            {vm.http_port && vm.os_type !== 'proxmox' && (
              <div style={{ marginTop: '8px' }}>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '8px' }}>Доступ к веб-серверу (HTTP/HTTPS):</div>
                <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
                  <input type="text" readOnly className="form-control" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }} value={`http://${window.location.hostname}:${vm.http_port}`} />
                  <button className="btn btn-secondary btn-icon" onClick={() => handleCopy(`http://${window.location.hostname}:${vm.http_port}`, 'extHttp')}>
                    {copiedField === 'extHttp' ? <Check size={14} color="var(--status-success)" /> : <Copy size={14} />}
                  </button>
                </div>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <input type="text" readOnly className="form-control" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }} value={`https://${window.location.hostname}:${vm.https_port}`} />
                  <button className="btn btn-secondary btn-icon" onClick={() => handleCopy(`https://${window.location.hostname}:${vm.https_port}`, 'extHttps')}>
                    {copiedField === 'extHttps' ? <Check size={14} color="var(--status-success)" /> : <Copy size={14} />}
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Real-time and Historical Metrics */}
          <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 className="section-title" style={{ margin: 0 }}><Activity size={18}/> График истории нагрузки (Prometheus)</h3>
              <div style={{ display: 'flex', gap: '6px' }}>
                {[1, 3, 6, 12, 24].map(h => (
                  <button 
                    key={h} 
                    className={`btn ${historyRange === h ? 'btn-primary' : 'btn-secondary'}`} 
                    style={{ padding: '2px 8px', fontSize: '0.75rem', minWidth: '32px' }} 
                    onClick={() => setHistoryRange(h)}
                  >
                    {h}ч
                  </button>
                ))}
              </div>
            </div>
            
            {vm.status !== 'Running' ? (
              <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>ВМ выключена</div>
            ) : historyLoading ? (
              <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
                <span className="spinner" style={{ marginBottom: '12px' }}/> <br/> 
                Загрузка истории метрик из Prometheus...
              </div>
            ) : metricsHistory.length === 0 ? (
              <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
                Нет исторических данных за выбранный период (ВМ была запущена недавно)
              </div>
            ) : (
              <div style={{ height: '220px', width: '100%' }}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={metricsHistory} margin={{ top: 5, right: 0, left: -20, bottom: 0 }}>
                    <defs>
                      <linearGradient id="colorCpu" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="var(--accent-primary)" stopOpacity={0.3}/>
                        <stop offset="95%" stopColor="var(--accent-primary)" stopOpacity={0}/>
                      </linearGradient>
                      <linearGradient id="colorMem" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="var(--status-success)" stopOpacity={0.3}/>
                        <stop offset="95%" stopColor="var(--status-success)" stopOpacity={0}/>
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="time" style={{ fontSize: '9px', fill: 'var(--text-muted)' }} />
                    <YAxis domain={[0, 100]} tickLine={false} axisLine={false} style={{ fontSize: '10px', fill: 'var(--text-muted)' }} />
                    <RechartsTooltip 
                      contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-lg)' }}
                      labelStyle={{ color: 'var(--text-secondary)', marginBottom: '4px', fontSize: '0.8rem' }}
                      itemStyle={{ fontSize: '0.85rem', fontWeight: 500 }}
                    />
                    <Area type="monotone" dataKey="cpu" name="CPU Нагрузка %" stroke="var(--accent-primary)" fillOpacity={1} fill="url(#colorCpu)" strokeWidth={2} />
                    <Area type="monotone" dataKey="memory" name="ОЗУ Загрузка %" stroke="var(--status-success)" fillOpacity={1} fill="url(#colorMem)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>

        {/* RIGHT COLUMN */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Detailed Storage Stats & Limits */}
          <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <h3 className="section-title" style={{ margin: 0 }}><HardDrive size={18}/> Производительность диска и Лимиты</h3>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
              <tbody>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '12px 0', color: 'var(--text-secondary)' }}>Скорость чтения (текущая)</td>
                  <td style={{ padding: '12px 0', textAlign: 'right', fontWeight: 600 }}>
                    {vm.disk_read_speed_kbps > 1024 ? `${(vm.disk_read_speed_kbps / 1024).toFixed(2)} МБ/с` : `${vm.disk_read_speed_kbps || 0} КБ/с`}
                  </td>
                </tr>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '12px 0', color: 'var(--text-secondary)' }}>Скорость записи (текущая)</td>
                  <td style={{ padding: '12px 0', textAlign: 'right', fontWeight: 600 }}>
                    {vm.disk_write_speed_kbps > 1024 ? `${(vm.disk_write_speed_kbps / 1024).toFixed(2)} МБ/с` : `${vm.disk_write_speed_kbps || 0} КБ/с`}
                  </td>
                </tr>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td style={{ padding: '12px 0', color: 'var(--text-secondary)' }}>IOPS чтения / записи (текущий)</td>
                  <td style={{ padding: '12px 0', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>
                    {vm.disk_read_iops_realtime || 0} / {vm.disk_write_iops_realtime || 0}
                  </td>
                </tr>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)', background: 'var(--card-bg-subtle)' }}>
                  <td style={{ padding: '12px 8px', color: 'var(--text-secondary)' }}>Лимит чтения / записи (cgroup)</td>
                  <td style={{ padding: '12px 8px', textAlign: 'right', fontWeight: 600 }}>
                    {vm.disk_read_mbs ? `${vm.disk_read_mbs} МБ/с` : 'Без лимита'} / {vm.disk_write_mbs ? `${vm.disk_write_mbs} МБ/с` : 'Без лимита'}
                  </td>
                </tr>
                <tr style={{ borderBottom: '1px solid var(--border-subtle)', background: 'var(--card-bg-subtle)' }}>
                  <td style={{ padding: '12px 8px', color: 'var(--text-secondary)' }}>Лимит IOPS чтения / записи (cgroup)</td>
                  <td style={{ padding: '12px 8px', textAlign: 'right', fontWeight: 600 }}>
                    {vm.disk_read_iops ? `${vm.disk_read_iops} IOPS` : 'Без лимита'} / {vm.disk_write_iops ? `${vm.disk_write_iops} IOPS` : 'Без лимита'}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Terminal */}
          {vm.status === 'Running' && vm.os_type !== 'windows' && (
            <div style={{ display: 'flex', flexDirection: 'column', height: '240px', background: '#0f172a', borderRadius: 'var(--radius-md)', overflow: 'hidden', padding: '16px', boxShadow: 'var(--shadow-md)' }}>
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

      {activeTab === 'settings' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(290px, 1fr))', gap: '24px' }}>
          {/* Left Panel: CPU/RAM/Disk limits */}
          <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <h3 className="section-title" style={{ margin: 0 }}><Settings size={18}/> Выделение ресурсов и лимиты диска</h3>
            
            <form onSubmit={handleSaveSettings} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '0.85rem' }}>
                  <span className="text-muted">CPU Cores</span>
                  <span style={{ fontWeight: 600 }}>{cpuCores} vCPUs</span>
                </div>
                <input type="range" min="1" max="16" value={cpuCores} onChange={(e) => setCpuCores(parseInt(e.target.value))} style={{ width: '100%' }} disabled={savingSettings} />
              </div>

              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '0.85rem' }}>
                  <span className="text-muted">Memory (RAM)</span>
                  <span style={{ fontWeight: 600 }}>{memoryGb} GB</span>
                </div>
                <input type="range" min="1" max="64" value={memoryGb} onChange={(e) => setMemoryGb(parseInt(e.target.value))} style={{ width: '100%' }} disabled={savingSettings} />
              </div>

              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '0.85rem' }}>
                  <span className="text-muted">Storage Disk</span>
                  <span style={{ fontWeight: 600 }}>{diskGb} GB</span>
                </div>
                <input type="range" min={currentDiskLimit} max="500" step="10" value={diskGb} onChange={(e) => setDiskGb(parseInt(e.target.value))} style={{ width: '100%' }} disabled={savingSettings} />
              </div>

              <div style={{ borderTop: '1px solid var(--border-subtle)', marginTop: '10px', paddingTop: '16px' }}></div>

              <h4 style={{ margin: '0 0 10px 0', fontSize: '0.95rem' }}><HardDrive size={16} style={{ marginRight: '6px', verticalAlign: 'middle' }}/> Ограничения скорости диска (IOPS / MBs)</h4>

              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '0.85rem' }}>
                  <span className="text-muted">Лимит чтения (МБ/с)</span>
                  <span style={{ fontWeight: 600 }}>{diskReadMbs === 0 ? 'Без лимита' : `${diskReadMbs} МБ/с`}</span>
                </div>
                <input type="range" min="0" max="500" step="10" value={diskReadMbs} onChange={(e) => setDiskReadMbs(parseInt(e.target.value))} style={{ width: '100%' }} disabled={savingSettings} />
              </div>

              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '0.85rem' }}>
                  <span className="text-muted">Лимит записи (МБ/с)</span>
                  <span style={{ fontWeight: 600 }}>{diskWriteMbs === 0 ? 'Без лимита' : `${diskWriteMbs} МБ/с`}</span>
                </div>
                <input type="range" min="0" max="500" step="10" value={diskWriteMbs} onChange={(e) => setDiskWriteMbs(parseInt(e.target.value))} style={{ width: '100%' }} disabled={savingSettings} />
              </div>

              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '0.85rem' }}>
                  <span className="text-muted">Лимит операций чтения (IOPS)</span>
                  <span style={{ fontWeight: 600 }}>{diskReadIops === 0 ? 'Без лимита' : `${diskReadIops} IOPS`}</span>
                </div>
                <input type="range" min="0" max="5000" step="100" value={diskReadIops} onChange={(e) => setDiskReadIops(parseInt(e.target.value))} style={{ width: '100%' }} disabled={savingSettings} />
              </div>

              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '0.85rem' }}>
                  <span className="text-muted">Лимит операций записи (IOPS)</span>
                  <span style={{ fontWeight: 600 }}>{diskWriteIops === 0 ? 'Без лимита' : `${diskWriteIops} IOPS`}</span>
                </div>
                <input type="range" min="0" max="5000" step="100" value={diskWriteIops} onChange={(e) => setDiskWriteIops(parseInt(e.target.value))} style={{ width: '100%' }} disabled={savingSettings} />
              </div>

              <button type="submit" className="btn btn-primary" disabled={savingSettings}>
                {savingSettings ? <span className="spinner" /> : 'Сохранить настройки ресурсов'}
              </button>
            </form>
          </div>

          {/* Right Panel: Port forwarding and Firewall */}
          <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <h3 className="section-title" style={{ margin: 0 }}><Shield size={18}/> Проброс портов и Белый список IP</h3>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-end', background: 'var(--card-bg-subtle)', padding: '12px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                <div style={{ flex: 1 }}>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>Название</label>
                  <input type="text" id="new_port_name" className="form-control" placeholder="Например, Web API" style={{ fontSize: '0.8rem' }} />
                </div>
                <div style={{ width: '90px' }}>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>Внешний</label>
                  <input type="number" id="new_ext_port" className="form-control" placeholder="30000" style={{ fontSize: '0.8rem' }} />
                </div>
                <div style={{ width: '90px' }}>
                  <label style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>Внутренний</label>
                  <input type="number" id="new_int_port" className="form-control" placeholder="80" style={{ fontSize: '0.8rem' }} />
                </div>
                <div>
                  <button className="btn btn-primary" onClick={handleAddPortForwardRule} style={{ fontSize: '0.8rem', padding: '10px 14px' }}>Добавить</button>
                </div>
              </div>

              <div style={{ overflowY: 'auto', maxHeight: '300px' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <th style={{ padding: '8px 0', color: 'var(--text-secondary)', fontWeight: 500 }}>Название</th>
                      <th style={{ padding: '8px 0', color: 'var(--text-secondary)', fontWeight: 500 }}>Внешний &rarr; Внутр.</th>
                      <th style={{ padding: '8px 0', color: 'var(--text-secondary)', fontWeight: 500 }}>Разрешенные IP (Белый список)</th>
                      <th style={{ padding: '8px 0', textAlign: 'right' }}>Действие</th>
                    </tr>
                  </thead>
                  <tbody>
                    {portsConfig.length === 0 ? (
                      <tr>
                        <td colSpan="4" style={{ padding: '24px 0', textAlign: 'center', color: 'var(--text-muted)' }}>
                          Кастомные порты не настроены. Используются стандартные порты (SSH, HTTP, HTTPS).
                        </td>
                      </tr>
                    ) : (
                      portsConfig.map((p, idx) => {
                        const rule = firewallRules.find(r => r.port === p.int_port) || { allowed_ips: [] };
                        return (
                          <tr key={idx} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                            <td style={{ padding: '12px 0', fontWeight: 500 }}>{p.name}</td>
                            <td style={{ padding: '12px 0', fontFamily: 'var(--font-mono)' }}>{p.ext_port} → {p.int_port}</td>
                            <td style={{ padding: '12px 0' }}>
                              <input 
                                type="text" 
                                className="form-control" 
                                style={{ fontSize: '0.8rem', padding: '4px 8px', width: '90%' }} 
                                value={rule.allowed_ips.join(', ')} 
                                placeholder="0.0.0.0/0 (доступно всем)"
                                onChange={(e) => handleUpdatePortWhitelist(p.int_port, e.target.value)} 
                              />
                            </td>
                            <td style={{ padding: '12px 0', textAlign: 'right' }}>
                              <button className="btn btn-secondary" style={{ padding: '4px 8px', color: 'var(--status-danger)' }} onClick={() => handleDeletePortRule(p.int_port)}>Удалить</button>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>

              <button className="btn btn-primary" onClick={handleSaveSettings} disabled={savingSettings} style={{ marginTop: '10px' }}>
                {savingSettings ? <span className="spinner" /> : 'Применить правила проброса и фаервола'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

function VMSnapshotsList({ vmName, vmStatus }) {
    const [snapshots, setSnapshots] = useState([]);
    const [loading, setLoading] = useState(true);
    const [snapName, setSnapName] = useState('');
    const [creating, setCreating] = useState(false);

    const getHeaders = () => {
        const token = localStorage.getItem('aegis_admin_token') || '';
        return {
            headers: { 'Authorization': `Bearer ${token}` }
        };
    };

    const fetchSnapshots = async () => {
        setLoading(true);
        try {
            const res = await fetch(`/api/snapshots/${vmName}`, getHeaders());
            if (res.ok) {
                const data = await res.json();
                setSnapshots(data);
            }
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchSnapshots();
    }, [vmName]);

    const handleCreateSnapshot = async (e) => {
        e.preventDefault();
        if (!snapName.trim()) return;
        setCreating(true);
        try {
            const res = await fetch(`/api/snapshots/${vmName}`, {
                method: 'POST',
                headers: {
                    ...getHeaders().headers,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ name: snapName })
            });
            if (res.ok) {
                setSnapName('');
                fetchSnapshots();
            } else {
                const errData = await res.json();
                alert(errData.detail || 'Ошибка создания снимка');
            }
        } catch (err) {
            alert(`Ошибка: ${err.message}`);
        } finally {
            setCreating(false);
        }
    };

    const handleDeleteSnapshot = async (snapshotName) => {
        if (!confirm(`Удалить снимок ${snapshotName}?`)) return;
        try {
            const res = await fetch(`/api/snapshots/${vmName}/${snapshotName}`, {
                method: 'DELETE',
                headers: getHeaders().headers
            });
            if (res.ok) {
                fetchSnapshots();
            } else {
                const errData = await res.json();
                alert(errData.detail || 'Ошибка удаления снимка');
            }
        } catch (err) {
            alert(`Ошибка: ${err.message}`);
        }
    };

    const handleRestoreSnapshot = async (snapshotName) => {
        if (!confirm(`Восстановить виртуальную машину из снимка ${snapshotName}? Все текущие данные будут утеряны.`)) return;
        try {
            const res = await fetch(`/api/snapshots/${vmName}/${snapshotName}/restore`, {
                method: 'POST',
                headers: getHeaders().headers
            });
            if (res.ok) {
                alert('Запрос на восстановление отправлен.');
                fetchSnapshots();
            } else {
                const errData = await res.json();
                alert(errData.detail || 'Ошибка восстановления снимка');
            }
        } catch (err) {
            alert(`Ошибка: ${err.message}`);
        }
    };

    return (
        <div style={{ padding: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <div>
                    <h3 style={{ margin: 0, fontSize: '1.2rem', color: 'var(--text-heading)' }}>Снимки виртуалки (Snapshots)</h3>
                    <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Слепки диска для быстрого отката состояния ВМ</p>
                </div>
            </div>

            <form onSubmit={handleCreateSnapshot} style={{ display: 'flex', gap: '10px', marginBottom: '20px' }}>
                <input 
                    type="text" 
                    className="form-control" 
                    placeholder="Название снимка (например, pre-install)" 
                    value={snapName}
                    onChange={e => setSnapName(e.target.value)}
                    required
                    style={{ flex: 1 }}
                />
                <button type="submit" className="btn btn-primary" disabled={creating}>
                    {creating ? 'Создание...' : 'Создать снимок'}
                </button>
            </form>

            {loading ? (
                <div style={{ display: 'flex', justifyContent: 'center', padding: '20px' }}><span className="spinner"></span></div>
            ) : (
                <div className="table-responsive">
                    <table className="table">
                        <thead>
                            <tr>
                                <th>Имя снимка</th>
                                <th>Дата создания</th>
                                <th>Статус</th>
                                <th>Действия</th>
                            </tr>
                        </thead>
                        <tbody>
                            {snapshots.map((s, idx) => (
                                <tr key={idx}>
                                    <td style={{ fontWeight: 'bold' }}>{s.name}</td>
                                    <td>{s.creation_time}</td>
                                    <td>
                                        <span className={`status-badge ${s.phase === 'Succeeded' ? 'status-active' : s.phase === 'Failed' ? 'status-danger' : 'status-pending'}`}>
                                            {s.phase === 'Succeeded' ? 'Готов' : s.phase === 'InProgress' ? 'Создается' : s.phase}
                                        </span>
                                    </td>
                                    <td>
                                        <div style={{ display: 'flex', gap: '8px' }}>
                                            <button 
                                                className="btn btn-secondary btn-sm" 
                                                onClick={() => handleRestoreSnapshot(s.name)}
                                                disabled={vmStatus === 'Running' || s.phase !== 'Succeeded'}
                                                title={vmStatus === 'Running' ? 'Остановите ВМ перед восстановлением' : 'Откатить состояние ВМ'}
                                            >
                                                Откатить
                                            </button>
                                            <button 
                                                className="btn btn-danger btn-sm" 
                                                onClick={() => handleDeleteSnapshot(s.name)}
                                            >
                                                Удалить
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                            {snapshots.length === 0 && (
                                <tr>
                                    <td colSpan="4" style={{ textAlign: 'center', padding: '20px', color: '#888' }}>
                                        Снимков пока нет
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}

export default VMDetail;
