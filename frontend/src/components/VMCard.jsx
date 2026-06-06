import React, { useEffect, useState } from 'react';
import { Play, Square, RotateCw, Monitor, Trash2, Cpu, HardDrive, Terminal, Settings, ShieldAlert, Key, Clipboard, Copy, Check, Eye, EyeOff } from 'lucide-react';
import BackupList from './BackupList';

const VMCard = ({ vm, onActionSuccess, onOpenConsole, onOpenEdit }) => {
  const [metrics, setMetrics] = useState(null);
  const [actionLoading, setActionLoading] = useState(null); // 'start' | 'stop' | 'restart' | 'delete'
  const [showBackups, setShowBackups] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  // Получаем живые метрики для запущенной виртуалки
  useEffect(() => {
    if (vm.status !== 'Running') {
      setMetrics(null);
      return;
    }

    const fetchVMMetrics = async () => {
      try {
        const response = await fetch(`/api/vms/${vm.name}/metrics`);
        if (!response.ok) return;
        const data = await response.json();
        setMetrics(data);
      } catch (err) {
        console.warn('Failed to fetch VM metrics:', err);
      }
    };

    fetchVMMetrics();
    const interval = setInterval(fetchVMMetrics, 4000);
    return () => clearInterval(interval);
  }, [vm.name, vm.status]);

  const handleAction = async (action) => {
    setActionLoading(action);
    try {
      let response;
      if (action === 'delete') {
        if (!confirm(`Вы действительно хотите безвозвратно удалить виртуальную машину "${vm.name}" и все ее диски?`)) {
          setActionLoading(null);
          return;
        }
        response = await fetch(`/api/vms/${vm.name}`, { method: 'DELETE' });
      } else {
        response = await fetch(`/api/vms/${vm.name}/${action}`, { method: 'POST' });
      }

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || `Действие ${action} завершилось ошибкой.`);
      }
      
      onActionSuccess();
    } catch (err) {
      alert(`Ошибка: ${err.message}`);
    } finally {
      setActionLoading(null);
    }
  };

  const copyPassword = () => {
    if (vm.credentials && vm.credentials.password !== 'N/A') {
      navigator.clipboard.writeText(vm.credentials.password);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
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
      case 'Importing': return `Импорт диска ${vm.import_progress && vm.import_progress !== 'N/A' ? `(${vm.import_progress})` : ''}`;
      case 'Starting': return 'Запуск...';
      case 'Stopping': return 'Остановка...';
      default: return status;
    }
  };

  const getOSIcon = (type) => {
    if (type === 'windows') return '🪟';
    if (type === 'ubuntu') return '🐧';
    return '💿';
  };

  const getRamPercent = () => {
    if (!metrics || !metrics.memory_mb) return 0;
    const limitGb = parseInt(vm.memory);
    if (isNaN(limitGb)) return 0;
    const limitMb = limitGb * 1024;
    return Math.min(100, Math.round((metrics.memory_mb / limitMb) * 100));
  };

  const getSshIp = () => {
    if (!vm.ips || vm.ips.length === 0) return null;
    // Находим IP, который не относится к внутренней сети подов K8s (10.244.x.x)
    const externalIp = vm.ips.find(ip => !ip.startsWith('10.244.'));
    return externalIp || vm.ips[0];
  };
  const sshIp = getSshIp();

  return (
    <div className="card vm-card" style={{ height: 'auto', minHeight: 'auto' }}>
      <div>
        <div className="vm-card-header">
          <div className="vm-title-group">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '1.25rem' }}>{getOSIcon(vm.os_type)}</span>
              <span className="vm-name">{vm.name}</span>
            </div>
            <span className="vm-template">{vm.os_type} template</span>
          </div>
          <span className={`status-badge ${getStatusClass(vm.status)}`}>
            <span className="status-dot"></span>
            {getStatusLabel(vm.status)}
          </span>
        </div>

        {/* Выделенные ресурсы */}
        <div className="vm-resources-row">
          <div className="resource-metric">
            <span className="resource-label">CPU Cores</span>
            <span className="resource-val">{vm.cpu_cores}</span>
          </div>
          <div className="resource-metric">
            <span className="resource-label">Memory</span>
            <span className="resource-val">{vm.memory}</span>
          </div>
          <div className="resource-metric">
            <span className="resource-label">Storage</span>
            <span className="resource-val">{vm.disks[0]?.size || 'N/A'}</span>
          </div>
        </div>

        {/* Реквизиты доступа (SSH / OS) */}
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
          padding: '16px',
          background: 'rgba(255, 255, 255, 0.02)',
          borderRadius: '12px',
          border: '1px solid var(--border-color)',
          fontSize: '0.82rem',
          marginBottom: '15px'
        }}>
          {/* IPv4 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.72rem', fontWeight: 500 }}>IPv4</span>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              {sshIp ? (
                <>
                  <strong style={{ fontSize: '0.95rem', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{sshIp}</strong>
                  <button 
                    onClick={() => {
                      navigator.clipboard.writeText(sshIp);
                      alert('IP-адрес скопирован в буфер обмена');
                    }}
                    style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', padding: '2px', display: 'flex' }}
                    title="Копировать IP"
                  >
                    <Copy size={13} />
                  </button>
                </>
              ) : (
                <span style={{ color: 'var(--text-muted)', fontSize: '0.78rem' }}>
                  {vm.status === 'Running' ? 'Ожидание получения IP...' : 'Выключена'}
                </span>
              )}
            </div>
          </div>

          {/* Подключение по SSH */}
          {sshIp && vm.os_type !== 'windows' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '8px' }}>
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.72rem', fontWeight: 500 }}>Подключение по SSH</span>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                <span style={{ color: 'var(--text-primary)' }}>ssh {vm.credentials?.username || 'root'}@{sshIp}</span>
                <button 
                  onClick={() => {
                    navigator.clipboard.writeText(`ssh ${vm.credentials?.username || 'root'}@${sshIp}`);
                    alert('Команда SSH скопирована в буфер обмена');
                  }}
                  style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', padding: '2px', display: 'flex' }}
                  title="Копировать команду SSH"
                >
                  <Copy size={13} />
                </button>
              </div>
            </div>
          )}

          {/* Пароль */}
          {vm.os_type !== 'windows' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '8px' }}>
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.72rem', fontWeight: 500 }}>
                {vm.credentials?.username === 'root' ? 'Root-пароль' : 'Пароль пользователя'}
              </span>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <strong style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', letterSpacing: showPassword ? '0px' : '2px', fontSize: showPassword ? '0.85rem' : '0.75rem' }}>
                  {showPassword ? (vm.credentials?.password || 'N/A') : '••••••••••••'}
                </strong>
                <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                  <button 
                    onClick={() => setShowPassword(!showPassword)}
                    style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', padding: '2px', display: 'flex' }}
                    title={showPassword ? "Скрыть пароль" : "Показать пароль"}
                  >
                    {showPassword ? <EyeOff size={13} /> : <Eye size={13} />}
                  </button>
                  {vm.credentials?.password !== 'N/A' && (
                    <button 
                      onClick={copyPassword}
                      style={{ background: 'none', border: 'none', color: copied ? 'var(--success)' : 'var(--text-secondary)', cursor: 'pointer', padding: '2px', display: 'flex' }}
                      title="Копировать пароль"
                    >
                      {copied ? <Check size={13} /> : <Copy size={13} />}
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Нода */}
          {vm.node && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '8px' }}>
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.72rem', fontWeight: 500 }}>Нода</span>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                <span style={{ color: 'var(--text-primary)' }}>{vm.node}</span>
                <button 
                  onClick={() => {
                    navigator.clipboard.writeText(vm.node);
                    alert('Имя ноды скопировано в буфер обмена');
                  }}
                  style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', padding: '2px', display: 'flex' }}
                  title="Копировать имя ноды"
                >
                  <Copy size={13} />
                </button>
              </div>
            </div>
          )}

          {/* Закрытые порты */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.72rem', fontWeight: 500 }}>Закрытые порты</span>
              <ShieldAlert size={11} color="var(--danger)" />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.75rem', color: 'rgba(255, 255, 255, 0.4)' }}>
              <span>2525, 465, 587, 389, 53413, 3389, 25</span>
            </div>
          </div>
        </div>

        {/* Прогресс импорта диска */}
        {vm.status === 'Importing' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '15px', padding: '0 4px' }}>
            <div className="stat-item">
              <div className="stat-label-container" style={{ fontSize: '0.75rem' }}>
                <span>Загрузка образа диска</span>
                <span className="stat-value">{vm.import_progress || '0%'}</span>
              </div>
              <div className="progress-bar-bg" style={{ height: '4px' }}>
                <div 
                  className="progress-bar-fill primary"
                  style={{ width: vm.import_progress && vm.import_progress.includes('%') ? vm.import_progress : '0%' }}
                />
              </div>
            </div>
          </div>
        )}

        {/* Метрики реального времени */}
        {vm.status === 'Running' && metrics && metrics.cpu_milli !== undefined && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '15px', padding: '0 4px' }}>
            <div className="stat-item">
              <div className="stat-label-container" style={{ fontSize: '0.75rem' }}>
                <span>Загрузка CPU</span>
                <span className="stat-value">{metrics.cpu_milli} mCores</span>
              </div>
              <div className="progress-bar-bg" style={{ height: '4px' }}>
                <div 
                  className="progress-bar-fill primary"
                  style={{ width: `${Math.min(100, Math.round(metrics.cpu_milli / (vm.cpu_cores * 10)))}%` }}
                />
              </div>
            </div>
            <div className="stat-item">
              <div className="stat-label-container" style={{ fontSize: '0.75rem' }}>
                <span>Использование RAM</span>
                <span className="stat-value">{metrics.memory_mb} MB ({getRamPercent()}%)</span>
              </div>
              <div className="progress-bar-bg" style={{ height: '4px' }}>
                <div 
                  className="progress-bar-fill success"
                  style={{ width: `${getRamPercent()}%` }}
                />
              </div>
            </div>
          </div>
        )}


      </div>

      {/* Выдвижная панель бэкапов */}
      {showBackups && (
        <div style={{
          borderTop: '1px solid var(--border-color)',
          paddingTop: '15px',
          marginTop: '15px',
          marginBottom: '15px'
        }}>
          <BackupList 
            vmName={vm.name} 
            vmStatus={vm.status} 
            onRestoreStarted={onActionSuccess} 
          />
        </div>
      )}

      {/* Действия с VM */}
      <div className="vm-card-actions">
        {vm.status !== 'Running' ? (
          <button 
            className="btn btn-primary btn-sm"
            onClick={() => handleAction('start')}
            disabled={actionLoading !== null}
            style={{ flex: 1 }}
          >
            {actionLoading === 'start' ? <span className="spinner" style={{ width: '12px', height: '12px', borderWidth: '2px' }} /> : <Play size={14} />}
            Запуск
          </button>
        ) : (
          <>
            <button 
              className="btn btn-secondary btn-sm"
              onClick={() => handleAction('stop')}
              disabled={actionLoading !== null}
              style={{ flex: 1 }}
            >
              {actionLoading === 'stop' ? <span className="spinner" style={{ width: '12px', height: '12px', borderWidth: '2px' }} /> : <Square size={14} />}
              Стоп
            </button>
            <button 
              className="btn btn-secondary btn-sm"
              onClick={() => handleAction('restart')}
              disabled={actionLoading !== null}
              title="Перезагрузить"
            >
              {actionLoading === 'restart' ? <span className="spinner" style={{ width: '12px', height: '12px', borderWidth: '2px' }} /> : <RotateCw size={14} />}
            </button>
            <button 
              className="btn btn-primary btn-sm"
              onClick={() => onOpenConsole(vm.name)}
              title="Открыть VNC экран"
            >
              <Monitor size={14} />
              Экран
            </button>
          </>
        )}
        
        {/* Кнопка бэкапов */}
        <button 
          className={`btn btn-secondary btn-sm ${showBackups ? 'active' : ''}`}
          onClick={() => setShowBackups(!showBackups)}
          title="Резервные копии"
          style={{ padding: '8px', border: showBackups ? '1px solid var(--primary)' : '1px solid var(--border-color)' }}
        >
          💾
        </button>

        {/* Настройки */}
        <button 
          className="btn btn-secondary btn-sm btn-icon-only"
          onClick={() => onOpenEdit(vm)}
          title="Настройка ресурсов"
        >
          <Settings size={14} />
        </button>

        <button 
          className="btn btn-danger btn-sm btn-icon-only"
          onClick={() => handleAction('delete')}
          disabled={actionLoading !== null}
          title="Удалить ВМ"
        >
          {actionLoading === 'delete' ? <span className="spinner" style={{ width: '12px', height: '12px', borderWidth: '2px', borderColor: 'var(--danger)' }} /> : <Trash2 size={14} />}
        </button>
      </div>
    </div>
  );
};

export default VMCard;
