import React, { useState } from 'react';
import { X, Server, ShieldAlert, Key, Network, ArrowRight } from 'lucide-react';

const ConnectServerModal = ({ onClose, onSuccess }) => {
  const [name, setName] = useState('');
  const [host, setHost] = useState('');
  const [port, setPort] = useState(22);
  const [username, setUsername] = useState('root');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  // Бастион (jump host)
  const [useBastion, setUseBastion] = useState(false);
  const [bastionHost, setBastionHost] = useState('');
  const [bastionPort, setBastionPort] = useState(22);
  const [bastionUsername, setBastionUsername] = useState('root');
  const [bastionPassword, setBastionPassword] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim() || !host.trim() || !password.trim()) return;
    if (useBastion && (!bastionHost.trim() || !bastionUsername.trim() || !bastionPassword.trim())) {
      alert('Для бастиона укажите хост, пользователя и пароль.');
      return;
    }

    setLoading(true);
    try {
      const payload = {
        name: name.trim(),
        host: host.trim(),
        port: parseInt(port),
        username: username.trim(),
        password: password,
        ...(useBastion ? {
          bastion_host: bastionHost.trim(),
          bastion_port: parseInt(bastionPort),
          bastion_username: bastionUsername.trim(),
          bastion_password: bastionPassword,
        } : {})
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
    <div className="slide-over-overlay" onClick={onClose}>
      <div className="slide-over-content" onClick={e => e.stopPropagation()}>
        <div className="slide-over-header">
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: "600", fontSize: "1.1rem" }}>
            <Server className="logo-icon" size={20} />
            <span>Подключить внешний Linux-сервер</span>
          </div>
          <button className="btn-close" onClick={onClose} disabled={loading} type="button">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          <div className="slide-over-body" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            
            <div style={{
              display: 'flex',
              gap: '10px',
              padding: '12px',
              background: 'rgba(0, 168, 255, 0.05)',
              border: '1px solid var(--border-subtle)',
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

            {/* Бастион (jump host) */}
            <div style={{
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)',
              padding: '16px',
              background: 'var(--bg-surface-hover)',
            }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer', userSelect: 'none' }}>
                <input
                  type="checkbox"
                  checked={useBastion}
                  onChange={(e) => setUseBastion(e.target.checked)}
                  disabled={loading}
                  style={{ width: '18px', height: '18px', accentColor: 'var(--accent-primary)', cursor: 'pointer' }}
                />
                <Network size={18} style={{ color: 'var(--accent-primary)' }} />
                <div>
                  <div style={{ fontWeight: 600, color: 'var(--text-heading)', fontSize: '0.9rem' }}>Подключение через бастион (jump host)</div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>Панель зайдёт на сервер не напрямую, а через промежуточный SSH-хост.</div>
                </div>
              </label>

              {useBastion && (
                <div style={{ marginTop: '16px', display: 'flex', flexDirection: 'column', gap: '14px', animation: 'fadeInUp var(--transition-normal) both' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                    <span>Панель</span> <ArrowRight size={14} /> <strong style={{ color: 'var(--accent-primary)' }}>Бастион</strong> <ArrowRight size={14} /> <span>{host || 'целевой сервер'}</span>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '3fr 1fr', gap: '15px' }}>
                    <div className="input-group" style={{ marginBottom: 0 }}>
                      <label className="input-label" htmlFor="bastion-host">Хост бастиона</label>
                      <input id="bastion-host" type="text" className="form-control" placeholder="bastion.example.com"
                        value={bastionHost} onChange={(e) => setBastionHost(e.target.value)} disabled={loading} required={useBastion} />
                    </div>
                    <div className="input-group" style={{ marginBottom: 0 }}>
                      <label className="input-label" htmlFor="bastion-port">Порт</label>
                      <input id="bastion-port" type="number" className="form-control"
                        value={bastionPort} onChange={(e) => setBastionPort(parseInt(e.target.value))} disabled={loading} required={useBastion} />
                    </div>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '15px' }}>
                    <div className="input-group" style={{ marginBottom: 0 }}>
                      <label className="input-label" htmlFor="bastion-user">Пользователь бастиона</label>
                      <input id="bastion-user" type="text" className="form-control"
                        value={bastionUsername} onChange={(e) => setBastionUsername(e.target.value)} disabled={loading} required={useBastion} />
                    </div>
                    <div className="input-group" style={{ marginBottom: 0 }}>
                      <label className="input-label" htmlFor="bastion-pass">Пароль бастиона</label>
                      <input id="bastion-pass" type="password" className="form-control" placeholder="••••••••"
                        value={bastionPassword} onChange={(e) => setBastionPassword(e.target.value)} disabled={loading} required={useBastion} />
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="slide-over-actions">
            <button 
              type="button" 
              className="btn btn-secondary" 
              onClick={onClose}
              disabled={loading}
            >
              Отмена
            </button>
            <button 
              type="submit" 
              className="btn btn-primary" 
              disabled={loading}
            >
              {loading ? (
                <>
                  <span className="spinner" style={{ width: '14px', height: '14px', borderWidth: '2px', borderColor: 'rgba(255,255,255,0.4)', borderTopColor: '#fff' }} />
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
