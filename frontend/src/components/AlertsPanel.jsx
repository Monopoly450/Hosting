import React, { useState, useEffect } from 'react';
import { Bell, BellRing, Plus, Trash2, X, Send, Power, Server, HardDrive, Webhook, MessageCircle, AlertTriangle, CheckCircle2 } from 'lucide-react';
import CustomSelect from './CustomSelect';

const METRICS = {
    vm: [
        { value: 'status', label: 'Доступность (ВМ упала)' },
        { value: 'cpu_percent', label: 'Загрузка CPU, %' },
        { value: 'memory_percent', label: 'Загрузка RAM, %' },
    ],
    host: [
        { value: 'cpu_percent', label: 'Загрузка CPU хоста, %' },
        { value: 'memory_percent', label: 'Загрузка RAM хоста, %' },
    ],
};
const METRIC_LABEL = { status: 'Доступность', cpu_percent: 'CPU', memory_percent: 'RAM' };

export default function AlertsPanel() {
    const isAdmin = localStorage.getItem('aegis_role') === 'admin';
    const [channels, setChannels] = useState([]);
    const [rules, setRules] = useState([]);
    const [vms, setVms] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [showChannel, setShowChannel] = useState(false);
    const [showRule, setShowRule] = useState(false);
    const [busy, setBusy] = useState(false);

    // форма канала
    const [chName, setChName] = useState('');
    const [chType, setChType] = useState('webhook');
    const [chUrl, setChUrl] = useState('');
    const [chToken, setChToken] = useState('');
    const [chChat, setChChat] = useState('');

    // форма правила
    const [rName, setRName] = useState('');
    const [rTargetType, setRTargetType] = useState('vm');
    const [rTarget, setRTarget] = useState('');
    const [rMetric, setRMetric] = useState('status');
    const [rComparator, setRComparator] = useState('>');
    const [rThreshold, setRThreshold] = useState(80);
    const [rChannel, setRChannel] = useState('');

    const headers = () => ({
        'Authorization': `Bearer ${localStorage.getItem('aegis_admin_token') || ''}`,
        'Content-Type': 'application/json',
    });

    const fetchAll = async () => {
        try {
            const [cRes, rRes, vRes] = await Promise.all([
                fetch('/api/alerts/channels', { headers: headers() }),
                fetch('/api/alerts/rules', { headers: headers() }),
                fetch('/api/vms', { headers: headers() }),
            ]);
            if (!cRes.ok) throw new Error((await cRes.json()).detail || 'Ошибка загрузки');
            setChannels(await cRes.json());
            setRules(rRes.ok ? await rRes.json() : []);
            setVms(vRes.ok ? await vRes.json() : []);
            setError('');
        } catch (e) { setError(e.message); } finally { setLoading(false); }
    };

    useEffect(() => { fetchAll(); }, []);

    // ------- каналы -------
    const createChannel = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            const config = chType === 'webhook' ? { url: chUrl.trim() } : { bot_token: chToken.trim(), chat_id: chChat.trim() };
            const res = await fetch('/api/alerts/channels', { method: 'POST', headers: headers(), body: JSON.stringify({ name: chName.trim(), type: chType, config }) });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка');
            setShowChannel(false); setChName(''); setChUrl(''); setChToken(''); setChChat('');
            fetchAll();
        } catch (e) { alert(`Ошибка: ${e.message}`); } finally { setBusy(false); }
    };

    const testChannel = async (id) => {
        try {
            const res = await fetch(`/api/alerts/channels/${id}/test`, { method: 'POST', headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка');
            alert('Тестовое уведомление отправлено.');
        } catch (e) { alert(`Не доставлено: ${e.message}`); }
    };

    const deleteChannel = async (id) => {
        if (!confirm('Удалить канал? Правила, использующие его, останутся без уведомлений.')) return;
        try {
            const res = await fetch(`/api/alerts/channels/${id}`, { method: 'DELETE', headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка');
            fetchAll();
        } catch (e) { alert(`Ошибка: ${e.message}`); }
    };

    // ------- правила -------
    const createRule = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            const body = {
                name: rName.trim(), target_type: rTargetType, metric: rMetric,
                comparator: rComparator, channel_id: rChannel ? parseInt(rChannel) : null,
            };
            if (rTargetType === 'vm') body.target_id = parseInt(rTarget);
            if (rMetric !== 'status') body.threshold = parseFloat(rThreshold);
            const res = await fetch('/api/alerts/rules', { method: 'POST', headers: headers(), body: JSON.stringify(body) });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка');
            setShowRule(false); setRName(''); setRTarget('');
            fetchAll();
        } catch (e) { alert(`Ошибка: ${e.message}`); } finally { setBusy(false); }
    };

    const toggleRule = async (r) => {
        try {
            const res = await fetch(`/api/alerts/rules/${r.id}`, { method: 'PUT', headers: headers(), body: JSON.stringify({ enabled: !r.enabled }) });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка');
            fetchAll();
        } catch (e) { alert(`Ошибка: ${e.message}`); }
    };

    const deleteRule = async (id) => {
        if (!confirm('Удалить правило алерта?')) return;
        try {
            const res = await fetch(`/api/alerts/rules/${id}`, { method: 'DELETE', headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка');
            fetchAll();
        } catch (e) { alert(`Ошибка: ${e.message}`); }
    };

    const condText = (r) => r.metric === 'status'
        ? 'недоступность (не Running)'
        : `${METRIC_LABEL[r.metric]} ${r.comparator} ${r.threshold}%`;

    const stateBadge = (r) => {
        if (!r.enabled) return <span className="badge" style={{ opacity: 0.6 }}>выкл</span>;
        if (r.state === 'firing') return <span className="badge" style={{ background: 'rgba(229,72,77,0.15)', color: '#e5484d', display: 'inline-flex', alignItems: 'center', gap: '4px' }}><BellRing size={12} /> сработал</span>;
        return <span className="badge" style={{ background: 'rgba(48,164,108,0.15)', color: 'var(--status-success)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}><CheckCircle2 size={12} /> норма</span>;
    };

    const availableMetrics = METRICS[rTargetType] || [];
    // если сменили тип цели и текущая метрика недоступна — сбросить
    useEffect(() => {
        if (!availableMetrics.find(m => m.value === rMetric)) setRMetric(availableMetrics[0]?.value || 'cpu_percent');
    }, [rTargetType]);

    return (
        <div className="panel-container">
            <div className="panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '18px' }}>
                <div>
                    <h2 className="panel-title">Алерты и уведомления</h2>
                    <p className="panel-subtitle">Оповещения о падении ВМ и превышении нагрузки — в Telegram или на webhook</p>
                </div>
            </div>

            {error && <div className="alert alert-danger">{error}</div>}

            {loading ? (
                <div style={{ display: 'flex', justifyContent: 'center', padding: '50px' }}><div className="spinner spinner-lg" /></div>
            ) : (
                <>
                    {/* Каналы */}
                    <div className="glass-card" style={{ marginBottom: '20px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                            <div className="section-title" style={{ margin: 0 }}><Send size={16} /> Каналы уведомлений</div>
                            <button className="btn btn-secondary btn-sm" onClick={() => setShowChannel(true)}><Plus size={14} /> Добавить</button>
                        </div>
                        {channels.length === 0 ? (
                            <p className="text-muted" style={{ fontSize: '0.85rem' }}>Нет каналов. Добавьте Telegram или webhook, чтобы получать уведомления.</p>
                        ) : (
                            <div className="table-responsive">
                                <table className="table">
                                    <thead><tr><th>Имя</th><th>Тип</th><th>Куда</th><th></th></tr></thead>
                                    <tbody>
                                        {channels.map(c => (
                                            <tr key={c.id}>
                                                <td style={{ fontWeight: 600 }}>{c.name}</td>
                                                <td><span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>{c.type === 'telegram' ? <MessageCircle size={14} /> : <Webhook size={14} />}{c.type}</span></td>
                                                <td style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>{c.summary}</td>
                                                <td>
                                                    <div style={{ display: 'flex', gap: '6px', justifyContent: 'flex-end' }}>
                                                        <button className="btn-icon" title="Отправить тест" onClick={() => testChannel(c.id)}><Send size={14} /></button>
                                                        <button className="btn-icon" title="Удалить" onClick={() => deleteChannel(c.id)}><Trash2 size={14} style={{ color: '#e5484d' }} /></button>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>

                    {/* Правила */}
                    <div className="glass-card">
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                            <div className="section-title" style={{ margin: 0 }}><Bell size={16} /> Правила</div>
                            <button className="btn btn-primary btn-sm" onClick={() => setShowRule(true)}><Plus size={14} /> Новое правило</button>
                        </div>
                        {rules.length === 0 ? (
                            <div style={{ textAlign: 'center', padding: '30px 20px' }}>
                                <Bell size={38} style={{ color: 'var(--text-muted)', marginBottom: '10px' }} />
                                <p className="text-muted">Правил пока нет. Например: «ВМ упала» или «CPU хоста &gt; 90%».</p>
                            </div>
                        ) : (
                            <div className="table-responsive">
                                <table className="table">
                                    <thead><tr><th>Имя</th><th>Объект</th><th>Условие</th><th>Состояние</th><th>Значение</th><th>Канал</th><th></th></tr></thead>
                                    <tbody>
                                        {rules.map(r => (
                                            <tr key={r.id} style={{ opacity: r.enabled ? 1 : 0.55 }}>
                                                <td style={{ fontWeight: 600 }}>{r.name}</td>
                                                <td><span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>{r.target_type === 'host' ? <HardDrive size={14} /> : <Server size={14} />}{r.target_name}</span></td>
                                                <td style={{ fontSize: '0.82rem' }}>{condText(r)}</td>
                                                <td>{stateBadge(r)}</td>
                                                <td style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>{r.last_error ? <span title={r.last_error} style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', color: 'var(--text-muted)' }}><AlertTriangle size={13} /> нет данных</span> : (r.last_value != null ? (r.metric === 'status' ? (r.last_value >= 1 ? 'Running' : 'down') : `${r.last_value}%`) : '—')}</td>
                                                <td style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>{channels.find(c => c.id === r.channel_id)?.name || '—'}</td>
                                                <td>
                                                    <div style={{ display: 'flex', gap: '6px', justifyContent: 'flex-end' }}>
                                                        <button className="btn-icon" title={r.enabled ? 'Выключить' : 'Включить'} onClick={() => toggleRule(r)}><Power size={15} style={{ color: r.enabled ? 'var(--status-success)' : 'var(--text-muted)' }} /></button>
                                                        <button className="btn-icon" title="Удалить" onClick={() => deleteRule(r.id)}><Trash2 size={14} style={{ color: '#e5484d' }} /></button>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                </>
            )}

            {/* Модалка канала */}
            {showChannel && (
                <div className="modal-overlay" onClick={() => setShowChannel(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '440px' }}>
                        <div className="modal-header"><h2>Новый канал уведомлений</h2><button className="btn-close" onClick={() => setShowChannel(false)} type="button"><X size={18} /></button></div>
                        <form onSubmit={createChannel}>
                            <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label">Название</label>
                                    <input className="form-control" value={chName} onChange={e => setChName(e.target.value)} placeholder="например: мой Telegram" required autoFocus />
                                </div>
                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label">Тип</label>
                                    <CustomSelect
                                        value={chType}
                                        onChange={e => setChType(e.target.value)}
                                        options={[
                                            { value: 'webhook', label: 'Webhook' },
                                            { value: 'telegram', label: 'Telegram' },
                                        ]}
                                    />
                                </div>
                                {chType === 'webhook' ? (
                                    <div className="input-group" style={{ marginBottom: 0 }}>
                                        <label className="input-label">URL</label>
                                        <input className="form-control" value={chUrl} onChange={e => setChUrl(e.target.value)} placeholder="https://example.com/hook" required />
                                    </div>
                                ) : (
                                    <>
                                        <div className="input-group" style={{ marginBottom: 0 }}>
                                            <label className="input-label">Bot token</label>
                                            <input className="form-control" value={chToken} onChange={e => setChToken(e.target.value)} placeholder="123456:ABC-DEF..." required />
                                        </div>
                                        <div className="input-group" style={{ marginBottom: 0 }}>
                                            <label className="input-label">Chat ID</label>
                                            <input className="form-control" value={chChat} onChange={e => setChChat(e.target.value)} placeholder="напр. 123456789" required />
                                        </div>
                                    </>
                                )}
                            </div>
                            <div className="modal-actions">
                                <button type="button" className="btn btn-secondary" onClick={() => setShowChannel(false)} disabled={busy}>Отмена</button>
                                <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? <span className="spinner" /> : 'Создать'}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Модалка правила */}
            {showRule && (
                <div className="modal-overlay" onClick={() => setShowRule(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '480px' }}>
                        <div className="modal-header"><h2>Новое правило алерта</h2><button className="btn-close" onClick={() => setShowRule(false)} type="button"><X size={18} /></button></div>
                        <form onSubmit={createRule}>
                            <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label">Имя правила</label>
                                    <input className="form-control" value={rName} onChange={e => setRName(e.target.value)} placeholder="например: web-1 упала" required autoFocus />
                                </div>
                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label">Объект</label>
                                    <CustomSelect
                                        value={rTargetType}
                                        onChange={e => setRTargetType(e.target.value)}
                                        options={[
                                            { value: 'vm', label: 'Виртуальная машина' },
                                            ...(isAdmin ? [{ value: 'host', label: 'Хост (сервер целиком)' }] : []),
                                        ]}
                                    />
                                </div>
                                {rTargetType === 'vm' && (
                                    <div className="input-group" style={{ marginBottom: 0 }}>
                                        <label className="input-label">Виртуальная машина</label>
                                        <CustomSelect
                                            value={rTarget}
                                            onChange={e => setRTarget(e.target.value)}
                                            placeholder="— выберите ВМ —"
                                            options={vms.filter(v => v.id).map(v => ({ value: v.id, label: v.name }))}
                                        />
                                    </div>
                                )}
                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label">Метрика</label>
                                    <CustomSelect
                                        value={rMetric}
                                        onChange={e => setRMetric(e.target.value)}
                                        options={availableMetrics}
                                    />
                                </div>
                                {rMetric !== 'status' && (
                                    <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
                                        <div className="input-group" style={{ marginBottom: 0, width: '110px' }}>
                                            <label className="input-label">Условие</label>
                                            <CustomSelect
                                                value={rComparator}
                                                onChange={e => setRComparator(e.target.value)}
                                                options={[
                                                    { value: '>', label: 'больше >' },
                                                    { value: '<', label: 'меньше <' },
                                                ]}
                                            />
                                        </div>
                                        <div className="input-group" style={{ marginBottom: 0, flex: 1 }}>
                                            <label className="input-label">Порог, %</label>
                                            <input type="number" className="form-control" value={rThreshold} onChange={e => setRThreshold(e.target.value)} min="0" max="100" />
                                        </div>
                                    </div>
                                )}
                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label">Канал уведомления</label>
                                    <CustomSelect
                                        value={rChannel}
                                        onChange={e => setRChannel(e.target.value)}
                                        placeholder="Без уведомления (только статус)"
                                        options={[
                                            { value: '', label: 'Без уведомления (только статус)' },
                                            ...channels.map(c => ({ value: c.id, label: `${c.name} (${c.type})` })),
                                        ]}
                                    />
                                </div>
                            </div>
                            <div className="modal-actions">
                                <button type="button" className="btn btn-secondary" onClick={() => setShowRule(false)} disabled={busy}>Отмена</button>
                                <button type="submit" className="btn btn-primary" disabled={busy || !rName.trim() || (rTargetType === 'vm' && !rTarget)}>{busy ? <span className="spinner" /> : 'Создать'}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}
