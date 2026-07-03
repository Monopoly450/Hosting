import React, { useState, useEffect } from 'react';
import { Database, Plus, Trash2, Key, Info, Copy, Eye, EyeOff, X, Link2, Unlink } from 'lucide-react';
import CustomSelect from './CustomSelect';

export default function DatabasesPanel() {
    const [databases, setDatabases] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [showCreateModal, setShowCreateModal] = useState(false);
    
    // Form fields
    const [dbName, setDbName] = useState('');
    const [engine, setEngine] = useState('postgresql');
    const [submitting, setSubmitting] = useState(false);
    
    // Visibility of password
    const [visiblePasswords, setVisiblePasswords] = useState({});

    // VM and Bind states
    const [vms, setVms] = useState([]);
    const [showBindModal, setShowBindModal] = useState(false);
    const [selectedDbId, setSelectedDbId] = useState(null);
    const [selectedVmId, setSelectedVmId] = useState('');

    const getHeaders = () => {
        const token = localStorage.getItem('aegis_admin_token') || '';
        return {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
        };
    };

    const fetchDatabases = async () => {
        setLoading(true);
        try {
            const res = await fetch('/api/databases', {
                headers: getHeaders()
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка при загрузке списка баз данных');
            }
            const data = await res.json();
            setDatabases(data);
            setError('');
        } catch (err) {
            setError(err.message || 'Ошибка при загрузке списка баз данных');
        } finally {
            setLoading(false);
        }
    };

    const fetchVMs = async () => {
        try {
            const res = await fetch('/api/vms', {
                headers: getHeaders()
            });
            if (res.ok) {
                const data = await res.json();
                setVms(data);
            }
        } catch (err) {
            console.error('Ошибка при загрузке ВМ:', err);
        }
    };

    const handleBindVM = async (e) => {
        e.preventDefault();
        if (!selectedDbId) return;
        setSubmitting(true);
        try {
            const res = await fetch(`/api/databases/${selectedDbId}/bind`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({
                    vm_id: selectedVmId ? parseInt(selectedVmId) : null
                })
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка при привязке базы данных');
            }
            setShowBindModal(false);
            setSelectedDbId(null);
            setSelectedVmId('');
            fetchDatabases();
        } catch (err) {
            alert(err.message || 'Ошибка при привязке базы данных');
        } finally {
            setSubmitting(false);
        }
    };

    const handleUnbindVM = async (dbId) => {
        if (!confirm('Вы уверены, что хотите отвязать базу данных от виртуальной машины?')) return;
        try {
            const res = await fetch(`/api/databases/${dbId}/bind`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({
                    vm_id: null
                })
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка при отвязке базы данных');
            }
            fetchDatabases();
        } catch (err) {
            alert(err.message || 'Ошибка при отвязке базы данных');
        }
    };

    useEffect(() => {
        fetchDatabases();
        fetchVMs();
    }, []);

    const handleCreateDatabase = async (e) => {
        e.preventDefault();
        setSubmitting(true);
        try {
            const res = await fetch('/api/databases', {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({
                    name: dbName,
                    engine
                })
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка создания базы данных');
            }
            
            setShowCreateModal(false);
            setDbName('');
            setEngine('postgresql');
            fetchDatabases();
        } catch (err) {
            alert(err.message || 'Ошибка создания базы данных');
        } finally {
            setSubmitting(false);
        }
    };

    const handleDeleteDatabase = async (dbId) => {
        if (!confirm('Вы уверены, что хотите удалить эту базу данных? Все данные будут стёрты навсегда!')) return;
        try {
            const res = await fetch(`/api/databases/${dbId}`, {
                method: 'DELETE',
                headers: getHeaders()
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка при удалении базы данных');
            }
            fetchDatabases();
        } catch (err) {
            alert(err.message || 'Ошибка при удалении базы данных');
        }
    };

    const togglePasswordVisibility = (dbId) => {
        setVisiblePasswords(prev => ({
            ...prev,
            [dbId]: !prev[dbId]
        }));
    };

    const copyToClipboard = (text) => {
        navigator.clipboard.writeText(text);
        alert('Скопировано в буфер обмена!');
    };

    const getHostIP = () => {
        return window.location.hostname;
    };

    const getVmIp = (vm) => {
        if (!vm || !vm.ips || vm.ips.length === 0) return null;
        const bridgeIp = vm.ips.find(ip => 
            !ip.startsWith('10.244.') && 
            !ip.startsWith('10.42.') && 
            !ip.startsWith('10.0.2.') && 
            !ip.startsWith('127.0.') && 
            !ip.includes(':')
        );
        return bridgeIp || vm.ips[0] || null;
    };

    return (
        <div className="panel-container">
            <div className="panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <div>
                    <h2 className="panel-title">Управляемые базы данных</h2>
                    <p className="panel-subtitle">Изолированные БД PostgreSQL и MySQL для ваших проектов</p>
                </div>
                <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
                    <Plus size={16} /> Создать БД
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
                                <th>Имя БД</th>
                                <th>СУБД</th>
                                <th>Адрес подключения (Host)</th>
                                <th>Порт</th>
                                <th>Пользователь</th>
                                <th>Пароль</th>
                                <th>Связанная ВМ</th>
                                <th>Владелец</th>
                                <th>Действия</th>
                            </tr>
                        </thead>
                        <tbody>
                            {databases.map(d => (
                                <tr key={d.id}>
                                    <td style={{ fontWeight: 'bold' }}>{d.db_name}</td>
                                    <td>
                                        <span className={`status-badge ${d.engine === 'postgresql' ? 'status-active' : 'status-pending'}`}>
                                            {d.engine === 'postgresql' ? 'PostgreSQL' : 'MySQL/MariaDB'}
                                        </span>
                                    </td>
                                    <td>
                                        <span style={{ fontFamily: 'monospace', background: 'var(--bg-surface)', padding: '2px 6px', borderRadius: '4px' }}>
                                            {d.db_host || getHostIP()}
                                        </span>
                                    </td>
                                    <td>{d.engine === 'postgresql' ? '5432' : '3306'}</td>
                                    <td>
                                        <span style={{ fontFamily: 'monospace' }}>{d.db_user}</span>
                                    </td>
                                    <td>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                            <input 
                                                type={visiblePasswords[d.id] ? 'text' : 'password'} 
                                                value={d.db_password} 
                                                readOnly 
                                                style={{ 
                                                    background: 'transparent', 
                                                    border: 'none', 
                                                    color: 'var(--text-primary)', 
                                                    fontFamily: 'monospace',
                                                    width: '120px'
                                                }}
                                            />
                                            <button 
                                                className="btn-icon" 
                                                onClick={() => togglePasswordVisibility(d.id)}
                                                title="Показать/скрыть"
                                            >
                                                {visiblePasswords[d.id] ? <EyeOff size={14} /> : <Eye size={14} />}
                                            </button>
                                            <button 
                                                className="btn-icon" 
                                                onClick={() => copyToClipboard(d.db_password)}
                                                title="Копировать"
                                            >
                                                <Copy size={14} />
                                            </button>
                                        </div>
                                    </td>
                                    <td>
                                        {d.associated_vm_name ? (
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--accent-primary)', background: 'var(--bg-surface-hover)', padding: '4px 8px', borderRadius: '4px' }}>
                                                    {d.associated_vm_name}
                                                </span>
                                                <button 
                                                    className="btn-icon" 
                                                    onClick={() => handleUnbindVM(d.id)}
                                                    title="Отвязать от ВМ"
                                                    style={{ color: '#ef4444' }}
                                                >
                                                    <Unlink size={14} />
                                                </button>
                                            </div>
                                        ) : (
                                            <button 
                                                className="btn btn-secondary btn-sm" 
                                                onClick={() => {
                                                    setSelectedDbId(d.id);
                                                    setShowBindModal(true);
                                                }}
                                                style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem', padding: '4px 8px' }}
                                            >
                                                <Link2 size={12} /> Привязать
                                            </button>
                                        )}
                                    </td>
                                    <td>{d.owner_username}</td>
                                    <td>
                                        <button 
                                            className="btn btn-danger btn-sm" 
                                            onClick={() => handleDeleteDatabase(d.id)}
                                            style={{ display: 'flex', alignItems: 'center', gap: '4px' }}
                                        >
                                            <Trash2 size={12} /> Удалить
                                        </button>
                                    </td>
                                </tr>
                            ))}
                            {databases.length === 0 && (
                                <tr>
                                    <td colSpan="9" style={{ textAlign: 'center', padding: '30px', color: '#888' }}>
                                        <Database size={32} style={{ marginBottom: '8px', opacity: 0.5 }} />
                                        <div>Нет активных баз данных. Создайте первую!</div>
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
                            <h2>Создание новой базы данных</h2>
                            <button className="btn-close" onClick={() => setShowCreateModal(false)} type="button">
                                <X size={18} />
                            </button>
                        </div>
                        <form onSubmit={handleCreateDatabase} style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                            <div className="slide-over-body">
                                <div className="input-group">
                                    <label className="input-label">Имя базы данных</label>
                                    <input 
                                        type="text" 
                                        className="form-control" 
                                        value={dbName} 
                                        onChange={e => setDbName(e.target.value)} 
                                        required 
                                        placeholder="Например, my_app_db"
                                    />
                                    <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px' }}>
                                        Только латинские строчные буквы, цифры и символ подчеркивания.
                                    </span>
                                </div>

                                <div className="input-group">
                                    <label className="input-label">Тип СУБД</label>
                                    <CustomSelect 
                                        value={engine} 
                                        onChange={e => setEngine(e.target.value)}
                                        options={[
                                            { value: 'postgresql', label: 'PostgreSQL (Порт 5432)' },
                                            { value: 'mysql', label: 'MySQL/MariaDB (Порт 3306)' }
                                        ]}
                                    />
                                </div>

                                <div style={{ background: 'var(--bg-surface-hover)', padding: '12px', borderRadius: '8px', marginTop: '20px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                    <Info size={16} style={{ marginRight: '8px', verticalAlign: 'middle', color: 'var(--accent-primary)' }} />
                                    Учетная запись с полными правами к созданной базе будет сгенерирована автоматически.
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

            {showBindModal && (
                <div className="slide-over-overlay" onClick={() => setShowBindModal(false)}>
                    <div className="slide-over-content" onClick={e => e.stopPropagation()}>
                        <div className="slide-over-header">
                            <h2>Привязка базы данных</h2>
                            <button className="btn-close" onClick={() => setShowBindModal(false)} type="button">
                                <X size={18} />
                            </button>
                        </div>
                        <form onSubmit={handleBindVM} style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                            <div className="slide-over-body">
                                <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '20px' }}>
                                    Выберите виртуальную машину, к которой хотите привязать эту базу данных. Это поможет структурировать инфраструктуру вашего проекта.
                                </p>
                                <div className="input-group">
                                    <label className="input-label">Виртуальная машина</label>
                                    <CustomSelect 
                                        value={selectedVmId} 
                                        onChange={e => setSelectedVmId(e.target.value)}
                                        placeholder="-- Выберите ВМ --"
                                        options={vms.map(vm => {
                                            const ip = getVmIp(vm);
                                            return {
                                                value: vm.id,
                                                label: `${vm.name} (${ip || 'Нет IP'})`
                                            };
                                        })}
                                    />
                                </div>
                            </div>
                            <div className="slide-over-actions">
                                <button type="button" className="btn btn-secondary" onClick={() => setShowBindModal(false)} disabled={submitting}>
                                    Отмена
                                </button>
                                <button type="submit" className="btn btn-primary" disabled={submitting}>
                                    {submitting ? 'Привязка...' : 'Привязать'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}
