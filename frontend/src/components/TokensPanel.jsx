import React, { useState, useEffect } from 'react';
import { Key, Plus, Trash2, Copy, Check, X, AlertTriangle, Terminal, Clock } from 'lucide-react';
import Portal from './Portal';

export default function TokensPanel() {
    const [tokens, setTokens] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [showCreate, setShowCreate] = useState(false);
    const [name, setName] = useState('');
    const [expires, setExpires] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [newToken, setNewToken] = useState(null); // показывается один раз
    const [copied, setCopied] = useState(false);

    const headers = () => ({
        'Authorization': `Bearer ${localStorage.getItem('aegis_admin_token') || ''}`,
        'Content-Type': 'application/json',
    });

    const fetchTokens = async () => {
        try {
            const res = await fetch('/api/tokens', { headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка загрузки токенов');
            setTokens(await res.json());
            setError('');
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchTokens(); }, []);

    const handleCreate = async (e) => {
        e.preventDefault();
        setSubmitting(true);
        try {
            const body = { name: name.trim() };
            if (expires) body.expires_days = parseInt(expires);
            const res = await fetch('/api/tokens', { method: 'POST', headers: headers(), body: JSON.stringify(body) });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка создания токена');
            const data = await res.json();
            setNewToken(data);      // показываем токен один раз
            setShowCreate(false);
            setName(''); setExpires('');
            fetchTokens();
        } catch (e) {
            alert(`Ошибка: ${e.message}`);
        } finally {
            setSubmitting(false);
        }
    };

    const handleRevoke = async (id) => {
        if (!confirm('Отозвать токен? Все скрипты/CLI, использующие его, перестанут работать.')) return;
        try {
            const res = await fetch(`/api/tokens/${id}`, { method: 'DELETE', headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка отзыва');
            fetchTokens();
        } catch (e) {
            alert(`Ошибка: ${e.message}`);
        }
    };

    const fmt = (iso) => iso ? new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—';

    return (
        <div className="panel-container">
            <div className="panel-header">
                <div>
                    <p className="panel-subtitle">Для доступа к API из CLI, скриптов и Terraform без пароля</p>
                </div>
                <button className="btn btn-primary" onClick={() => setShowCreate(true)}><Plus size={16} /> Новый токен</button>
            </div>

            {error && <div className="alert alert-danger">{error}</div>}

            {newToken && (
                <div className="glass-card accent-top" style={{ marginBottom: '20px' }}>
                    <div className="section-title"><Check size={18} style={{ color: 'var(--status-success)' }} /> Токен «{newToken.name}» создан</div>
                    <div className="alert alert-danger" style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                        <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
                        <span>Скопируйте токен сейчас — он показывается <b>только один раз</b> и больше не будет доступен.</span>
                    </div>
                    <div className="copy-field" style={{ marginTop: '10px' }}>
                        <code style={{ fontFamily: 'var(--font-mono)' }}>{newToken.token}</code>
                        <button className="btn-icon" onClick={() => { navigator.clipboard.writeText(newToken.token); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
                            {copied ? <Check size={16} color="var(--status-success)" /> : <Copy size={16} />}
                        </button>
                    </div>
                    <div style={{ marginTop: '14px' }}>
                        <div className="text-muted" style={{ fontSize: '0.78rem', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}><Terminal size={14} /> Использование в CLI:</div>
                        <pre style={{ background: 'var(--bg-surface-hover)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: '12px', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', margin: 0, overflowX: 'auto' }}>{`aegis configure --url ${window.location.origin.replace(/:\d+$/, ':8000')} --token ${newToken.token}`}</pre>
                    </div>
                    <button className="btn btn-secondary" style={{ marginTop: '14px' }} onClick={() => setNewToken(null)}>Я сохранил токен</button>
                </div>
            )}

            {loading ? (
                <div style={{ display: 'flex', justifyContent: 'center', padding: '50px' }}><div className="spinner spinner-lg" /></div>
            ) : tokens.length === 0 ? (
                <div className="glass-card" style={{ textAlign: 'center', padding: '54px 20px' }}>
                    <Key size={44} style={{ color: 'var(--text-muted)', marginBottom: '12px' }} />
                    <h3 className="section-title" style={{ justifyContent: 'center' }}>Токенов пока нет</h3>
                    <p className="text-muted">Создайте токен, чтобы управлять хостингом из консоли или Terraform.</p>
                </div>
            ) : (
                <div className="table-responsive">
                    <table className="table">
                        <thead><tr><th>Имя</th><th>Префикс</th><th>Создан</th><th>Последнее использование</th><th>Истекает</th><th></th></tr></thead>
                        <tbody>
                            {tokens.map(t => (
                                <tr key={t.id}>
                                    <td style={{ fontWeight: 600 }}><span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}><Key size={14} /> {t.name}</span></td>
                                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{t.prefix}</td>
                                    <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{fmt(t.created_at)}</td>
                                    <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{t.last_used ? fmt(t.last_used) : 'ни разу'}</td>
                                    <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{t.expires_at ? fmt(t.expires_at) : 'без срока'}</td>
                                    <td><button className="btn btn-danger btn-sm" onClick={() => handleRevoke(t.id)}><Trash2 size={14} /> Отозвать</button></td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {showCreate && (
                <Portal>
                    <div className="modal-overlay" onClick={() => setShowCreate(false)}>
                        <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '440px' }}>
                            <div className="modal-header">
                                <h2>Новый API-токен</h2>
                                <button className="btn-close" onClick={() => setShowCreate(false)} type="button"><X size={18} /></button>
                            </div>
                            <form onSubmit={handleCreate}>
                                <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                    <div className="input-group" style={{ marginBottom: 0 }}>
                                        <label className="input-label">Имя токена</label>
                                        <input className="form-control" placeholder="например: ci-runner, terraform" value={name} onChange={e => setName(e.target.value)} required autoFocus />
                                    </div>
                                    <div className="input-group" style={{ marginBottom: 0 }}>
                                        <label className="input-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><Clock size={14} /> Срок жизни (дней, необязательно)</label>
                                        <input type="number" className="form-control" placeholder="без ограничения" value={expires} onChange={e => setExpires(e.target.value)} min="1" max="3650" />
                                    </div>
                                </div>
                                <div className="modal-actions">
                                    <button type="button" className="btn btn-secondary" onClick={() => setShowCreate(false)} disabled={submitting}>Отмена</button>
                                    <button type="submit" className="btn btn-primary" disabled={submitting || !name.trim()}>{submitting ? <span className="spinner" /> : <><Key size={14} /> Создать</>}</button>
                                </div>
                            </form>
                        </div>
                    </div>
                </Portal>
            )}
        </div>
    );
}
