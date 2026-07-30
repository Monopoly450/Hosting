import React, { useState, useEffect } from 'react';
import { FolderOpen, Plus, Trash2, Key, Info, Copy, Eye, EyeOff, Upload, ArrowLeft, File, X, Check, Server, Code2, Terminal, Plug, HardDrive, FileText, FileImage, FileArchive, FileVideo } from 'lucide-react';

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
    const [dragOver, setDragOver] = useState(false);
    const [copiedKey, setCopiedKey] = useState(null);
    const [showConnect, setShowConnect] = useState(false);
    const [connTab, setConnTab] = useState('cli');

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
            const res = await fetch('/api/s3', {
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
            const res = await fetch(`/api/s3/${bucket.id}/files`, {
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
            const res = await fetch('/api/s3', {
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
            const res = await fetch(`/api/s3/${bucketId}`, {
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

    const uploadFile = async (file) => {
        if (!file) return;
        setUploadingFile(true);
        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch(`/api/s3/${selectedBucket.id}/upload`, {
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

    const handleFileUpload = (e) => {
        uploadFile(e.target.files[0]);
        e.target.value = '';
    };

    const handleDrop = (e) => {
        e.preventDefault();
        setDragOver(false);
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            uploadFile(e.dataTransfer.files[0]);
        }
    };

    const handleDeleteFile = async (fileName) => {
        if (!confirm(`Удалить файл "${fileName}"?`)) return;
        try {
            const res = await fetch(`/api/s3/${selectedBucket.id}/files/${encodeURIComponent(fileName)}`, {
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

    const copyToClipboard = (text, key = null) => {
        navigator.clipboard.writeText(text);
        if (key) {
            setCopiedKey(key);
            setTimeout(() => setCopiedKey(c => (c === key ? null : c)), 1400);
        }
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

    const fileIcon = (name) => {
        const ext = (name.split('.').pop() || '').toLowerCase();
        if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'].includes(ext)) return FileImage;
        if (['zip', 'tar', 'gz', 'rar', '7z'].includes(ext)) return FileArchive;
        if (['mp4', 'mov', 'avi', 'mkv', 'webm'].includes(ext)) return FileVideo;
        if (['txt', 'md', 'json', 'log', 'csv', 'yaml', 'yml', 'sql'].includes(ext)) return FileText;
        return File;
    };

    const buildS3Snippet = (b, tab) => {
        const endpoint = getMinioEndpoint();
        if (tab === 'cli') {
            return `aws configure set aws_access_key_id ${b.access_key}\naws configure set aws_secret_access_key ${b.secret_key}\naws --endpoint-url ${endpoint} s3 ls s3://${b.bucket_name}\naws --endpoint-url ${endpoint} s3 cp ./file.txt s3://${b.bucket_name}/`;
        }
        if (tab === 'boto3') {
            return `import boto3\ns3 = boto3.client(\n    "s3",\n    endpoint_url="${endpoint}",\n    aws_access_key_id="${b.access_key}",\n    aws_secret_access_key="${b.secret_key}",\n)\ns3.upload_file("file.txt", "${b.bucket_name}", "file.txt")`;
        }
        if (tab === 'mc') {
            return `mc alias set mybucket ${endpoint} ${b.access_key} ${b.secret_key}\nmc ls mybucket/${b.bucket_name}\nmc cp ./file.txt mybucket/${b.bucket_name}/`;
        }
        return '';
    };

    const S3CopyField = ({ label, value, ck, type = 'text', toggleable = false, id = null }) => (
        <div className="input-group" style={{ marginBottom: 0 }}>
            {label && <label className="input-label">{label}</label>}
            <div className="copy-field">
                <code style={{ fontFamily: 'var(--font-mono)' }}>
                    {toggleable && !visibleSecrets[id] ? '•'.repeat(Math.min(value.length, 20)) : value}
                </code>
                {toggleable && (
                    <button className="btn-icon" onClick={() => toggleSecretVisibility(id)} title="Показать/скрыть">
                        {visibleSecrets[id] ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                )}
                <button className="btn-icon" onClick={() => copyToClipboard(value, ck)} title="Копировать">
                    {copiedKey === ck ? <Check size={14} color="var(--status-success)" /> : <Copy size={14} />}
                </button>
            </div>
        </div>
    );

    // Render File Explorer for the selected bucket ("enter storage")
    if (selectedBucket) {
        const b = selectedBucket;
        const connTabs = [
            { id: 'cli', label: 'AWS CLI', icon: Terminal },
            { id: 'boto3', label: 'Python (boto3)', icon: Code2 },
            { id: 'mc', label: 'MinIO Client', icon: Code2 },
        ];
        const totalSize = bucketFiles.reduce((s, f) => s + (f.size || 0), 0);
        return (
            <div className="panel-container">
                <button className="btn btn-secondary" onClick={() => { setSelectedBucket(null); setShowConnect(false); }} style={{ marginBottom: '18px' }}>
                    <ArrowLeft size={16} /> Назад к списку бакетов
                </button>

                <div className="glass-card accent-top" style={{ marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '18px', flexWrap: 'wrap' }}>
                    <div className="connect-tile-icon" style={{ width: '54px', height: '54px', flexShrink: 0 }}>
                        <HardDrive size={26} />
                    </div>
                    <div style={{ flex: 1, minWidth: '200px' }}>
                        <h2 className="panel-title" style={{ fontSize: '1.5rem' }}>{b.bucket_name}</h2>
                        <p className="panel-subtitle" style={{ marginTop: '2px' }}>
                            {bucketFiles.length} объектов · {formatBytes(totalSize)} · S3-совместимое хранилище
                        </p>
                    </div>
                    <button className={`btn ${showConnect ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setShowConnect(v => !v)}>
                        <Plug size={16} /> Подключиться
                    </button>
                </div>

                {showConnect && (
                    <div className="glass-card" style={{ marginBottom: '20px' }}>
                        <div className="section-title"><Key size={18} /> Доступ к бакету по API S3</div>
                        <div className="grid-cols-4 stagger" style={{ marginBottom: '18px' }}>
                            <div className="connect-tile">
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-secondary)', fontSize: '0.78rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}><Server size={14} /> Endpoint</div>
                                <S3CopyField value={getMinioEndpoint()} ck="endpoint" />
                            </div>
                            <div className="connect-tile">
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-secondary)', fontSize: '0.78rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}><FolderOpen size={14} /> Bucket</div>
                                <S3CopyField value={b.bucket_name} ck="bname" />
                            </div>
                            <div className="connect-tile">
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-secondary)', fontSize: '0.78rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}><Key size={14} /> Access Key</div>
                                <S3CopyField value={b.access_key} ck="akey" />
                            </div>
                            <div className="connect-tile">
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-secondary)', fontSize: '0.78rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}><Key size={14} /> Secret Key</div>
                                <S3CopyField value={b.secret_key} ck="skey" toggleable id={b.id} />
                            </div>
                        </div>
                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '14px' }}>
                            {connTabs.map(t => (
                                <button key={t.id} className={`btn ${connTab === t.id ? 'btn-primary' : 'btn-secondary'} btn-sm`} onClick={() => setConnTab(t.id)}>
                                    <t.icon size={14} /> {t.label}
                                </button>
                            ))}
                        </div>
                        <div style={{ position: 'relative' }}>
                            <pre style={{
                                background: 'var(--bg-surface-hover)', border: '1px solid var(--border-subtle)',
                                borderRadius: 'var(--radius-md)', padding: '18px 48px 18px 18px',
                                fontFamily: 'var(--font-mono)', fontSize: '0.82rem', color: 'var(--text-primary)',
                                overflowX: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: 0,
                            }}>{buildS3Snippet(b, connTab)}</pre>
                            <button className="btn-icon" style={{ position: 'absolute', top: '12px', right: '12px' }}
                                onClick={() => copyToClipboard(buildS3Snippet(b, connTab), 'snippet')} title="Копировать">
                                {copiedKey === 'snippet' ? <Check size={16} color="var(--status-success)" /> : <Copy size={16} />}
                            </button>
                        </div>
                    </div>
                )}

                {/* Drag & drop upload zone */}
                <div
                    className="glass-card"
                    onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                    onDragLeave={() => setDragOver(false)}
                    onDrop={handleDrop}
                    style={{
                        marginBottom: '20px',
                        border: `2px dashed ${dragOver ? 'var(--accent-primary)' : 'var(--border-default)'}`,
                        background: dragOver ? 'var(--accent-primary-light)' : 'var(--bg-surface)',
                        textAlign: 'center',
                        padding: '30px 20px',
                        transition: 'all var(--transition-fast)',
                    }}
                >
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
                        <div className="connect-tile-icon" style={{ width: '48px', height: '48px' }}>
                            {uploadingFile ? <span className="spinner" style={{ borderColor: 'rgba(255,255,255,0.4)', borderTopColor: '#fff' }} /> : <Upload size={22} />}
                        </div>
                        <div style={{ fontWeight: 600, color: 'var(--text-heading)' }}>
                            {uploadingFile ? 'Загрузка...' : 'Перетащите файл сюда'}
                        </div>
                        <div className="text-muted">или</div>
                        <label className="btn btn-primary" style={{ cursor: 'pointer' }}>
                            <Upload size={16} /> Выберите файл
                            <input type="file" onChange={handleFileUpload} style={{ display: 'none' }} disabled={uploadingFile} />
                        </label>
                    </div>
                </div>

                {filesLoading ? (
                    <div style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}>
                        <div className="spinner spinner-lg"></div>
                    </div>
                ) : bucketFiles.length === 0 ? (
                    <div className="glass-card" style={{ textAlign: 'center', padding: '54px 20px' }}>
                        <FolderOpen size={44} style={{ color: 'var(--text-muted)', marginBottom: '12px' }} />
                        <h3 className="section-title" style={{ justifyContent: 'center' }}>Бакет пуст</h3>
                        <p className="text-muted">Загрузите первый файл — перетащите его в зону выше.</p>
                    </div>
                ) : (
                    <div className="grid-cols-4 stagger">
                        {bucketFiles.map((file, idx) => {
                            const Icon = fileIcon(file.name);
                            return (
                                <div key={idx} className="glass-card interactive" style={{ padding: '18px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                                        <div className="connect-tile-icon" style={{ width: '40px', height: '40px', background: 'var(--gradient-accent-soft)', color: 'var(--accent-primary)' }}>
                                            <Icon size={20} />
                                        </div>
                                        <button className="btn-icon" onClick={() => handleDeleteFile(file.name)} title="Удалить" style={{ color: 'var(--status-danger)' }}>
                                            <Trash2 size={15} />
                                        </button>
                                    </div>
                                    <div style={{ fontWeight: 600, color: 'var(--text-heading)', fontSize: '0.9rem', wordBreak: 'break-all', lineHeight: 1.3 }}>
                                        {file.name}
                                    </div>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.76rem', color: 'var(--text-muted)', marginTop: 'auto' }}>
                                        <span>{formatBytes(file.size)}</span>
                                        <span>{file.last_modified}</span>
                                    </div>
                                </div>
                            );
                        })}
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
                                    <td colSpan="7" style={{ textAlign: 'center', padding: '30px', color: 'var(--text-muted)' }}>
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
                <div className="slide-over-overlay" onClick={() => setShowCreateModal(false)}>
                    <div className="slide-over-content" onClick={e => e.stopPropagation()}>
                        <div className="slide-over-header">
                            <h2>Создание нового бакета S3</h2>
                            <button className="btn-close" onClick={() => setShowCreateModal(false)} type="button">
                                <X size={18} />
                            </button>
                        </div>
                        <form onSubmit={handleCreateBucket} style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                            <div className="slide-over-body">
                                <div className="input-group">
                                    <label className="input-label">Имя бакета (Bucket Name)</label>
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

                                <div style={{ background: 'var(--bg-surface-hover)', padding: '12px', borderRadius: '8px', marginTop: '20px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                    <Info size={16} style={{ marginRight: '8px', verticalAlign: 'middle', color: 'var(--accent-primary)' }} />
                                    Будет создан индивидуальный S3 Service Account с доступом только к этому бакету.
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
        </div>
    );
}
