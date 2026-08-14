import React, { useState, useEffect } from 'react';
import { Boxes, Play, Square, RefreshCw, Trash2, Copy, Check, ChevronRight, ChevronDown, Terminal, AlertTriangle } from 'lucide-react';

export default function RegistryPanel() {
    const [status, setStatus] = useState(null);
    const [info, setInfo] = useState(null);
    const [repos, setRepos] = useState([]);
    const [expanded, setExpanded] = useState({});   // repo -> tags[]
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [copied, setCopied] = useState('');

    const headers = () => ({
        'Authorization': `Bearer ${localStorage.getItem('aegis_admin_token') || ''}`,
        'Content-Type': 'application/json',
    });

    const loadStatus = async () => {
        try {
            const [sRes, iRes] = await Promise.all([
                fetch('/api/registry/status', { headers: headers() }),
                fetch('/api/registry/info', { headers: headers() }),
            ]);
            const s = await sRes.json();
            setStatus(s);
            setInfo(iRes.ok ? await iRes.json() : null);
            if (s.running) loadRepos();
        } catch (e) { setError(e.message); } finally { setLoading(false); }
    };

    const loadRepos = async () => {
        try {
            const res = await fetch('/api/registry/repositories', { headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка');
            setRepos(await res.json());
            setError('');
        } catch (e) { setError(e.message); }
    };

    useEffect(() => { loadStatus(); }, []);

    const provision = async () => {
        setBusy(true);
        try {
            const res = await fetch('/api/registry/provision', { method: 'POST', headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка');
            await loadStatus();
        } catch (e) { alert(`Ошибка: ${e.message}`); } finally { setBusy(false); }
    };

    const stop = async () => {
        if (!confirm('Остановить реестр? Загруженные образы сохранятся в томе.')) return;
        setBusy(true);
        try {
            const res = await fetch('/api/registry/stop', { method: 'POST', headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка');
            setRepos([]); setExpanded({});
            await loadStatus();
        } catch (e) { alert(`Ошибка: ${e.message}`); } finally { setBusy(false); }
    };

    const toggleRepo = async (name) => {
        if (expanded[name]) { const e = { ...expanded }; delete e[name]; setExpanded(e); return; }
        try {
            const res = await fetch(`/api/registry/repositories/${name}/tags`, { headers: headers() });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Ошибка');
            setExpanded({ ...expanded, [name]: data.tags });
        } catch (e) { alert(`Ошибка: ${e.message}`); }
    };

    const deleteTag = async (repo, tag) => {
        if (!confirm(`Удалить образ ${repo}:${tag}?`)) return;
        try {
            const res = await fetch(`/api/registry/repositories/${repo}/tags/${tag}`, { method: 'DELETE', headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка');
            setExpanded({ ...expanded, [repo]: expanded[repo].filter(t => t !== tag) });
            loadRepos();
        } catch (e) { alert(`Ошибка: ${e.message}`); }
    };

    const copy = (val, key) => { navigator.clipboard.writeText(val); setCopied(key); setTimeout(() => setCopied(''), 1500); };

    if (loading) return <div className="panel-container"><div style={{ display: 'flex', justifyContent: 'center', padding: '50px' }}><div className="spinner spinner-lg" /></div></div>;

    return (
        <div className="panel-container">
            <div className="panel-header">
                <div>
                    <p className="panel-subtitle">Приватный Docker-реестр для ваших образов</p>
                </div>
                {status?.running && <button className="btn btn-secondary btn-sm" onClick={loadRepos}><RefreshCw size={14} /> Обновить</button>}
            </div>

            {error && <div className="alert alert-danger">{error}</div>}

            {!status?.docker ? (
                <div className="glass-card" style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                    <AlertTriangle size={20} style={{ color: 'var(--status-warning, #f5a623)' }} />
                    <span>Docker на хосте недоступен — реестр запустить нельзя.</span>
                </div>
            ) : !status?.running ? (
                <div className="glass-card" style={{ textAlign: 'center', padding: '48px 20px' }}>
                    <Boxes size={44} style={{ color: 'var(--text-muted)', marginBottom: '12px' }} />
                    <h3 className="section-title" style={{ justifyContent: 'center' }}>Реестр не запущен</h3>
                    <p className="text-muted" style={{ marginBottom: '16px' }}>Запустите приватный реестр, чтобы пушить и хранить свои Docker-образы.</p>
                    <button className="btn btn-primary" onClick={provision} disabled={busy}>{busy ? <span className="spinner" /> : <><Play size={15} /> Запустить реестр</>}</button>
                </div>
            ) : (
                <>
                    {/* Инструкция по подключению */}
                    <div className="glass-card" style={{ marginBottom: '20px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                            <div className="section-title" style={{ margin: 0 }}><Terminal size={16} /> Как загружать образы</div>
                            <button className="btn btn-danger btn-sm" onClick={stop} disabled={busy}><Square size={13} /> Остановить</button>
                        </div>
                        <p className="text-muted" style={{ fontSize: '0.8rem', marginTop: 0 }}>
                            Адрес ниже — для команд <code>docker login</code> и <code>docker push</code>.
                            В браузере он откроет пустую страницу: у реестра нет веб-интерфейса, только API.
                            Загруженные образы видны в списке ниже.
                        </p>
                        <div className="copy-field" style={{ marginBottom: '10px' }}>
                            <code style={{ fontFamily: 'var(--font-mono)' }}>{info?.push_host}</code>
                            <button className="btn-icon" onClick={() => copy(info.push_host, 'host')}>{copied === 'host' ? <Check size={16} color="var(--status-success)" /> : <Copy size={16} />}</button>
                        </div>
                        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginBottom: '10px' }}>
                            <div style={{ flex: '1 1 160px' }}>
                                <div className="text-muted" style={{ fontSize: '0.72rem' }}>Логин</div>
                                <div className="copy-field">
                                    <code style={{ fontFamily: 'var(--font-mono)' }}>{info?.username}</code>
                                    <button className="btn-icon" onClick={() => copy(info.username, 'user')}>{copied === 'user' ? <Check size={16} color="var(--status-success)" /> : <Copy size={16} />}</button>
                                </div>
                            </div>
                            <div style={{ flex: '1 1 220px' }}>
                                <div className="text-muted" style={{ fontSize: '0.72rem' }}>Пароль</div>
                                <div className="copy-field">
                                    <code style={{ fontFamily: 'var(--font-mono)', wordBreak: 'break-all' }}>{info?.password || '—'}</code>
                                    {info?.password && <button className="btn-icon" onClick={() => copy(info.password, 'pass')}>{copied === 'pass' ? <Check size={16} color="var(--status-success)" /> : <Copy size={16} />}</button>}
                                </div>
                            </div>
                        </div>
                        <pre style={{ background: 'var(--bg-surface-hover)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: '12px', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', margin: 0, overflowX: 'auto' }}>{(info?.examples || []).join('\n')}</pre>
                        {info?.insecure_note && <p className="text-muted" style={{ fontSize: '0.76rem', marginTop: '10px' }}>{info.insecure_note}</p>}
                    </div>

                    {/* Репозитории */}
                    <div className="glass-card">
                        <div className="section-title"><Boxes size={16} /> Репозитории</div>
                        {repos.length === 0 ? (
                            <p className="text-muted" style={{ fontSize: '0.85rem' }}>Пока нет ни одного образа. Запушьте первый по инструкции выше.</p>
                        ) : (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                {repos.map(r => (
                                    <div key={r.name} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 4px', cursor: 'pointer' }} onClick={() => toggleRepo(r.name)}>
                                            {expanded[r.name] ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                                            <span style={{ fontWeight: 600, fontFamily: 'var(--font-mono)' }}>{r.name}</span>
                                            <span className="badge" style={{ marginLeft: 'auto' }}>{r.tags_count} тегов</span>
                                        </div>
                                        {expanded[r.name] && (
                                            <div style={{ padding: '0 0 10px 28px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                                {expanded[r.name].length === 0 ? <span className="text-muted" style={{ fontSize: '0.8rem' }}>нет тегов</span> :
                                                    expanded[r.name].map(t => (
                                                        <div key={t} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                            <code style={{ fontFamily: 'var(--font-mono)', fontSize: '0.82rem' }}>{r.name}:{t}</code>
                                                            <button className="btn-icon" title="Удалить" style={{ marginLeft: 'auto' }} onClick={() => deleteTag(r.name, t)}><Trash2 size={13} style={{ color: '#e5484d' }} /></button>
                                                        </div>
                                                    ))}
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </>
            )}
        </div>
    );
}
