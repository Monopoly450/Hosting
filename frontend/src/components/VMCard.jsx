import React, { useEffect, useState } from 'react';
import { Play, Square, RotateCw, Monitor, Cpu, HardDrive, Network, Trash2, Copy, X } from 'lucide-react';

const VMCard = ({ vm, onActionSuccess, onOpenDetail }) => {
  const [metrics, setMetrics] = useState(null);
  const [actionLoading, setActionLoading] = useState(null);
  const [showClone, setShowClone] = useState(false);
  const [cloneName, setCloneName] = useState('');
  const [cloning, setCloning] = useState(false);

  const getSshIp = () => {
    if (!vm || !vm.ips || vm.ips.length === 0) return null;
    const bridgeIp = vm.ips.find(ip => 
      !ip.startsWith('10.244.') && 
      !ip.startsWith('10.42.') && 
      !ip.startsWith('10.0.2.') && 
      !ip.startsWith('127.0.') &&
      !ip.includes(':')
    );
    return bridgeIp || vm.ips[0] || null;
  };

  const sshIp = getSshIp();
  const isReady = vm.status === 'Stopped' || (vm.status === 'Running' && sshIp !== null);

  const handleCardClick = (e) => {
    if (e.target.closest('button') || e.target.closest('.vm-card-actions')) return;
    if (onOpenDetail) onOpenDetail(vm.name);
  };

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
      const response = await fetch(`/api/vms/${vm.name}/${action}`, { method: 'POST' });
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || `Ошибка ${action}`);
      }
      if (onActionSuccess) onActionSuccess();
    } catch (err) {
      alert(`Ошибка: ${err.message}`);
    } finally {
      setActionLoading(null);
    }
  };

  const handleDelete = async (e) => {
    e.stopPropagation();
    if (!window.confirm(`Удалить виртуалку ${vm.name}?`)) return;
    setActionLoading('delete');
    try {
      const response = await fetch(`/api/vms/${vm.name}`, { method: 'DELETE' });
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || `Ошибка удаления`);
      }
      if (onActionSuccess) onActionSuccess();
    } catch (err) {
      alert(`Ошибка: ${err.message}`);
    } finally {
      setActionLoading(null);
    }
  };

  const handleClone = async (e) => {
    e.preventDefault();
    e.stopPropagation();
    const target = cloneName.trim().toLowerCase().replace(/[^a-z0-9-]/g, '-');
    if (!target) return;
    setCloning(true);
    try {
      const response = await fetch(`/api/vms/${vm.name}/clone`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_name: target })
      });
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Ошибка клонирования');
      }
      setShowClone(false);
      setCloneName('');
      if (onActionSuccess) onActionSuccess();
    } catch (err) {
      alert(`Ошибка: ${err.message}`);
    } finally {
      setCloning(false);
    }
  };

  const getBadgeClass = (status) => {
    if (status === 'Running') return isReady ? 'badge-success' : 'badge-warning';
    if (status === 'Stopped') return 'badge-danger';
    if (status === 'Stopping') return 'badge-warning';
    if (status === 'Starting' || status === 'Provisioning' || status === 'Scheduled') return 'badge-info animate-pulse';
    return 'badge-info';
  };

  const getStatusLabel = (status) => {
    if (status === 'Running') return isReady ? 'Запущена' : 'Настройка сети...';
    if (status === 'Stopped') return 'Остановлена';
    if (status === 'Provisioning') return 'Создание...';
    if (status === 'Importing') return `Импорт ${vm.import_progress || ''}`;
    if (status === 'Starting') return 'Запуск...';
    if (status === 'Stopping') return 'Выключение...';
    if (status === 'Scheduled') return 'Планирование...';
    return status;
  };

  const getOSIcon = (type) => {
    if (type === 'windows') return '🪟';
    if (type === 'ubuntu') return '🐧';
    if (type === 'proxmox') return '🧱';
    return '💿';
  };

  const getRamPercent = () => {
    if (!metrics || !metrics.memory_mb) return 0;
    const limitGb = parseInt(vm.memory);
    if (isNaN(limitGb)) return 0;
    const limitMb = limitGb * 1024;
    return Math.min(100, Math.round((metrics.memory_mb / limitMb) * 100));
  };

  return (
    <div 
      className="glass-card interactive" 
      onClick={handleCardClick}
      style={{ cursor: 'pointer', display: 'flex', flexDirection: 'column', padding: '20px' }}
    >
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ fontSize: '1.75rem', lineHeight: 1 }}>{getOSIcon(vm.os_type)}</div>
          <div>
            <div style={{ fontWeight: 600, color: 'var(--text-heading)', fontSize: '1.05rem', marginBottom: '2px' }}>{vm.name}</div>
            <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', display: 'flex', gap: '8px', alignItems: 'center' }}>
              <span>{vm.os_type} OS</span>
              {vm.owner_username && (
                <>
                  <span style={{ width: '4px', height: '4px', borderRadius: '50%', backgroundColor: 'var(--border-subtle)' }}></span>
                  <span style={{ color: 'var(--accent-primary)', fontWeight: 500 }}>👤 {vm.owner_username}</span>
                </>
              )}
            </div>
          </div>
        </div>
        <span className={`badge ${getBadgeClass(vm.status)}`}>
          <span className="status-dot"></span>
          {getStatusLabel(vm.status)}
        </span>
      </div>

      {/* Network / Details Info */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '16px', fontSize: '0.8rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span className="text-muted" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Network size={12}/> IP Address</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--text-heading)' }}>{sshIp || 'N/A'}</span>
        </div>
      </div>

      {/* Resources Info */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '16px', background: 'var(--bg-surface)', padding: '10px 12px', borderRadius: 'var(--radius-md)' }}>
        <div style={{ flex: 1, textAlign: 'center', borderRight: '1px solid var(--border-subtle)' }}>
          <div className="text-muted" style={{ fontSize: '0.7rem', marginBottom: '2px' }}>CPU</div>
          <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>{vm.cpu_cores} Cores</div>
        </div>
        <div style={{ flex: 1, textAlign: 'center', borderRight: '1px solid var(--border-subtle)' }}>
          <div className="text-muted" style={{ fontSize: '0.7rem', marginBottom: '2px' }}>RAM</div>
          <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>{vm.memory}</div>
        </div>
        <div style={{ flex: 1, textAlign: 'center' }}>
          <div className="text-muted" style={{ fontSize: '0.7rem', marginBottom: '2px' }}>Disk</div>
          <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>{vm.disks[0]?.size || 'N/A'}</div>
        </div>
      </div>

      {/* Metrics or Import Progress */}
      <div style={{ flex: 1 }}>
        {vm.status === 'Importing' && (
          <div style={{ marginBottom: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: '6px' }}>
              <span className="text-muted">Прогресс импорта</span>
              <span style={{ fontWeight: 600 }}>{vm.import_progress || '0%'}</span>
            </div>
            <div className="progress-track">
              <div className="progress-fill primary" style={{ width: vm.import_progress && vm.import_progress.includes('%') ? vm.import_progress : '0%' }} />
            </div>
          </div>
        )}

        {vm.status === 'Running' && metrics && metrics.cpu_milli !== undefined && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '16px' }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: '4px' }}>
                <span className="text-muted" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Cpu size={12}/> Load</span>
                <span style={{ fontWeight: 600 }}>{metrics.cpu_milli} m</span>
              </div>
              <div className="progress-track" style={{ height: '4px' }}>
                <div className="progress-fill primary" style={{ width: `${Math.min(100, Math.round(metrics.cpu_milli / (vm.cpu_cores * 10)))}%` }} />
              </div>
            </div>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: '4px' }}>
                <span className="text-muted" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><HardDrive size={12}/> RAM</span>
                <span style={{ fontWeight: 600 }}>{getRamPercent()}%</span>
              </div>
              <div className="progress-track" style={{ height: '4px' }}>
                <div className="progress-fill success" style={{ width: `${getRamPercent()}%` }} />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="vm-card-actions" style={{ marginTop: 'auto', paddingTop: '16px', borderTop: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="text-muted" style={{ fontSize: '0.75rem' }}>
          {isReady ? 'Доступно ➔' : vm.status === 'Stopped' ? 'Остановлена' : (vm.status === 'Stopping' ? 'Выключение...' : 'Загрузка...')}
        </span>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            className="btn btn-secondary btn-icon"
            onClick={(e) => { e.stopPropagation(); setShowClone(true); }}
            disabled={actionLoading !== null}
            title="Клонировать ВМ (создать копию)"
          >
            <Copy size={14} />
          </button>
          <button
            className="btn btn-secondary btn-icon"
            onClick={handleDelete}
            disabled={vm.status !== 'Stopped' || actionLoading !== null}
            title="Удалить можно только выключенную ВМ"
            style={{ 
              color: vm.status !== 'Stopped' ? 'var(--text-muted)' : '#ef4444', 
              borderColor: vm.status !== 'Stopped' ? 'var(--border-subtle)' : '#fee2e2',
              cursor: vm.status !== 'Stopped' ? 'not-allowed' : 'pointer'
            }}
          >
            {actionLoading === 'delete' ? <span className="spinner"/> : <Trash2 size={14}/>}
          </button>
          {vm.status !== 'Running' ? (
            <button 
              className="btn btn-primary"
              style={{ padding: '6px 16px', borderRadius: 'var(--radius-pill)' }}
              onClick={(e) => { e.stopPropagation(); handleAction('start'); }}
              disabled={actionLoading !== null}
            >
              {actionLoading === 'start' ? <span className="spinner"/> : <><Play size={14}/> Start</>}
            </button>
          ) : (
            <>
              <button 
                className="btn btn-secondary btn-icon"
                onClick={(e) => { e.stopPropagation(); handleAction('restart'); }}
                disabled={actionLoading !== null}
                title="Перезагрузить"
              >
                {actionLoading === 'restart' ? <span className="spinner"/> : <RotateCw size={14}/>}
              </button>
              <button 
                className="btn btn-secondary"
                style={{ padding: '6px 12px', borderRadius: 'var(--radius-pill)' }}
                onClick={(e) => { e.stopPropagation(); handleAction('stop'); }}
                disabled={actionLoading !== null}
              >
                {actionLoading === 'stop' ? <span className="spinner"/> : <><Square size={14}/> Stop</>}
              </button>
            </>
          )}
        </div>
      </div>

      {showClone && (
        <div className="modal-overlay" onClick={(e) => { e.stopPropagation(); setShowClone(false); }}>
          <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '440px' }}>
            <div className="modal-header">
              <h2>Клонировать «{vm.name}»</h2>
              <button className="btn-close" onClick={() => setShowClone(false)} type="button"><X size={18} /></button>
            </div>
            <form onSubmit={handleClone}>
              <div style={{ padding: '24px' }}>
                <div className="input-group" style={{ marginBottom: 0 }}>
                  <label className="input-label">Имя новой ВМ</label>
                  <input
                    type="text"
                    className="form-control"
                    placeholder="например: web-server-copy"
                    value={cloneName}
                    onChange={e => setCloneName(e.target.value)}
                    autoFocus
                    required
                  />
                  <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '6px' }}>
                    Будет создана полная копия диска и настроек. Ресурсы (CPU, RAM, диск) — как у исходной ВМ.
                    Для надёжного клонирования исходную ВМ лучше сначала выключить.
                  </span>
                </div>
              </div>
              <div className="modal-actions">
                <button type="button" className="btn btn-secondary" onClick={() => setShowClone(false)} disabled={cloning}>Отмена</button>
                <button type="submit" className="btn btn-primary" disabled={cloning || !cloneName.trim()}>
                  {cloning ? <span className="spinner" /> : <><Copy size={15} /> Клонировать</>}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default VMCard;
