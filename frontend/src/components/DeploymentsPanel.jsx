import React, { useState, useEffect } from 'react';
import { Rocket, Plus, Trash2, X, Github, GitBranch, ExternalLink, Copy, Check, Server, Cpu, Terminal, Package, RefreshCw, Activity, Settings, Calendar, Globe, Layers, Shield, Network } from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip as RechartsTooltip } from 'recharts';
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

// Деплой из маркетплейса не имеет ни репозитория, ни ветки: бэкенд пишет туда
// синтетическое marketplace://<id> и прочерк. Без этой развилки в карточке
// висела оранжевая «ссылка» в никуда и ветка «-» рядом с иконкой git.
const isMarketplace = (d) => d.stack === 'marketplace';
const marketplaceAppId = (d) => (d.repo_url || '').replace('marketplace://', '');

export default function DeploymentsPanel() {
    const [deps, setDeps] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [showCreate, setShowCreate] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [copied, setCopied] = useState(null);

    // Подробная консоль деплоя
    const [selectedDep, setSelectedDep] = useState(null);
    const [consoleTab, setConsoleTab] = useState('overview'); // 'overview' | 'logs' | 'metrics' | 'settings'
    const [logsContent, setLogsContent] = useState('');
    const [loadingLogs, setLoadingLogs] = useState(false);
    const [metricsHistory, setMetricsHistory] = useState([]);
    const [loadingMetrics, setLoadingMetrics] = useState(false);
    const [redeploying, setRedeploying] = useState(false);

    // Форма создания
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
            const data = await res.json();
            setDeps(data);

            // Если сейчас открыта панель управления конкретным деплоем, обновим объект
            // в стейте. Обязательно через функциональную форму: обычное чтение
            // selectedDep взялось бы из замыкания на момент запуска запроса, и ответ,
            // прилетевший после закрытия панели, открывал бы её заново.
            setSelectedDep(prev => (prev ? data.find(d => d.id === prev.id) || prev : null));
            setError('');
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

    // Пустой массив зависимостей важен: с [selectedDep] каждый ответ подставлял
    // новый объект из JSON, эффект перезапускался и сразу дёргал fetchDeps снова —
    // при открытой панели это был бесконечный цикл запросов вместо опроса раз в 5с.
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
        if (!confirm('Удалить деплой вместе с его выделенной виртуальной машиной? Все данные приложения будут безвозвратно стерты.')) return;
        try {
            const res = await fetch(`/api/deployments/${id}`, { method: 'DELETE', headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка удаления');
            setSelectedDep(null);
            fetchDeps();
        } catch (e) {
            alert(`Ошибка: ${e.message}`);
        }
    };

    const handleRedeploy = async (id) => {
        if (!confirm('Пересобрать и перезапустить приложение? Система скачает свежий код из выбранной ветки GitHub.')) return;
        setRedeploying(true);
        try {
            const res = await fetch(`/api/deployments/${id}/redeploy`, { method: 'POST', headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка запуска передеплоя');
            alert('Сборка запущена! Прогресс сборки можно смотреть во вкладке "Логи".');
            setConsoleTab('logs');
            fetchLogs(id);
        } catch (e) {
            alert(`Ошибка: ${e.message}`);
        } finally {
            setRedeploying(false);
        }
    };

    const fetchLogs = async (id) => {
        setLoadingLogs(true);
        setLogsContent('Подключение к виртуальной машине по SSH для получения логов...');
        try {
            const res = await fetch(`/api/deployments/${id}/logs`, { headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка получения логов');
            const data = await res.json();
            setLogsContent(data.logs || 'Логи пусты.');
        } catch (e) {
            setLogsContent(`Ошибка: ${e.message}`);
        } finally {
            setLoadingLogs(false);
        }
    };

    const fetchMetrics = async (vmName) => {
        if (!vmName) return;
        setLoadingMetrics(true);
        try {
            const res = await fetch(`/api/vms/${vmName}/metrics/history`, { headers: headers() });
            if (!res.ok) throw new Error('Ошибка получения истории метрик');
            const data = await res.json();
            const formatted = data.map(item => ({
                time: new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
                cpu: parseFloat(item.cpu_usage_percent.toFixed(1)),
                memory: parseFloat(item.memory_usage_percent.toFixed(1)),
            }));
            setMetricsHistory(formatted);
        } catch (err) {
            console.error(err);
        } finally {
            setLoadingMetrics(false);
        }
    };

    const openConsole = (dep) => {
        setSelectedDep(dep);
        setConsoleTab('overview');
        setLogsContent('');
        setMetricsHistory([]);
    };

    const onTabChange = (tab) => {
        setConsoleTab(tab);
        if (tab === 'logs' && selectedDep) {
            fetchLogs(selectedDep.id);
        } else if (tab === 'metrics' && selectedDep) {
            fetchMetrics(selectedDep.vm_name);
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
            <div className="panel-header">
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
                                    {isMarketplace(d) ? (
                                        <><Package size={13} /> <span>{marketplaceAppId(d)}</span></>
                                    ) : (
                                        <>
                                            <Github size={13} />
                                            <a href={d.repo_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-primary)', textDecoration: 'none', wordBreak: 'break-all' }}>
                                                {d.repo_url.replace('https://', '')}
                                            </a>
                                        </>
                                    )}
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-secondary)' }}>
                                    {isMarketplace(d)
                                        ? <><Network size={13} /> порт {d.app_port}</>
                                        : <><GitBranch size={13} /> {d.branch} · порт {d.app_port}</>}
                                </div>
                            </div>

                            {d.app_url && (
                                <a href={d.app_url} target="_blank" rel="noreferrer" className="btn btn-secondary" style={{ justifyContent: 'space-between', gap: '10px' }}>
                                    <span style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}><ExternalLink size={14} /> Открыть приложение</span>
                                    {/* .btn режет по overflow: hidden, поэтому адрес сжимаем сами
                                        с многоточием — иначе на узкой карточке он обрубался посреди порта. */}
                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-muted)', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>{d.app_url.replace('http://', '')}</span>
                                </a>
                            )}

                            <div style={{ display: 'flex', gap: '8px', marginTop: 'auto', paddingTop: '6px', alignItems: 'center' }}>
                                <button className="btn btn-primary btn-sm" onClick={() => openConsole(d)} style={{ padding: '6px 12px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
                                    <Terminal size={14} /> Управление
                                </button>
                                <button className="btn btn-danger btn-sm" onClick={() => handleDelete(d.id)} style={{ marginLeft: 'auto' }}>
                                    <Trash2 size={13} />
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* ПОДРОБНАЯ ПАНЕЛЬ КОНСОЛИ ДЕПЛОЯ (Drawer/Slide-over) */}
            {selectedDep && (
                <div className="slide-over-overlay" onClick={() => setSelectedDep(null)}>
                    <div className="slide-over-content" style={{ maxWidth: '760px', width: '100%' }} onClick={e => e.stopPropagation()}>
                        
                        {/* Header */}
                        <div className="slide-over-header">
                            <div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                    <h2 style={{ margin: 0 }}>{selectedDep.name}</h2>
                                    {statusBadge(selectedDep)}
                                </div>
                                <p className="text-muted" style={{ fontSize: '0.8rem', margin: '4px 0 0 0', display: 'flex', alignItems: 'center', gap: '6px' }}>
                                    {isMarketplace(selectedDep) ? (
                                        <><Package size={14} /> Приложение из маркетплейса: <strong>{marketplaceAppId(selectedDep)}</strong></>
                                    ) : (
                                        <>
                                            <Github size={14} /> <a href={selectedDep.repo_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-primary)' }}>{selectedDep.repo_url}</a>
                                            · <GitBranch size={14} /> <strong>{selectedDep.branch}</strong>
                                        </>
                                    )}
                                </p>
                            </div>
                            <button className="btn-close" onClick={() => setSelectedDep(null)} type="button"><X size={18} /></button>
                        </div>

                        {/* Tabs Navigation */}
                        <div style={{ display: 'flex', gap: '6px', borderBottom: '1px solid var(--border-subtle)', padding: '0 24px', background: 'var(--bg-surface-hover)' }}>
                            <button className={`tab-btn ${consoleTab === 'overview' ? 'active' : ''}`} onClick={() => onTabChange('overview')} style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '12px 16px', background: 'none', border: 'none', borderBottom: consoleTab === 'overview' ? '2px solid var(--accent-primary)' : '2px solid transparent', color: consoleTab === 'overview' ? 'var(--text-heading)' : 'var(--text-muted)', fontWeight: 600, cursor: 'pointer', fontSize: '0.85rem' }}>
                                <Server size={14} /> Обзор
                            </button>
                            <button className={`tab-btn ${consoleTab === 'logs' ? 'active' : ''}`} onClick={() => onTabChange('logs')} style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '12px 16px', background: 'none', border: 'none', borderBottom: consoleTab === 'logs' ? '2px solid var(--accent-primary)' : '2px solid transparent', color: consoleTab === 'logs' ? 'var(--text-heading)' : 'var(--text-muted)', fontWeight: 600, cursor: 'pointer', fontSize: '0.85rem' }}>
                                <Terminal size={14} /> Логи сборки & работы
                            </button>
                            <button className={`tab-btn ${consoleTab === 'metrics' ? 'active' : ''}`} onClick={() => onTabChange('metrics')} style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '12px 16px', background: 'none', border: 'none', borderBottom: consoleTab === 'metrics' ? '2px solid var(--accent-primary)' : '2px solid transparent', color: consoleTab === 'metrics' ? 'var(--text-heading)' : 'var(--text-muted)', fontWeight: 600, cursor: 'pointer', fontSize: '0.85rem' }}>
                                <Activity size={14} /> Нагрузка (Prometheus)
                            </button>
                            <button className={`tab-btn ${consoleTab === 'settings' ? 'active' : ''}`} onClick={() => onTabChange('settings')} style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '12px 16px', background: 'none', border: 'none', borderBottom: consoleTab === 'settings' ? '2px solid var(--accent-primary)' : '2px solid transparent', color: consoleTab === 'settings' ? 'var(--text-heading)' : 'var(--text-muted)', fontWeight: 600, cursor: 'pointer', fontSize: '0.85rem' }}>
                                <Settings size={14} /> Управление
                            </button>
                        </div>

                        {/* Tab Content */}
                        {/* flex-колонка, чтобы вкладки логов и нагрузки могли занять всю
                            доступную высоту вместо фиксированных пикселей. */}
                        <div className="slide-over-body" style={{ flex: 1, padding: '24px', overflowY: 'auto', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                            
                            {/* OVERVIEW TAB */}
                            {consoleTab === 'overview' && (
                                /* Один поток на всю ширину, а не две колонки: правая колонка
                                   со спецификацией была вдвое короче левой, обзор обрывался
                                   на середине панели и выглядел сломанным. */
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                    <div className="glass-card" style={{ padding: '16px' }}>
                                        <h3 className="section-title" style={{ fontSize: '0.95rem', margin: '0 0 12px 0' }}><Globe size={16}/> Ссылка приложения</h3>
                                        {selectedDep.app_url ? (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', alignItems: 'flex-start' }}>
                                                <a href={selectedDep.app_url} target="_blank" rel="noreferrer" className="btn btn-secondary" style={{ maxWidth: '100%', padding: '10px 14px', gap: '10px' }}>
                                                    <span style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--accent-primary)', fontWeight: 600, flexShrink: 0 }}><ExternalLink size={16} /> Открыть сайт</span>
                                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>{selectedDep.app_url}</span>
                                                </a>
                                                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Внешнее подключение проброшено автоматически на выделенный порт приложения.</span>
                                            </div>
                                        ) : (
                                            <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Генерируется... Приложение еще не готово или выключено.</span>
                                        )}
                                    </div>

                                    <div className="glass-card" style={{ padding: '16px' }}>
                                        <h3 className="section-title" style={{ fontSize: '0.95rem', margin: '0 0 12px 0' }}><Terminal size={16}/> SSH-подключение к ВМ</h3>
                                        {selectedDep.ssh_command ? (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                                <div className="copy-field" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
                                                    <code style={{ fontSize: '0.8rem' }}>{selectedDep.ssh_command}</code>
                                                    <button className="btn-icon" onClick={() => copy(selectedDep.ssh_command, 'ssh-console')} title="Копировать">
                                                        {copied === 'ssh-console' ? <Check size={14} color="var(--status-success)" /> : <Copy size={14} />}
                                                    </button>
                                                </div>
                                                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Подключение по SSH к ВМ деплоя через jump-сервер хостинга.</span>
                                            </div>
                                        ) : (
                                            <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Генерируется... Виртуальная машина еще не создана.</span>
                                        )}
                                    </div>

                                    <div className="glass-card" style={{ padding: '16px', background: 'var(--card-bg-subtle)' }}>
                                        <h3 className="section-title" style={{ fontSize: '0.95rem', margin: '0 0 14px 0' }}><Layers size={16}/> Спецификация ВМ</h3>
                                        {/* Плитки вместо строк «метка — значение»: на всю ширину панели
                                            строки растягивались, оставляя провал между меткой и значением. */}
                                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '14px', fontSize: '0.85rem' }}>
                                            {[
                                                { label: 'Имя ВМ', value: selectedDep.vm_name || '—' },
                                                { label: 'Статус ВМ', value: selectedDep.vm_status || '—', color: selectedDep.vm_status === 'Running' ? 'var(--status-success)' : 'var(--text-muted)' },
                                                { label: 'IP ВМ', value: selectedDep.ip || '—', mono: true },
                                                { label: 'Стек', value: selectedDep.stack_label },
                                                { label: 'Внутренний порт', value: selectedDep.app_port, mono: true },
                                                { label: 'Владелец', value: selectedDep.owner_username || '—' },
                                            ].map(f => (
                                                <div key={f.label} style={{ display: 'flex', flexDirection: 'column', gap: '3px', minWidth: 0 }}>
                                                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>{f.label}</span>
                                                    <span style={{ fontWeight: 600, color: f.color || 'var(--text-primary)', fontFamily: f.mono ? 'var(--font-mono)' : 'inherit', overflow: 'hidden', textOverflow: 'ellipsis' }}>{f.value}</span>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* LOGS TAB */}
                            {consoleTab === 'logs' && (
                                /* flex: 1 вместо height: 480px — иначе на всю высоту панели
                                   логи занимали половину, а под ними оставалась пустота. */
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', flex: 1, minHeight: '320px' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
                                        <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Включает логи клонирования Git, установки пакетов и работы запущенного контейнера/службы.</span>
                                        <button className="btn btn-secondary btn-sm" onClick={() => fetchLogs(selectedDep.id)} disabled={loadingLogs} style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
                                            <RefreshCw size={14} className={loadingLogs ? 'spinner' : ''} /> Обновить
                                        </button>
                                    </div>
                                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--terminal-bg)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                                        <pre style={{
                                            flex: 1,
                                            overflow: 'auto',
                                            margin: 0,
                                            padding: '16px',
                                            fontFamily: 'var(--font-mono)',
                                            fontSize: '0.8rem',
                                            color: 'var(--terminal-fg)',
                                            lineHeight: '1.5',
                                            whiteSpace: 'pre-wrap',
                                            wordBreak: 'break-all',
                                            textAlign: 'left'
                                        }}>
                                            {logsContent}
                                        </pre>
                                    </div>
                                </div>
                            )}

                            {/* METRICS (PROMETHEUS) TAB */}
                            {consoleTab === 'metrics' && (
                                /* Как и логи, тянется на всю высоту: график в 320px посреди
                                   высокой панели оставлял под собой пустое место. */
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', flex: 1, minHeight: '320px' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
                                        <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>История нагрузки CPU и памяти на выделенной виртуальной машине (данные из Prometheus).</span>
                                        <button className="btn btn-secondary btn-sm" onClick={() => fetchMetrics(selectedDep.vm_name)} disabled={loadingMetrics} style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
                                            <RefreshCw size={14} className={loadingMetrics ? 'spinner' : ''} /> Обновить
                                        </button>
                                    </div>
                                    <div className="glass-card" style={{ padding: '20px', flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                                        {loadingMetrics ? (
                                            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', flex: 1 }}><div className="spinner spinner-lg" /></div>
                                        ) : metricsHistory.length === 0 ? (
                                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1, textAlign: 'center', color: 'var(--text-muted)' }}>История метрик пуста (возможно, ВМ только запустилась).</div>
                                        ) : (
                                            <div style={{ flex: 1, minHeight: 0, width: '100%' }}>
                                                <ResponsiveContainer width="100%" height="100%">
                                                    <AreaChart data={metricsHistory} margin={{ top: 5, right: 0, left: -20, bottom: 0 }}>
                                                        <defs>
                                                            <linearGradient id="colorCpu" x1="0" y1="0" x2="0" y2="1">
                                                                <stop offset="5%" stopColor="var(--accent-primary)" stopOpacity={0.3}/>
                                                                <stop offset="95%" stopColor="var(--accent-primary)" stopOpacity={0}/>
                                                            </linearGradient>
                                                            <linearGradient id="colorMem" x1="0" y1="0" x2="0" y2="1">
                                                                <stop offset="5%" stopColor="var(--status-success)" stopOpacity={0.3}/>
                                                                <stop offset="95%" stopColor="var(--status-success)" stopOpacity={0}/>
                                                            </linearGradient>
                                                        </defs>
                                                        <XAxis dataKey="time" style={{ fontSize: '9px', fill: 'var(--text-muted)' }} />
                                                        <YAxis domain={[0, 100]} tickLine={false} axisLine={false} style={{ fontSize: '10px', fill: 'var(--text-muted)' }} />
                                                        <RechartsTooltip 
                                                            contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}
                                                            labelStyle={{ color: 'var(--text-secondary)', marginBottom: '4px', fontSize: '0.8rem' }}
                                                            itemStyle={{ fontSize: '0.85rem', fontWeight: 500 }}
                                                        />
                                                        <Area type="monotone" dataKey="cpu" name="CPU Нагрузка %" stroke="var(--accent-primary)" fillOpacity={1} fill="url(#colorCpu)" strokeWidth={2} />
                                                        <Area type="monotone" dataKey="memory" name="ОЗУ Загрузка %" stroke="var(--status-success)" fillOpacity={1} fill="url(#colorMem)" strokeWidth={2} />
                                                    </AreaChart>
                                                </ResponsiveContainer>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            )}

                            {/* SETTINGS / MANAGE TAB */}
                            {consoleTab === 'settings' && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                    {isMarketplace(selectedDep) ? (
                                        /* Передеплой тянет git pull в /opt/app — у приложения из
                                           маркетплейса нет ни репозитория, ни этого каталога, так
                                           что кнопка гарантированно возвращала ошибку git. */
                                        <div className="glass-card" style={{ padding: '20px', borderLeft: '4px solid var(--status-info)' }}>
                                            <h3 className="section-title" style={{ fontSize: '1rem', margin: '0 0 8px 0' }}><Package size={16}/> Обновление приложения</h3>
                                            <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', margin: 0, lineHeight: '1.5' }}>
                                                Приложение установлено из маркетплейса, а не из репозитория, поэтому передеплой через <code>git pull</code> к нему не применяется. Обновлять его нужно средствами самого приложения — либо подключиться к ВМ по SSH с вкладки «Обзор».
                                            </p>
                                        </div>
                                    ) : (
                                        <div className="glass-card" style={{ padding: '20px', borderLeft: '4px solid var(--accent-primary)' }}>
                                            <h3 className="section-title" style={{ fontSize: '1rem', margin: '0 0 8px 0' }}><RefreshCw size={16}/> Переразвернуть приложение</h3>
                                            <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', margin: '0 0 16px 0', lineHeight: '1.5' }}>
                                                Система подключится к ВМ деплоя по SSH, выполнит команду <code>git pull</code> из вашей ветки, скачает свежие коммиты и перезапустит контейнеры или системную службу приложения. Удобно для обновления бота или сайта при отправке изменений в GitHub.
                                            </p>
                                            <button className="btn btn-primary" onClick={() => handleRedeploy(selectedDep.id)} disabled={redeploying} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                                <RefreshCw size={15} className={redeploying ? 'spinner' : ''} />
                                                {redeploying ? 'Переразвертывание...' : 'Переразвернуть из GitHub'}
                                            </button>
                                        </div>
                                    )}

                                    <div className="glass-card" style={{ padding: '20px', borderLeft: '4px solid var(--status-danger)' }}>
                                        <h3 className="section-title" style={{ fontSize: '1rem', margin: '0 0 8px 0', color: 'var(--status-danger)' }}><Trash2 size={16}/> Опасная зона</h3>
                                        <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', margin: '0 0 16px 0', lineHeight: '1.5' }}>
                                            Удаление деплоя полностью сотрет эту виртуальную машину со всеми локальными данными, базами данных и файлами вашего бота/приложения. Отменить это действие невозможно.
                                        </p>
                                        <button className="btn btn-danger" onClick={() => handleDelete(selectedDep.id)} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                            <Trash2 size={15} />
                                            Удалить деплой и ВМ
                                        </button>
                                    </div>
                                </div>
                            )}

                        </div>
                    </div>
                </div>
            )}

            {/* СОЗДАНИЕ НОВОГО ДЕПЛОЯ */}
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
