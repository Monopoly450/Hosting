import React, { useState, useEffect } from 'react';
import { Mail, Plus, Trash2, Key, Info, Copy, X } from 'lucide-react';

export default function MailPanel() {
    const [mailboxes, setMailboxes] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [showCreateModal, setShowCreateModal] = useState(false);
    
    // Form fields
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [submitting, setSubmitting] = useState(false);
    // Домен почты задаётся в .env (MAIL_DOMAIN) и подставляется почтовому
    // серверу как DOMAINNAME (см. docker-compose.yml). Интерфейс узнаёт о нём
    // из /api/domains/status — иначе в подсказках оставалась заглушка
    // domain.local, и было непонятно, на каком домене создавать ящик.
    const [mailDomain, setMailDomain] = useState('');
    // IP самого хоста: на нём слушают порты почты (25/143/587/993) и вебмейл
    // (8082). Нужен и как запасной адрес без домена, и чтобы было видно, куда
    // указывать MX/A-записи.
    const [hostIp, setHostIp] = useState('');

    const getHeaders = () => {
        const token = localStorage.getItem('aegis_admin_token') || '';
        return {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
        };
    };

    const fetchMailboxes = async () => {
        setLoading(true);
        try {
            const res = await fetch('/api/mail', { headers: getHeaders() });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка при загрузке списка почтовых ящиков');
            }
            const data = await res.json();
            setMailboxes(data);
            setError('');
        } catch (err) {
            setError(err.message || 'Ошибка при загрузке списка почтовых ящиков');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchMailboxes();
        fetch('/api/domains/status', { headers: getHeaders() })
            .then(r => (r.ok ? r.json() : null))
            .then(d => {
                if (!d) return;
                setMailDomain(d.mail_domain || '');
                setHostIp(d.host_ip || '');
            })
            .catch(() => { /* необязательно: без домена покажем общий пример */ });
    }, []);

    const handleCreateMailbox = async (e) => {
        e.preventDefault();
        setSubmitting(true);
        try {
            const res = await fetch('/api/mail', {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({
                    email,
                    password
                })
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка при создании почтового ящика');
            }
            
            setShowCreateModal(false);
            setEmail('');
            setPassword('');
            fetchMailboxes();
        } catch (err) {
            alert(err.message || 'Ошибка при создании почтового ящика');
        } finally {
            setSubmitting(false);
        }
    };

    const handleDeleteMailbox = async (mailboxId) => {
        if (!confirm('Вы уверены, что хотите удалить этот почтовый ящик? Все письма будут безвозвратно стёрты.')) return;
        try {
            const res = await fetch(`/api/mail/${mailboxId}`, {
                method: 'DELETE',
                headers: getHeaders()
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка при удалении ящика');
            }
            fetchMailboxes();
        } catch (err) {
            alert(err.message || 'Ошибка при удалении ящика');
        }
    };

    const copyToClipboard = (text) => {
        navigator.clipboard.writeText(text);
        alert('Скопировано в буфер обмена!');
    };

    // Адрес почтового сервера для IMAP/SMTP.
    //
    // Раньше здесь стоял window.location.hostname — адрес, по которому открыта
    // ПАНЕЛЬ. С привязанным доменом панели это давало home.byteburners.ru в
    // настройках почты, хотя почта живёт на своём домене. Порты почты слушает
    // сам хост, поэтому верный адрес — почтовый домен, а без него IP хоста.
    const getMailServerIP = () => {
        return mailDomain || hostIp || window.location.hostname;
    };

    // Куда ведёт «Войти в Webmail». С доменом — на него (Caddy проксирует его
    // на Roundcube и держит сертификат), иначе на порт 8082 хоста.
    const webmailUrl = () => {
        if (mailDomain) return `https://${mailDomain}`;
        return `http://${hostIp || window.location.hostname}:8082`;
    };

    return (
        <div className="panel-container">
            <div className="panel-header">
                <div>
                    <p className="panel-subtitle">
                        {mailDomain
                            ? <>Домен почты: <strong style={{ fontFamily: 'var(--font-mono)' }}>{mailDomain}</strong> — ящики создаются на нём</>
                            : <>Свой домен не привязан — ящики создаются на локальном <span style={{ fontFamily: 'var(--font-mono)' }}>aegis.local</span>, письма наружу с него не уйдут. Привязать: <span style={{ fontFamily: 'var(--font-mono)' }}>scripts/add-domain.sh</span></>}
                    </p>
                </div>
                <div style={{ display: 'flex', gap: '12px' }}>
                    <a
                        href={webmailUrl()}
                        target="_blank"
                        rel="noopener noreferrer" 
                        className="btn btn-secondary"
                        style={{ display: 'flex', alignItems: 'center', gap: '8px', textDecoration: 'none' }}
                    >
                        <Mail size={16} /> Войти в Webmail
                    </a>
                    <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
                        <Plus size={16} /> Создать ящик
                    </button>
                </div>
            </div>

            {error && <div className="alert alert-danger">{error}</div>}

            {loading ? (
                <div style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}>
                    <div className="spinner"></div>
                </div>
            ) : (
                <div className="table-responsive">
                    <table className="table">
                        <thead>
                            <tr>
                                <th>Адрес ящика</th>
                                <th>Размер квоты</th>
                                <th>Дата создания</th>
                                <th>Владелец</th>
                                <th>Статус</th>
                                <th>Действия</th>
                            </tr>
                        </thead>
                        <tbody>
                            {mailboxes.map(m => (
                                <tr key={m.id}>
                                    <td style={{ fontWeight: 'bold', color: 'var(--accent-primary)' }}>{m.email}</td>
                                    <td>{m.quota_mb} МБ</td>
                                    <td>{m.created_at}</td>
                                    <td>{m.owner_username}</td>
                                    <td>
                                        <span className="status-badge status-active">
                                            Активен
                                        </span>
                                    </td>
                                    <td>
                                        <div style={{ display: 'flex', gap: '8px' }}>
                                            <a 
                                                href={`http://${getMailServerIP()}:8082/?_user=${m.email}`} 
                                                target="_blank" 
                                                rel="noopener noreferrer" 
                                                className="btn btn-secondary btn-sm"
                                                style={{ display: 'flex', alignItems: 'center', gap: '4px', textDecoration: 'none', fontSize: '0.75rem' }}
                                            >
                                                <Mail size={12} /> Войти
                                            </a>
                                            <button 
                                                className="btn btn-danger btn-sm" 
                                                onClick={() => handleDeleteMailbox(m.id)}
                                                style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem' }}
                                            >
                                                <Trash2 size={12} /> Удалить
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                            {mailboxes.length === 0 && (
                                <tr>
                                    <td colSpan="6" style={{ textAlign: 'center', padding: '30px', color: 'var(--text-muted)' }}>
                                        <Mail size={32} style={{ marginBottom: '8px', opacity: 0.5 }} />
                                        <div>Нет активных почтовых ящиков. Создайте первый!</div>
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            )}

            <div className="glass-card" style={{ marginTop: '30px', padding: '20px' }}>
                <h3 style={{ margin: '0 0 15px 0', fontSize: '1.1rem', color: 'var(--text-heading)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Info size={18} color="var(--accent-primary)" /> Настройки подключения почтовых клиентов
                </h3>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '20px', fontSize: '0.85rem' }}>
                    <div style={{ background: 'var(--bg-surface)', padding: '15px', borderRadius: '8px' }}>
                        <h4 style={{ margin: '0 0 10px 0', color: 'var(--text-primary)' }}>Протокол IMAP (Получение писем)</h4>
                        <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            <li><strong>Сервер:</strong> <span style={{ fontFamily: 'monospace' }}>{getMailServerIP()}</span></li>
                            <li><strong>Порт (Без SSL):</strong> <span style={{ fontFamily: 'monospace' }}>143</span></li>
                            <li><strong>Порт (SSL/TLS):</strong> <span style={{ fontFamily: 'monospace' }}>993</span></li>
                        </ul>
                    </div>

                    <div style={{ background: 'var(--bg-surface)', padding: '15px', borderRadius: '8px' }}>
                        <h4 style={{ margin: '0 0 10px 0', color: 'var(--text-primary)' }}>Протокол SMTP (Отправка писем)</h4>
                        <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            <li><strong>Сервер:</strong> <span style={{ fontFamily: 'monospace' }}>{getMailServerIP()}</span></li>
                            <li><strong>Порт (Без SSL):</strong> <span style={{ fontFamily: 'monospace' }}>25</span></li>
                            <li><strong>Порт (STARTTLS):</strong> <span style={{ fontFamily: 'monospace' }}>587</span></li>
                        </ul>
                    </div>

                    <div style={{ background: 'var(--bg-surface)', padding: '15px', borderRadius: '8px' }}>
                        <h4 style={{ margin: '0 0 10px 0', color: 'var(--text-primary)' }}>Сервер (куда указывать DNS)</h4>
                        <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            <li><strong>IP хоста:</strong> <span style={{ fontFamily: 'monospace' }}>{hostIp || '—'}</span></li>
                            <li><strong>Вебмейл (Roundcube):</strong> <span style={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>{webmailUrl()}</span></li>
                            {mailDomain
                                ? <li className="text-muted" style={{ fontSize: '0.8rem' }}>MX-запись домена <span style={{ fontFamily: 'monospace' }}>{mailDomain}</span> должна указывать на этот IP, иначе входящие письма до сервера не дойдут.</li>
                                : <li className="text-muted" style={{ fontSize: '0.8rem' }}>Порты почты (25, 143, 587, 993) слушает сам хост по этому адресу.</li>}
                        </ul>
                    </div>

                    <div style={{ background: 'var(--bg-surface)', padding: '15px', borderRadius: '8px' }}>
                        <h4 style={{ margin: '0 0 10px 0', color: 'var(--text-primary)' }}>Авторизация</h4>
                        <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            <li><strong>Логин:</strong> Полный адрес ящика (например, <span style={{ fontFamily: 'monospace' }}>user@{mailDomain || 'aegis.local'}</span>)</li>
                            <li><strong>Пароль:</strong> Пароль, указанный при создании ящика</li>
                            <li><strong>Метод:</strong> Обычный пароль (Plain password)</li>
                        </ul>
                    </div>
                </div>
            </div>

            {showCreateModal && (
                <div className="slide-over-overlay" onClick={() => setShowCreateModal(false)}>
                    <div className="slide-over-content" onClick={e => e.stopPropagation()}>
                        <div className="slide-over-header">
                            <h2>Создание почтового ящика</h2>
                            <button className="btn-close" onClick={() => setShowCreateModal(false)} type="button">
                                <X size={18} />
                            </button>
                        </div>
                        <form onSubmit={handleCreateMailbox} style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                            <div className="slide-over-body">
                                <div className="input-group">
                                    <label className="input-label">Email адрес</label>
                                    <input 
                                        type="email" 
                                        className="form-control" 
                                        value={email} 
                                        onChange={e => setEmail(e.target.value)} 
                                        required
                                        placeholder={`Например, admin@${mailDomain || 'aegis.local'}`}
                                    />
                                    <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px' }}>
                                        {mailDomain
                                            ? <>Полный адрес, включая домен. Почтовый сервер настроен на <strong>{mailDomain}</strong> — ящики на других доменах письма отправлять не смогут.</>
                                            : <>Полный адрес, включая домен. Свой домен не привязан, поэтому сервер принимает только <strong>aegis.local</strong> (локально).</>}
                                    </span>
                                </div>

                                <div className="input-group">
                                    <label className="input-label">Пароль ящика</label>
                                    <input 
                                        type="password" 
                                        className="form-control" 
                                        value={password} 
                                        onChange={e => setPassword(e.target.value)} 
                                        required 
                                        placeholder="Сложный пароль"
                                    />
                                </div>
                            </div>

                            <div className="slide-over-actions">
                                <button type="button" className="btn btn-secondary" onClick={() => setShowCreateModal(false)} disabled={submitting}>
                                    Отмена
                                </button>
                                <button type="submit" className="btn btn-primary" disabled={submitting}>
                                    {submitting ? 'Создание...' : 'Создать'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}
