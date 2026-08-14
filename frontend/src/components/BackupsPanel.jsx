import React, { useState, useEffect } from 'react';
import { CalendarClock, Plus, Trash2, X, Play, Server, Database, Clock, CheckCircle2, AlertTriangle, Power } from 'lucide-react';
import CustomSelect from './CustomSelect';

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const pad = (n) => String(n).padStart(2, '0');

export default function BackupsPanel() {
    const [schedules, setSchedules] = useState([]);
    const [vms, setVms] = useState([]);
    const [databases, setDatabases] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [showCreate, setShowCreate] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [runningId, setRunningId] = useState(null);

    // Поля формы
    const [name, setName] = useState('');
    const [target, setTarget] = useState('');      // "vm:3" | "database:5"
    const [frequency, setFrequency] = useState('daily');
    const [hour, setHour] = useState(3);
    const [minute, setMinute] = useState(0);
    const [weekday, setWeekday] = useState(0);
    const [retention, setRetention] = useState(7);

    const headers = () => ({
        'Authorization': `Bearer ${localStorage.getItem('aegis_admin_token') || ''}`,
        'Content-Type': 'application/json',
    });

    const fetchAll = async () => {
        try {
            const [sRes, vRes, dRes] = await Promise.all([
                fetch('/api/backup-schedules', { headers: headers() }),
                fetch('/api/vms', { headers: headers() }),
                fetch('/api/databases', { headers: headers() }),
            ]);
            if (!sRes.ok) throw new Error((await sRes.json()).detail || 'Ошибка загрузки расписаний');
            setSchedules(await sRes.json());
            setVms(vRes.ok ? await vRes.json() : []);
            setDatabases(dRes.ok ? await dRes.json() : []);
            setError('');
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchAll(); }, []);

    const resetForm = () => {
        setName(''); setTarget(''); setFrequency('daily');
        setHour(3); setMinute(0); setWeekday(0); setRetention(7);
    };

    const handleCreate = async (e) => {
        e.preventDefault();
        if (!target) { alert('Выберите объект для бэкапа'); return; }
        const [target_type, target_id] = target.split(':');
        setSubmitting(true);
        try {
            const body = {
                name: name.trim(),
                target_type,
                target_id: parseInt(target_id),
                frequency,
                hour: parseInt(hour),
                minute: parseInt(minute),
                retention: parseInt(retention),
            };
            if (frequency === 'weekly') body.weekday = parseInt(weekday);
            const res = await fetch('/api/backup-schedules', { method: 'POST', headers: headers(), body: JSON.stringify(body) });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка создания расписания');
            setShowCreate(false); resetForm(); fetchAll();
        } catch (e) {
            alert(`Ошибка: ${e.message}`);
        } finally {
            setSubmitting(false);
        }
    };

    const toggleEnabled = async (s) => {
        try {
            const res = await fetch(`/api/backup-schedules/${s.id}`, {
                method: 'PUT', headers: headers(), body: JSON.stringify({ enabled: !s.enabled }),
            });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка');
            fetchAll();
        } catch (e) { alert(`Ошибка: ${e.message}`); }
    };

    const handleRunNow = async (id) => {
        setRunningId(id);
        try {
            const res = await fetch(`/api/backup-schedules/${id}/run`, { method: 'POST', headers: headers() });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Ошибка запуска');
            fetchAll();
            if (data.last_status && data.last_status !== 'success') alert(`Бэкап завершился с ошибкой: ${data.last_status}`);
        } catch (e) {
            alert(`Ошибка: ${e.message}`);
        } finally {
            setRunningId(null);
        }
    };

    const handleDelete = async (id) => {
        if (!confirm('Удалить расписание? Уже созданные бэкапы останутся, новые создаваться не будут.')) return;
        try {
            const res = await fetch(`/api/backup-schedules/${id}`, { method: 'DELETE', headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка удаления');
            fetchAll();
        } catch (e) { alert(`Ошибка: ${e.message}`); }
    };

    const freqText = (s) => {
        if (s.frequency === 'hourly') return `Каждый час, в :${pad(s.minute)}`;
        if (s.frequency === 'weekly') return `Еженедельно, ${WEEKDAYS[s.weekday ?? 0]} в ${pad(s.hour)}:${pad(s.minute)}`;
        return `Ежедневно в ${pad(s.hour)}:${pad(s.minute)}`;
    };

    const fmt = (iso) => iso ? new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—';

    return (
        <div className="panel-container">
            <div className="panel-header">
                <div>
                    <p className="panel-subtitle">Автоматические резервные копии ВМ и баз данных по расписанию (время в UTC)</p>
                </div>
                <button className="btn btn-primary" onClick={() => setShowCreate(true)}><Plus size={16} /> Новое расписание</button>
            </div>

            {error && <div className="alert alert-danger">{error}</div>}

            {loading ? (
                <div style={{ display: 'flex', justifyContent: 'center', padding: '50px' }}><div className="spinner spinner-lg" /></div>
            ) : schedules.length === 0 ? (
                <div className="glass-card" style={{ textAlign: 'center', padding: '54px 20px' }}>
                    <CalendarClock size={44} style={{ color: 'var(--text-muted)', marginBottom: '12px' }} />
                    <h3 className="section-title" style={{ justifyContent: 'center' }}>Расписаний пока нет</h3>
                    <p className="text-muted">Создайте расписание, чтобы бэкапы ВМ и БД делались автоматически.</p>
                </div>
            ) : (
                <div className="table-responsive">
                    <table className="table">
                        <thead><tr><th>Имя</th><th>Объект</th><th>Расписание</th><th>Хранить</th><th>Следующий</th><th>Последний</th><th></th></tr></thead>
                        <tbody>
                            {schedules.map(s => (
                                <tr key={s.id} style={{ opacity: s.enabled ? 1 : 0.55 }}>
                                    <td style={{ fontWeight: 600 }}>{s.name}</td>
                                    <td>
                                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                                            {s.target_type === 'vm' ? <Server size={14} /> : <Database size={14} />}
                                            {s.target_name}
                                        </span>
                                    </td>
                                    <td style={{ fontSize: '0.82rem' }}>{freqText(s)}</td>
                                    <td>{s.retention} копий</td>
                                    <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{s.enabled ? fmt(s.next_run) : 'выключено'}</td>
                                    <td style={{ fontSize: '0.8rem' }}>
                                        {s.last_run ? (
                                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}>
                                                {(s.last_status === 'success')
                                                    ? <CheckCircle2 size={14} style={{ color: 'var(--status-success)' }} />
                                                    : <AlertTriangle size={14} style={{ color: 'var(--status-danger, #e5484d)' }} />}
                                                <span title={s.last_status || ''}>{fmt(s.last_run)}</span>
                                            </span>
                                        ) : <span className="text-muted">ни разу</span>}
                                    </td>
                                    <td>
                                        <div style={{ display: 'flex', gap: '6px', justifyContent: 'flex-end' }}>
                                            <button className="btn-icon" title={s.enabled ? 'Выключить' : 'Включить'} onClick={() => toggleEnabled(s)}>
                                                <Power size={14} style={{ color: s.enabled ? 'var(--status-success)' : 'var(--text-muted)' }} />
                                            </button>
                                            <button className="btn-icon" title="Запустить сейчас" disabled={runningId === s.id} onClick={() => handleRunNow(s.id)}>
                                                {runningId === s.id ? <span className="spinner" /> : <Play size={14} />}
                                            </button>
                                            <button className="btn-icon" title="Удалить" onClick={() => handleDelete(s.id)}>
                                                <Trash2 size={14} style={{ color: 'var(--status-danger, #e5484d)' }} />
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {showCreate && (
                <div className="modal-overlay" onClick={() => setShowCreate(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '480px' }}>
                        <div className="modal-header">
                            <h2>Новое расписание бэкапов</h2>
                            <button className="btn-close" onClick={() => setShowCreate(false)} type="button"><X size={18} /></button>
                        </div>
                        <form onSubmit={handleCreate}>
                            <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label">Имя расписания</label>
                                    <input className="form-control" placeholder="например: ночной бэкап web-1" value={name} onChange={e => setName(e.target.value)} required autoFocus />
                                </div>

                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label">Что бэкапить</label>
                                    <CustomSelect
                                        value={target}
                                        onChange={e => setTarget(e.target.value)}
                                        placeholder="— выберите объект —"
                                        options={[
                                            ...vms.filter(v => v.id).map(v => ({ value: `vm:${v.id}`, label: `🖥 ${v.name}` })),
                                            ...databases.map(d => ({ value: `database:${d.id}`, label: `🗄 ${d.db_name}` })),
                                        ]}
                                    />
                                </div>

                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label">Частота</label>
                                    <CustomSelect
                                        value={frequency}
                                        onChange={e => setFrequency(e.target.value)}
                                        options={[
                                            { value: 'hourly', label: 'Каждый час' },
                                            { value: 'daily', label: 'Ежедневно' },
                                            { value: 'weekly', label: 'Еженедельно' },
                                        ]}
                                    />
                                </div>

                                <div style={{ display: 'flex', gap: '12px' }}>
                                    {frequency === 'weekly' && (
                                        <div className="input-group" style={{ marginBottom: 0, flex: 1 }}>
                                            <label className="input-label">День недели</label>
                                            <CustomSelect
                                                value={weekday}
                                                onChange={e => setWeekday(e.target.value)}
                                                options={WEEKDAYS.map((d, i) => ({ value: i, label: d }))}
                                            />
                                        </div>
                                    )}
                                    {frequency !== 'hourly' && (
                                        <div className="input-group" style={{ marginBottom: 0, width: '90px' }}>
                                            <label className="input-label"><Clock size={14} /> Час</label>
                                            <input type="number" className="form-control" value={hour} onChange={e => setHour(e.target.value)} min="0" max="23" />
                                        </div>
                                    )}
                                    <div className="input-group" style={{ marginBottom: 0, width: '90px' }}>
                                        <label className="input-label">Минута</label>
                                        <input type="number" className="form-control" value={minute} onChange={e => setMinute(e.target.value)} min="0" max="59" />
                                    </div>
                                </div>

                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label">Хранить последних копий (ротация)</label>
                                    <input type="number" className="form-control" value={retention} onChange={e => setRetention(e.target.value)} min="1" max="365" />
                                </div>
                            </div>
                            <div className="modal-actions">
                                <button type="button" className="btn btn-secondary" onClick={() => setShowCreate(false)} disabled={submitting}>Отмена</button>
                                <button type="submit" className="btn btn-primary" disabled={submitting || !name.trim() || !target}>{submitting ? <span className="spinner" /> : <><CalendarClock size={14} /> Создать</>}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}
