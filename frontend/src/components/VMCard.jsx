import React, { useEffect, useState } from 'react';
import { Play, Square, RotateCw, Monitor, Trash2, Cpu, HardDrive, Terminal } from 'lucide-react';

const VMCard = ({ vm, onActionSuccess, onOpenConsole }) => {
  const [metrics, setMetrics] = useState(null);
  const [actionLoading, setActionLoading] = useState(null); // 'start' | 'stop' | 'restart' | 'delete'

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
      case 'Importing': return 'Импорт диска...';
      case 'Starting': return 'Запуск...';
      case 'Stopping': return 'Остановка...';
      default: return status;
    }
  };

  const getOSIcon = (type) => {
    return type === 'windows' ? '🪟' : '🐧';
  };

  // Расчет процента RAM под виртуалку
  const getRamPercent = () => {
    if (!metrics || !metrics.memory_mb) return 0;
    // Лимит памяти VM (например, "2Gi" -> 2048)
    const limitGb = parseInt(vm.memory);
    if (isNaN(limitGb)) return 0;
    const limitMb = limitGb * 1024;
    return Math.min(100, Math.round((metrics.memory_mb / limitMb) * 100));
  };

  return (
    <div className="card vm-card">
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

      {/* Метрики реального времени (показываем только когда VM работает) */}
      {vm.status === 'Running' && metrics && metrics.cpu_milli !== undefined && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '15px', padding: '0 4px' }}>
          {/* Нагрузка CPU */}
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
          {/* Потребление RAM */}
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

      {/* IP адреса ВМ */}
      <div className="vm-ips-section">
        <div className="resource-label" style={{ marginBottom: '4px' }}>Сеть и IP адреса:</div>
        {vm.status === 'Running' && vm.ips && vm.ips.length > 0 ? (
          vm.ips.map((ip, i) => (
            <div key={i} className="ip-row">
              <Terminal size={12} />
              <span>{ip} {i === 0 ? '(Internal)' : '(Home Bridge)'}</span>
            </div>
          ))
        ) : (
          <div className="ip-row" style={{ color: 'var(--text-muted)' }}>
            <span>{vm.status === 'Running' ? 'Ожидание получения IP...' : 'Выключена'}</span>
          </div>
        )}
      </div>

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
