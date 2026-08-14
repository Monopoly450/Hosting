import React, { useState, useEffect } from 'react';
import { ScrollText, RefreshCw, Search, User, Globe, AlertTriangle, CheckCircle2, ShieldCheck, X } from 'lucide-react';

export default function AuditPanel() {
    const [rows, setRows] = useState([]);
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [search, setSearch] = useState('');
    const [onlyFailed, setOnlyFailed] = useState(false);
    const [selectedRow, setSelectedRow] = useState(null);

    const headers = () => ({ 'Authorization': `Bearer ${localStorage.getItem('aegis_admin_token') || ''}` });

    const fetchAll = async () => {
        try {
            const params = new URLSearchParams();
            if (search.trim()) params.set('action', search.trim());
            if (onlyFailed) params.set('only_failed', 'true');
            const res = await fetch(`/api/audit?${params}`, { headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка загрузки журнала');
            setRows(await res.json());
            setError('');
            fetch('/api/audit/stats', { headers: headers() }).then(r => r.ok ? r.json() : null).then(s => s && setStats(s)).catch(() => {});
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchAll();
        const t = setInterval(fetchAll, 10000);
        return () => clearInterval(t);
    }, [onlyFailed]);

    const fmt = (iso) => {
        if (!iso) return '—';
        const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
        return d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
    };

    const Stat = ({ icon: Icon, label, value, danger }) => (
        <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <div className="connect-tile-icon" style={{ width: '44px', height: '44px', flexShrink: 0, background: danger ? 'var(--status-danger-bg)' : undefined, color: danger ? 'var(--status-danger)' : undefined }}><Icon size={20} /></div>
            <div>
                <div style={{ fontSize: '1.5rem', fontWeight: 800, color: danger && value > 0 ? 'var(--status-danger)' : 'var(--text-heading)', lineHeight: 1.1 }}>{value ?? '—'}</div>
                <div className="text-muted" style={{ fontSize: '0.8rem' }}>{label}</div>
            </div>
        </div>
    );

    return (
        <div className="panel-container">
            <div className="panel-header">
                <div>
                    <p className="panel-subtitle">Кто, когда и с какого IP выполнял действия в системе</p>
                </div>
                <button className="btn btn-secondary" onClick={fetchAll}><RefreshCw size={15} /> Обновить</button>
            </div>

            {error && <div className="alert alert-danger">{error}</div>}

            <div className="grid-cols-4 stagger" style={{ marginBottom: '20px' }}>
                <Stat icon={ScrollText} label="Всего событий" value={stats?.total} />
                <Stat icon={AlertTriangle} label="Ошибок/отказов" value={stats?.failed} danger />
                <Stat icon={User} label="Пользователей" value={stats?.users} />
                <Stat icon={Globe} label="Уникальных IP" value={stats?.ips} />
            </div>

            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginBottom: '14px', alignItems: 'center' }}>
                <div style={{ position: 'relative', flex: 1, minWidth: '220px' }}>
                    <Search size={15} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                    <input className="form-control" style={{ paddingLeft: '36px' }} placeholder="Поиск по действию (напр. «удаление», «вход»)"
                        value={search} onChange={e => setSearch(e.target.value)} onKeyDown={e => e.key === 'Enter' && fetchAll()} />
                </div>
                <button className={`btn ${onlyFailed ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setOnlyFailed(v => !v)}>
                    <AlertTriangle size={15} /> Только отказы
                </button>
                <button className="btn btn-secondary" onClick={fetchAll}><Search size={15} /> Найти</button>
            </div>

            {loading ? (
                <div style={{ display: 'flex', justifyContent: 'center', padding: '50px' }}><div className="spinner spinner-lg" /></div>
            ) : (
                <div className="table-responsive">
                    <table className="table">
                        <thead><tr><th>Время</th><th>Пользователь</th><th>IP</th><th>Действие</th><th>Результат</th></tr></thead>
                        <tbody>
                            {rows.map(r => (
                                <tr key={r.id} onClick={() => setSelectedRow(r)} style={{ cursor: 'pointer' }}>
                                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{fmt(r.timestamp)}</td>
                                    <td><span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', fontWeight: 600 }}><User size={13} /> {r.username}</span></td>
                                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{r.ip}</td>
                                    <td>{r.action}</td>
                                    <td>
                                        {r.success
                                            ? <span className="badge badge-success"><CheckCircle2 size={12} /> {r.status_code}</span>
                                            : <span className="badge badge-danger"><AlertTriangle size={12} /> {r.status_code}</span>}
                                    </td>
                                </tr>
                            ))}
                            {rows.length === 0 && (
                                <tr><td colSpan="5" style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                                    <ShieldCheck size={32} style={{ opacity: 0.5, marginBottom: '8px' }} /><div>Событий пока нет</div>
                                </td></tr>
                            )}
                        </tbody>
                    </table>
                </div>
            )}

            {selectedRow && (
                <div className="modal-overlay" onClick={() => setSelectedRow(null)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '500px' }}>
                        <div className="modal-header">
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <ScrollText size={20} style={{ color: 'var(--accent)' }} />
                                <h2 style={{ fontSize: '1.25rem', fontWeight: 700 }}>Информация о действии</h2>
                            </div>
                            <button className="btn-icon" onClick={() => setSelectedRow(null)}><X size={20} /></button>
                        </div>
                        <div style={{ padding: '0 24px 20px 24px' }}>
                            <div className="glass-card" style={{ padding: '16px', background: 'rgba(255, 255, 255, 0.02)', display: 'flex', flexDirection: 'column', gap: '14px', border: '1px solid var(--border-color)' }}>
                                <div>
                                    <span className="text-muted" style={{ fontSize: '0.78rem', display: 'block', marginBottom: '3px' }}>Действие</span>
                                    <span style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-heading)' }}>{selectedRow.action}</span>
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
                                    <div>
                                        <span className="text-muted" style={{ fontSize: '0.78rem', display: 'block', marginBottom: '3px' }}>Пользователь</span>
                                        <span style={{ fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: '5px' }}><User size={13} /> {selectedRow.username}</span>
                                    </div>
                                    <div>
                                        <span className="text-muted" style={{ fontSize: '0.78rem', display: 'block', marginBottom: '3px' }}>IP-адрес</span>
                                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.85rem' }}><Globe size={13} style={{ verticalAlign: 'middle', marginRight: '4px' }} /> {selectedRow.ip}</span>
                                    </div>
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
                                    <div>
                                        <span className="text-muted" style={{ fontSize: '0.78rem', display: 'block', marginBottom: '3px' }}>Метод запроса</span>
                                        <span className="badge" style={{ textTransform: 'uppercase', padding: '4px 8px', fontSize: '0.75rem', fontWeight: 700, background: 'var(--border-color)', color: 'var(--text-secondary)' }}>{selectedRow.method}</span>
                                    </div>
                                    <div>
                                        <span className="text-muted" style={{ fontSize: '0.78rem', display: 'block', marginBottom: '3px' }}>Код ответа</span>
                                        {selectedRow.success ? (
                                            <span className="badge badge-success" style={{ display: 'inline-flex', padding: '4px 8px' }}><CheckCircle2 size={12} /> {selectedRow.status_code} (OK)</span>
                                        ) : (
                                            <span className="badge badge-danger" style={{ display: 'inline-flex', padding: '4px 8px' }}><AlertTriangle size={12} /> {selectedRow.status_code} (Ошибка)</span>
                                        )}
                                    </div>
                                </div>
                                <div>
                                    <span className="text-muted" style={{ fontSize: '0.78rem', display: 'block', marginBottom: '3px' }}>API Путь</span>
                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', wordBreak: 'break-all', display: 'block', padding: '8px', background: 'rgba(0,0,0,0.15)', borderRadius: '6px' }}>{selectedRow.path}</span>
                                </div>
                                <div>
                                    <span className="text-muted" style={{ fontSize: '0.78rem', display: 'block', marginBottom: '3px' }}>Время события</span>
                                    <span style={{ fontSize: '0.85rem' }}>{fmt(selectedRow.timestamp)}</span>
                                </div>
                            </div>
                        </div>
                        <div className="modal-actions">
                            <button type="button" className="btn btn-secondary" onClick={() => setSelectedRow(null)}>Закрыть</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
