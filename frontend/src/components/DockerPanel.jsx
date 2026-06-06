import React, { useEffect, useState } from 'react';
import { Play, Square, RotateCw, RefreshCw, Layers, AlertTriangle } from 'lucide-react';

const DockerPanel = () => {
  const [containers, setContainers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [actionLoading, setActionLoading] = useState(null); // 'id-action'

  const fetchContainers = async () => {
    try {
      const response = await fetch('/api/docker/containers');
      if (!response.ok) throw new Error('Docker unavailable');
      const data = await response.json();
      setContainers(data);
      setError(false);
    } catch (err) {
      console.error(err);
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchContainers();
    const interval = setInterval(fetchContainers, 4000);
    return () => clearInterval(interval);
  }, []);

  const handleAction = async (id, action) => {
    setActionLoading(`${id}-${action}`);
    try {
      const response = await fetch(`/api/docker/containers/${id}/${action}`, {
        method: 'POST'
      });
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Ошибка выполнения команды Docker.');
      }
      fetchContainers();
    } catch (err) {
      alert(`Ошибка Docker: ${err.message}`);
    } finally {
      setActionLoading(null);
    }
  };

  if (loading && containers.length === 0) {
    return (
      <div className="card" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '400px' }}>
        <div className="spinner"></div>
      </div>
    );
  }

  if (error && containers.length === 0) {
    return (
      <div className="card" style={{ textAlign: 'center', padding: '60px', color: 'var(--danger)' }}>
        <AlertTriangle size={48} style={{ marginBottom: '15px' }} />
        <h3>Служба Docker на хосте недоступна</h3>
        <p style={{ maxWidth: '400px', margin: '10px auto', fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
          Убедитесь, что Docker запущен на вашей Ubuntu и файл сокета `/var/run/docker.sock` смонтирован в контейнер бэкенда.
        </p>
        <button className="btn btn-secondary btn-sm" style={{ marginTop: '15px' }} onClick={fetchContainers}>
          <RefreshCw size={14} /> Повторить подключение
        </button>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div className="vms-section-header">
        <h2 style={{ fontSize: '1.4rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '10px' }}>
          <Layers className="logo-icon" size={22} />
          Панель управления Docker (Хост)
        </h2>
        <button className="btn btn-secondary btn-sm" onClick={fetchContainers} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spinner' : ''} /> Обновить
        </button>
      </div>

      <div className="card" style={{ padding: '0', overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.9rem' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}>
              <th style={{ padding: '16px 24px' }}>Контейнер</th>
              <th style={{ padding: '16px 24px' }}>Образ</th>
              <th style={{ padding: '16px 24px' }}>Статус</th>
              <th style={{ padding: '16px 24px' }}>Порты</th>
              <th style={{ padding: '16px 24px', textAlign: 'right' }}>Действия</th>
            </tr>
          </thead>
          <tbody>
            {containers.map((c) => (
              <tr key={c.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)', transition: 'background 0.2s' }} className="docker-row">
                <td style={{ padding: '16px 24px' }}>
                  <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{c.name}</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>ID: {c.id}</div>
                </td>
                <td style={{ padding: '16px 24px', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--text-secondary)', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={c.image}>
                  {c.image}
                </td>
                <td style={{ padding: '16px 24px' }}>
                  <span className={`status-badge ${c.status === 'running' ? 'running' : 'stopped'}`}>
                    <span className="status-dot" />
                    {c.status}
                  </span>
                </td>
                <td style={{ padding: '16px 24px', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  {c.ports.length > 0 ? c.ports.join(', ') : 'No bindings'}
                </td>
                <td style={{ padding: '16px 24px', textAlign: 'right' }}>
                  <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                    {c.status !== 'running' ? (
                      <button 
                        className="btn btn-primary btn-sm btn-icon-only"
                        onClick={() => handleAction(c.full_id, 'start')}
                        disabled={actionLoading !== null}
                        title="Запустить"
                      >
                        {actionLoading === `${c.full_id}-start` ? (
                          <span className="spinner" style={{ width: '12px', height: '12px', borderWidth: '2px' }} />
                        ) : (
                          <Play size={12} />
                        )}
                      </button>
                    ) : (
                      <>
                        <button 
                          className="btn btn-secondary btn-sm btn-icon-only"
                          onClick={() => handleAction(c.full_id, 'stop')}
                          disabled={actionLoading !== null}
                          title="Остановить"
                        >
                          {actionLoading === `${c.full_id}-stop` ? (
                            <span className="spinner" style={{ width: '12px', height: '12px', borderWidth: '2px' }} />
                          ) : (
                            <Square size={12} />
                          )}
                        </button>
                        <button 
                          className="btn btn-secondary btn-sm btn-icon-only"
                          onClick={() => handleAction(c.full_id, 'restart')}
                          disabled={actionLoading !== null}
                          title="Перезапустить"
                        >
                          {actionLoading === `${c.full_id}-restart` ? (
                            <span className="spinner" style={{ width: '12px', height: '12px', borderWidth: '2px' }} />
                          ) : (
                            <RotateCw size={12} />
                          )}
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default DockerPanel;
