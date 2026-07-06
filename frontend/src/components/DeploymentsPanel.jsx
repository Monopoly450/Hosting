import React, { useState, useEffect } from 'react';
import { Rocket, Plus, Trash2, X, Github, GitBranch, ExternalLink, Copy, Check, Server, Cpu, Terminal, Package, RefreshCw } from 'lucide-react';
import CustomSelect from './CustomSelect';

const STACKS = [
    { value: 'compose', label: 'Docker Compose (docker-compose.yml)' },
    { value: 'dockerfile', label: 'Dockerfile' },
    { value: 'node', label: 'Node.js (npm)' },
    { value: 'python', label: 'Python (requirements.txt)' },
    { value: 'static', label: 'Статический сайт (nginx)' },
    { value: 'custom', label: 'Своя команда запуска' },
];

const DEFAULT_PORTS = { compose: 3000, dockerfile: 8080, node: 3000, python: 8000, static: 80, custom: 3000 };

export default function DeploymentsPanel() {
    const [deps, setDeps] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [showCreate, setShowCreate] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [copied, setCopied] = useState(null);

    // Форма
    const [name, setName] = useState('');
    const [repoUrl, setRepoUrl] = useState('');
    const [branch, setBranch] = useState('main');
    const [stack, setStack] = useState('compose');
    const [appPort, setAppPort] = useState(3000);
    const [runCommand, setRunCommand] = useState('');
    const [cpu, setCpu] = useState(2);
    const [ram, setRam] = useState(2);
    const [disk, setDisk] = useState(20);

    const headers = () => ({
        'Authorization': `Bearer ${localStorage.getItem('aegis_admin_token') || ''}`,
        'Content-Type': 'application/json',
    });

    const fetchDeps = async () => {
        try {
            const res = await fetch('/api/deployments', { headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка загрузки деплоев');
            setDeps(await res.json());
            setError('');
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchDeps();
        const t = setInterval(fetchDeps, 5000);
        return () => clearInterval(t);
    }, []);

    const onStackChange = (v) => {
        setStack(v);
        if (DEFAULT_PORTS[v]) setAppPort(DEFAULT_PORTS[v]);
    };

    const handleCreate = async (e) => {
        e.preventDefault();
        setSubmitting(true);
        try {
            const res = await fetch('/api/deployments', {
                method: 'POST',
                headers: headers(),
                body: JSON.stringify({
                    name: name.trim().toLowerCase().replace(/[^a-z0-9-]/g, '-'),
                    repo_url: repoUrl.trim(),
                    branch: branch.trim() || 'main',
                    stack,
                    app_port: parseInt(appPort),
                    run_command: runCommand.trim() || null,
                    cpu_cores: parseInt(cpu),
                    memory_gb: parseInt(ram),
                    disk_gb: parseInt(disk),
                }),
            });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка создания деплоя');
            setShowCreate(false);
            setName(''); setRepoUrl(''); setBranch('main'); setRunCommand('');
            fetchDeps();
        } catch (e) {
            alert(`Ошибка: ${e.message}`);
        } finally {
            setSubmitting(false);
        }
    };

    const handleDelete = async (id) => {
        if (!confirm('Удалить деплой вместе с его виртуальной машиной?')) return;
        try {
            const res = await fetch(`/api/deployments/${id}`, { method: 'DELETE', headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка удаления');
            fetchDeps();
        } catch (e) {
            alert(`Ошибка: ${e.message}`);
        }
    };

    const copy = (text, key) => {
        navigator.clipboard.writeText(text);
        setCopied(key);
        setTimeout(() => setCopied(c => (c === key ? null : c)), 1400);
    };

    const statusBadge = (d) => {
        if (d.status === 'Running') return <span className="badge badge-success"><span className="status-dot" /> Работает</span>;
        if (d.status === 'Error') return <span className="badge badge-danger"><span className="status-dot" /> Ошибка</span>;
        return <span className="badge badge-warning"><span className="status-dot" /> Разворачивается…</span>;
    };

    return (
        <div className="panel-container">
            <div className="panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <div>
                    <h2 className="panel-title">Деплой приложений из GitHub</h2>
                    <p className="panel-subtitle">Каждый деплой разворачивается на своей выделенной виртуальной машине</p>
                </div>
                <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
                    <Plus size={16} /> Новый деплой
                </button>
            </div>

            {error && <div className="alert alert-danger">{error}</div>}

            {loading ? (
                <div style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}><div className="spinner spinner-lg" /></div>
            ) : deps.length === 0 ? (
                <div className="glass-card" style={{ textAlign: 'center', padding: '56px 20px' }}>
                    <Rocket size={44} style={{ color: 'var(--text-muted)', marginBottom: '12px' }} />
                    <h3 className="section-title" style={{ justifyContent: 'center' }}>Пока нет ни одного деплоя</h3>
                    <p className="text-muted">Укажите репозиторий GitHub — система поднимет отдельную ВМ, склонирует код и запустит приложение.</p>
                </div>
            ) : (
                <div className="grid-cols-3 stagger">
                    {deps.map(d => (
                        <div key={d.id} className="glass-card accent-top" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                    <div className="connect-tile-icon" style={{ width: '40px', height: '40px' }}><Rocket size={20} /></div>
                                    <div>
                                        <div style={{ fontWeight: 700, color: 'var(--text-heading)', fontSize: '1.05rem' }}>{d.name}</div>
                                        <div className="text-muted" style={{ fontSize: '0.75rem' }}>{d.stack_label}</div>
                                    </div>
                                </div>
                                {statusBadge(d)}
                            </div>

                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '0.82rem' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-secondary)' }}>
                                    <Github size={13} />
                                    <a href={d.repo_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-primary)', textDecoration: 'none', wordBreak: 'break-all' }}>
                                        {d.repo_url.replace('https://', '')}
                                    </a>
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-secondary)' }}>
                                    <GitBranch size={13} /> {d.branch} · порт {d.app_port}
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-secondary)' }}>
                                    <Server size={13} /> ВМ: {d.vm_name || '—'} {d.ip ? `(${d.ip})` : ''}
                                </div>
                            </div>

                            {d.app_url && (
                                <a href={d.app_url} target="_blank" rel="noreferrer" className="btn btn-secondary" style={{ justifyContent: 'space-between' }}>
                                    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><ExternalLink size={14} /> Открыть приложение</span>
                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-muted)' }}>{d.app_url.replace('http://', '')}</span>
                                </a>
                            )}

                            {d.ssh_command && (
                                <div className="copy-field">
                                    <code>{d.ssh_command}</code>
                                    <button className="btn-icon" onClick={() => copy(d.ssh_command, `ssh-${d.id}`)} title="Копировать SSH">
                                        {copied === `ssh-${d.id}` ? <Check size={14} color="var(--status-success)" /> : <Copy size={14} />}
                                    </button>
                                </div>
                            )}

                            <div style={{ display: 'flex', gap: '8px', marginTop: 'auto', paddingTop: '6px' }}>
                                <button className="btn btn-danger btn-sm" onClick={() => handleDelete(d.id)} style={{ marginLeft: 'auto' }}>
                                    <Trash2 size={13} /> Удалить
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {showCreate && (
                <div className="slide-over-overlay" onClick={() => setShowCreate(false)}>
                    <div className="slide-over-content" onClick={e => e.stopPropagation()}>
                        <div className="slide-over-header">
                            <h2>Новый деплой из GitHub</h2>
                            <button className="btn-close" onClick={() => setShowCreate(false)} type="button"><X size={18} /></button>
                        </div>
                        <form onSubmit={handleCreate} style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
                            <div className="slide-over-body" style={{ display: 'flex', flexDirection: 'column', gap: '18px', flex: 1, overflowY: 'auto' }}>
                                <div className="alert alert-info" style={{ marginBottom: 0, display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                                    <Rocket size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
                                    <span>Будет создана отдельная Ubuntu-ВМ: система склонирует репозиторий, установит окружение и запустит приложение. Публичные репозитории — без токена.</span>
                                </div>

                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label">Имя деплоя (a-z, 0-9, -)</label>
                                    <input className="form-control" placeholder="например: my-web-app" value={name} onChange={e => setName(e.target.value)} required />
                                </div>

                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><Github size={14} /> URL репозитория</label>
                                    <input className="form-control" placeholder="https://github.com/user/repo" value={repoUrl} onChange={e => setRepoUrl(e.target.value)} required />
                                </div>

                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
                                    <div className="input-group" style={{ marginBottom: 0 }}>
                                        <label className="input-label">Ветка</label>
                                        <input className="form-control" value={branch} onChange={e => setBranch(e.target.value)} />
                                    </div>
                                    <div className="input-group" style={{ marginBottom: 0 }}>
                                        <label className="input-label">Порт приложения</label>
                                        <input type="number" className="form-control" value={appPort} onChange={e => setAppPort(e.target.value)} required />
                                    </div>
                                </div>

                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><Package size={14} /> Тип стека</label>
                                    <CustomSelect value={stack} onChange={e => onStackChange(e.target.value)} options={STACKS} />
                                </div>

                                {(stack === 'custom' || stack === 'node' || stack === 'python') && (
                                    <div className="input-group" style={{ marginBottom: 0 }}>
                                        <label className="input-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                            <Terminal size={14} /> Команда запуска {stack === 'custom' ? '(обязательно)' : '(необязательно)'}
                                        </label>
                                        <input className="form-control" placeholder={stack === 'node' ? 'npm start' : stack === 'python' ? 'python3 app.py' : 'ваша команда'} value={runCommand} onChange={e => setRunCommand(e.target.value)} />
                                    </div>
                                )}

                                <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginTop: '4px' }}>
                                    <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}><Cpu size={14} /> Ресурсы выделенной ВМ</div>
                                    <Slider label="CPU" value={cpu} min={1} max={16} onChange={setCpu} suffix=" ядер" />
                                    <Slider label="RAM" value={ram} min={1} max={32} onChange={setRam} suffix=" ГБ" />
                                    <Slider label="Диск" value={disk} min={10} max={200} step={10} onChange={setDisk} suffix=" ГБ" />
                                </div>
                            </div>
                            <div className="slide-over-actions">
                                <button type="button" className="btn btn-secondary" onClick={() => setShowCreate(false)} disabled={submitting}>Отмена</button>
                                <button type="submit" className="btn btn-primary" disabled={submitting}>
                                    {submitting ? <span className="spinner" /> : <><Rocket size={15} /> Развернуть</>}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}

function Slider({ label, value, min, max, step = 1, onChange, suffix }) {
    return (
        <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                <span className="input-label">{label}</span>
                <span style={{ fontWeight: 600, color: 'var(--accent-primary)' }}>{value}{suffix}</span>
            </div>
            <input type="range" min={min} max={max} step={step} value={value} onChange={e => onChange(parseInt(e.target.value))} style={{ width: '100%' }} />
        </div>
    );
}
