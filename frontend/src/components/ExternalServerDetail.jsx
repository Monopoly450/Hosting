import React, { useEffect, useState } from 'react';
import { X, RefreshCw, Cpu, HardDrive, ShieldAlert, Terminal, Activity, Layers, ListFilter } from 'lucide-react';

const ExternalServerDetail = ({ serverId, onClose }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeSubTab, setActiveSubTab] = useState('processes'); // 'processes' | 'services' | 'docker'

  const fetchDetails = async () => {
    try {
      const response = await fetch(`/api/external-servers/${serverId}/details`);
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Не удалось получить данные с сервера.');
      }
      const resData = await response.json();
      setData(resData);
      setError(null);
    } catch (err) {
      console.error(err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDetails();
    // Опрашиваем удаленный сервер каждые 6 секунд (чтобы не перегружать SSH-сессиями)
    const interval = setInterval(fetchDetails, 6000);
    return () => clearInterval(interval);
  }, [serverId]);

  if (loading && !data) {
    return (
      <div className="console-modal-backdrop">
        <div className="console-container" style={{ maxWidth: '600px', padding: '40px', textAlign: 'center' }}>
          <div className="spinner" style={{ margin: '0 auto 20px' }} />
          <p style={{ fontWeight: 600 }}>Подключение по SSH и сбор системных метрик...</p>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '8px' }}>
            Это может занять несколько секунд...
          </p>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="console-modal-backdrop">
        <div className="console-container" style={{ maxWidth: '500px', padding: '40px', textAlign: 'center', color: 'var(--danger)' }}>
          <ShieldAlert size={48} style={{ margin: '0 auto 15px' }} />
          <h3>Не удалось связаться с сервером</h3>
          <p style={{ margin: '10px 0', fontSize: '0.9rem', color: 'var(--text-secondary)' }}>{error}</p>
          <div style={{ display: 'flex', gap: '10px', justifyContent: 'center', marginTop: '20px' }}>
            <button className="btn btn-secondary btn-sm" onClick={onClose}>Закрыть</button>
            <button className="btn btn-primary btn-sm" onClick={fetchDetails}>Повторить</button>
          </div>
        </div>
      </div>
    );
  }

  const getProgressColor = (val) => {
    if (val < 70) return 'success';
    if (val < 90) return 'warning';
    return 'danger';
  };

  return (
    <div className="console-modal-backdrop">
      <div className="console-container" style={{ width: '95vw', maxWidth: '1000px', height: '85vh', display: 'flex', flexDirection: 'column' }}>
        
        {/* Шапка */}
        <div className="console-header">
          <div className="console-title">
            <Activity className="logo-icon" size={20} />
            <span>Мониторинг сервера: <strong style={{ color: 'var(--primary)' }}>{data.name}</strong> ({data.host})</span>
          </div>
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <button className="btn btn-secondary btn-sm" onClick={fetchDetails} title="Обновить сейчас">
              <RefreshCw size={12} />
            </button>
            <button className="btn btn-danger btn-icon-only btn-sm" onClick={onClose}>
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Тело */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Верхняя панель: Метаданные */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '15px',
            padding: '16px',
            background: 'rgba(255, 255, 255, 0.02)',
            border: '1px solid var(--border-color)',
            borderRadius: '0px',
            fontSize: '0.85rem'
          }}>
            <div>ОС: <strong style={{ color: 'var(--text-primary)' }}>{data.os_name}</strong></div>
            <div>Ядро: <strong style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{data.kernel}</strong></div>
            <div>Время работы: <strong style={{ color: 'var(--text-primary)' }}>{data.uptime}</strong></div>
            <div>SSH: <strong style={{ color: 'var(--primary)', fontFamily: 'var(--font-mono)' }}>{data.username}@{data.host}:{data.port}</strong></div>
          </div>

          {/* Средняя панель: Ресурсы (Диаграммы/Шкалы) */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '20px' }}>
            
            {/* CPU */}
            <div className="card" style={{ padding: '20px' }}>
              <div className="stat-item">
                <div className="stat-label-container">
                  <span style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600 }}>
                    <Cpu size={16} color="var(--primary)" /> CPU Нагрузка
                  </span>
                  <span className="stat-value">{data.cpu.usage_percent}% ({data.cpu.cores} Cores)</span>
                </div>
                <div className="progress-bar-bg" style={{ height: '8px', marginTop: '10px' }}>
                  <div 
                    className={`progress-bar-fill ${getProgressColor(data.cpu.usage_percent)}`}
                    style={{ width: `${data.cpu.usage_percent}%` }}
                  />
                </div>
              </div>
            </div>

            {/* RAM */}
            <div className="card" style={{ padding: '20px' }}>
              <div className="stat-item">
                <div className="stat-label-container">
                  <span style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600 }}>
                    <HardDrive size={16} color="var(--success)" /> Оперативная память
                  </span>
                  <span className="stat-value">
                    {data.memory.used_mb} / {data.memory.total_mb} MB ({data.memory.usage_percent}%)
                  </span>
                </div>
                <div className="progress-bar-bg" style={{ height: '8px', marginTop: '10px' }}>
                  <div 
                    className={`progress-bar-fill ${getProgressColor(data.memory.usage_percent)}`}
                    style={{ width: `${data.memory.usage_percent}%` }}
                  />
                </div>
              </div>
            </div>

            {/* Disk */}
            <div className="card" style={{ padding: '20px' }}>
              <div className="stat-item">
                <div className="stat-label-container">
                  <span style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600 }}>
                    <HardDrive size={16} color="var(--warning)" /> Системный накопитель (/)
                  </span>
                  <span className="stat-value">
                    {data.disk.used_gb} / {data.disk.total_gb} GB ({data.disk.usage_percent}%)
                  </span>
                </div>
                <div className="progress-bar-bg" style={{ height: '8px', marginTop: '10px' }}>
                  <div 
                    className={`progress-bar-fill ${getProgressColor(data.disk.usage_percent)}`}
                    style={{ width: `${data.disk.usage_percent}%` }}
                  />
                </div>
              </div>
            </div>

          </div>

          {/* Нижняя панель: Переключаемые списки (Процессы, Сервисы, Docker) */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
            
            {/* Меню переключения списков */}
            <div style={{ display: 'flex', gap: '8px', borderBottom: '1px solid var(--border-color)', paddingBottom: '10px' }}>
              <button 
                className={`btn btn-sm ${activeSubTab === 'processes' ? 'btn-primary' : 'btn-secondary'}`}
                style={{ color: activeSubTab === 'processes' ? '#000' : 'var(--text-primary)' }}
                onClick={() => setActiveSubTab('processes')}
              >
                <Terminal size={12} />
                Активные процессы ({data.processes?.length || 0})
              </button>
              <button 
                className={`btn btn-sm ${activeSubTab === 'services' ? 'btn-primary' : 'btn-secondary'}`}
                style={{ color: activeSubTab === 'services' ? '#000' : 'var(--text-primary)' }}
                onClick={() => setActiveSubTab('services')}
              >
                <ListFilter size={12} />
                Службы Systemd ({data.services?.length || 0})
              </button>
              <button 
                className={`btn btn-sm ${activeSubTab === 'docker' ? 'btn-primary' : 'btn-secondary'}`}
                style={{ color: activeSubTab === 'docker' ? '#000' : 'var(--text-primary)' }}
                onClick={() => setActiveSubTab('docker')}
              >
                <Layers size={12} />
                Docker Контейнеры ({data.docker?.installed ? data.docker.containers.length : 'N/A'})
              </button>
            </div>

            {/* Под-вкладка 1: Топ Процессов */}
            {activeSubTab === 'processes' && (
              <div className="card" style={{ padding: '0', overflowX: 'auto', maxHeight: '350px' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.8rem' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-secondary)', background: 'rgba(0,0,0,0.1)' }}>
                      <th style={{ padding: '10px 16px' }}>PID</th>
                      <th style={{ padding: '10px 16px' }}>USER</th>
                      <th style={{ padding: '10px 16px' }}>%CPU</th>
                      <th style={{ padding: '10px 16px' }}>%MEM</th>
                      <th style={{ padding: '10px 16px' }}>COMMAND</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.processes && data.processes.map((proc, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                        <td style={{ padding: '10px 16px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>{proc.pid}</td>
                        <td style={{ padding: '10px 16px', fontWeight: 500 }}>{proc.user}</td>
                        <td style={{ padding: '10px 16px', color: 'var(--primary)', fontWeight: 600 }}>{proc.cpu}%</td>
                        <td style={{ padding: '10px 16px' }}>{proc.mem}%</td>
                        <td style={{ padding: '10px 16px', fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-secondary)', maxWidth: '400px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={proc.command}>
                          {proc.command}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Под-вкладка 2: Службы Systemd */}
            {activeSubTab === 'services' && (
              <div className="card" style={{ padding: '0', overflowX: 'auto', maxHeight: '350px' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.8rem' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-secondary)', background: 'rgba(0,0,0,0.1)' }}>
                      <th style={{ padding: '10px 16px' }}>Служба</th>
                      <th style={{ padding: '10px 16px' }}>Статус</th>
                      <th style={{ padding: '10px 16px' }}>Описание</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.services && data.services.map((svc, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                        <td style={{ padding: '10px 16px', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{svc.unit}</td>
                        <td style={{ padding: '10px 16px' }}>
                          <span className="status-badge running" style={{ fontSize: '0.7rem', padding: '2px 8px' }}>
                            <span className="status-dot" />
                            {svc.status}
                          </span>
                        </td>
                        <td style={{ padding: '10px 16px', color: 'var(--text-secondary)' }}>{svc.description}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Под-вкладка 3: Контейнеры Docker */}
            {activeSubTab === 'docker' && (
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                {!data.docker.installed ? (
                  <div style={{
                    padding: '30px',
                    textAlign: 'center',
                    color: 'var(--text-muted)',
                    border: '1px dashed var(--border-color)',
                    borderRadius: '0px'
                  }}>
                    Служба Docker не установлена на этом сервере.
                  </div>
                ) : data.docker.containers.length === 0 ? (
                  <div style={{
                    padding: '30px',
                    textAlign: 'center',
                    color: 'var(--text-muted)',
                    border: '1px dashed var(--border-color)',
                    borderRadius: '0px'
                  }}>
                    Нет запущенных Docker-контейнеров на этом хосте.
                  </div>
                ) : (
                  <div className="card" style={{ padding: '0', overflowX: 'auto', maxHeight: '350px' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.8rem' }}>
                      <thead>
                        <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-secondary)', background: 'rgba(0,0,0,0.1)' }}>
                          <th style={{ padding: '10px 16px' }}>Контейнер</th>
                          <th style={{ padding: '10px 16px' }}>Образ</th>
                          <th style={{ padding: '10px 16px' }}>Статус</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.docker.containers.map((c, i) => (
                          <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                            <td style={{ padding: '10px 16px', fontWeight: 600 }}>{c.name}</td>
                            <td style={{ padding: '10px 16px', fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-muted)' }}>{c.image}</td>
                            <td style={{ padding: '10px 16px' }}>
                              <span className="status-badge running" style={{ fontSize: '0.7rem', padding: '2px 8px' }}>
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

      </div>
    </div>
  );
};

export default ExternalServerDetail;
