import React, { useState, useEffect } from 'react';
import { Boxes, Server, Cpu, HardDrive, Layers, Network, RefreshCw, Copy, Check, Terminal, Package, CircleDot, Download, Info, ShieldCheck } from 'lucide-react';

export default function KubernetesPanel() {
    const [data, setData] = useState(null);
    const [join, setJoin] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [tab, setTab] = useState('overview'); // overview | nodes | pods | install
    const [nsFilter, setNsFilter] = useState('all');
    const [copied, setCopied] = useState(null);

    const headers = () => ({ 'Authorization': `Bearer ${localStorage.getItem('aegis_admin_token') || ''}` });

    const fetchAll = async () => {
        try {
            const res = await fetch('/api/kubernetes/overview', { headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка загрузки данных кластера');
            setData(await res.json());
            setError('');
            fetch('/api/kubernetes/join-token', { headers: headers() })
                .then(r => r.ok ? r.json() : null).then(j => j && setJoin(j)).catch(() => {});
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
    }, []);

    const copy = (text, key) => {
        navigator.clipboard.writeText(text);
        setCopied(key);
        setTimeout(() => setCopied(c => (c === key ? null : c)), 1400);
    };

    // Шапка рисуется и во время загрузки — иначе она появляется только
    // после прихода данных, и контент прыгает вниз. Версии в подзаголовке
    // до загрузки просто пустые.
    const header = (
        <div className="panel-header">
            <div>
                <p className="panel-subtitle">
                    {data?.k8s_version} · KubeVirt {data?.kubevirt_version} · CDI {data?.cdi_version}
                </p>
            </div>
            <button className="btn btn-secondary" onClick={fetchAll} disabled={loading}><RefreshCw size={15} /> Обновить</button>
        </div>
    );

    if (loading) return (
        <div className="panel-container">{header}<div className="panel-loading"><div className="spinner spinner-lg" /></div></div>
    );

    const c = data?.counts || {};
    const tabs = [
        { id: 'overview', label: 'Обзор', icon: Boxes },
        { id: 'nodes', label: `Ноды (${c.nodes || 0})`, icon: Server },
        { id: 'pods', label: `Поды (${c.pods_running || 0}/${c.pods_total || 0})`, icon: Package },
        { id: 'install', label: 'Установка', icon: Download },
    ];

    const namespaces = data?.namespaces || [];
    const pods = (data?.pods || []).filter(p => nsFilter === 'all' || p.namespace === nsFilter);

    const StatCard = ({ icon: Icon, label, value, sub }) => (
        <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <div className="connect-tile-icon" style={{ width: '46px', height: '46px', flexShrink: 0 }}><Icon size={22} /></div>
            <div>
                <div style={{ fontSize: '1.5rem', fontWeight: 800, color: 'var(--text-heading)', lineHeight: 1.1 }}>{value}</div>
                <div className="text-muted" style={{ fontSize: '0.8rem' }}>{label}</div>
                {sub && <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '2px' }}>{sub}</div>}
            </div>
        </div>
    );

    const podBadge = (phase) => {
        const map = { Running: 'badge-success', Succeeded: 'badge-info', Pending: 'badge-warning', Failed: 'badge-danger', Unknown: 'badge-warning' };
        return <span className={`badge ${map[phase] || 'badge-warning'}`}><span className="status-dot" /> {phase}</span>;
    };

    return (
        <div className="panel-container">
            {header}

            {error && <div className="alert alert-danger">{error}</div>}

            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '20px' }}>
                {tabs.map(t => (
                    <button key={t.id} className={`btn ${tab === t.id ? 'btn-primary' : 'btn-secondary'} btn-sm`} onClick={() => setTab(t.id)}>
                        <t.icon size={14} /> {t.label}
                    </button>
                ))}
            </div>

            {tab === 'overview' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
                    <div className="grid-cols-4 stagger">
                        <StatCard icon={Server} label="Ноды кластера" value={c.nodes} sub={`${(data.nodes || []).filter(n => n.ready === 'Ready').length} Ready`} />
                        <StatCard icon={Package} label="Поды" value={`${c.pods_running}/${c.pods_total}`} sub="запущено / всего" />
                        <StatCard icon={Layers} label="Namespaces" value={c.namespaces} />
                        <StatCard icon={Boxes} label="Виртуальные машины" value={c.vms} sub="KubeVirt VMI" />
                    </div>

                    <div className="glass-card accent-top">
                        <div className="section-title"><ShieldCheck size={18} /> Версии компонентов</div>
                        <div className="grid-cols-4">
                            {[
                                ['Kubernetes', data.k8s_version],
                                ['KubeVirt', data.kubevirt_version],
                                ['CDI (импорт дисков)', data.cdi_version],
                                ['Storage Class', data.storage_class],
                            ].map(([k, v]) => (
                                <div key={k} className="connect-tile">
                                    <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.5px', fontWeight: 600 }}>{k}</div>
                                    <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--text-heading)', marginTop: '4px', wordBreak: 'break-all' }}>{v}</div>
                                </div>
                            ))}
                        </div>
                    </div>

                    <div className="glass-card">
                        <div className="section-title"><CircleDot size={18} /> Feature Gates KubeVirt ({(data.feature_gates || []).length})</div>
                        {(data.feature_gates || []).length ? (
                            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                {data.feature_gates.map(fg => (
                                    <span key={fg} className="badge badge-info" style={{ fontFamily: 'var(--font-mono)' }}>{fg}</span>
                                ))}
                            </div>
                        ) : <p className="text-muted">Feature-gates не заданы (стандартная конфигурация).</p>}
                    </div>
                </div>
            )}

            {tab === 'nodes' && (
                <div className="grid-cols-3 stagger">
                    {(data.nodes || []).map(n => (
                        <div key={n.name} className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                    <div className="connect-tile-icon" style={{ width: '38px', height: '38px' }}><Server size={18} /></div>
                                    <div>
                                        <div style={{ fontWeight: 700, color: 'var(--text-heading)' }}>{n.name}</div>
                                        <div style={{ display: 'flex', gap: '4px', marginTop: '2px' }}>
                                            {n.roles.map(r => <span key={r} className="badge badge-info" style={{ fontSize: '0.65rem' }}>{r}</span>)}
                                        </div>
                                    </div>
                                </div>
                                <span className={`badge ${n.ready === 'Ready' ? 'badge-success' : 'badge-danger'}`}><span className="status-dot" /> {n.ready}</span>
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.82rem' }}>
                                <Row icon={Network} k="IP" v={n.internal_ip} mono />
                                <Row icon={Cpu} k="CPU / RAM" v={`${n.cpu} ядер · ${n.memory_gb} ГБ`} />
                                <Row icon={Package} k="Подов" v={n.pods} />
                                <Row icon={Boxes} k="Kubelet" v={n.version} mono />
                                <Row icon={HardDrive} k="ОС" v={n.os_image} />
                                <Row icon={Terminal} k="Runtime" v={n.container_runtime} mono />
                            </div>
                            {!n.schedulable && <span className="badge badge-warning" style={{ width: 'fit-content' }}>Планирование отключено</span>}
                        </div>
                    ))}
                </div>
            )}

            {tab === 'pods' && (
                <div>
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '14px' }}>
                        <button className={`btn ${nsFilter === 'all' ? 'btn-primary' : 'btn-secondary'} btn-sm`} onClick={() => setNsFilter('all')}>Все namespaces</button>
                        {namespaces.map(ns => (
                            <button key={ns} className={`btn ${nsFilter === ns ? 'btn-primary' : 'btn-secondary'} btn-sm`} onClick={() => setNsFilter(ns)}>{ns}</button>
                        ))}
                    </div>
                    <div className="table-responsive">
                        <table className="table">
                            <thead><tr><th>Namespace</th><th>Под</th><th>Статус</th><th>Нода</th><th>Рестарты</th></tr></thead>
                            <tbody>
                                {pods.map((p, i) => (
                                    <tr key={i}>
                                        <td><span className="badge badge-info" style={{ fontSize: '0.68rem' }}>{p.namespace}</span></td>
                                        <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>{p.name}</td>
                                        <td>{podBadge(p.phase)}</td>
                                        <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{p.node}</td>
                                        <td style={{ color: p.restarts > 0 ? 'var(--status-warning)' : 'var(--text-muted)' }}>{p.restarts}</td>
                                    </tr>
                                ))}
                                {pods.length === 0 && <tr><td colSpan="5" style={{ textAlign: 'center', padding: '30px', color: 'var(--text-muted)' }}>Подов нет</td></tr>}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {tab === 'install' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                    <div className="alert alert-info" style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                        <Info size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
                        <span>Кластер уже развёрнут на этом сервере (K3s + KubeVirt). Ниже — как присоединить ещё одну вычислительную ноду и с чего собирается кластер.</span>
                    </div>

                    <InstallStep n="1" title="Присоединить новую worker-ноду">
                        <p className="text-muted" style={{ marginBottom: '10px' }}>
                            Выполните на новом сервере (Ubuntu 22.04/24.04). Команда содержит адрес master-ноды и токен присоединения:
                        </p>
                        <CodeBlock text={join?.join_command || 'Загрузка команды присоединения...'} copied={copied === 'join'} onCopy={() => copy(join?.join_command || '', 'join')} />
                        {!join?.available && <p className="text-muted" style={{ fontSize: '0.75rem', marginTop: '6px' }}>Токен недоступен — панель не смогла прочитать его на хосте. Master IP: {join?.master_ip || '—'}.</p>}
                    </InstallStep>

                    <InstallStep n="2" title="Или через готовый скрипт из репозитория">
                        <CodeBlock text={"git clone https://github.com/Monopoly450/Hosting.git ~/Hosting\ncd ~/Hosting\nsudo ./scripts/bootstrap-cluster-node2.sh"} copied={copied === 's'} onCopy={() => copy('git clone https://github.com/Monopoly450/Hosting.git ~/Hosting\ncd ~/Hosting\nsudo ./scripts/bootstrap-cluster-node2.sh', 's')} />
                        <p className="text-muted" style={{ fontSize: '0.8rem', marginTop: '8px' }}>Скрипт спросит IP master-ноды и K3S join-token (см. шаг 1).</p>
                    </InstallStep>

                    <InstallStep n="3" title="Из чего состоит кластер">
                        <ul style={{ margin: 0, paddingLeft: '18px', color: 'var(--text-secondary)', fontSize: '0.88rem', lineHeight: 1.8 }}>
                            <li><b>K3s</b> — лёгкий Kubernetes (без traefik/servicelb).</li>
                            <li><b>KubeVirt</b> — запуск ВМ (QEMU/KVM) как подов.</li>
                            <li><b>CDI</b> — импорт дисков ВМ из облачных образов/ISO.</li>
                            <li><b>Multus CNI</b> — доп. сетевые интерфейсы (мост br-vms для стабильных IP).</li>
                            <li><b>Storage</b> — {data.storage_class} (local-path / OpenEBS LVM / NFS для HA).</li>
                        </ul>
                    </InstallStep>
                </div>
            )}
        </div>
    );
}

function Row({ icon: Icon, k, v, mono }) {
    return (
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
            <span className="text-muted" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><Icon size={13} /> {k}</span>
            <span style={{ fontFamily: mono ? 'var(--font-mono)' : 'inherit', color: 'var(--text-primary)', fontWeight: 500, textAlign: 'right', wordBreak: 'break-all' }}>{v}</span>
        </div>
    );
}

function InstallStep({ n, title, children }) {
    return (
        <div className="glass-card">
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
                <div style={{ width: '28px', height: '28px', borderRadius: '50%', background: 'var(--gradient-accent)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: '0.85rem', flexShrink: 0 }}>{n}</div>
                <h3 style={{ margin: 0, fontSize: '1.05rem', color: 'var(--text-heading)' }}>{title}</h3>
            </div>
            {children}
        </div>
    );
}

function CodeBlock({ text, copied, onCopy }) {
    return (
        <div style={{ position: 'relative' }}>
            <pre style={{ background: 'var(--bg-surface-hover)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: '16px 48px 16px 16px', fontFamily: 'var(--font-mono)', fontSize: '0.82rem', color: 'var(--text-primary)', overflowX: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: 0 }}>{text}</pre>
            <button className="btn-icon" style={{ position: 'absolute', top: '10px', right: '10px' }} onClick={onCopy}>
                {copied ? <Check size={16} color="var(--status-success)" /> : <Copy size={16} />}
            </button>
        </div>
    );
}
