import React, { useState } from 'react';
import { Terminal, Trash2, ShieldCheck, ShieldAlert } from 'lucide-react';

const ExternalServerCard = ({ server, onClick, onDeleteSuccess }) => {
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async (e) => {
    e.stopPropagation(); // Предотвращаем открытие деталей при клике на удаление
    if (!confirm(`Вы действительно хотите отключить сервер "${server.name}" (${server.host})?`)) return;

    setDeleting(true);
    try {
      const response = await fetch(`/api/external-servers/${server.id}`, {
        method: 'DELETE'
      });
      if (!response.ok) throw new Error('Ошибка удаления сервера');
      onDeleteSuccess();
    } catch (err) {
      alert(err.message);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div 
      className="card vm-card" 
      onClick={onClick}
      style={{
        cursor: 'pointer',
        minHeight: '180px',
        justifyContent: 'space-between',
        border: server.status === 'Online' ? '1px solid rgba(16, 185, 129, 0.15)' : '1px solid rgba(239, 68, 68, 0.15)',
        background: 'var(--bg-card)',
        transition: 'all 0.2s ease'
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = server.status === 'Online' ? 'var(--success)' : 'var(--danger)';
        e.currentTarget.style.transform = 'translateY(-2px)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = server.status === 'Online' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)';
        e.currentTarget.style.transform = 'translateY(0)';
      }}
    >
      <div>
        <div className="vm-card-header">
          <div className="vm-title-group">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '1.2rem' }}>🌐</span>
              <span className="vm-name">{server.name}</span>
            </div>
            <span className="vm-template" style={{ fontFamily: 'var(--font-mono)' }}>IP: {server.host}:{server.port}</span>
          </div>
          <span className={`status-badge ${server.status === 'Online' ? 'running' : 'stopped'}`}>
            <span className="status-dot"></span>
            {server.status === 'Online' ? 'В сети' : 'Не в сети'}
          </span>
        </div>

        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '6px',
          fontSize: '0.8rem',
          color: 'var(--text-secondary)',
          fontFamily: 'var(--font-mono)',
          padding: '8px 12px',
          background: 'rgba(0, 0, 0, 0.15)',
          borderRadius: '0px'
        }}>
          <div>Пользователь: <strong style={{ color: 'var(--primary)' }}>{server.username}</strong></div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem', marginTop: '4px' }}>
            {server.status === 'Online' ? (
              <>
                <ShieldCheck size={12} color="var(--success)" />
                <span style={{ color: 'var(--success)' }}>Доступ по SSH подтвержден</span>
              </>
            ) : (
              <>
                <ShieldAlert size={12} color="var(--danger)" />
                <span style={{ color: 'var(--danger)' }}>Ошибка авторизации или хост оффлайн</span>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="vm-card-actions" style={{ borderTop: '1px solid var(--border-color)', paddingTop: '12px' }}>
        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
          <Terminal size={10} /> Кликните для мониторинга
        </span>
        <button 
          className="btn btn-danger btn-sm btn-icon-only"
          onClick={handleDelete}
          disabled={deleting}
          title="Отключить сервер"
          style={{ marginLeft: 'auto', padding: '6px' }}
        >
          {deleting ? (
            <span className="spinner" style={{ width: '12px', height: '12px', borderWidth: '2px', borderColor: 'var(--danger)' }} />
          ) : (
            <Trash2 size={12} />
          )}
        </button>
      </div>
    </div>
  );
};

export default ExternalServerCard;
