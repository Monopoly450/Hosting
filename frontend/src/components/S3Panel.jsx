import React, { useState, useEffect } from 'react';
import { FolderOpen, Plus, Trash2, Key, Info, Copy, Eye, EyeOff, Upload, ArrowLeft, File } from 'lucide-react';

export default function S3Panel() {
    const [buckets, setBuckets] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [showCreateModal, setShowCreateModal] = useState(false);
    
    // Form fields
    const [bucketName, setBucketName] = useState('');
    const [submitting, setSubmitting] = useState(false);
    
    // Secret Key visibility
    const [visibleSecrets, setVisibleSecrets] = useState({});

    // File Explorer State
    const [selectedBucket, setSelectedBucket] = useState(null);
    const [bucketFiles, setBucketFiles] = useState([]);
    const [filesLoading, setFilesLoading] = useState(false);
    const [uploadingFile, setUploadingFile] = useState(false);

    const getHeaders = (isMultipart = false) => {
        const token = localStorage.getItem('aegis_admin_token') || '';
        const headers = { 'Authorization': `Bearer ${token}` };
        if (!isMultipart) {
            headers['Content-Type'] = 'application/json';
        }
        return headers;
    };

    const fetchBuckets = async () => {
        setLoading(true);
        try {
            const res = await fetch('/api/v1/s3', {
                headers: getHeaders()
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка при загрузке списка бакетов');
            }
            const data = await res.json();
            setBuckets(data);
            setError('');
        } catch (err) {
            setError(err.message || 'Ошибка при загрузке списка бакетов');
        } finally {
            setLoading(false);
        }
    };

    const fetchBucketFiles = async (bucket) => {
        setFilesLoading(true);
        try {
            const res = await fetch(`/api/v1/s3/${bucket.id}/files`, {
                headers: getHeaders()
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка при получении файлов бакета');
            }
            const data = await res.json();
            setBucketFiles(data);
        } catch (err) {
            alert(err.message || 'Ошибка при получении файлов бакета');
        } finally {
            setFilesLoading(false);
        }
    };

    useEffect(() => {
        fetchBuckets();
    }, []);

    const handleCreateBucket = async (e) => {
        e.preventDefault();
        setSubmitting(true);
        try {
            const res = await fetch('/api/v1/s3', {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({
                    name: bucketName
                })
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка создания бакета');
            }
            
            setShowCreateModal(false);
            setBucketName('');
            fetchBuckets();
        } catch (err) {
            alert(err.message || 'Ошибка создания бакета');
        } finally {
            setSubmitting(false);
        }
    };

    const handleDeleteBucket = async (bucketId) => {
        if (!confirm('Вы уверены, что хотите удалить этот бакет? Все хранящиеся файлы будут стёрты навсегда!')) return;
        try {
            const res = await fetch(`/api/v1/s3/${bucketId}`, {
                method: 'DELETE',
                headers: getHeaders()
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка при удалении бакета');
            }
            fetchBuckets();
        } catch (err) {
            alert(err.message || 'Ошибка при удалении бакета');
        }
    };

    const handleFileUpload = async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        setUploadingFile(true);
        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch(`/api/v1/s3/${selectedBucket.id}/upload`, {
                method: 'POST',
                headers: getHeaders(true),
                body: formData
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка при загрузке файла');
            }
            fetchBucketFiles(selectedBucket);
        } catch (err) {
            alert(err.message || 'Ошибка при загрузке файла');
        } finally {
            setUploadingFile(false);
        }
    };

    const handleDeleteFile = async (fileName) => {
        if (!confirm(`Удалить файл "${fileName}"?`)) return;
        try {
            const res = await fetch(`/api/v1/s3/${selectedBucket.id}/files/${encodeURIComponent(fileName)}`, {
                method: 'DELETE',
                headers: getHeaders()
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка при удалении файла');
            }
            fetchBucketFiles(selectedBucket);
        } catch (err) {
            alert(err.message || 'Ошибка при удалении файла');
        }
    };

    const toggleSecretVisibility = (bucketId) => {
        setVisibleSecrets(prev => ({
            ...prev,
            [bucketId]: !prev[bucketId]
        }));
    };

    const copyToClipboard = (text) => {
        navigator.clipboard.writeText(text);
        alert('Скопировано в буфер обмена!');
    };

    const getMinioEndpoint = () => {
        return `http://${window.location.hostname}:9000`;
    };

    const formatBytes = (bytes) => {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    };

    // Render File Explorer for the selected bucket
    if (selectedBucket) {
        return (
            <div className="panel-container">
                <div className="panel-header" style={{ marginBottom: '20px' }}>
                    <button className="btn btn-secondary" onClick={() => setSelectedBucket(null)} style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '15px' }}>
                        <ArrowLeft size={16} /> Назад к списку бакетов
                    </button>
                    <div>
                        <h2 className="panel-title">Бакет: {selectedBucket.bucket_name}</h2>
                        <p className="panel-subtitle">Просмотр, загрузка и удаление файлов</p>
                    </div>
                </div>

                <div className="glass-card" style={{ padding: '20px', marginBottom: '20px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div style={{ display: 'flex', gap: '15px', alignItems: 'center' }}>
                            <span style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>Загрузить файл в хранилище:</span>
                            <label className="btn btn-primary" style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                <Upload size={16} /> Выберите файл
                                <input type="file" onChange={handleFileUpload} style={{ display: 'none' }} disabled={uploadingFile} />
                            </label>
                        </div>
                        {uploadingFile && <span className="spinner"></span>}
                    </div>
                </div>

                {filesLoading ? (
                    <div style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}>
                        <div className="spinner"></div>
                    </div>
                ) : (
                    <div className="table-responsive">
                        <table className="table">
                            <thead>
                                <tr>
                                    <th>Имя файла</th>
                                    <th>Размер</th>
                                    <th>Дата изменения</th>
                                    <th>Действия</th>
                                </tr>
                            </thead>
                            <tbody>
                                {bucketFiles.map((file, idx) => (
                                    <tr key={idx}>
                                        <td style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 'bold' }}>
                                            <File size={16} color="var(--accent-primary)" /> {file.name}
                                        </td>
                                        <td>{formatBytes(file.size)}</td>
                                        <td>{file.last_modified}</td>
                                        <td>
                                            <button 
                                                className="btn btn-danger btn-sm" 
                                                onClick={() => handleDeleteFile(file.name)}
                                                style={{ display: 'flex', alignItems: 'center', gap: '4px' }}
                                            >
                                                <Trash2 size={12} /> Удалить
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                                {bucketFiles.length === 0 && (
                                    <tr>
                                        <td colSpan="4" style={{ textAlign: 'center', padding: '30px', color: '#888' }}>
                                            Бакет пуст. Загрузите файлы для проверки!
                                        </td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        );
    }

    return (
        <div className="panel-container">
            <div className="panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <div>
                    <h2 className="panel-title">S3 Объектное хранилище (MinIO)</h2>
                    <p className="panel-subtitle">Создание бакетов и управление ключами доступа (API S3)</p>
                </div>
                <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
                    <Plus size={16} /> Создать бакет
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
                                <th>Имя бакета</th>
                                <th>S3 Endpoint</th>
                                <th>Access Key</th>
                                <th>Secret Key</th>
                                <th>Статус</th>
                                <th>Владелец</th>
                                <th>Действия</th>
                            </tr>
                        </thead>
                        <tbody>
                            {buckets.map(b => (
                                <tr key={b.id}>
                                    <td style={{ fontWeight: 'bold' }}>{b.bucket_name}</td>
                                    <td>
                                        <span style={{ fontFamily: 'monospace', background: 'var(--bg-surface)', padding: '2px 6px', borderRadius: '4px' }}>
                                            {getMinioEndpoint()}
                                        </span>
                                    </td>
                                    <td>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                            <span style={{ fontFamily: 'monospace' }}>{b.access_key}</span>
                                            <button className="btn-icon" onClick={() => copyToClipboard(b.access_key)} title="Копировать">
                                                <Copy size={12} />
                                            </button>
                                        </div>
                                    </td>
                                    <td>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                            <input 
                                                type={visibleSecrets[b.id] ? 'text' : 'password'} 
                                                value={b.secret_key} 
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
                                                onClick={() => toggleSecretVisibility(b.id)}
                                                title="Показать/скрыть"
                                            >
                                                {visibleSecrets[b.id] ? <EyeOff size={14} /> : <Eye size={14} />}
                                            </button>
                                            <button 
                                                className="btn-icon" 
                                                onClick={() => copyToClipboard(b.secret_key)}
                                                title="Копировать"
                                            >
                                                <Copy size={14} />
                                            </button>
                                        </div>
                                    </td>
                                    <td>
                                        <span className="status-badge status-active">
                                            Активен
                                        </span>
                                    </td>
                                    <td>{b.owner_username}</td>
                                    <td>
                                        <div style={{ display: 'flex', gap: '8px' }}>
                                            <button 
                                                className="btn btn-secondary btn-sm" 
                                                onClick={() => { setSelectedBucket(b); fetchBucketFiles(b); }}
                                                style={{ display: 'flex', alignItems: 'center', gap: '4px' }}
                                            >
                                                <FolderOpen size={12} /> Проводник
                                            </button>
                                            <button 
                                                className="btn btn-danger btn-sm" 
                                                onClick={() => handleDeleteBucket(b.id)}
                                                style={{ display: 'flex', alignItems: 'center', gap: '4px' }}
                                            >
                                                <Trash2 size={12} /> Удалить
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                            {buckets.length === 0 && (
                                <tr>
                                    <td colSpan="7" style={{ textAlign: 'center', padding: '30px', color: '#888' }}>
                                        <FolderOpen size={32} style={{ marginBottom: '8px', opacity: 0.5 }} />
                                        <div>Нет active бакетов S3. Создайте первый!</div>
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            )}

            {showCreateModal && (
                <div className="modal-backdrop">
                    <div className="modal-content glass-card" style={{ maxWidth: '450px' }}>
                        <div className="modal-header">
                            <h3 className="modal-title">Создание нового бакета S3</h3>
                            <button className="btn-close" onClick={() => setShowCreateModal(false)}>×</button>
                        </div>
                        <form onSubmit={handleCreateBucket}>
                            <div className="form-group" style={{ marginBottom: '15px' }}>
                                <label className="form-label">Имя бакета (Bucket Name)</label>
                                <input 
                                    type="text" 
                                    className="form-control" 
                                    value={bucketName} 
                                    onChange={e => setBucketName(e.target.value)} 
                                    required 
                                    placeholder="Например, storage-1"
                                />
                                <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px' }}>
                                    Только латинские строчные буквы, цифры и дефис. Название будет дополнено префиксом вашего логина.
                                </span>
                            </div>

                            <div style={{ background: 'var(--bg-surface-hover)', padding: '12px', borderRadius: '8px', marginBottom: '20px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                <Info size={16} style={{ marginRight: '8px', verticalAlign: 'middle', color: 'var(--accent-primary)' }} />
                                Будет создан индивидуальный S3 Service Account с доступом только к этому бакету.
                            </div>

                            <div className="modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
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
        </div>
    );
}
