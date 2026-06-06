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
    <div className="console-modal-backdrop">
      <div className="console-container" style={{ maxWidth: '500px' }}>
        <div className="console-header">
          <div className="console-title">
            <Server className="logo-icon" size={20} />
            <span>Подключить внешний Linux-сервер</span>
          </div>
          <button className="btn btn-danger btn-icon-only btn-sm" onClick={onClose} disabled={loading}>
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          
          <div style={{
            display: 'flex',
            gap: '10px',
            padding: '12px',
            background: 'rgba(0, 168, 255, 0.05)',
            border: '1px solid var(--border-color)',
            borderRadius: '0px',
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
          <div className="form-group">
            <label className="form-label" htmlFor="server-alias">Понятное имя сервера</label>
            <input 
              id="server-alias"
              type="text" 
              className="form-input" 
              placeholder="e.g. My Ubuntu VPS"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              disabled={loading}
            />
          </div>

          {/* IP и Порт */}
          <div style={{ display: 'grid', gridTemplateColumns: '3fr 1fr', gap: '15px' }}>
            <div className="form-group">
              <label className="form-label" htmlFor="server-ip">IP-адрес / Hostname</label>
              <input 
                id="server-ip"
                type="text" 
                className="form-input" 
                placeholder="192.168.1.100"
                value={host}
                onChange={(e) => setHost(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="server-port">Порт SSH</label>
              <input 
                id="server-port"
                type="number" 
                className="form-input" 
                value={port}
                onChange={(e) => setPort(parseInt(e.target.value))}
                required
                disabled={loading}
              />
            </div>
          </div>

          {/* Пользователь и Пароль */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '15px' }}>
            <div className="form-group">
              <label className="form-label" htmlFor="server-user">Пользователь</label>
              <input 
                id="server-user"
                type="text" 
                className="form-input" 
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="server-pass">Пароль SSH</label>
              <input 
                id="server-pass"
                type="password" 
                className="form-input" 
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
