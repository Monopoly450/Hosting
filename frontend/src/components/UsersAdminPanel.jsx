import React, { useState, useEffect } from 'react';

export default function UsersAdminPanel({ apiToken, apiUrl }) {
    const [users, setUsers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [showCreateModal, setShowCreateModal] = useState(false);
    
    // Form fields
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [role, setRole] = useState('student');
    const [maxVcpus, setMaxVcpus] = useState(4);
    const [maxRamMb, setMaxRamMb] = useState(4096);
    const [maxVms, setMaxVms] = useState(2);
    const [maxStorageGb, setMaxStorageGb] = useState(40);

    const getHeaders = () => ({
        'Authorization': `Bearer ${apiToken}`,
        'Content-Type': 'application/json'
    });

    const fetchUsers = async () => {
        setLoading(true);
        try {
            const res = await fetch(`${apiUrl}/api/v1/auth/users`, {
                headers: { 'Authorization': `Bearer ${apiToken}` }
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка при загрузке списка пользователей');
            }
            const data = await res.json();
            setUsers(data);
            setError('');
        } catch (err) {
            setError(err.message || 'Ошибка при загрузке списка пользователей');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchUsers();
    }, [apiUrl, apiToken]);

    const handleCreateUser = async (e) => {
        e.preventDefault();
        try {
            const res = await fetch(`${apiUrl}/api/v1/auth/register`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({
                    username,
                    password,
                    role,
                    max_vcpus: Number(maxVcpus),
                    max_ram_mb: Number(maxRamMb),
                    max_vms: Number(maxVms),
                    max_storage_gb: Number(maxStorageGb)
                })
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка создания пользователя');
            }
            
            setShowCreateModal(false);
            // Reset form
            setUsername('');
            setPassword('');
            setRole('student');
            setMaxVcpus(4);
            setMaxRamMb(4096);
            setMaxVms(2);
            setMaxStorageGb(40);
            
            fetchUsers();
        } catch (err) {
            alert(err.message || 'Ошибка создания пользователя');
        }
    };

    const handleDeleteUser = async (userId) => {
        if (!confirm('Вы уверены, что хотите удалить этого пользователя и все его ресурсы?')) return;
        try {
            const res = await fetch(`${apiUrl}/api/v1/auth/users/${userId}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${apiToken}` }
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка при удалении пользователя');
            }
            fetchUsers();
        } catch (err) {
            alert(err.message || 'Ошибка при удалении пользователя');
        }
    };

    const generatePassword = () => {
        const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$';
        let pass = '';
        for (let i = 0; i < 12; i++) {
            pass += chars.charAt(Math.floor(Math.random() * chars.length));
        }
        setPassword(pass);
    };

    return (
        <div className="panel-container">
            <div className="panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <div>
                    <h2 className="panel-title">Управление пользователями</h2>
                    <p className="panel-subtitle">Регистрация студентов, мониторинг квот и баланса</p>
                </div>
                <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
                    + Создать пользователя
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
                                <th>ID</th>
                                <th>Имя пользователя</th>
                                <th>Роль</th>
                                <th>Баланс (₽)</th>
                                <th>Лимит CPU</th>
                                <th>Лимит RAM (МБ)</th>
                                <th>Лимит ВМ</th>
                                <th>Лимит диска (ГБ)</th>
                                <th>Действия</th>
                            </tr>
                        </thead>
                        <tbody>
                            {users.map(u => (
                                <tr key={u.id}>
                                    <td>{u.id}</td>
                                    <td style={{ fontWeight: 'bold' }}>{u.username}</td>
                                    <td>
                                        <span className={`status-badge ${u.role === 'admin' ? 'status-active' : 'status-pending'}`} style={{ textTransform: 'capitalize' }}>
                                            {u.role === 'admin' ? 'Админ' : 'Студент'}
                                        </span>
                                    </td>
                                    <td>{u.balance.toFixed(2)} ₽</td>
                                    <td>{u.max_vcpus} Cores</td>
                                    <td>{u.max_ram_mb} MB</td>
                                    <td>{u.max_vms} VMs</td>
                                    <td>{u.max_storage_gb} GB</td>
                                    <td>
                                        <button 
                                            className="btn btn-danger btn-sm" 
                                            onClick={() => handleDeleteUser(u.id)}
                                            style={{ padding: '4px 8px', fontSize: '12px' }}
                                        >
                                            Удалить
                                        </button>
                                    </td>
                                </tr>
                            ))}
                            {users.length === 0 && (
                                <tr>
                                    <td colSpan="9" style={{ textAlign: 'center', padding: '20px', color: '#888' }}>
                                        Нет зарегистрированных пользователей
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            )}

            {showCreateModal && (
                <div className="modal-backdrop">
                    <div className="modal-content glass-card" style={{ maxWidth: '500px' }}>
                        <div className="modal-header">
                            <h3 className="modal-title">Создание нового пользователя</h3>
                            <button className="btn-close" onClick={() => setShowCreateModal(false)}>×</button>
                        </div>
                        <form onSubmit={handleCreateUser}>
                            <div className="form-group" style={{ marginBottom: '15px' }}>
                                <label className="form-label">Имя пользователя</label>
                                <input 
                                    type="text" 
                                    className="form-control" 
                                    value={username} 
                                    onChange={e => setUsername(e.target.value)} 
                                    required 
                                    placeholder="Например, ivan_ivanov"
                                />
                            </div>

                            <div className="form-group" style={{ marginBottom: '15px' }}>
                                <label className="form-label">Пароль</label>
                                <div style={{ display: 'flex', gap: '10px' }}>
                                    <input 
                                        type="text" 
                                        className="form-control" 
                                        value={password} 
                                        onChange={e => setPassword(e.target.value)} 
                                        required
                                        placeholder="Сложный пароль"
                                    />
                                    <button type="button" className="btn btn-secondary" onClick={generatePassword}>
                                        Генер.
                                    </button>
                                </div>
                            </div>

                            <div className="form-group" style={{ marginBottom: '15px' }}>
                                <label className="form-label">Роль</label>
                                <select className="form-control" value={role} onChange={e => setRole(e.target.value)}>
                                    <option value="student">Студент</option>
                                    <option value="admin">Преподаватель (Администратор)</option>
                                </select>
                            </div>

                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '15px', marginBottom: '20px' }}>
                                <div className="form-group">
                                    <label className="form-label">Лимит CPU (ядер)</label>
                                    <input 
                                        type="number" 
                                        className="form-control" 
                                        value={maxVcpus} 
                                        onChange={e => setMaxVcpus(e.target.value)} 
                                        min="1" 
                                        required
                                    />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">Лимит RAM (МБ)</label>
                                    <input 
                                        type="number" 
                                        className="form-control" 
                                        value={maxRamMb} 
                                        onChange={e => setMaxRamMb(e.target.value)} 
                                        min="256" 
                                        step="256"
                                        required
                                    />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">Лимит ВМ (шт)</label>
                                    <input 
                                        type="number" 
                                        className="form-control" 
                                        value={maxVms} 
                                        onChange={e => setMaxVms(e.target.value)} 
                                        min="1" 
                                        required
                                    />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">Лимит диска (ГБ)</label>
                                    <input 
                                        type="number" 
                                        className="form-control" 
                                        value={maxStorageGb} 
                                        onChange={e => setMaxStorageGb(e.target.value)} 
                                        min="5" 
                                        required
                                    />
                                </div>
                            </div>

                            <div className="modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowCreateModal(false)}>
                                    Отмена
                                </button>
                                <button type="submit" className="btn btn-primary">
                                    Создать
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}
