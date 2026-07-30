import React, { useState, useEffect } from 'react';
import { Globe, Plus, Trash2, X, ShieldCheck, RefreshCw, Copy, Check, AlertTriangle, ExternalLink } from 'lucide-react';

export default function DomainsPanel() {
    const isAdmin = localStorage.getItem('aegis_role') === 'admin';
    const [status, setStatus] = useState(null);
    const [domains, setDomains] = useState([]);
    const [deployments, setDeployments] = useState([]);
    const [vms, setVms] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [showAdd, setShowAdd] = useState(false);
    const [busy, setBusy] = useState(false);
    const [verifying, setVerifying] = useState(null);
    const [copied, setCopied] = useState('');

    // форма
    const [name, setName] = useState('');
    const [targetType, setTargetType] = useState('deployment');
    const [target, setTarget] = useState('');
    const [port, setPort] = useState('');

    const headers = () => ({
        'Authorization': `Bearer ${localStorage.getItem('aegis_admin_token') || ''}`,
        'Content-Type': 'application/json',
    });

    const fetchAll = async () => {
        try {
            const [sRes, dRes, depRes, vRes] = await Promise.all([
                fetch('/api/domains/status', { headers: headers() }),
                fetch('/api/domains', { headers: headers() }),
                fetch('/api/deployments', { headers: headers() }),
                fetch('/api/vms', { headers: headers() }),
            ]);
            setStatus(sRes.ok ? await sRes.json() : null);
            if (!dRes.ok) throw new Error((await dRes.json()).detail || 'Ошибка загрузки доменов');
            setDomains(await dRes.json());
            setDeployments(depRes.ok ? await depRes.json() : []);
            setVms(vRes.ok ? await vRes.json() : []);
            setError('');
        } catch (e) { setError(e.message); } finally { setLoading(false); }
    };

    useEffect(() => { fetchAll(); }, []);

    const addDomain = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            const body = { domain: name.trim(), target_type: targetType, target_id: parseInt(target) };
            if (port) body.target_port = parseInt(port);
            const res = await fetch('/api/domains', { method: 'POST', headers: headers(), body: JSON.stringify(body) });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка');
            setShowAdd(false); setName(''); setTarget(''); setPort('');
            fetchAll();
        } catch (e) { alert(`Ошибка: ${e.message}`); } finally { setBusy(false); }
    };

    const verify = async (id) => {
        setVerifying(id);
        try {
            const res = await fetch(`/api/domains/${id}/verify`, { method: 'POST', headers: headers() });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Ошибка');
            if (!data.ownership_ok) {
                alert(`Владение доменом не подтверждено: ${data.ownership_detail}\n\n`
                    + `Создайте TXT-запись:\n${data.challenge_record}\nсо значением:\n${data.verification_token}\n\n`
                    + `Затем повторите проверку (изменения DNS могут идти до нескольких часов).`);
            } else if (!data.dns_ok) {
                alert(`DNS ещё не готов: ${data.detail}\n\nСоздайте A-запись на ${data.expected_ip} и повторите.`);
            }
            fetchAll();
        } catch (e) { alert(`Ошибка: ${e.message}`); } finally { setVerifying(null); }
    };

    const remove = async (id) => {
        if (!confirm('Удалить домен? Сертификат перестанет обновляться, маршрут будет убран.')) return;
        try {
            const res = await fetch(`/api/domains/${id}`, { method: 'DELETE', headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка');
            fetchAll();
        } catch (e) { alert(`Ошибка: ${e.message}`); }
    };

    const reapply = async () => {
        setBusy(true);
        try {
            const res = await fetch('/api/domains/reapply', { method: 'POST', headers: headers() });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Ошибка');
            alert(data.applied ? `Конфиг применён, сайтов: ${data.sites}` : `Не применён: ${data.reason}`);
            fetchAll();
        } catch (e) { alert(`Ошибка: ${e.message}`); } finally { setBusy(false); }
    };

    const copy = (v, k) => { navigator.clipboard.writeText(v); setCopied(k); setTimeout(() => setCopied(''), 1500); };

    const badge = (d) => {
        if (d.dns_ok && d.ownership_ok) return <span className="badge" style={{ background: 'rgba(48,164,108,0.15)', color: 'var(--status-success)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}><ShieldCheck size={12} /> активен (TLS)</span>;
        const text = !d.ownership_ok ? 'нужна TXT-запись' : 'ожидает A-запись';
        return <span className="badge" style={{ background: 'rgba(245,166,35,0.15)', color: '#f5a623', display: 'inline-flex', alignItems: 'center', gap: '4px' }}><AlertTriangle size={12} /> {text}</span>;
    };

    if (loading) return <div className="panel-container"><div style={{ display: 'flex', justifyContent: 'center', padding: '50px' }}><div className="spinner spinner-lg" /></div></div>;

    return (
        <div className="panel-container">
            <div className="panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '18px' }}>
                <div>
                    <h2 className="panel-title">Свои домены и TLS</h2>
                    <p className="panel-subtitle">Привяжите свой домен — сертификат Let's Encrypt выпустится автоматически</p>
                </div>
                <div style={{ display: 'flex', gap: '8px' }}>
                    {isAdmin && <button className="btn btn-secondary btn-sm" onClick={reapply} disabled={busy}><RefreshCw size={14} /> Переприменить</button>}
                    <button className="btn btn-primary btn-sm" onClick={() => setShowAdd(true)}><Plus size={14} /> Добавить домен</button>
                </div>
            </div>

            {error && <div className="alert alert-danger">{error}</div>}

            {/* Инструкция по DNS */}
            <div className="glass-card" style={{ marginBottom: '20px' }}>
                <div className="section-title"><Globe size={16} /> Как подключить домен</div>
                <p className="text-muted" style={{ fontSize: '0.85rem' }}>
                    Нужны <b>две записи</b>. TXT подтверждает, что домен принадлежит вам (без неё чужой домен
                    можно было бы увести на свою ВМ), A — направляет трафик на этот сервер.
                    После успешной проверки сертификат выпустится автоматически (порты 80 и 443 должны быть открыты снаружи).
                </p>
                <div className="copy-field">
                    <code style={{ fontFamily: 'var(--font-mono)' }}>A  @  →  {status?.host_ip || '—'}</code>
                    <button className="btn-icon" onClick={() => copy(status?.host_ip || '', 'ip')}>{copied === 'ip' ? <Check size={16} color="var(--status-success)" /> : <Copy size={16} />}</button>
                </div>
                <p className="text-muted" style={{ fontSize: '0.78rem', marginTop: '8px' }}>
                    TXT-запись для подтверждения владения индивидуальна для каждого домена — она показана в таблице ниже.
                </p>

                {status?.host_ip_is_private && (
                    <div className="alert alert-danger" style={{ marginTop: '12px', display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                        <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
                        <div style={{ fontSize: '0.84rem' }}>
                            <b>Адрес {status.host_ip} — локальный, из интернета он недоступен.</b>
                            <p style={{ margin: '6px 0 0' }}>
                                Let's Encrypt проверяет домен, обращаясь к порту 80 извне, поэтому сертификат
                                на такой адрес выпустить не получится, а неудачные попытки расходуют лимиты.
                            </p>
                            <p style={{ margin: '6px 0 0' }}>
                                Если у сервера есть «белый» IP за NAT: пропишите его в переменной
                                <code style={{ margin: '0 4px' }}>AEGIS_HOST_IP</code> и настройте на роутере
                                проброс портов 80 и 443 на этот сервер. Тогда A-запись нужно указывать
                                на публичный адрес.
                            </p>
                            <p style={{ margin: '6px 0 0' }}>
                                Без публичного адреса домены и автоматический TLS работать не будут —
                                приложения остаются доступными по IP и порту.
                            </p>
                        </div>
                    </div>
                )}
                {status && !status.running && (
                    <div className="alert alert-danger" style={{ marginTop: '10px', display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                        <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
                        <span>{status.docker ? 'Прокси Caddy ещё не запущен — он поднимется при первой успешной проверке домена.' : 'Docker на хосте недоступен, прокси запустить нельзя.'}</span>
                    </div>
                )}
                {status && !status.acme_email && (
                    <p className="text-muted" style={{ fontSize: '0.76rem', marginTop: '8px' }}>
                        Совет: задайте переменную окружения <code>ACME_EMAIL</code> — Let's Encrypt будет присылать уведомления об истечении сертификатов.
                    </p>
                )}
            </div>

            {domains.length === 0 ? (
                <div className="glass-card" style={{ textAlign: 'center', padding: '48px 20px' }}>
                    <Globe size={44} style={{ color: 'var(--text-muted)', marginBottom: '12px' }} />
                    <h3 className="section-title" style={{ justifyContent: 'center' }}>Доменов пока нет</h3>
                    <p className="text-muted">Добавьте свой домен и направьте его на приложение или ВМ.</p>
                </div>
            ) : (
                <div className="table-responsive">
                    <table className="table">
                        <thead><tr><th>Домен</th><th>Куда ведёт</th><th>Порт</th><th>Статус</th><th></th></tr></thead>
                        <tbody>
                            {domains.map(d => (
                                <tr key={d.id}>
                                    <td style={{ fontWeight: 600 }}>
                                        {d.dns_ok
                                            ? <a href={d.url} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}>{d.domain} <ExternalLink size={12} /></a>
                                            : d.domain}
                                    </td>
                                    <td style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                                        {d.target_type === 'deployment'
                                            ? (deployments.find(x => x.id === d.target_id)?.name || `деплой #${d.target_id}`)
                                            : (vms.find(x => x.id === d.target_id)?.name || `ВМ #${d.target_id}`)}
                                    </td>
                                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.82rem' }}>{d.target_port}</td>
                                    <td>
                                        {badge(d)}
                                        {!d.ownership_ok && d.verification_token && (
                                            <div style={{ marginTop: '6px' }}>
                                                <div className="text-muted" style={{ fontSize: '0.7rem' }}>TXT {d.challenge_record}</div>
                                                <div className="copy-field" style={{ marginTop: '2px' }}>
                                                    <code style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem' }}>{d.verification_token}</code>
                                                    <button className="btn-icon" onClick={() => copy(d.verification_token, `t${d.id}`)}>{copied === `t${d.id}` ? <Check size={14} color="var(--status-success)" /> : <Copy size={14} />}</button>
                                                </div>
                                            </div>
                                        )}
                                        {d.last_error && <div className="text-muted" style={{ fontSize: '0.72rem', marginTop: '4px' }} title={d.last_error}>{d.last_error}</div>}
                                    </td>
                                    <td>
                                        <div style={{ display: 'flex', gap: '6px', justifyContent: 'flex-end' }}>
                                            <button className="btn btn-secondary btn-sm" onClick={() => verify(d.id)} disabled={verifying === d.id}>
                                                {verifying === d.id ? <span className="spinner" /> : <><ShieldCheck size={13} /> Проверить</>}
                                            </button>
                                            <button className="btn-icon" title="Удалить" onClick={() => remove(d.id)}><Trash2 size={14} style={{ color: '#e5484d' }} /></button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {showAdd && (
                <div className="modal-overlay" onClick={() => setShowAdd(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '460px' }}>
                        <div className="modal-header"><h2>Добавить домен</h2><button className="btn-close" onClick={() => setShowAdd(false)} type="button"><X size={18} /></button></div>
                        <form onSubmit={addDomain}>
                            <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label">Домен</label>
                                    <input className="form-control" value={name} onChange={e => setName(e.target.value)} placeholder="app.example.com" required autoFocus />
                                </div>
                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label">Направить на</label>
                                    <select className="form-control" value={targetType} onChange={e => { setTargetType(e.target.value); setTarget(''); }}>
                                        <option value="deployment">Приложение (деплой)</option>
                                        <option value="vm">Виртуальную машину</option>
                                    </select>
                                </div>
                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label">{targetType === 'deployment' ? 'Деплой' : 'Виртуальная машина'}</label>
                                    <select className="form-control" value={target} onChange={e => setTarget(e.target.value)} required>
                                        <option value="">— выберите —</option>
                                        {targetType === 'deployment'
                                            ? deployments.map(x => <option key={x.id} value={x.id}>{x.name} (порт {x.app_port})</option>)
                                            : vms.filter(v => v.id).map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
                                    </select>
                                </div>
                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label">Внутренний порт {targetType === 'deployment' && <span className="text-muted">(по умолчанию — порт деплоя)</span>}</label>
                                    <input type="number" className="form-control" value={port} onChange={e => setPort(e.target.value)} placeholder={targetType === 'deployment' ? 'авто' : 'например 8080'} min="1" max="65535" required={targetType === 'vm'} />
                                </div>
                            </div>
                            <div className="modal-actions">
                                <button type="button" className="btn btn-secondary" onClick={() => setShowAdd(false)} disabled={busy}>Отмена</button>
                                <button type="submit" className="btn btn-primary" disabled={busy || !name.trim() || !target}>{busy ? <span className="spinner" /> : 'Добавить'}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}
