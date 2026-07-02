import React, { useState, useEffect } from 'react';
import { HardDrive, Plus, Trash2, Link2, Unlink, Info } from 'lucide-react';

export default function VolumesPanel() {
    const [volumes, setVolumes] = useState([]);
    const [vms, setVms] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [showAttachModal, setShowAttachModal] = useState(false);

    // Form fields
    const [volName, setVolName] = useState('');
    const [sizeGb, setSizeGb] = useState(10);
    const [selectedVolId, setSelectedVolId] = useState(null);
    const [selectedVmName, setSelectedVmName] = useState('');
    const [submitting, setSubmitting] = useState(false);

    const getHeaders = () => {
        const token = localStorage.getItem('aegis_admin_token') || '';
        return {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
        };
    };

    const fetchData = async () => {
        setLoading(true);
        try {
            // Fetch volumes
            const volRes = await fetch('/api/volumes', { headers: getHeaders() });
            if (!volRes.ok) {
                const data = await volRes.json();
                throw new Error(data.detail || 'Ошибка при загрузке данных дисков');
            }
            const volData = await volRes.json();
            setVolumes(volData);

            // Fetch VMs
            const vmRes = await fetch('/api/vms', { headers: getHeaders() });
            if (!vmRes.ok) {
                const data = await vmRes.json();
                throw new Error(data.detail || 'Ошибка при загрузке списка ВМ');
            }
            const vmData = await vmRes.json();
            setVms(vmData);
            
            if (vmData.length > 0) {
                setSelectedVmName(vmData[0].name);
            }
            
            setError('');
        } catch (err) {
            setError(err.message || 'Ошибка при загрузке данных дисков');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchData();
    }, []);

    const handleCreateVolume = async (e) => {
        e.preventDefault();
        setSubmitting(true);
        try {
            const res = await fetch('/api/volumes', {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({
                    name: volName,
                    size_gb: Number(sizeGb)
                })
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка при создании диска');
            }
            
            setShowCreateModal(false);
            setVolName('');
            setSizeGb(10);
            fetchData();
        } catch (err) {
            alert(err.message || 'Ошибка при создании диска');
        } finally {
            setSubmitting(false);
        }
    };

    const handleDeleteVolume = async (volId) => {
        if (!confirm('Вы уверены, что хотите удалить этот сетевой диск? Все данные на нём будут стёрты!')) return;
        try {
            const res = await fetch(`/api/volumes/${volId}`, {
                method: 'DELETE',
                headers: getHeaders()
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка при удалении диска');
            }
            fetchData();
        } catch (err) {
            alert(err.message || 'Ошибка при удалении диска');
        }
    };

    const handleAttachVolume = async (e) => {
        e.preventDefault();
        if (!selectedVmName) {
            alert('Сначала создайте виртуальную машину!');
            return;
        }
        setSubmitting(true);
        try {
            const res = await fetch(`/api/volumes/${selectedVolId}/attach/${selectedVmName}`, {
                method: 'POST',
                headers: getHeaders()
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка подключения диска');
            }
            setShowAttachModal(false);
            fetchData();
        } catch (err) {
            alert(err.message || 'Ошибка подключения диска');
        } finally {
            setSubmitting(false);
        }
    };

    const handleDetachVolume = async (volId) => {
        if (!confirm('Отключить диск от виртуальной машины? Это безопасное извлечение.')) return;
        try {
            const res = await fetch(`/api/volumes/${volId}/detach`, {
                method: 'POST',
                headers: getHeaders()
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка отключения диска');
            }
            fetchData();
        } catch (err) {
            alert(err.message || 'Ошибка отключения диска');
        }
    };

    return (
        <div className="panel-container">
            <div className="panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <div>
                    <h2 className="panel-title">Сетевые диски (Persistent Volumes)</h2>
                    <p className="panel-subtitle">Динамическое создание и горячее подключение (hotplug) дисков к ВМ</p>
                </div>
                <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
                    <Plus size={16} /> Создать диск
                </button>
            </div>

            {error && <div className="alert alert-danger">{error}</div>}

            {loading ? (
                <div style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}>
                    <div className="spinner"></div>
                </div>
            ) : (
                <div className="table-responsive">
                    <table className="table">
                        <thead>
                            <tr>
                                <th>Имя диска</th>
                                <th>Размер</th>
                                <th>Статус</th>
                                <th>Подключен к VM</th>
                                <th>Дата создания</th>
                                <th>Владелец</th>
                                <th>Действия</th>
                            </tr>
                        </thead>
                        <tbody>
                            {volumes.map(v => (
                                <tr key={v.id}>
                                    <td style={{ fontWeight: 'bold' }}>{v.name}</td>
                                    <td>{v.size_gb} ГБ</td>
                                    <td>
                                        <span className={`status-badge ${v.status === 'Attached' ? 'status-active' : 'status-pending'}`}>
                                            {v.status === 'Attached' ? 'Подключен' : 'Свободен'}
                                        </span>
                                    </td>
                                    <td>
                                        {v.attached_vm_name ? (
                                            <span style={{ fontWeight: 600 }}>{v.attached_vm_name}</span>
                                        ) : (
                                            <span style={{ color: '#888', fontStyle: 'italic' }}>—</span>
                                        )}
                                    </td>
                                    <td>{v.created_at}</td>
                                    <td>{v.owner_username}</td>
                                    <td>
                                        <div style={{ display: 'flex', gap: '8px' }}>
                                            {v.status === 'Attached' ? (
                                                <button 
                                                    className="btn btn-secondary btn-sm" 
                                                    onClick={() => handleDetachVolume(v.id)}
                                                    style={{ display: 'flex', alignItems: 'center', gap: '4px' }}
                                                >
                                                    <Unlink size={12} /> Отключить
                                                </button>
                                            ) : (
                                                <button 
                                                    className="btn btn-secondary btn-sm" 
                                                    onClick={() => { setSelectedVolId(v.id); setShowAttachModal(true); }}
                                                    style={{ display: 'flex', alignItems: 'center', gap: '4px' }}
                                                >
                                                    <Link2 size={12} /> Подключить
                                                </button>
                                            )}
                                            <button 
                                                className="btn btn-danger btn-sm" 
                                                onClick={() => handleDeleteVolume(v.id)}
                                                style={{ display: 'flex', alignItems: 'center', gap: '4px' }}
                                            >
                                                <Trash2 size={12} /> Удалить
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                            {volumes.length === 0 && (
                                <tr>
                                    <td colSpan="7" style={{ textAlign: 'center', padding: '30px', color: '#888' }}>
                                        <HardDrive size={32} style={{ marginBottom: '8px', opacity: 0.5 }} />
                                        <div>Нет активных сетевых дисков. Создайте первый!</div>
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            )}

            {showCreateModal && (
                <div className="slide-over-overlay" onClick={() => setShowCreateModal(false)}>
                    <div className="slide-over-content" onClick={e => e.stopPropagation()}>
                        <div className="slide-over-header">
                            <h2>Создание сетевого диска</h2>
                            <button className="btn-close" onClick={() => setShowCreateModal(false)}>×</button>
                        </div>
                        <form onSubmit={handleCreateVolume} style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                            <div className="slide-over-body">
                                <div className="input-group">
                                    <label className="input-label">Имя тома</label>
                                    <input 
                                        type="text" 
                                        className="form-control" 
                                        value={volName} 
                                        onChange={e => setVolName(e.target.value)} 
                                        required 
                                        placeholder="Например, shared-data"
                                    />
                                    <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px' }}>
                                        Только строчные латинские буквы, цифры и дефис.
                                    </span>
                                </div>

                                <div className="input-group">
                                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                                        <label className="input-label">Размер диска (ГБ)</label>
                                        <span style={{ fontWeight: 600, color: 'var(--accent-primary)' }}>{sizeGb} ГБ</span>
                                    </div>
                                    <input 
                                        type="range" 
                                        min="1" 
                                        max="200" 
                                        value={sizeGb} 
                                        onChange={e => setSizeGb(e.target.value)} 
                                        style={{ width: '100%' }}
                                    />
                                </div>

                                <div style={{ background: 'var(--bg-surface-hover)', padding: '12px', borderRadius: '8px', marginTop: '20px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                    <Info size={16} style={{ marginRight: '8px', verticalAlign: 'middle', color: 'var(--accent-primary)' }} />
                                    Диски создаются мгновенно в СХД Kubernetes и могут монтироваться на лету (hotplug) без перезагрузки ВМ.
                                </div>
                            </div>

                            <div className="slide-over-actions">
                                <button type="button" className="btn btn-secondary" onClick={() => setShowCreateModal(false)} disabled={submitting}>
                                    Отмена
                                </button>
                                <button type="submit" className="btn btn-primary" disabled={submitting}>
                                    {submitting ? 'Создание...' : 'Создать'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {showAttachModal && (
                <div className="slide-over-overlay" onClick={() => setShowAttachModal(false)}>
                    <div className="slide-over-content" onClick={e => e.stopPropagation()}>
                        <div className="slide-over-header">
                            <h2>Подключение диска к ВМ</h2>
                            <button className="btn-close" onClick={() => setShowAttachModal(false)}>×</button>
                        </div>
                        <form onSubmit={handleAttachVolume} style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                            <div className="slide-over-body">
                                <div className="input-group">
                                    <label className="input-label">Выберите виртуальную машину</label>
                                    <select className="form-control" value={selectedVmName} onChange={e => setSelectedVmName(e.target.value)} required>
                                        {vms.map(vm => (
                                            <option key={vm.name} value={vm.name}>{vm.name} ({vm.status})</option>
                                        ))}
                                        {vms.length === 0 && <option value="" disabled>У вас нет виртуальных машин</option>}
                                    </select>
                                </div>

                                <div style={{ background: 'var(--bg-surface-hover)', padding: '12px', borderRadius: '8px', marginTop: '20px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                    <Info size={16} style={{ marginRight: '8px', verticalAlign: 'middle', color: 'var(--accent-primary)' }} />
                                    После подключения диск отобразится внутри ВМ как новое блочное устройство `/dev/vd*`.
                                </div>
                            </div>

                            <div className="slide-over-actions">
                                <button type="button" className="btn btn-secondary" onClick={() => setShowAttachModal(false)} disabled={submitting}>
                                    Отмена
                                </button>
                                <button type="submit" className="btn btn-primary" disabled={submitting || vms.length === 0}>
                                    {submitting ? 'Подключение...' : 'Подключить'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}
