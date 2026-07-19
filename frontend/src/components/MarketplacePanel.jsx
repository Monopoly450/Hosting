import React, { useState, useEffect } from 'react';
import { Store, X, Rocket, Check, Copy, AlertTriangle } from 'lucide-react';

export default function MarketplacePanel() {
    const [catalog, setCatalog] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [category, setCategory] = useState('Все');
    const [selected, setSelected] = useState(null);   // приложение для установки
    const [result, setResult] = useState(null);       // результат деплоя
    const [busy, setBusy] = useState(false);
    const [copied, setCopied] = useState('');

    // форма установки
    const [name, setName] = useState('');
    const [cpu, setCpu] = useState(2);
    const [ram, setRam] = useState(2);
    const [disk, setDisk] = useState(20);
    const [envVals, setEnvVals] = useState({});

    const headers = () => ({
        'Authorization': `Bearer ${localStorage.getItem('aegis_admin_token') || ''}`,
        'Content-Type': 'application/json',
    });

    useEffect(() => {
        (async () => {
            try {
                const res = await fetch('/api/marketplace/catalog', { headers: headers() });
                if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка загрузки каталога');
                setCatalog(await res.json());
            } catch (e) { setError(e.message); } finally { setLoading(false); }
        })();
    }, []);

    const categories = ['Все', ...Array.from(new Set(catalog.map(a => a.category)))];
    const visible = category === 'Все' ? catalog : catalog.filter(a => a.category === category);

    const openInstall = (app) => {
        setSelected(app);
        setName(`${app.id}-${Math.random().toString(36).slice(2, 6)}`);
        setCpu(2); setRam(2); setDisk(20); setEnvVals({});
    };

    const doDeploy = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            const res = await fetch('/api/marketplace/deploy', {
                method: 'POST', headers: headers(),
                body: JSON.stringify({ app_id: selected.id, name: name.trim(), cpu_cores: cpu, memory_gb: ram, disk_gb: disk, env: envVals }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Ошибка деплоя');
            setResult(data);
            setSelected(null);
        } catch (e) {
            alert(`Ошибка: ${e.message}`);
        } finally { setBusy(false); }
    };

    const copy = (val, key) => { navigator.clipboard.writeText(val); setCopied(key); setTimeout(() => setCopied(''), 1500); };

    return (
        <div className="panel-container">
            <div className="panel-header" style={{ marginBottom: '18px' }}>
                <h2 className="panel-title">Маркетплейс приложений</h2>
                <p className="panel-subtitle">Популярные приложения в один клик — каждое разворачивается в отдельной ВМ</p>
            </div>

            {error && <div className="alert alert-danger">{error}</div>}

            {result && (
                <div className="glass-card accent-top" style={{ marginBottom: '20px' }}>
                    <div className="section-title"><Check size={18} style={{ color: 'var(--status-success)' }} /> «{result.app}» разворачивается</div>
                    <p className="text-muted" style={{ fontSize: '0.86rem' }}>
                        ВМ «{result.name}» создаётся. Когда она поднимется, приложение станет доступно на вкладке
                        <b> «Деплой приложений»</b> по ссылке (внутренний порт {result.app_port}).
                    </p>
                    {result.generated_secrets && Object.keys(result.generated_secrets).length > 0 && (
                        <>
                            <div className="alert alert-danger" style={{ display: 'flex', gap: '8px', alignItems: 'flex-start', marginTop: '10px' }}>
                                <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
                                <span>Сгенерированные секреты — сохраните их сейчас, они показываются один раз.</span>
                            </div>
                            {Object.entries(result.generated_secrets).map(([k, v]) => (
                                <div key={k} className="copy-field" style={{ marginTop: '8px' }}>
                                    <code style={{ fontFamily: 'var(--font-mono)', fontSize: '0.82rem' }}>{k} = {v}</code>
                                    <button className="btn-icon" onClick={() => copy(v, k)}>{copied === k ? <Check size={16} color="var(--status-success)" /> : <Copy size={16} />}</button>
                                </div>
                            ))}
                        </>
                    )}
                    <button className="btn btn-secondary" style={{ marginTop: '14px' }} onClick={() => setResult(null)}>Понятно</button>
                </div>
            )}

            {loading ? (
                <div style={{ display: 'flex', justifyContent: 'center', padding: '50px' }}><div className="spinner spinner-lg" /></div>
            ) : (
                <>
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '18px' }}>
                        {categories.map(c => (
                            <button key={c} className={`btn btn-sm ${category === c ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setCategory(c)}>{c}</button>
                        ))}
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '16px' }}>
                        {visible.map(app => (
                            <div key={app.id} className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                    <div style={{ fontSize: '2rem', lineHeight: 1 }}>{app.icon}</div>
                                    <div>
                                        <div style={{ fontWeight: 700 }}>{app.name}</div>
                                        <span className="badge" style={{ fontSize: '0.7rem' }}>{app.category}</span>
                                    </div>
                                </div>
                                <p className="text-muted" style={{ fontSize: '0.82rem', flex: 1, margin: 0 }}>{app.description}</p>
                                <button className="btn btn-primary btn-sm" onClick={() => openInstall(app)}><Rocket size={14} /> Установить</button>
                            </div>
                        ))}
                    </div>
                </>
            )}

            {selected && (
                <div className="modal-overlay" onClick={() => setSelected(null)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '460px' }}>
                        <div className="modal-header">
                            <h2>{selected.icon} Установить {selected.name}</h2>
                            <button className="btn-close" onClick={() => setSelected(null)} type="button"><X size={18} /></button>
                        </div>
                        <form onSubmit={doDeploy}>
                            <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label">Имя (домен ВМ)</label>
                                    <input className="form-control" value={name} onChange={e => setName(e.target.value)} pattern="[a-z0-9]([-a-z0-9]*[a-z0-9])?" required autoFocus />
                                </div>
                                <div style={{ display: 'flex', gap: '12px' }}>
                                    <div className="input-group" style={{ marginBottom: 0, flex: 1 }}>
                                        <label className="input-label">CPU</label>
                                        <input type="number" className="form-control" value={cpu} min="1" max="16" onChange={e => setCpu(parseInt(e.target.value))} />
                                    </div>
                                    <div className="input-group" style={{ marginBottom: 0, flex: 1 }}>
                                        <label className="input-label">RAM, ГБ</label>
                                        <input type="number" className="form-control" value={ram} min="1" max="64" onChange={e => setRam(parseInt(e.target.value))} />
                                    </div>
                                    <div className="input-group" style={{ marginBottom: 0, flex: 1 }}>
                                        <label className="input-label">Диск, ГБ</label>
                                        <input type="number" className="form-control" value={disk} min="10" max="500" onChange={e => setDisk(parseInt(e.target.value))} />
                                    </div>
                                </div>
                                {selected.env.filter(e => !e.secret).map(e => (
                                    <div className="input-group" key={e.key} style={{ marginBottom: 0 }}>
                                        <label className="input-label">{e.label}</label>
                                        <input className="form-control" value={envVals[e.key] || ''} onChange={ev => setEnvVals({ ...envVals, [e.key]: ev.target.value })} />
                                    </div>
                                ))}
                                {selected.env.some(e => e.secret) && (
                                    <p className="text-muted" style={{ fontSize: '0.76rem', margin: 0 }}>Секретные значения (пароли/токены) будут сгенерированы автоматически и показаны один раз.</p>
                                )}
                            </div>
                            <div className="modal-actions">
                                <button type="button" className="btn btn-secondary" onClick={() => setSelected(null)} disabled={busy}>Отмена</button>
                                <button type="submit" className="btn btn-primary" disabled={busy || !name.trim()}>{busy ? <span className="spinner" /> : <><Rocket size={15} /> Установить</>}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}
