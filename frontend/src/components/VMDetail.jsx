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
  
  const [activeTab, setActiveTab] = useState('vnc'); // 'vnc' | 'terminal' | 'monitoring' | 'backups' | 'resize'
  const [activeSubTab, setActiveSubTab] = useState('processes'); // 'processes' | 'services' | 'docker'
  
  // Resizing states
  const [cpuCores, setCpuCores] = useState(2);
  const [memoryGb, setMemoryGb] = useState(2);
  const [diskGb, setDiskGb] = useState(20);
  const [hasInitializedResize, setHasInitializedResize] = useState(false);
  const [savingResize, setSavingResize] = useState(false);

  // Power control loader
  const [actionLoading, setActionLoading] = useState(null); // 'start' | 'stop' | 'restart' | 'delete'

  // Access credentials show/hide & copy states
  const [showPassword, setShowPassword] = useState(false);
  const [copiedField, setCopiedField] = useState(null);

  // Terminal states
  const [command, setCommand] = useState('');
  const [executing, setExecuting] = useState(false);
  const [cwd, setCwd] = useState('~');
  const [terminalHistory, setTerminalHistory] = useState([]);
  
  const terminalEndRef = useRef(null);

  const fetchVmDetails = async () => {
    try {
      const response = await fetch(`/api/vms/${vmName}`);
      if (!response.ok) {
        throw new Error('Не удалось получить статус виртуальной машины.');
      }
      const data = await response.json();
      setVm(data);
      setError(null);

      // Initialize resize sliders
      if (data && !hasInitializedResize) {
        setCpuCores(data.cpu_cores || 2);
        const currentRam = parseInt(data.memory) || 2;
        const currentDisk = data.disks && data.disks[0] ? parseInt(data.disks[0].size) || 20 : 20;
        setMemoryGb(currentRam);
        setDiskGb(currentDisk);
        setHasInitializedResize(true);
      }
    } catch (err) {
      console.error(err);
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
      console.warn('SSH metrics offline:', err.message);
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

  // Terminal welcome banner initialization
  useEffect(() => {
    if (sshData && terminalHistory.length === 0) {
      setTerminalHistory([
        { type: 'info', text: `Welcome to ${sshData.name} (${sshData.host}) SSH session.` },
        { type: 'info', text: `OS: ${sshData.os_name} | Kernel: ${sshData.kernel}` },
        { type: 'info', text: `Type your bash commands below.` },
        { type: 'info', text: '' }
      ]);
    }
  }, [sshData]);

  // Scroll to bottom when terminal history changes
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
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || `Действие ${action} завершилось ошибкой.`);
      }
      await fetchVmDetails();
      if (onActionSuccess) onActionSuccess();
    } catch (err) {
      alert(`Ошибка: ${err.message}`);
    } finally {
      setActionLoading(null);
    }
  };

  const handleDeleteVM = async () => {
    if (!confirm(`Вы действительно хотите безвозвратно удалить виртуальную машину "${vmName}" и все ее диски?`)) {
      return;
    }
    setActionLoading('delete');
    try {
      const response = await fetch(`/api/vms/${vmName}`, { method: 'DELETE' });
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Не удалось удалить ВМ.');
      }
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
        body: JSON.stringify({
          cpu_cores: parseInt(cpuCores),
          memory_gb: parseInt(memoryGb),
          disk_gb: parseInt(diskGb)
        })
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Не удалось обновить ресурсы.');
      }

      alert('Настройки успешно обновлены! Изменения CPU и RAM вступят в силу после перезапуска виртуалки.');
      fetchVmDetails();
      if (onActionSuccess) onActionSuccess();
    } catch (err) {
      alert(`Ошибка изменения ресурсов: ${err.message}`);
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
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: cmdText, cwd: cwd })
      });
      
      if (!response.ok) throw new Error('Ошибка связи с API');
      
      const resData = await response.json();
      
      if (resData.cwd) setCwd(resData.cwd);

      setTerminalHistory(prev => {
        const next = [...prev];
        if (resData.stdout) next.push({ type: 'stdout', text: resData.stdout });
        if (resData.stderr) next.push({ type: 'stderr', text: resData.stderr });
        if (!resData.stdout && !resData.stderr && resData.exit_status !== 0) {
          next.push({ type: 'stderr', text: `Command exited with status ${resData.exit_status}` });
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
    const externalIp = vm.ips.find(ip => !ip.startsWith('10.244.'));
    return externalIp || vm.ips[0];
  };

  const getStatusClass = (status) => {
    switch (status) {
      case 'Running': return 'running';
      case 'Stopped': return 'stopped';
      default: return 'pending';
    }
  };

  const getStatusLabel = (status) => {
    switch (status) {
      case 'Running': return 'Активна';
      case 'Stopped': return 'Выключена';
      case 'Provisioning': return 'Создание...';
      case 'Importing': return 'Импорт...';
      case 'Starting': return 'Запуск...';
      case 'Stopping': return 'Остановка...';
      default: return status;
    }
  };

  const getProgressColor = (val) => {
    if (val < 70) return 'success';
    if (val < 90) return 'warning';
    return 'danger';
  };

  if (loading && !vm) {
    return (
      <div className="console-modal-backdrop">
        <div className="console-container" style={{ maxWidth: '500px', padding: '40px', textAlign: 'center' }}>
          <div className="spinner" style={{ margin: '0 auto 20px' }} />
          <p style={{ fontWeight: 600 }}>Загрузка панели управления ВМ...</p>
        </div>
      </div>
    );
  }

  if (error && !vm) {
    return (
      <div className="console-modal-backdrop">
        <div className="console-container" style={{ maxWidth: '500px', padding: '40px', textAlign: 'center', color: 'var(--danger)' }}>
          <ShieldAlert size={48} style={{ margin: '0 auto 15px' }} />
          <h3>Не удалось найти виртуальную машину</h3>
          <p style={{ margin: '10px 0', fontSize: '0.9rem' }}>{error}</p>
          <button className="btn btn-secondary btn-sm" style={{ marginTop: '15px' }} onClick={onClose}>Закрыть</button>
        </div>
      </div>
    );
  }

  const sshIp = getSshIp();
  const currentDiskLimit = vm.disks && vm.disks[0] ? parseInt(vm.disks[0].size) || 20 : 20;

  return (
    <div className="console-modal-backdrop">
      <div className="console-container" style={{ width: '95vw', maxWidth: '1200px', height: '90vh', display: 'flex', flexDirection: 'column' }}>
        
        {/* Шапка модального окна */}
        <div className="console-header" style={{ background: 'rgba(255,255,255,0.95)' }}>
          <div className="console-title" style={{ fontSize: '1.1rem' }}>
            <Activity className="logo-icon" size={20} />
            <span>Панель управления ВМ: <strong>{vm.name}</strong></span>
          </div>
          <button className="btn btn-danger btn-icon-only btn-sm" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        {/* Тело панели */}
        <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
          
          {/* ЛЕВАЯ КОЛОНКА (Сайдбар информации и управления) */}
          <div style={{
            width: '330px',
            borderRight: '1px solid var(--border-color)',
            padding: '20px',
            display: 'flex',
            flexDirection: 'column',
            gap: '20px',
            overflowY: 'auto',
            background: 'rgba(0, 0, 0, 0.015)'
          }}>
            
            {/* Статус и Кнопки запуска */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: 500 }}>Состояние</span>
                <span className={`status-badge ${getStatusClass(vm.status)}`} style={{ padding: '4px 10px', fontSize: '0.8rem' }}>
                  <span className="status-dot"></span>
                  {getStatusLabel(vm.status)}
                </span>
              </div>

              {/* Управление питанием */}
              <div style={{ display: 'flex', gap: '8px' }}>
                {vm.status !== 'Running' ? (
                  <button 
                    className="btn btn-primary btn-sm"
                    onClick={() => handlePowerAction('start')}
                    disabled={actionLoading !== null}
                    style={{ flex: 1, borderRadius: '0px', height: '36px' }}
                  >
                    {actionLoading === 'start' ? <span className="spinner" style={{ width: '12px', height: '12px', borderWidth: '2px' }} /> : <Play size={14} />}
                    Запуск ВМ
                  </button>
                ) : (
                  <>
                    <button 
                      className="btn btn-secondary btn-sm"
                      onClick={() => handlePowerAction('stop')}
                      disabled={actionLoading !== null}
                      style={{ flex: 1, borderRadius: '0px', height: '36px' }}
                    >
                      {actionLoading === 'stop' ? <span className="spinner" style={{ width: '12px', height: '12px', borderWidth: '2px' }} /> : <Square size={14} />}
                      Выключить
                    </button>
                    <button 
                      className="btn btn-secondary btn-sm"
                      onClick={() => handlePowerAction('restart')}
                      disabled={actionLoading !== null}
                      title="Перезагрузить"
                      style={{ width: '38px', padding: 0, display: 'flex', justifyContent: 'center', alignItems: 'center', borderRadius: '0px' }}
                    >
                      {actionLoading === 'restart' ? <span className="spinner" style={{ width: '12px', height: '12px', borderWidth: '2px' }} /> : <RotateCw size={14} />}
                    </button>
                  </>
                )}
              </div>
            </div>

            {/* Выделенные спецификации */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: '10px',
              padding: '12px',
              background: 'rgba(0,0,0,0.02)',
              border: '1px solid var(--border-color)',
              textAlign: 'center',
              fontSize: '0.8rem'
            }}>
              <div>
                <div style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>CPU Ядра</div>
                <strong style={{ fontSize: '1.05rem', color: 'var(--text-primary)' }}>{vm.cpu_cores}</strong>
              </div>
              <div style={{ borderLeft: '1px solid var(--border-color)' }}>
                <div style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>RAM</div>
                <strong style={{ fontSize: '1.05rem', color: 'var(--text-primary)' }}>{vm.memory}</strong>
              </div>
              <div style={{ borderLeft: '1px solid var(--border-color)' }}>
                <div style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>Диск</div>
                <strong style={{ fontSize: '1.05rem', color: 'var(--text-primary)' }}>{vm.disks?.[0]?.size || 'N/A'}</strong>
              </div>
            </div>

            {/* Доступ и реквизиты */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', borderTop: '1px solid var(--border-color)', paddingTop: '15px' }}>
              <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>Реквизиты подключения</span>
              
              {/* IP */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>IP-адрес (IPv4)</span>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 8px', background: 'rgba(0,0,0,0.03)', border: '1px solid var(--border-color)' }}>
                  {sshIp ? (
                    <>
                      <strong style={{ fontFamily: 'var(--font-mono)', fontSize: '0.85rem' }}>{sshIp}</strong>
                      <button 
                        className="btn-icon-only" 
                        onClick={() => handleCopy(sshIp, 'ip')}
                        style={{ border: 'none', background: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}
                      >
                        {copiedField === 'ip' ? <Check size={13} color="var(--success)" /> : <Copy size={13} />}
                      </button>
                    </>
                  ) : (
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>Ожидание получения IP...</span>
                  )}
                </div>
              </div>

              {/* SSH команда */}
              {sshIp && vm.os_type !== 'windows' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Команда SSH</span>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 8px', background: 'rgba(0,0,0,0.03)', border: '1px solid var(--border-color)' }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '240px' }}>
                      ssh {vm.credentials?.username || 'root'}@{sshIp}
                    </span>
                    <button 
                      className="btn-icon-only" 
                      onClick={() => handleCopy(`ssh ${vm.credentials?.username || 'root'}@${sshIp}`, 'ssh')}
                      style={{ border: 'none', background: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}
                    >
                      {copiedField === 'ssh' ? <Check size={13} color="var(--success)" /> : <Copy size={13} />}
                    </button>
                  </div>
                </div>
              )}

              {/* Логин / Пароль */}
              {vm.os_type !== 'windows' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', padding: '10px', background: 'rgba(0,0,0,0.02)', border: '1px solid var(--border-color)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Пользователь:</span>
                    <strong style={{ color: 'var(--text-primary)' }}>{vm.credentials?.username || 'root'}</strong>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.75rem', borderTop: '1px solid rgba(0,0,0,0.04)', paddingTop: '6px' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Пароль:</span>
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                      <strong style={{ fontFamily: 'var(--font-mono)', letterSpacing: showPassword ? '0px' : '2px' }}>
                        {showPassword ? (vm.credentials?.password || 'N/A') : '••••••••'}
                      </strong>
                      <button 
                        onClick={() => setShowPassword(!showPassword)}
                        style={{ border: 'none', background: 'none', cursor: 'pointer', color: 'var(--text-secondary)', padding: '2px', display: 'flex' }}
                      >
                        {showPassword ? <EyeOff size={12} /> : <Eye size={12} />}
                      </button>
                      <button 
                        onClick={() => handleCopy(vm.credentials?.password, 'password')}
                        style={{ border: 'none', background: 'none', cursor: 'pointer', color: 'var(--text-secondary)', padding: '2px', display: 'flex' }}
                      >
                        {copiedField === 'password' ? <Check size={12} color="var(--success)" /> : <Copy size={12} />}
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Нода размещения */}
              {vm.node && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Нода кластера</span>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 8px', background: 'rgba(0,0,0,0.03)', border: '1px solid var(--border-color)' }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>{vm.node}</span>
                    <button 
                      className="btn-icon-only" 
                      onClick={() => handleCopy(vm.node, 'node')}
                      style={{ border: 'none', background: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}
                    >
                      {copiedField === 'node' ? <Check size={13} color="var(--success)" /> : <Copy size={13} />}
                    </button>
                  </div>
                </div>
              )}

              {/* Закрытые порты */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Закрытые порты</span>
                  <ShieldAlert size={11} color="var(--danger)" />
                </div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', background: 'rgba(239, 68, 68, 0.05)', padding: '6px 8px', border: '1px solid rgba(239, 68, 68, 0.15)' }}>
                  2525, 465, 587, 389, 53413, 3389, 25
                </div>
              </div>
            </div>

            {/* Опасная зона */}
            <div style={{ marginTop: 'auto', borderTop: '1px solid var(--border-color)', paddingTop: '20px' }}>
              <button 
                className="btn btn-danger btn-sm"
                onClick={handleDeleteVM}
                disabled={actionLoading !== null}
                style={{ width: '100%', borderRadius: '0px', height: '36px' }}
              >
                {actionLoading === 'delete' ? <span className="spinner" style={{ width: '12px', height: '12px', borderWidth: '2px', borderColor: 'var(--danger)' }} /> : <Trash2 size={14} />}
                Удалить виртуалку
              </button>
            </div>

          </div>

          {/* ПРАВАЯ КОЛОНКА (Контент вкладок) */}
          <div style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            padding: '24px',
            minHeight: 0
          }}>
            
            {/* Меню переключения вкладок */}
            <div style={{ display: 'flex', gap: '8px', borderBottom: '1px solid var(--border-color)', paddingBottom: '12px', marginBottom: '20px' }}>
              {vm.status === 'Running' && (
                <>
                  <button 
                    className={`btn btn-sm ${activeTab === 'vnc' ? 'btn-primary' : 'btn-secondary'}`}
                    style={{ color: activeTab === 'vnc' ? '#ffffff' : 'var(--text-primary)', borderRadius: '0px' }}
                    onClick={() => setActiveTab('vnc')}
                  >
                    <Monitor size={12} />
                    Экран (noVNC)
                  </button>
                  {vm.os_type !== 'windows' && (
                    <>
                      <button 
                        className={`btn btn-sm ${activeTab === 'terminal' ? 'btn-primary' : 'btn-secondary'}`}
                        style={{ color: activeTab === 'terminal' ? '#ffffff' : 'var(--text-primary)', borderRadius: '0px' }}
                        onClick={() => setActiveTab('terminal')}
                      >
                        <Terminal size={12} />
                        Консоль SSH
                      </button>
                      <button 
                        className={`btn btn-sm ${activeTab === 'monitoring' ? 'btn-primary' : 'btn-secondary'}`}
                        style={{ color: activeTab === 'monitoring' ? '#ffffff' : 'var(--text-primary)', borderRadius: '0px' }}
                        onClick={() => setActiveTab('monitoring')}
                      >
                        <Activity size={12} />
                        Мониторинг ОС
                      </button>
                    </>
                  )}
                </>
              )}
              <button 
                className={`btn btn-sm ${activeTab === 'backups' ? 'btn-primary' : 'btn-secondary'}`}
                style={{ color: activeTab === 'backups' ? '#ffffff' : 'var(--text-primary)', borderRadius: '0px' }}
                onClick={() => setActiveTab('backups')}
              >
                💾 Резервные копии
              </button>
              <button 
                className={`btn btn-sm ${activeTab === 'resize' ? 'btn-primary' : 'btn-secondary'}`}
                style={{ color: activeTab === 'resize' ? '#ffffff' : 'var(--text-primary)', borderRadius: '0px' }}
                onClick={() => setActiveTab('resize')}
              >
                <Settings size={12} />
                Ресурсы
              </button>
            </div>

            {/* Контент вкладок */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
              
              {/* Вкладка 1: Экран (noVNC) */}
              {activeTab === 'vnc' && (
                <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
                  {vm.status !== 'Running' ? (
                    <div style={{
                      flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', 
                      border: '1px dashed var(--border-color)', color: 'var(--text-muted)', gap: '10px', minHeight: '300px'
                    }}>
                      <Monitor size={48} />
                      <h3>Виртуальная машина выключена</h3>
                      <p style={{ fontSize: '0.85rem' }}>Запустите виртуальную машину, чтобы подключиться к экрану VNC.</p>
                      <button className="btn btn-primary btn-sm" onClick={() => handlePowerAction('start')} disabled={actionLoading !== null} style={{ marginTop: '10px' }}>
                        Запустить сейчас
                      </button>
                    </div>
                  ) : (
                    <VncConsole 
                      name={vmName} 
                      username={vm.credentials?.username} 
                      password={vm.credentials?.password} 
                      isInline={true}
                      onClose={() => {}} 
                    />
                  )}
                </div>
              )}

              {/* Вкладка 2: Консоль SSH (Putty) */}
              {activeTab === 'terminal' && (
                <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
                  {vm.status !== 'Running' ? (
                    <div style={{
                      flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', 
                      border: '1px dashed var(--border-color)', color: 'var(--text-muted)', gap: '10px', minHeight: '300px'
                    }}>
                      <Terminal size={48} />
                      <h3>Виртуальная машина выключена</h3>
                      <p style={{ fontSize: '0.85rem' }}>Терминал SSH будет доступен после запуска виртуальной машины.</p>
                    </div>
                  ) : vm.os_type === 'windows' ? (
                    <div style={{
                      flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', 
                      border: '1px dashed var(--border-color)', color: 'var(--text-muted)', gap: '10px', minHeight: '300px'
                    }}>
                      <Shield size={48} color="var(--warning)" />
                      <h3>Недоступно для ОС Windows</h3>
                      <p style={{ fontSize: '0.85rem' }}>Интерактивный терминал SSH поддерживается только для Linux-дистрибутивов.</p>
                    </div>
                  ) : sshError && !sshData ? (
                    <div style={{
                      flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', 
                      border: '1px dashed var(--border-color)', color: 'var(--danger)', gap: '10px', minHeight: '300px', padding: '20px', textAlign: 'center'
                    }}>
                      <ShieldAlert size={48} />
                      <h3>Служба SSH на ВМ не отвечает</h3>
                      <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', maxWidth: '400px' }}>
                        {sshError}. Убедитесь, что внутри ВМ запущен sshd, настроены сетевые интерфейсы, и завершилась начальная инициализация.
                      </p>
                      <button className="btn btn-secondary btn-sm" onClick={fetchSshDetails} style={{ marginTop: '10px' }}>
                        <RefreshCw size={12} /> Переподключиться
                      </button>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '15px', flex: 1, minHeight: 0 }}>
                      <div style={{ 
                        flex: 1, background: '#1d1d1f', color: '#f5f5f7', padding: '20px', 
                        fontFamily: 'var(--font-mono)', fontSize: '0.85rem', overflowY: 'auto',
                        minHeight: '300px', maxHeight: '420px', border: '1px solid rgba(255, 255, 255, 0.1)',
                        display: 'flex', flexDirection: 'column', gap: '4px'
                      }}>
                        {terminalHistory.map((line, idx) => {
                          if (line.type === 'prompt') {
                            return <div key={idx} style={{ color: 'var(--primary)', fontWeight: 600 }}>{line.text}</div>;
                          } else if (line.type === 'stderr') {
                            return <pre key={idx} style={{ color: 'var(--danger)', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{line.text}</pre>;
                          } else if (line.type === 'info') {
                            return <div key={idx} style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>{line.text}</div>;
                          } else {
                            return <pre key={idx} style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{line.text}</pre>;
                          }
                        })}
                        {executing && (
                          <div style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span className="spinner" style={{ width: '12px', height: '12px', borderWidth: '2px', borderColor: '#fff' }} />
                            <span>Выполнение...</span>
                          </div>
                        )}
                        <div ref={terminalEndRef} />
                      </div>

                      <form onSubmit={handleExecuteCommand} style={{ display: 'flex', gap: '10px' }}>
                        <div style={{ 
                          display: 'flex', alignItems: 'center', background: 'rgba(0,0,0,0.05)', 
                          border: '1px solid var(--border-color)', padding: '0 12px', 
                          fontFamily: 'var(--font-mono)', fontSize: '0.85rem', color: 'var(--text-secondary)'
                        }}>
                          {sshData?.username || 'ubuntu'}@{sshData?.host || 'vm'}:{cwd}$
                        </div>
                        <input 
                          type="text"
                          className="form-input"
                          placeholder="Введите bash команду..."
                          value={command}
                          onChange={(e) => setCommand(e.target.value)}
                          disabled={executing}
                          autoFocus
                          style={{ flex: 1, fontFamily: 'var(--font-mono)', fontSize: '0.85rem' }}
                        />
                        <button type="submit" className="btn btn-primary" disabled={executing || !command.trim()} style={{ width: '110px', borderRadius: '0px' }}>
                          Выполнить
                        </button>
                        <button type="button" className="btn btn-secondary" onClick={() => setTerminalHistory([])} style={{ width: '100px', borderRadius: '0px' }}>
                          Очистить
                        </button>
                      </form>
                    </div>
                  )}
                </div>
              )}

              {/* Вкладка 3: Мониторинг ОС */}
              {activeTab === 'monitoring' && (
                <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, overflowY: 'auto' }}>
                  {vm.status !== 'Running' ? (
                    <div style={{
                      flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', 
                      border: '1px dashed var(--border-color)', color: 'var(--text-muted)', gap: '10px', minHeight: '300px'
                    }}>
                      <Activity size={48} />
                      <h3>Виртуальная машина выключена</h3>
                      <p style={{ fontSize: '0.85rem' }}>Показатели мониторинга операционной системы будут доступны после запуска ВМ.</p>
                    </div>
                  ) : !sshData ? (
                    <div style={{
                      flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', 
                      border: '1px dashed var(--border-color)', color: 'var(--text-muted)', gap: '10px', minHeight: '300px'
                    }}>
                      <RefreshCw className="spinner" size={32} />
                      <p style={{ fontSize: '0.85rem', marginTop: '10px' }}>Сбор системных метрик по SSH...</p>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', minHeight: 0 }}>
                      
                      {/* Шкалы ресурсов */}
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '15px' }}>
                        {/* CPU */}
                        <div className="card" style={{ padding: '16px', background: 'rgba(0,0,0,0.01)' }}>
                          <div className="stat-item">
                            <div className="stat-label-container" style={{ fontSize: '0.78rem' }}>
                              <span style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600 }}>
                                <Cpu size={14} color="var(--primary)" /> CPU
                              </span>
                              <span className="stat-value">{sshData.cpu.usage_percent}%</span>
                            </div>
                            <div className="progress-bar-bg" style={{ height: '6px', marginTop: '8px' }}>
                              <div className={`progress-bar-fill ${getProgressColor(sshData.cpu.usage_percent)}`} style={{ width: `${sshData.cpu.usage_percent}%` }} />
                            </div>
                          </div>
                        </div>

                        {/* RAM */}
                        <div className="card" style={{ padding: '16px', background: 'rgba(0,0,0,0.01)' }}>
                          <div className="stat-item">
                            <div className="stat-label-container" style={{ fontSize: '0.78rem' }}>
                              <span style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600 }}>
                                <HardDrive size={14} color="var(--success)" /> RAM
                              </span>
                              <span className="stat-value">{sshData.memory.usage_percent}%</span>
                            </div>
                            <div className="progress-bar-bg" style={{ height: '6px', marginTop: '8px' }}>
                              <div className={`progress-bar-fill ${getProgressColor(sshData.memory.usage_percent)}`} style={{ width: `${sshData.memory.usage_percent}%` }} />
                            </div>
                            <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', display: 'block', marginTop: '4px' }}>
                              {sshData.memory.used_mb} / {sshData.memory.total_mb} MB
                            </span>
                          </div>
                        </div>

                        {/* Disk */}
                        <div className="card" style={{ padding: '16px', background: 'rgba(0,0,0,0.01)' }}>
                          <div className="stat-item">
                            <div className="stat-label-container" style={{ fontSize: '0.78rem' }}>
                              <span style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600 }}>
                                <HardDrive size={14} color="var(--warning)" /> Disk (/)
                              </span>
                              <span className="stat-value">{sshData.disk.usage_percent}%</span>
                            </div>
                            <div className="progress-bar-bg" style={{ height: '6px', marginTop: '8px' }}>
                              <div className={`progress-bar-fill ${getProgressColor(sshData.disk.usage_percent)}`} style={{ width: `${sshData.disk.usage_percent}%` }} />
                            </div>
                            <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', display: 'block', marginTop: '4px' }}>
                              {sshData.disk.used_gb} / {sshData.disk.total_gb} GB
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Меню списков процессов/docker */}
                      <div>
                        <div style={{ display: 'flex', gap: '6px', borderBottom: '1px solid var(--border-color)', paddingBottom: '8px', marginBottom: '12px' }}>
                          <button 
                            className={`btn btn-sm ${activeSubTab === 'processes' ? 'btn-primary' : 'btn-secondary'}`}
                            style={{ fontSize: '0.75rem', borderRadius: '0px', padding: '4px 10px' }}
                            onClick={() => setActiveSubTab('processes')}
                          >
                            <Terminal size={10} /> Процессы ({sshData.processes?.length || 0})
                          </button>
                          <button 
                            className={`btn btn-sm ${activeSubTab === 'services' ? 'btn-primary' : 'btn-secondary'}`}
                            style={{ fontSize: '0.75rem', borderRadius: '0px', padding: '4px 10px' }}
                            onClick={() => setActiveSubTab('services')}
                          >
                            <ListFilter size={10} /> Systemd ({sshData.services?.length || 0})
                          </button>
                          <button 
                            className={`btn btn-sm ${activeSubTab === 'docker' ? 'btn-primary' : 'btn-secondary'}`}
                            style={{ fontSize: '0.75rem', borderRadius: '0px', padding: '4px 10px' }}
                            onClick={() => setActiveSubTab('docker')}
                          >
                            <Layers size={10} /> Docker ({sshData.docker?.installed ? sshData.docker.containers.length : 'N/A'})
                          </button>
                        </div>

                        {/* Списки */}
                        {activeSubTab === 'processes' && (
                          <div className="card" style={{ padding: '0', overflowX: 'auto', maxHeight: '240px', border: '1px solid var(--border-color)' }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.78rem' }}>
                              <thead>
                                <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-secondary)', background: 'rgba(0,0,0,0.05)' }}>
                                  <th style={{ padding: '8px 12px' }}>PID</th>
                                  <th style={{ padding: '8px 12px' }}>USER</th>
                                  <th style={{ padding: '8px 12px' }}>%CPU</th>
                                  <th style={{ padding: '8px 12px' }}>%MEM</th>
                                  <th style={{ padding: '8px 12px' }}>COMMAND</th>
                                </tr>
                              </thead>
                              <tbody>
                                {sshData.processes && sshData.processes.map((proc, i) => (
                                  <tr key={i} style={{ borderBottom: '1px solid rgba(0,0,0,0.03)' }}>
                                    <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>{proc.pid}</td>
                                    <td style={{ padding: '8px 12px', fontWeight: 500 }}>{proc.user}</td>
                                    <td style={{ padding: '8px 12px', color: 'var(--primary)', fontWeight: 600 }}>{proc.cpu}%</td>
                                    <td style={{ padding: '8px 12px' }}>{proc.mem}%</td>
                                    <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text-secondary)', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={proc.command}>
                                      {proc.command}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}

                        {activeSubTab === 'services' && (
                          <div className="card" style={{ padding: '0', overflowX: 'auto', maxHeight: '240px', border: '1px solid var(--border-color)' }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.78rem' }}>
                              <thead>
                                <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-secondary)', background: 'rgba(0,0,0,0.05)' }}>
                                  <th style={{ padding: '8px 12px' }}>Служба</th>
                                  <th style={{ padding: '8px 12px' }}>Статус</th>
                                  <th style={{ padding: '8px 12px' }}>Описание</th>
                                </tr>
                              </thead>
                              <tbody>
                                {sshData.services && sshData.services.map((svc, i) => (
                                  <tr key={i} style={{ borderBottom: '1px solid rgba(0,0,0,0.03)' }}>
                                    <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{svc.unit}</td>
                                    <td style={{ padding: '8px 12px' }}>
                                      <span className="status-badge running" style={{ fontSize: '0.65rem', padding: '1px 6px' }}>
                                        <span className="status-dot" />
                                        {svc.status}
                                      </span>
                                    </td>
                                    <td style={{ padding: '8px 12px', color: 'var(--text-secondary)', fontSize: '0.72rem' }}>{svc.description}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}

                        {activeSubTab === 'docker' && (
                          <div>
                            {!sshData.docker.installed ? (
                              <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', border: '1px dashed var(--border-color)' }}>
                                Docker не установлен на этой виртуальной машине.
                              </div>
                            ) : sshData.docker.containers.length === 0 ? (
                              <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', border: '1px dashed var(--border-color)' }}>
                                Нет запущенных Docker контейнеров.
                              </div>
                            ) : (
                              <div className="card" style={{ padding: '0', overflowX: 'auto', maxHeight: '240px', border: '1px solid var(--border-color)' }}>
                                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.78rem' }}>
                                  <thead>
                                    <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-secondary)', background: 'rgba(0,0,0,0.05)' }}>
                                      <th style={{ padding: '8px 12px' }}>Контейнер</th>
                                      <th style={{ padding: '8px 12px' }}>Образ</th>
                                      <th style={{ padding: '8px 12px' }}>Статус</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {sshData.docker.containers.map((c, i) => (
                                      <tr key={i} style={{ borderBottom: '1px solid rgba(0,0,0,0.03)' }}>
                                        <td style={{ padding: '8px 12px', fontWeight: 600 }}>{c.name}</td>
                                        <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text-muted)' }}>{c.image}</td>
                                        <td style={{ padding: '8px 12px' }}>
                                          <span className="status-badge running" style={{ fontSize: '0.65rem', padding: '1px 6px' }}>
                                            <span className="status-dot" />
                                            {c.status}
                                          </span>
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            )}
                          </div>
                        )}
                      </div>

                    </div>
                  )}
                </div>
              )}

              {/* Вкладка 4: Резервные копии */}
              {activeTab === 'backups' && (
                <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
                  <BackupList 
                    vmName={vmName} 
                    vmStatus={vm.status} 
                    onRestoreStarted={fetchVmDetails} 
                  />
                </div>
              )}

              {/* Вкладка 5: Настройка ресурсов */}
              {activeTab === 'resize' && (
                <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
                  <form onSubmit={handleResize} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                    
                    <div style={{
                      display: 'flex', gap: '10px', padding: '12px', background: 'rgba(245, 158, 11, 0.08)',
                      border: '1px solid rgba(245, 158, 11, 0.2)', fontSize: '0.8rem', color: 'var(--warning)', alignItems: 'flex-start'
                    }}>
                      <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
                      <div>
                        Изменение ядер CPU и памяти RAM применится только после **перезагрузки** виртуальной машины.
                        Размер жесткого диска можно **только увеличивать** (уменьшение дисков не поддерживается).
                      </div>
                    </div>

                    {/* CPU */}
                    <div className="slider-container">
                      <div className="slider-header">
                        <span>CPU Cores</span>
                        <span className="slider-value">{cpuCores} Cores</span>
                      </div>
                      <input 
                        type="range" 
                        min="1" 
                        max="8" 
                        className="range-input"
                        value={cpuCores}
                        onChange={(e) => setCpuCores(parseInt(e.target.value))}
                        disabled={savingResize}
                      />
                    </div>

                    {/* RAM */}
                    <div className="slider-container">
                      <div className="slider-header">
                        <span>Оперативная память (RAM)</span>
                        <span className="slider-value">{memoryGb} GB</span>
                      </div>
                      <input 
                        type="range" 
                        min="1" 
                        max="32" 
                        className="range-input"
                        value={memoryGb}
                        onChange={(e) => setMemoryGb(parseInt(e.target.value))}
                        disabled={savingResize}
                      />
                    </div>

                    {/* Disk */}
                    <div className="slider-container">
                      <div className="slider-header">
                        <span>Объем системного диска</span>
                        <span className="slider-value">{diskGb} GB</span>
                      </div>
                      <input 
                        type="range" 
                        min={currentDiskLimit} 
                        max="200" 
                        step="10"
                        className="range-input"
                        value={diskGb}
                        onChange={(e) => setDiskGb(parseInt(e.target.value))}
                        disabled={savingResize}
                      />
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', display: 'block', marginTop: '4px' }}>
                        Текущий лимит диска: {currentDiskLimit} GB.
                      </span>
                    </div>

                    <button type="submit" className="btn btn-primary" disabled={savingResize} style={{ marginTop: '10px', height: '40px', borderRadius: '0px' }}>
                      {savingResize ? <span className="spinner" style={{ width: '14px', height: '14px', borderWidth: '2px' }} /> : 'Сохранить изменения ресурсов'}
                    </button>

                  </form>
                </div>
              )}

            </div>

          </div>

        </div>

      </div>
    </div>
  );
};

export default VMDetail;
