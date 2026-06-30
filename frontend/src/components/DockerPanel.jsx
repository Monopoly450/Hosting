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
      <div className="glass-card" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '400px' }}>
        <div className="spinner"></div>
      </div>
    );
  }

  if (error && containers.length === 0) {
    return (
      <div className="glass-card" style={{ textAlign: 'center', padding: '60px', color: 'var(--status-danger)' }}>
        <AlertTriangle size={48} style={{ marginBottom: '15px' }} />
        <h3 className="section-title" style={{ justifyContent: 'center', color: 'var(--status-danger)' }}>Служба Docker недоступна</h3>
        <p className="text-muted" style={{ maxWidth: '400px', margin: '10px auto' }}>
          Убедитесь, что Docker запущен на хосте и сокет примонтирован.
        </p>
        <button className="btn btn-secondary" style={{ margin: '15px auto 0' }} onClick={fetchContainers}>
          <RefreshCw size={14} /> Переподключиться
        </button>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 className="section-title" style={{ margin: 0 }}>
            <Layers size={22} color="var(--accent-primary)" />
            Управление Docker-контейнерами
          </h2>
          <p className="text-muted" style={{ margin: '4px 0 0', fontSize: '0.9rem' }}>Хостовый уровень кластера</p>
        </div>
        <button className="btn btn-secondary" onClick={fetchContainers} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spinner' : ''} /> Обновить
        </button>
      </div>

      <div className="glass-card" style={{ padding: '0', overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.9rem' }}>
            <thead>
              <tr style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-subtle)' }}>
                <th style={{ padding: '16px 24px', fontWeight: 500, color: 'var(--text-secondary)' }}>Контейнер</th>
                <th style={{ padding: '16px 24px', fontWeight: 500, color: 'var(--text-secondary)' }}>Образ</th>
                <th style={{ padding: '16px 24px', fontWeight: 500, color: 'var(--text-secondary)' }}>Статус</th>
                <th style={{ padding: '16px 24px', fontWeight: 500, color: 'var(--text-secondary)' }}>Порты</th>
                <th style={{ padding: '16px 24px', fontWeight: 500, color: 'var(--text-secondary)', textAlign: 'right' }}>Действия</th>
              </tr>
            </thead>
            <tbody>
              {containers.map((c) => (
                <tr key={c.id} style={{ borderBottom: '1px solid var(--border-subtle)' }} className="interactive">
                  <td style={{ padding: '16px 24px' }}>
                    <div style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{c.name}</div>
                    <div className="text-muted" style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)' }}>{c.id}</div>
                  </td>
                  <td style={{ padding: '16px 24px', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--text-secondary)', maxWidth: '240px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={c.image}>
                    {c.image}
                  </td>
                  <td style={{ padding: '16px 24px' }}>
                    <span className={`badge badge-${c.status === 'running' ? 'success' : 'danger'}`}>
                      <span className="status-dot" />
                      {c.status}
                    </span>
                  </td>
                  <td style={{ padding: '16px 24px', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    {c.ports.length > 0 ? c.ports.join(', ') : 'Нет биндингов'}
                  </td>
                  <td style={{ padding: '16px 24px', textAlign: 'right' }}>
                    <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                      {c.status !== 'running' ? (
                        <button 
                          className="btn btn-primary btn-icon"
                          onClick={() => handleAction(c.full_id, 'start')}
                          disabled={actionLoading !== null}
                          title="Запустить"
                        >
                          {actionLoading === `${c.full_id}-start` ? <span className="spinner"/> : <Play size={14} />}
                        </button>
                      ) : (
                        <>
                          <button 
                            className="btn btn-secondary btn-icon"
                            onClick={() => handleAction(c.full_id, 'stop')}
                            disabled={actionLoading !== null}
                            title="Остановить"
                          >
                            {actionLoading === `${c.full_id}-stop` ? <span className="spinner"/> : <Square size={14} />}
                          </button>
                          <button 
                            className="btn btn-secondary btn-icon"
                            onClick={() => handleAction(c.full_id, 'restart')}
                            disabled={actionLoading !== null}
                            title="Перезапустить"
                          >
                            {actionLoading === `${c.full_id}-restart` ? <span className="spinner"/> : <RotateCw size={14} />}
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {containers.length === 0 && !loading && (
                <tr>
                  <td colSpan="5" style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>Нет запущенных контейнеров</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default DockerPanel;
