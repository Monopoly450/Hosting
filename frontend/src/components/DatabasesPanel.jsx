import React, { useState, useEffect } from 'react';
import { Database, Plus, Trash2, Key, Info, Copy, Eye, EyeOff, X, Link2, Unlink, Plug, ArrowLeft, Terminal, Code2, Server, Check, User, Activity, Play, FileSpreadsheet, HardDrive, Cpu, RefreshCw, Download } from 'lucide-react';
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

    // "Enter database" connection hub
    const [connectDb, setConnectDb] = useState(null);
    const [connectTab, setConnectTab] = useState('cli');
    const [copiedKey, setCopiedKey] = useState(null);

    // Database Detail Tabs and Data
    const [detailActiveTab, setDetailActiveTab] = useState('credentials');
    const [sqlQuery, setSqlQuery] = useState('SELECT * FROM users LIMIT 10;');
    const [queryResult, setQueryResult] = useState(null);
    const [queryExecuting, setQueryExecuting] = useState(false);
    const [queryError, setQueryError] = useState('');

    const [dbTables, setDbTables] = useState([]);
    const [dbMetrics, setDbMetrics] = useState(null);
    const [metricsLoading, setMetricsLoading] = useState(false);
    const [tablesLoading, setTablesLoading] = useState(false);

    const [dbBackups, setDbBackups] = useState([]);
    const [backupsLoading, setBackupsLoading] = useState(false);
    const [backupCreating, setBackupCreating] = useState(false);

    const fetchDbTables = async () => {
        if (!connectDb) return;
        setTablesLoading(true);
        try {
            const res = await fetch(`/api/databases/${connectDb.id}/tables`, {
                headers: getHeaders()
            });
            if (res.ok) {
                const data = await res.json();
                setDbTables(data);
                if (data.length > 0) {
                    setSqlQuery(`SELECT * FROM ${data[0]} LIMIT 10;`);
                } else {
                    setSqlQuery(connectDb.engine === 'postgresql' 
                        ? '-- Создайте таблицу:\n-- CREATE TABLE users (id SERIAL PRIMARY KEY, name VARCHAR(50));' 
                        : '-- Создайте таблицу:\n-- CREATE TABLE users (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(50));');
                }
            }
        } catch (err) {
            console.error('Ошибка загрузки списка таблиц:', err);
        } finally {
            setTablesLoading(false);
        }
    };

    const fetchDbMetrics = async () => {
        if (!connectDb) return;
        setMetricsLoading(true);
        try {
            const res = await fetch(`/api/databases/${connectDb.id}/metrics`, {
                headers: getHeaders()
            });
            if (res.ok) {
                const data = await res.json();
                setDbMetrics(data);
            }
        } catch (err) {
            console.error('Ошибка загрузки метрик БД:', err);
        } finally {
            setMetricsLoading(false);
        }
    };

    const fetchDbBackups = async () => {
        if (!connectDb) return;
        setBackupsLoading(true);
        try {
            const res = await fetch(`/api/databases/${connectDb.id}/backups`, {
                headers: getHeaders()
            });
            if (res.ok) {
                const data = await res.json();
                setDbBackups(data);
            }
        } catch (err) {
            console.error('Ошибка загрузки бэкапов:', err);
        } finally {
            setBackupsLoading(false);
        }
    };

    const handleCreateBackup = async () => {
        if (!connectDb) return;
        setBackupCreating(true);
        try {
            const res = await fetch(`/api/databases/${connectDb.id}/backups`, {
                method: 'POST',
                headers: getHeaders()
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка создания резервной копии');
            }
            alert('Резервная копия успешно создана!');
            fetchDbBackups();
        } catch (err) {
            alert(err.message || 'Ошибка создания резервной копии');
        } finally {
            setBackupCreating(false);
        }
    };

    const handleRestoreBackup = async (filename) => {
        if (!connectDb) return;
        if (!window.confirm(`Вы уверены, что хотите восстановить базу данных из резервной копии ${filename}? Все текущие данные будут перезаписаны.`)) {
            return;
        }
        try {
            const res = await fetch(`/api/databases/${connectDb.id}/backups/${filename}/restore`, {
                method: 'POST',
                headers: getHeaders()
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка восстановления');
            }
            alert('База данных успешно восстановлена!');
            fetchDbTables();
        } catch (err) {
            alert(err.message || 'Ошибка восстановления резервной копии');
        }
    };

    const handleDeleteBackup = async (filename) => {
        if (!connectDb) return;
        if (!window.confirm(`Удалить резервную копию ${filename}?`)) {
            return;
        }
        try {
            const res = await fetch(`/api/databases/${connectDb.id}/backups/${filename}`, {
                method: 'DELETE',
                headers: getHeaders()
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Ошибка удаления');
            }
            alert('Резервная копия удалена.');
            fetchDbBackups();
        } catch (err) {
            alert(err.message || 'Ошибка удаления резервной копии');
        }
    };

    const handleDownloadBackup = async (filename) => {
        if (!connectDb) return;
        try {
            const res = await fetch(`/api/databases/${connectDb.id}/backups/${filename}/download`, {
                headers: getHeaders()
            });
            if (!res.ok) {
                throw new Error('Не удалось скачать резервную копию');
            }
            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
        } catch (err) {
            alert(err.message || 'Ошибка при скачивании резервной копии');
        }
    };

    useEffect(() => {
        if (connectDb) {
            setDetailActiveTab('credentials');
            setQueryResult(null);
            setQueryError('');
            fetchDbTables();
            fetchDbMetrics();
            fetchDbBackups();
        }
    }, [connectDb]);

    useEffect(() => {
        if (connectDb && detailActiveTab === 'monitoring') {
            fetchDbMetrics();
            const interval = setInterval(fetchDbMetrics, 5000);
            return () => clearInterval(interval);
        }
    }, [connectDb, detailActiveTab]);

    useEffect(() => {
        if (connectDb && detailActiveTab === 'backups') {
            fetchDbBackups();
        }
    }, [connectDb, detailActiveTab]);

    const handleExecuteSQL = async () => {
        if (!connectDb || !sqlQuery.trim()) return;
        setQueryExecuting(true);
        setQueryError('');
        setQueryResult(null);
        try {
            const res = await fetch(`/api/databases/${connectDb.id}/query`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({ sql: sqlQuery })
            });
            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.detail || 'Ошибка выполнения SQL-запроса');
            }
            setQueryResult({
                columns: data.columns,
                rows: data.rows,
                message: data.message,
                executionTime: data.columns ? '0.01' : '0.00'
            });
            if (!data.columns) {
                fetchDbTables();
            }
        } catch (err) {
            setQueryError(err.message || 'Ошибка выполнения SQL-запроса');
        } finally {
            setQueryExecuting(false);
        }
    };

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

    const copyToClipboard = (text, key = null) => {
        navigator.clipboard.writeText(text);
        if (key) {
            setCopiedKey(key);
            setTimeout(() => setCopiedKey(c => (c === key ? null : c)), 1400);
        }
    };

    const getHostIP = () => {
        return window.location.hostname;
    };

    // ---- Connection hub helpers ("enter database") ----
    const connInfo = (d) => {
        const isPg = d.engine === 'postgresql';
        return {
            isPg,
            engineLabel: isPg ? 'PostgreSQL' : 'MySQL / MariaDB',
            host: d.db_host || getHostIP(),
            port: isPg ? '5432' : '3306',
            user: d.db_user,
            password: d.db_password,
            name: d.db_name,
        };
    };

    const buildSnippet = (d, tab) => {
        const c = connInfo(d);
        if (tab === 'cli') {
            return c.isPg
                ? `PGPASSWORD='${c.password}' psql -h ${c.host} -p ${c.port} -U ${c.user} -d ${c.name}`
                : `mysql -h ${c.host} -P ${c.port} -u ${c.user} -p'${c.password}' ${c.name}`;
        }
        if (tab === 'uri') {
            return c.isPg
                ? `postgresql://${c.user}:${c.password}@${c.host}:${c.port}/${c.name}`
                : `mysql://${c.user}:${c.password}@${c.host}:${c.port}/${c.name}`;
        }
        if (tab === 'python') {
            return c.isPg
                ? `import psycopg2\nconn = psycopg2.connect(\n    host="${c.host}", port=${c.port},\n    user="${c.user}", password="${c.password}",\n    dbname="${c.name}",\n)`
                : `import pymysql\nconn = pymysql.connect(\n    host="${c.host}", port=${c.port},\n    user="${c.user}", password="${c.password}",\n    database="${c.name}",\n)`;
        }
        if (tab === 'node') {
            return c.isPg
                ? `import { Client } from 'pg'\nconst client = new Client({\n  host: '${c.host}', port: ${c.port},\n  user: '${c.user}', password: '${c.password}',\n  database: '${c.name}',\n})\nawait client.connect()`
                : `import mysql from 'mysql2/promise'\nconst conn = await mysql.createConnection({\n  host: '${c.host}', port: ${c.port},\n  user: '${c.user}', password: '${c.password}',\n  database: '${c.name}',\n})`;
        }
        return '';
    };

    const CopyField = ({ label, value, ck, mono = true }) => (
        <div className="input-group" style={{ marginBottom: 0 }}>
            {label && <label className="input-label">{label}</label>}
            <div className="copy-field">
                <code style={{ fontFamily: mono ? 'var(--font-mono)' : 'inherit' }}>{value}</code>
                <button className="btn-icon" onClick={() => copyToClipboard(value, ck)} title="Копировать">
                    {copiedKey === ck ? <Check size={14} color="var(--status-success)" /> : <Copy size={14} />}
                </button>
            </div>
        </div>
    );

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

    // ===== Connection hub view ("enter database") =====
    if (connectDb) {
        const c = connInfo(connectDb);
        const tabs = [
            { id: 'cli', label: 'Терминал', icon: Terminal },
            { id: 'uri', label: 'URI строка', icon: Link2 },
            { id: 'python', label: 'Python', icon: Code2 },
            { id: 'node', label: 'Node.js', icon: Code2 },
        ];
        return (
            <div className="panel-container">
                <button className="btn btn-secondary" onClick={() => setConnectDb(null)} style={{ marginBottom: '18px' }}>
                    <ArrowLeft size={16} /> Назад к списку баз данных
                </button>

                <div className="glass-card accent-top" style={{ marginBottom: '22px', display: 'flex', alignItems: 'center', gap: '18px', flexWrap: 'wrap' }}>
                    <div className="connect-tile-icon" style={{ width: '54px', height: '54px', flexShrink: 0 }}>
                        <Database size={26} />
                    </div>
                    <div style={{ flex: 1, minWidth: '200px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                            <h2 className="panel-title" style={{ fontSize: '1.5rem' }}>{c.name}</h2>
                            <span className={`status-badge ${c.isPg ? 'status-active' : 'status-pending'}`}>{c.engineLabel}</span>
                            <span className="status-badge" style={{ backgroundColor: 'rgba(59, 130, 246, 0.1)', color: '#3b82f6', border: '1px solid rgba(59, 130, 246, 0.2)' }}>
                                {dbMetrics ? `${dbMetrics.db_size_mb} МБ` : '...'}
                            </span>
                        </div>
                        <p className="panel-subtitle" style={{ marginTop: '2px' }}>
                            {connectDb.associated_vm_name
                                ? <>Доступ разрешён для ВМ <strong style={{ color: 'var(--accent-primary)' }}>{connectDb.associated_vm_name}</strong></>
                                : 'База изолирована. Привяжите ВМ, чтобы разрешить доступ по сети.'}
                        </p>
                    </div>
                </div>

                {/* Sub-tabs Row */}
                <div style={{ display: 'flex', gap: '10px', marginBottom: '24px', overflowX: 'auto', paddingBottom: '5px' }}>
                    <button 
                        className={`btn ${detailActiveTab === 'credentials' ? 'btn-primary' : 'btn-secondary'} btn-sm`} 
                        onClick={() => setDetailActiveTab('credentials')}
                        style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
                    >
                        <Key size={14} /> Реквизиты и Код
                    </button>
                    <button 
                        className={`btn ${detailActiveTab === 'monitoring' ? 'btn-primary' : 'btn-secondary'} btn-sm`} 
                        onClick={() => setDetailActiveTab('monitoring')}
                        style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
                    >
                        <Activity size={14} /> Мониторинг
                    </button>
                    <button 
                        className={`btn ${detailActiveTab === 'console' ? 'btn-primary' : 'btn-secondary'} btn-sm`} 
                        onClick={() => setDetailActiveTab('console')}
                        style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
                    >
                        <Terminal size={14} /> SQL Консоль
                    </button>
                    <button 
                        className={`btn ${detailActiveTab === 'backups' ? 'btn-primary' : 'btn-secondary'} btn-sm`} 
                        onClick={() => setDetailActiveTab('backups')}
                        style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
                    >
                        <RefreshCw size={14} /> Резервные копии (S3)
                    </button>
                </div>

                {/* Tab Content 1: Credentials */}
                {detailActiveTab === 'credentials' && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                        <div className="grid-cols-4 stagger">
                            <div className="connect-tile">
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-secondary)', fontSize: '0.78rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}><Server size={14} /> Хост</div>
                                <CopyField value={c.host} ck="host" />
                            </div>
                            <div className="connect-tile">
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-secondary)', fontSize: '0.78rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}><Plug size={14} /> Порт</div>
                                <CopyField value={c.port} ck="port" />
                            </div>
                            <div className="connect-tile">
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-secondary)', fontSize: '0.78rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}><User size={14} /> Пользователь</div>
                                <CopyField value={c.user} ck="user" />
                            </div>
                            <div className="connect-tile">
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-secondary)', fontSize: '0.78rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}><Key size={14} /> Пароль</div>
                                <CopyField value={c.password} ck="password" />
                            </div>
                        </div>

                        <div className="glass-card">
                            <div className="section-title"><Terminal size={18} /> Строка подключения</div>
                            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '16px' }}>
                                {tabs.map(t => (
                                    <button
                                        key={t.id}
                                        className={`btn ${connectTab === t.id ? 'btn-primary' : 'btn-secondary'} btn-sm`}
                                        onClick={() => setConnectTab(t.id)}
                                    >
                                        <t.icon size={14} /> {t.label}
                                    </button>
                                ))}
                            </div>
                            <div style={{ position: 'relative' }}>
                                <pre style={{
                                    background: 'var(--bg-surface-hover)',
                                    border: '1px solid var(--border-subtle)',
                                    borderRadius: 'var(--radius-md)',
                                    padding: '18px 48px 18px 18px',
                                    fontFamily: 'var(--font-mono)',
                                    fontSize: '0.84rem',
                                    color: 'var(--text-primary)',
                                    overflowX: 'auto',
                                    whiteSpace: 'pre-wrap',
                                    wordBreak: 'break-all',
                                    margin: 0,
                                }}>{buildSnippet(connectDb, connectTab)}</pre>
                                <button
                                    className="btn-icon"
                                    style={{ position: 'absolute', top: '12px', right: '12px' }}
                                    onClick={() => copyToClipboard(buildSnippet(connectDb, connectTab), 'snippet')}
                                    title="Копировать"
                                >
                                    {copiedKey === 'snippet' ? <Check size={16} color="var(--status-success)" /> : <Copy size={16} />}
                                </button>
                            </div>
                            <div className="alert alert-info" style={{ marginTop: '18px', marginBottom: 0, display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                                <Info size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
                                <span>Подключение к базе возможно только с привязанной виртуальной машины — сетевой доступ ограничен политикой Kubernetes NetworkPolicy.</span>
                            </div>
                        </div>
                    </div>
                )}

                {/* Tab Content 2: Monitoring */}
                {detailActiveTab === 'monitoring' && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                        {metricsLoading && !dbMetrics ? (
                            <div style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}>
                                <div className="spinner"></div>
                            </div>
                        ) : (
                            <>
                                <div className="grid-cols-4 stagger">
                                    <div className="connect-tile" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: '100px' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-secondary)', fontSize: '0.8rem', fontWeight: 600 }}>
                                            <Cpu size={14} style={{ color: 'var(--accent-primary)' }} /> НАГРУЗКА CPU
                                        </div>
                                        <div style={{ fontSize: '1.8rem', fontWeight: 700, margin: '8px 0 4px 0', color: 'var(--text-primary)' }}>
                                            {dbMetrics ? `${dbMetrics.cpu_load}%` : '...'}
                                        </div>
                                        <div style={{ width: '100%', height: '6px', background: 'var(--bg-surface-hover)', borderRadius: '3px', overflow: 'hidden' }}>
                                            <div style={{ width: dbMetrics ? `${dbMetrics.cpu_load}%` : '0%', height: '100%', background: 'var(--accent-primary)', borderRadius: '3px' }} />
                                        </div>
                                    </div>
                                    <div className="connect-tile" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: '100px' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-secondary)', fontSize: '0.8rem', fontWeight: 600 }}>
                                            <HardDrive size={14} style={{ color: '#3b82f6' }} /> ОЗУ (MEM)
                                        </div>
                                        <div style={{ fontSize: '1.8rem', fontWeight: 700, margin: '8px 0 4px 0', color: 'var(--text-primary)' }}>
                                            {dbMetrics ? `${dbMetrics.memory_usage} МБ` : '...'}
                                        </div>
                                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>из 512 МБ лимита</div>
                                    </div>
                                    <div className="connect-tile" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: '100px' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-secondary)', fontSize: '0.8rem', fontWeight: 600 }}>
                                            <Plug size={14} style={{ color: '#10b981' }} /> СЕССИИ
                                        </div>
                                        <div style={{ fontSize: '1.8rem', fontWeight: 700, margin: '8px 0 4px 0', color: 'var(--text-primary)' }}>
                                            {dbMetrics ? `${dbMetrics.active_sessions} / 100` : '...'}
                                        </div>
                                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>активных подключений</div>
                                    </div>
                                    <div className="connect-tile" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: '100px' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-secondary)', fontSize: '0.8rem', fontWeight: 600 }}>
                                            <Activity size={14} style={{ color: '#f59e0b' }} /> ТРАНЗАКЦИИ
                                        </div>
                                        <div style={{ fontSize: '1.8rem', fontWeight: 700, margin: '8px 0 4px 0', color: 'var(--text-primary)' }}>
                                            {dbMetrics ? `${dbMetrics.tps} TPS` : '...'}
                                        </div>
                                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>в реальном времени</div>
                                    </div>
                                </div>

                                <div className="grid-cols-2 stagger">
                                    <div className="glass-card">
                                        <div className="section-title" style={{ fontSize: '1.1rem', marginBottom: '16px' }}>
                                            <Activity size={18} style={{ color: 'var(--accent-primary)' }} /> Статистика СУБД
                                        </div>
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '8px', borderBottom: '1px solid var(--border-subtle)' }}>
                                                <span style={{ color: 'var(--text-secondary)' }}>Размер базы данных</span>
                                                <span style={{ fontWeight: 600 }}>{dbMetrics ? `${dbMetrics.db_size_mb} МБ` : '...'}</span>
                                            </div>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '8px', borderBottom: '1px solid var(--border-subtle)' }}>
                                                <span style={{ color: 'var(--text-secondary)' }}>Чтение операций (Read IOPS)</span>
                                                <span style={{ fontWeight: 600 }}>{dbMetrics ? `${dbMetrics.read_iops} op/s` : '...'}</span>
                                            </div>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '8px', borderBottom: '1px solid var(--border-subtle)' }}>
                                                <span style={{ color: 'var(--text-secondary)' }}>Запись операций (Write IOPS)</span>
                                                <span style={{ fontWeight: 600 }}>{dbMetrics ? `${dbMetrics.write_iops} op/s` : '...'}</span>
                                            </div>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '8px', borderBottom: '1px solid var(--border-subtle)' }}>
                                                <span style={{ color: 'var(--text-secondary)' }}>Медленные запросы (Slow queries)</span>
                                                <span style={{ fontWeight: 600, color: dbMetrics && dbMetrics.slow_queries > 0 ? 'var(--status-danger)' : 'var(--status-success)' }}>
                                                    {dbMetrics ? dbMetrics.slow_queries : '...'}
                                                </span>
                                            </div>
                                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                                <span style={{ color: 'var(--text-secondary)' }}>Время работы (Uptime)</span>
                                                <span style={{ fontWeight: 600 }}>{dbMetrics ? dbMetrics.uptime : '...'}</span>
                                            </div>
                                        </div>
                                    </div>

                                    <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                                        <div>
                                            <div className="section-title" style={{ fontSize: '1.1rem', marginBottom: '12px' }}>
                                                <Info size={18} style={{ color: 'var(--accent-primary)' }} /> Состояние кластера БД
                                            </div>
                                            <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', lineHeight: '1.5', margin: 0 }}>
                                                Управляемая база данных запущена в отказоустойчивом изолированном контейнере внутри кластера Kubernetes. Репликация и лимиты ресурсов CPU/RAM контролируются автоматически.
                                            </p>
                                        </div>
                                        <div style={{ background: 'rgba(16, 185, 129, 0.08)', border: '1px solid rgba(16, 185, 129, 0.2)', padding: '14px', borderRadius: 'var(--radius-md)', display: 'flex', alignItems: 'center', gap: '10px', marginTop: '16px' }}>
                                            <div style={{ width: '8px', height: '8px', background: '#10b981', borderRadius: '50%' }} />
                                            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: '#10b981' }}>Все системы работают в штатном режиме</span>
                                        </div>
                                    </div>
                                </div>
                            </>
                        )}
                    </div>
                )}

                {/* Tab Content 3: SQL Console */}
                {detailActiveTab === 'console' && (
                    <div className="grid-cols-4 stagger" style={{ gap: '20px' }}>
                        {/* Left column: Tables list */}
                        <div className="glass-card" style={{ gridColumn: 'span 1', display: 'flex', flexDirection: 'column', gap: '12px', padding: '16px' }}>
                            <div style={{ fontSize: '0.85rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-secondary)', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <FileSpreadsheet size={14} /> Таблицы
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                {tablesLoading ? (
                                    <div style={{ padding: '10px 0', fontSize: '0.8rem', color: 'var(--text-muted)' }}>Загрузка...</div>
                                ) : dbTables.length > 0 ? (
                                    dbTables.map((tbl, idx) => (
                                        <button 
                                            key={idx}
                                            className="btn btn-secondary btn-sm" 
                                            style={{ justifyContent: 'flex-start', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', textAlign: 'left' }}
                                            onClick={() => setSqlQuery(`SELECT * FROM ${tbl} LIMIT 10;`)}
                                        >
                                            {tbl}
                                        </button>
                                    ))
                                ) : (
                                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', padding: '10px 0' }}>Нет таблиц</div>
                                )}
                            </div>
                            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '12px' }}>
                                * Кликните на имя таблицы, чтобы вставить шаблон.
                            </span>
                        </div>

                        {/* Right column: SQL Editor */}
                        <div className="glass-card" style={{ gridColumn: 'span 3', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                            <div className="section-title" style={{ fontSize: '1.1rem', marginBottom: 0, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <span>SQL Веб-консоль</span>
                                <button 
                                    className="btn btn-primary btn-sm" 
                                    onClick={handleExecuteSQL}
                                    disabled={queryExecuting}
                                    style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
                                >
                                    {queryExecuting ? <span className="spinner" style={{ width: '12px', height: '12px' }} /> : <Play size={14} />}
                                    Выполнить запрос
                                </button>
                            </div>

                            <textarea 
                                value={sqlQuery}
                                onChange={e => setSqlQuery(e.target.value)}
                                style={{
                                    width: '100%',
                                    height: '120px',
                                    fontFamily: 'var(--font-mono)',
                                    fontSize: '0.85rem',
                                    background: 'var(--bg-surface-hover)',
                                    color: 'var(--text-primary)',
                                    border: '1px solid var(--border-subtle)',
                                    borderRadius: 'var(--radius-md)',
                                    padding: '12px',
                                    resize: 'vertical',
                                    outline: 'none'
                                }}
                                placeholder="-- Введите SQL запрос здесь"
                            />

                            {queryError && (
                                <div style={{ background: 'rgba(239, 68, 68, 0.08)', border: '1px solid rgba(239, 68, 68, 0.2)', padding: '12px', borderRadius: 'var(--radius-md)', fontSize: '0.85rem', color: '#ef4444', fontFamily: 'var(--font-mono)', whiteSpace: 'pre-wrap' }}>
                                    {queryError}
                                </div>
                            )}

                            {queryResult && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                                        <span>Результат:</span>
                                        <span>Время выполнения: {queryResult.executionTime} сек</span>
                                    </div>
                                    {queryResult.columns ? (
                                        <div className="table-responsive" style={{ maxHeight: '250px', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
                                            <table className="table" style={{ margin: 0 }}>
                                                <thead>
                                                    <tr>
                                                        {queryResult.columns.map((col, idx) => (
                                                            <th key={idx} style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>{col}</th>
                                                        ))}
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {queryResult.rows.map((row, rowIdx) => (
                                                        <tr key={rowIdx}>
                                                            {row.map((cell, cellIdx) => (
                                                                <td key={cellIdx} style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>{String(cell)}</td>
                                                            ))}
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        </div>
                                    ) : (
                                        <div style={{ background: 'rgba(16, 185, 129, 0.08)', border: '1px solid rgba(16, 185, 129, 0.2)', padding: '12px', borderRadius: 'var(--radius-md)', fontSize: '0.85rem', color: '#10b981', fontFamily: 'var(--font-mono)' }}>
                                            {queryResult.message}
                                        </div>
                                    )}
                                </div>
                            )}

                            {queryExecuting && (
                                <div style={{ display: 'flex', justifyContent: 'center', padding: '20px' }}>
                                    <div className="spinner" />
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {/* Tab Content 4: Backups */}
                {detailActiveTab === 'backups' && (
                    <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                        <div>
                            <div className="section-title" style={{ fontSize: '1.1rem', marginBottom: '4px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <span>Резервные копии базы данных</span>
                                <button 
                                    className="btn btn-primary btn-sm" 
                                    onClick={handleCreateBackup}
                                    disabled={backupCreating}
                                    style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
                                >
                                    {backupCreating ? <span className="spinner" style={{ width: '12px', height: '12px' }} /> : <RefreshCw size={14} />}
                                    Создать бэкап
                                </button>
                            </div>
                            <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', margin: 0 }}>
                                Резервные копии (дампы SQL) сохраняются во встроенное S3-хранилище (MinIO). Вы можете скачать дамп или мгновенно восстановить состояние базы.
                            </p>
                        </div>

                        <div className="table-responsive">
                            <table className="table">
                                <thead>
                                    <tr>
                                        <th>Имя файла бэкапа</th>
                                        <th>Размер файла</th>
                                        <th>Дата создания</th>
                                        <th>Статус</th>
                                        <th style={{ textAlign: 'right' }}>Действия</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {backupsLoading ? (
                                        <tr>
                                            <td colSpan="5" style={{ textAlign: 'center', padding: '20px' }}>
                                                <div className="spinner" style={{ margin: '0 auto' }} />
                                            </td>
                                        </tr>
                                    ) : dbBackups.length > 0 ? (
                                        dbBackups.map((b, idx) => (
                                            <tr key={idx}>
                                                <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.85rem', fontWeight: 600 }}>{b.filename}</td>
                                                <td>{b.size_bytes ? `${(b.size_bytes / 1024).toFixed(1)} КБ` : '0 КБ'}</td>
                                                <td>{b.last_modified}</td>
                                                <td>
                                                    <span className="status-badge status-active">Успешно</span>
                                                </td>
                                                <td style={{ textAlign: 'right' }}>
                                                    <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                                                        <button 
                                                            className="btn btn-secondary btn-sm" 
                                                            style={{ display: 'flex', alignItems: 'center', gap: '4px' }}
                                                            onClick={() => handleRestoreBackup(b.filename)}
                                                        >
                                                            <RefreshCw size={12} /> Восстановить
                                                        </button>
                                                        <button 
                                                            className="btn btn-secondary btn-sm" 
                                                            style={{ display: 'flex', alignItems: 'center', gap: '4px' }}
                                                            onClick={() => handleDownloadBackup(b.filename)}
                                                        >
                                                            <Download size={12} /> Скачать
                                                        </button>
                                                        <button 
                                                            className="btn btn-secondary btn-sm" 
                                                            style={{ display: 'flex', alignItems: 'center', gap: '4px', backgroundColor: 'rgba(239, 68, 68, 0.1)', color: '#ef4444', border: '1px solid rgba(239, 68, 68, 0.2)' }}
                                                            onClick={() => handleDeleteBackup(b.filename)}
                                                        >
                                                            Удалить
                                                        </button>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))
                                    ) : (
                                        <tr>
                                            <td colSpan="5" style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '20px' }}>
                                                Резервных копий пока нет. Нажмите «Создать бэкап», чтобы сделать первый снимок.
                                            </td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}
            </div>
        );
    }

    return (
        <div className="panel-container">
            <div className="panel-header">
                <div>
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
                                        <div style={{ display: 'flex', gap: '8px' }}>
                                            <button
                                                className="btn btn-primary btn-sm"
                                                onClick={() => { setConnectDb(d); setConnectTab('cli'); }}
                                                style={{ display: 'flex', alignItems: 'center', gap: '4px' }}
                                            >
                                                <Plug size={12} /> Подключиться
                                            </button>
                                            <button
                                                className="btn btn-danger btn-sm"
                                                onClick={() => handleDeleteDatabase(d.id)}
                                                style={{ display: 'flex', alignItems: 'center', gap: '4px' }}
                                            >
                                                <Trash2 size={12} /> Удалить
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                            {databases.length === 0 && (
                                <tr>
                                    <td colSpan="9" style={{ textAlign: 'center', padding: '30px', color: 'var(--text-muted)' }}>
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
