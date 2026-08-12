import React, { useState, useEffect } from 'react';
import { FolderKanban, Plus, Trash2, X, Users, Server, Database, Rocket, UserPlus, Link2, HardDrive } from 'lucide-react';
import CustomSelect from './CustomSelect';

const ROLE_LABEL = { owner: 'владелец', editor: 'редактор', viewer: 'наблюдатель', admin: 'админ' };
const ROLE_HINT = {
    owner: 'Полный доступ, включая управление участниками',
    editor: 'Может управлять ресурсами проекта',
    viewer: 'Только просмотр',
};

export default function ProjectsPanel() {
    const [projects, setProjects] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [showCreate, setShowCreate] = useState(false);
    const [busy, setBusy] = useState(false);

    const [selected, setSelected] = useState(null);   // открытый проект
    const [members, setMembers] = useState([]);
    const [resources, setResources] = useState({ vm: [], database: [], deployment: [], bucket: [] });

    // формы
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [memberName, setMemberName] = useState('');
    const [memberRole, setMemberRole] = useState('viewer');
    const [resType, setResType] = useState('vm');
    const [resId, setResId] = useState('');

    const headers = () => ({
        'Authorization': `Bearer ${localStorage.getItem('aegis_admin_token') || ''}`,
        'Content-Type': 'application/json',
    });

    const fetchProjects = async () => {
        try {
            const res = await fetch('/api/projects', { headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка загрузки проектов');
            setProjects(await res.json());
            setError('');
        } catch (e) { setError(e.message); } finally { setLoading(false); }
    };

    const fetchResources = async () => {
        const [v, d, dep, s3] = await Promise.all([
            fetch('/api/vms', { headers: headers() }),
            fetch('/api/databases', { headers: headers() }),
            fetch('/api/deployments', { headers: headers() }),
            fetch('/api/s3', { headers: headers() }),
        ]);
        setResources({
            vm: v.ok ? (await v.json()).filter(x => x.id) : [],
            database: d.ok ? await d.json() : [],
            deployment: dep.ok ? await dep.json() : [],
            bucket: s3.ok ? await s3.json() : [],
        });
    };

    useEffect(() => { fetchProjects(); fetchResources(); }, []);

    const openProject = async (p) => {
        setSelected(p);
        try {
            const res = await fetch(`/api/projects/${p.id}/members`, { headers: headers() });
            setMembers(res.ok ? await res.json() : []);
        } catch { setMembers([]); }
    };

    const createProject = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            const res = await fetch('/api/projects', {
                method: 'POST', headers: headers(),
                body: JSON.stringify({ name: name.trim(), description: description.trim() || null }),
            });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка');
            setShowCreate(false); setName(''); setDescription('');
            fetchProjects();
        } catch (e) { alert(`Ошибка: ${e.message}`); } finally { setBusy(false); }
    };

    const removeProject = async (id) => {
        if (!confirm('Удалить проект? Ресурсы не удалятся — они просто открепятся от проекта.')) return;
        try {
            const res = await fetch(`/api/projects/${id}`, { method: 'DELETE', headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка');
            setSelected(null);
            fetchProjects();
        } catch (e) { alert(`Ошибка: ${e.message}`); }
    };

    const addMember = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            const res = await fetch(`/api/projects/${selected.id}/members`, {
                method: 'POST', headers: headers(),
                body: JSON.stringify({ username: memberName.trim(), role: memberRole }),
            });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка');
            setMemberName('');
            openProject(selected); fetchProjects();
        } catch (e) { alert(`Ошибка: ${e.message}`); } finally { setBusy(false); }
    };

    const removeMember = async (userId) => {
        try {
            const res = await fetch(`/api/projects/${selected.id}/members/${userId}`, { method: 'DELETE', headers: headers() });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка');
            openProject(selected); fetchProjects();
        } catch (e) { alert(`Ошибка: ${e.message}`); }
    };

    const assign = async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
            const res = await fetch('/api/projects/assign', {
                method: 'POST', headers: headers(),
                body: JSON.stringify({ resource_type: resType, resource_id: parseInt(resId), project_id: selected.id }),
            });
            if (!res.ok) throw new Error((await res.json()).detail || 'Ошибка');
            setResId('');
            fetchProjects(); fetchResources();
        } catch (e) { alert(`Ошибка: ${e.message}`); } finally { setBusy(false); }
    };

    const canManage = (p) => p.my_role === 'owner' || p.my_role === 'admin';

    if (loading) return <div className="panel-container"><div style={{ display: 'flex', justifyContent: 'center', padding: '50px' }}><div className="spinner spinner-lg" /></div></div>;

    return (
        <div className="panel-container">
            <div className="panel-header">
                <div>
                    <h2 className="panel-title">Проекты и доступы</h2>
                    <p className="panel-subtitle">Объединяйте ресурсы в проекты и давайте коллегам доступ по ролям</p>
                </div>
                <button className="btn btn-primary" onClick={() => setShowCreate(true)}><Plus size={16} /> Новый проект</button>
            </div>

            {error && <div className="alert alert-danger">{error}</div>}

            {projects.length === 0 ? (
                <div className="glass-card" style={{ textAlign: 'center', padding: '54px 20px' }}>
                    <FolderKanban size={44} style={{ color: 'var(--text-muted)', marginBottom: '12px' }} />
                    <h3 className="section-title" style={{ justifyContent: 'center' }}>Проектов пока нет</h3>
                    <p className="text-muted">Создайте проект, чтобы делиться ВМ, базами и деплоями с командой.</p>
                </div>
            ) : (
                // grid-cols-3 — единый размер плиток с серверами и инстансами
                <div className="grid-cols-3">
                    {projects.map(p => (
                        <div key={p.id} className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '10px', cursor: 'pointer', outline: selected?.id === p.id ? '1px solid var(--accent-primary)' : 'none' }} onClick={() => openProject(p)}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                <FolderKanban size={20} style={{ color: 'var(--accent-primary)' }} />
                                <div style={{ fontWeight: 700, flex: 1 }}>{p.name}</div>
                                <span className="badge">{ROLE_LABEL[p.my_role] || p.my_role}</span>
                            </div>
                            {p.description && <p className="text-muted" style={{ fontSize: '0.8rem', margin: 0 }}>{p.description}</p>}
                            <div style={{ display: 'flex', gap: '12px', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}><Users size={13} /> {p.members_count}</span>
                                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}><Server size={13} /> {p.resources.vm}</span>
                                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}><Database size={13} /> {p.resources.database}</span>
                                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}><Rocket size={13} /> {p.resources.deployment}</span>
                                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }} title="Бакеты S3"><HardDrive size={13} /> {p.resources.bucket ?? 0}</span>
                            </div>
                            <div className="text-muted" style={{ fontSize: '0.74rem' }}>владелец: {p.owner_username}</div>
                        </div>
                    ))}
                </div>
            )}

            {/* Детали выбранного проекта */}
            {selected && (
                <div className="glass-card" style={{ marginTop: '20px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
                        <div className="section-title" style={{ margin: 0 }}><FolderKanban size={16} /> {selected.name}</div>
                        <div style={{ display: 'flex', gap: '8px' }}>
                            {canManage(selected) && <button className="btn btn-danger btn-sm" onClick={() => removeProject(selected.id)}><Trash2 size={13} /> Удалить проект</button>}
                            <button className="btn-icon" onClick={() => setSelected(null)}><X size={16} /></button>
                        </div>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '20px' }}>
                        {/* Участники */}
                        <div>
                            <div className="section-title" style={{ fontSize: '0.9rem' }}><Users size={15} /> Участники</div>
                            {members.length === 0 ? <p className="text-muted" style={{ fontSize: '0.8rem' }}>Нет участников</p> : (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '12px' }}>
                                    {members.map(m => (
                                        <div key={m.user_id} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem' }}>
                                            <span style={{ fontWeight: 600 }}>{m.username}</span>
                                            <span className="badge" title={ROLE_HINT[m.role]}>{ROLE_LABEL[m.role] || m.role}</span>
                                            {canManage(selected) && m.role !== 'owner' && (
                                                <button className="btn-icon" style={{ marginLeft: 'auto' }} title="Исключить" onClick={() => removeMember(m.user_id)}><Trash2 size={13} style={{ color: '#e5484d' }} /></button>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            )}
                            {canManage(selected) && (
                                <form onSubmit={addMember} style={{ display: 'flex', gap: '6px', alignItems: 'flex-end' }}>
                                    <div className="input-group" style={{ marginBottom: 0, flex: 1 }}>
                                        <label className="input-label">Пользователь</label>
                                        <input className="form-control" value={memberName} onChange={e => setMemberName(e.target.value)} placeholder="логин" required />
                                    </div>
                                    <div className="input-group" style={{ marginBottom: 0, width: '130px' }}>
                                        <label className="input-label">Роль</label>
                                        <CustomSelect
                                            value={memberRole}
                                            onChange={e => setMemberRole(e.target.value)}
                                            options={[
                                                { value: 'viewer', label: 'наблюдатель' },
                                                { value: 'editor', label: 'редактор' },
                                                { value: 'owner', label: 'владелец' },
                                            ]}
                                        />
                                    </div>
                                    <button type="submit" className="btn btn-secondary btn-sm" disabled={busy || !memberName.trim()}><UserPlus size={14} /></button>
                                </form>
                            )}
                        </div>

                        {/* Ресурсы */}
                        <div>
                            <div className="section-title" style={{ fontSize: '0.9rem' }}><Link2 size={15} /> Добавить ресурс в проект</div>
                            <p className="text-muted" style={{ fontSize: '0.78rem' }}>
                                Ресурс станет виден участникам проекта. Наблюдатели смогут только смотреть, редакторы — управлять.
                            </p>
                            <form onSubmit={assign} style={{ display: 'flex', gap: '6px', alignItems: 'flex-end' }}>
                                {/* 165px — чтобы «Хранилище S3» помещалось в одну строку */}
                                <div className="input-group" style={{ marginBottom: 0, width: '165px' }}>
                                    <label className="input-label">Тип</label>
                                    <CustomSelect
                                        value={resType}
                                        onChange={e => { setResType(e.target.value); setResId(''); }}
                                        options={[
                                            { value: 'vm', label: 'Виртуалка' },
                                            { value: 'database', label: 'База данных' },
                                            { value: 'deployment', label: 'Деплой' },
                                            { value: 'bucket', label: 'Хранилище S3' },
                                        ]}
                                    />
                                </div>
                                <div className="input-group" style={{ marginBottom: 0, flex: 1 }}>
                                    <label className="input-label">Ресурс</label>
                                    <CustomSelect
                                        value={resId}
                                        onChange={e => setResId(e.target.value)}
                                        placeholder="— выберите —"
                                        options={(resources[resType] || []).map(r => ({
                                            value: r.id, label: r.name || r.db_name || r.bucket_name,
                                        }))}
                                    />
                                </div>
                                <button type="submit" className="btn btn-secondary btn-sm" disabled={busy || !resId}><Link2 size={14} /></button>
                            </form>
                        </div>
                    </div>
                </div>
            )}

            {showCreate && (
                <div className="modal-overlay" onClick={() => setShowCreate(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '440px' }}>
                        <div className="modal-header"><h2>Новый проект</h2><button className="btn-close" onClick={() => setShowCreate(false)} type="button"><X size={18} /></button></div>
                        <form onSubmit={createProject}>
                            <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label">Название</label>
                                    <input className="form-control" value={name} onChange={e => setName(e.target.value)} placeholder="например: Курсовая работа" required autoFocus />
                                </div>
                                <div className="input-group" style={{ marginBottom: 0 }}>
                                    <label className="input-label">Описание (необязательно)</label>
                                    <input className="form-control" value={description} onChange={e => setDescription(e.target.value)} />
                                </div>
                            </div>
                            <div className="modal-actions">
                                <button type="button" className="btn btn-secondary" onClick={() => setShowCreate(false)} disabled={busy}>Отмена</button>
                                <button type="submit" className="btn btn-primary" disabled={busy || !name.trim()}>{busy ? <span className="spinner" /> : 'Создать'}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}
