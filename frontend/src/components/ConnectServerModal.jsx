import React, { useState } from 'react';
import { X, Server, ShieldAlert, Key } from 'lucide-react';

const ConnectServerModal = ({ onClose, onSuccess }) => {
  const [name, setName] = useState('');
  const [host, setHost] = useState('');
  const [port, setPort] = useState(22);
  const [username, setUsername] = useState('root');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim() || !host.trim() || !password.trim()) return;

    setLoading(true);
    try {
      const payload = {
        name: name.trim(),
        host: host.trim(),
        port: parseInt(port),
        username: username.trim(),
        password: password
      };

      const response = await fetch('/api/external-servers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Не удалось подключиться к серверу.');
      }

      alert(`Сервер "${payload.name}" успешно подключен!`);
      onSuccess();
      onClose();
    } catch (err) {
      alert(`Ошибка подключения: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: '500px' }}>
        <div className="modal-header">
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: "600", fontSize: "1.1rem" }}>
            <Server className="logo-icon" size={20} />
            <span>Подключить внешний Linux-сервер</span>
          </div>
          <button className="btn-icon-only" style={{ background: "transparent", border: "none" }} onClick={onClose} disabled={loading}>
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '20px', padding: '24px' }}>
          
          <div style={{
            display: 'flex',
            gap: '10px',
            padding: '12px',
            background: 'rgba(0, 168, 255, 0.05)',
            border: '1px solid var(--border-color)',
            borderRadius: 'var(--radius-md)',
            fontSize: '0.8rem',
            color: 'var(--text-secondary)'
          }}>
            <ShieldAlert size={18} style={{ flexShrink: 0 }} />
            <div>
              Панель подключится по SSH для сбора метрик (загрузка CPU/RAM, процессы, докер, службы).
              Необходим доступ по паролю для указанного пользователя.
            </div>
          </div>

          {/* Имя (Алиас) */}
          <div className="input-group">
            <label className="input-label" htmlFor="server-alias">Понятное имя сервера</label>
            <input 
              id="server-alias"
              type="text" 
              className="form-control" 
              placeholder="e.g. My Ubuntu VPS"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              disabled={loading}
            />
          </div>

          {/* IP и Порт */}
          <div style={{ display: 'grid', gridTemplateColumns: '3fr 1fr', gap: '15px' }}>
            <div className="input-group">
              <label className="input-label" htmlFor="server-ip">IP-адрес / Hostname</label>
              <input 
                id="server-ip"
                type="text" 
                className="form-control" 
                placeholder="192.168.1.100"
                value={host}
                onChange={(e) => setHost(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            <div className="input-group">
              <label className="input-label" htmlFor="server-port">Порт SSH</label>
              <input 
                id="server-port"
                type="number" 
                className="form-control" 
                value={port}
                onChange={(e) => setPort(parseInt(e.target.value))}
                required
                disabled={loading}
              />
            </div>
          </div>

          {/* Пользователь и Пароль */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '15px' }}>
            <div className="input-group">
              <label className="input-label" htmlFor="server-user">Пользователь</label>
              <input 
                id="server-user"
                type="text" 
                className="form-control" 
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            <div className="input-group">
              <label className="input-label" htmlFor="server-pass">Пароль SSH</label>
              <input 
                id="server-pass"
                type="password" 
                className="form-control" 
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={loading}
              />
            </div>
          </div>

          <div style={{ display: 'flex', gap: '12px', marginTop: '10px' }}>
            <button 
              type="button" 
              className="btn btn-secondary" 
              style={{ flex: 1 }}
              onClick={onClose}
              disabled={loading}
            >
              Отмена
            </button>
            <button 
              type="submit" 
              className="btn btn-primary" 
              style={{ flex: 1 }}
              disabled={loading}
            >
              {loading ? (
                <>
                  <span className="spinner" style={{ width: '14px', height: '14px', borderWidth: '2px', borderColor: '#000' }} />
                  Тестирование SSH...
                </>
              ) : (
                'Подключить'
              )}
            </button>
          </div>

        </form>
      </div>
    </div>
  );
};

export default ConnectServerModal;
