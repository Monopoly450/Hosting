import React, { useEffect, useState } from 'react';
import { RefreshCw, Play, Trash2, Calendar, HardDrive, Plus, CheckCircle, AlertCircle } from 'lucide-react';

const BackupList = ({ vmName, vmStatus, onRestoreStarted }) => {
  const [backups, setBackups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(null); // 'create' | 'delete-id' | 'restore-id'

  const fetchBackups = async () => {
    try {
      const response = await fetch(`/api/vms/${vmName}/backups`);
      if (!response.ok) throw new Error('Failed to fetch backups');
      const data = await response.json();
      setBackups(data);
    } catch (err) {
      console.error('Error fetching backups:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBackups();
    // Опрашиваем бэкапы каждые 4 секунды (полезно для отслеживания прогресса создания)
    const interval = setInterval(fetchBackups, 4000);
    return () => clearInterval(interval);
  }, [vmName]);

  const handleCreateBackup = async () => {
    setActionLoading('create');
    try {
      const response = await fetch(`/api/vms/${vmName}/backup`, { method: 'POST' });
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Не удалось запустить резервное копирование.');
      }
      fetchBackups();
    } catch (err) {
      alert(`Ошибка бэкапа: ${err.message}`);
    } finally {
      setActionLoading(null);
    }
  };

  const handleDeleteBackup = async (backupName) => {
    if (!confirm(`Вы действительно хотите безвозвратно удалить резервную копию "${backupName}"?`)) return;
    setActionLoading(`delete-${backupName}`);
    try {
      const response = await fetch(`/api/vms/${vmName}/backups/${backupName}`, { method: 'DELETE' });
      if (!response.ok) throw new Error('Failed to delete backup');
      fetchBackups();
    } catch (err) {
      alert(`Ошибка удаления бэкапа: ${err.message}`);
    } finally {
      setActionLoading(null);
    }
  };

  const handleRestoreBackup = async (backupName) => {
    let confirmMsg = `Внимание! При восстановлении из резервной копии "${backupName}" текущий диск виртуальной машины будет заменен на момент сохранения бэкапа.\n`;
    if (vmStatus === 'Running') {
      confirmMsg += `\nВиртуальная машина "${vmName}" будет автоматически выключена для проведения замены диска.`;
    }
    confirmMsg += `\n\nПродолжить восстановление?`;

    if (!confirm(confirmMsg)) return;

    setActionLoading(`restore-${backupName}`);
    try {
      const response = await fetch(`/api/vms/${vmName}/restore/${backupName}`, { method: 'POST' });
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Ошибка при восстановлении.');
      }
      alert('Запущен процесс восстановления диска. Виртуалка запустится после копирования.');
      if (onRestoreStarted) onRestoreStarted();
    } catch (err) {
      alert(`Ошибка восстановления: ${err.message}`);
    } finally {
      setActionLoading(null);
    }
  };

  const formatTime = (timeStr) => {
    if (!timeStr) return '';
    const date = new Date(timeStr);
    return date.toLocaleString();
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'Succeeded': return <CheckCircle size={14} color="var(--success)" />;
      case 'Importing': 
      case 'CloneSource':
      case 'Running':
        return <span className="spinner" style={{ width: '12px', height: '12px', borderWidth: '2px' }} />;
      default: return <AlertCircle size={14} color="var(--danger)" />;
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="resource-label">Список резервных копий:</span>
        <button 
          className="btn btn-primary btn-sm"
          onClick={handleCreateBackup}
          disabled={actionLoading !== null}
        >
          {actionLoading === 'create' ? (
            <span className="spinner" style={{ width: '12px', height: '12px', borderWidth: '2px', borderColor: '#000' }} />
          ) : (
            <Plus size={12} />
          )}
          Создать копию
        </button>
      </div>

      {loading && backups.length === 0 ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '15px' }}>
          <div className="spinner"></div>
        </div>
      ) : backups.length === 0 ? (
        <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8rem', padding: '15px', border: '1px dashed var(--border-color)', borderRadius: 'var(--radius-md)' }}>
          Нет сохраненных резервных копий.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '250px', overflowY: 'auto', paddingRight: '4px' }}>
          {backups.map((b) => (
            <div 
              key={b.name}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '10px 14px',
                borderRadius: 'var(--radius-md)',
                background: 'rgba(0, 0, 0, 0.2)',
                border: '1px solid var(--border-color)',
                fontSize: '0.8rem'
              }}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <div style={{ fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  {getStatusIcon(b.status)}
                  <span>{b.name}</span>
                </div>
                <div style={{ display: 'flex', gap: '15px', color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Calendar size={12} /> {formatTime(b.created_at)}
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <HardDrive size={12} /> {b.size}
                  </span>
                </div>
                {/* Если бэкап клонируется, показываем прогресс */}
                {b.status !== 'Succeeded' && b.progress !== 'N/A' && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '4px' }}>
                    {/* .progress-bar-bg/.progress-bar-fill в CSS нет —
                        полоса прогресса не рисовалась вовсе. Классы
                        дизайн-системы: .progress-track/.progress-fill. */}
                    <div className="progress-track" style={{ height: '3px', width: '80px' }}>
                      <div className="progress-fill primary" style={{ width: b.progress }} />
                    </div>
                    <span style={{ fontSize: '0.7rem', color: 'var(--primary)', fontWeight: 600 }}>{b.progress}</span>
                  </div>
                )}
              </div>

              <div style={{ display: 'flex', gap: '6px' }}>
                {b.status === 'Succeeded' && (
                  <button 
                    className="btn btn-secondary btn-sm"
                    onClick={() => handleRestoreBackup(b.name)}
                    disabled={actionLoading !== null}
                    style={{ fontSize: '0.75rem', padding: '4px 8px' }}
                  >
                    {actionLoading === `restore-${b.name}` ? 'Восстановление...' : 'Восстановить'}
                  </button>
                )}
                <button 
                  className="btn btn-danger btn-sm btn-icon-only"
                  onClick={() => handleDeleteBackup(b.name)}
                  disabled={actionLoading !== null}
                  style={{ padding: '6px' }}
                >
                  <Trash2 size={12} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default BackupList;
