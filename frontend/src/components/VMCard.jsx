import React, { useEffect, useState } from 'react';
import { Play, Square, Cpu, HardDrive, RotateCw } from 'lucide-react';

const VMCard = ({ vm, onActionSuccess, onOpenDetail }) => {
  const [metrics, setMetrics] = useState(null);
  const [actionLoading, setActionLoading] = useState(null); // 'start' | 'stop' | 'restart'

  const getSshIp = () => {
    if (!vm || !vm.ips || vm.ips.length === 0) return null;
    const bridgeIp = vm.ips.find(ip => 
      !ip.startsWith('10.244.') && 
      !ip.startsWith('10.42.') && 
      !ip.startsWith('10.0.2.') && 
      !ip.startsWith('127.0.') &&
      !ip.includes(':')
    );
    return bridgeIp || null;
  };

  const isReady = vm.status === 'Running' && getSshIp() !== null;

  const handleCardClick = (e) => {
    if (
      e.target.closest('button') || 
      e.target.closest('svg') || 
      e.target.closest('.vm-card-actions')
    ) {
      return;
    }
    if (!isReady) {
      return;
    }
    if (onOpenDetail) {
      onOpenDetail(vm.name);
    }
  };

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
      const response = await fetch(`/api/vms/${vm.name}/${action}`, { method: 'POST' });
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

  const getStatusClass = (status) => {
    switch (status) {
      case 'Running': return isReady ? 'running' : 'pending';
      case 'Stopped': return 'stopped';
      default: return 'pending';
    }
  };

  const getStatusLabel = (status) => {
    switch (status) {
      case 'Running': return isReady ? 'Активна' : 'Настройка сети...';
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

  return (
    <div 
      className="card vm-card" 
      onClick={handleCardClick}
      style={{ 
        height: 'auto', 
        minHeight: '230px', 
        cursor: isReady ? 'pointer' : 'wait',
        opacity: isReady ? 1 : 0.88,
        transition: 'all 0.2s ease',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between'
      }}
      onMouseEnter={(e) => {
        if (!isReady) return;
        e.currentTarget.style.transform = 'translateY(-2px)';
        e.currentTarget.style.borderColor = 'rgba(0, 113, 227, 0.25)';
        e.currentTarget.style.boxShadow = '0 8px 24px rgba(0,0,0,0.08)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = 'translateY(0)';
        e.currentTarget.style.borderColor = 'rgba(0, 0, 0, 0.08)';
        e.currentTarget.style.boxShadow = 'none';
      }}
    >
      <div>
        {/* Заголовок карточки */}
        <div className="vm-card-header">
          <div className="vm-title-group">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '1.25rem' }}>{getOSIcon(vm.os_type)}</span>
              <span className="vm-name" style={{ fontWeight: 600 }}>{vm.name}</span>
            </div>
            <span className="vm-template" style={{ fontSize: '0.75rem', opacity: 0.7 }}>{vm.os_type} template</span>
          </div>
          <span className={`status-badge ${getStatusClass(vm.status)}`}>
            <span className="status-dot"></span>
            {getStatusLabel(vm.status)}
          </span>
        </div>

        {/* Выделенные ресурсы */}
        <div className="vm-resources-row" style={{ marginTop: '12px', marginBottom: '15px' }}>
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

        {/* Прогресс импорта диска */}
        {vm.status === 'Importing' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '12px', padding: '0 4px' }}>
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
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '12px', padding: '0 4px' }}>
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

      {/* Нижняя панель действий */}
      <div className="vm-card-actions" style={{ borderTop: '1px solid var(--border-color)', paddingTop: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ 
          fontSize: '0.75rem', 
          color: isReady ? 'var(--text-secondary)' : 'var(--warning-text, #e28743)', 
          fontWeight: isReady ? 400 : 500 
        }}>
          {isReady ? 'Кликните для управления' : 'Ожидайте получения IP...'}
        </span>
        {vm.status !== 'Running' ? (
          <button 
            className="btn btn-primary btn-sm"
            onClick={(e) => { e.stopPropagation(); handleAction('start'); }}
            disabled={actionLoading !== null}
            style={{ padding: '6px 12px', fontSize: '0.75rem', borderRadius: '0px' }}
          >
            {actionLoading === 'start' ? <span className="spinner" style={{ width: '10px', height: '10px', borderWidth: '2px' }} /> : <Play size={10} style={{ marginRight: '4px' }} />}
            Запуск
          </button>
        ) : (
          <div style={{ display: 'flex', gap: '6px' }}>
            <button 
              className="btn btn-secondary btn-sm"
              onClick={(e) => { e.stopPropagation(); handleAction('restart'); }}
              disabled={actionLoading !== null}
              title="Перезагрузить"
              style={{ padding: '6px 10px', fontSize: '0.75rem', borderRadius: '0px' }}
            >
              {actionLoading === 'restart' ? <span className="spinner" style={{ width: '10px', height: '10px', borderWidth: '2px' }} /> : <RotateCw size={10} />}
            </button>
            <button 
              className="btn btn-secondary btn-sm"
              onClick={(e) => { e.stopPropagation(); handleAction('stop'); }}
              disabled={actionLoading !== null}
              style={{ padding: '6px 12px', fontSize: '0.75rem', borderRadius: '0px' }}
            >
              {actionLoading === 'stop' ? <span className="spinner" style={{ width: '10px', height: '10px', borderWidth: '2px' }} /> : <Square size={10} style={{ marginRight: '4px' }} />}
              Стоп
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default VMCard;
