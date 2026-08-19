import React, { useEffect, useState } from 'react';
import { Trash2, Calendar, HardDrive, Plus, CheckCircle, AlertCircle, RotateCcw } from 'lucide-react';

const BackupList = ({ vmName, vmStatus, onRestoreStarted }) => {
  const [backups, setBackups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(null); // 'create' | 'delete-id' | 'restore-id'

  const fetchBackups = async () => {
    try {
      const response = await fetch(`/api/vms/${vmName}/backups`, { cache: 'no-store' });
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
      const data = await response.json().catch(() => ({}));
      alert(data.will_restart
        ? 'Запущено восстановление диска. Виртуалка включится сама после копирования.'
        : 'Запущено восстановление диска. Виртуалка останется выключенной, как и до восстановления.');
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

  /* Фазы DataVolume у CDI. Раньше разбирались ровно три, а «в работе» у CDI
     их с десяток — все остальные попадали в default и рисовались красным
     кружком «ошибка». Копия, которая спокойно клонируется, выглядела
     сломанной, и восстановить её было нельзя: кнопка появляется только у
     Succeeded. */
  const IN_PROGRESS = [
    'Pending', 'PendingPopulation', 'PVCBound', 'WaitForFirstConsumer',
    'ImportScheduled', 'ImportInProgress', 'Importing',
    'CloneScheduled', 'CloneInProgress', 'CloneSource', 'Running',
    'SnapshotForSmartCloneInProgress', 'CloneFromSnapshotSourceInProgress',
    'SmartClonePVCInProgress', 'CSICloneInProgress', 'ExpansionInProgress',
    'NamespaceTransferInProgress', 'UploadScheduled', 'UploadReady', 'Paused',
  ];

  const STATUS_LABELS = {
    Succeeded: 'Готова',
    Failed: 'Не удалась',
    Unknown: 'Состояние неизвестно',
    Pending: 'В очереди',
    PendingPopulation: 'В очереди',
    PVCBound: 'Том выделен',
    WaitForFirstConsumer: 'Ждёт запуска ВМ',
    Paused: 'Приостановлена',
  };

  /* CDI отдаёт progress строкой — «43.2%», либо «N/A», пока считать нечего
     (клон ещё не начался, или драйвер копирует снимком и промежуточных
     значений не сообщает вовсе). */
  const hasPercent = (raw) => typeof raw === 'string' && /^[\d.]+%$/.test(raw);
  const percentOf = (raw) => (hasPercent(raw) ? raw : '0%');

  const isDone = (b) => b.status === 'Succeeded';
  const isBusy = (b) => IN_PROGRESS.includes(b.status);

  const statusLabel = (b) => STATUS_LABELS[b.status] || (isBusy(b) ? 'Копируется' : b.status);

  const getStatusIcon = (b) => {
    if (isDone(b)) return <CheckCircle size={14} color="var(--status-success)" />;
    if (isBusy(b)) return <span className="spinner" style={{ width: '12px', height: '12px', borderWidth: '2px' }} />;
    return <AlertCircle size={14} color="var(--status-danger)" />;
  };

  /* Размер приходит из PVC как есть: «22763326669» — столько байт, сколько
     запросил CDI. В списке это читалось как случайный номер. */
  const formatSize = (raw) => {
    if (raw === null || raw === undefined || raw === '') return '';
    const asNumber = Number(raw);
    if (!Number.isFinite(asNumber)) return String(raw);  // «40Gi» и подобное — уже читаемо
    const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
    let value = asNumber;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
      value /= 1024;
      unit += 1;
    }
    return `${value >= 10 || unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
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
            <Plus size={14} />
          )}
          Создать копию
        </button>
      </div>

      {loading && backups.length === 0 ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '15px' }}>
          <div className="spinner"></div>
        </div>
      ) : backups.length === 0 ? (
        <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.9rem', padding: '28px', border: '1px dashed var(--border-default)', borderRadius: 'var(--radius-md)' }}>
          Нет сохраненных резервных копий.
        </div>
      ) : (
        /* Блок был заметно мельче всего вокруг: строка 0.8rem против 0.9rem
           в таблицах, и окно на 250px, в котором помещались две копии из
           десяти. Список бэкапов — не подпись под графиком, читать его
           приходится так же, как таблицу снимков рядом. */
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', maxHeight: '460px', overflowY: 'auto', paddingRight: '4px' }}>
          {backups.map((b) => (
            <div 
              key={b.name}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '14px 18px',
                borderRadius: 'var(--radius-md)',
                /* Было rgba(0,0,0,0.2) — заливка чёрным поверх фона. В тёмной
                   теме сходило за подложку, а в светлой давало ровно ту серую
                   плашку, на которой не читались ни текст, ни кнопки. */
                background: 'var(--bg-surface-hover)',
                border: '1px solid var(--border-default)',
                fontSize: '0.9rem'
              }}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <div style={{ fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  {getStatusIcon(b)}
                  <span>{b.name}</span>
                </div>
                <div style={{ display: 'flex', gap: '16px', color: 'var(--text-muted)', fontSize: '0.82rem' }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Calendar size={14} /> {formatTime(b.created_at)}
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <HardDrive size={14} /> {formatSize(b.size)}
                  </span>
                  {/* Статус словами. Без него у незавершённой копии просто нет
                      кнопки «Восстановить», и непонятно, ждать её или это
                      уже отказ. */}
                  <span style={{ color: isDone(b) ? 'var(--status-success)' : isBusy(b) ? 'var(--text-muted)' : 'var(--status-danger)' }}
                        title={b.detail || undefined}>
                    {statusLabel(b)}
                  </span>
                </div>
                {/* Причина, по которой копия встала. Сама фаза не объясняет
                    ничего: «Состояние неизвестно» одинаково выглядит и у копии,
                    созданной секунду назад, и у той, которой некуда лечь. CDI
                    пишет причину в conditions — её и показываем, иначе
                    пользователю остаётся гадать, ждать или чинить. */}
                {b.detail && !isDone(b) && (
                  <div style={{ marginTop: '6px', fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.4 }}>
                    {b.detail}
                  </div>
                )}
                {/* Полоса нужна на всём времени копирования, а не только
                    когда CDI уже посчитал процент. Условие progress !== 'N/A'
                    прятало её целиком в самом начале — ровно тогда, когда
                    смотришь, пошло ли дело: копия висела строкой без единого
                    признака движения. Ширину в этот момент берём нулевой, а
                    само число заменяем на «идёт» — врать про 0% не нужно,
                    ноль означал бы «посчитано и ничего не сделано». */}
                {isBusy(b) && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '6px' }}>
                    {/* .progress-bar-bg/.progress-bar-fill в CSS нет —
                        полоса прогресса не рисовалась вовсе. Классы
                        дизайн-системы: .progress-track/.progress-fill. */}
                    <div className="progress-track" style={{ height: '4px', width: '110px' }}>
                      <div
                        className={`progress-fill primary ${hasPercent(b.progress) ? '' : 'indeterminate'}`}
                        style={hasPercent(b.progress) ? { width: percentOf(b.progress) } : undefined}
                      />
                    </div>
                    <span style={{ fontSize: '0.78rem', color: 'var(--accent-primary)', fontWeight: 600 }}>
                      {hasPercent(b.progress) ? b.progress : 'идёт…'}
                    </span>
                  </div>
                )}
              </div>

              <div style={{ display: 'flex', gap: '6px' }}>
                {/* Кнопку показываем всегда, а не только у готовой копии:
                    иначе на строке нет ничего, кроме корзины, и создаётся
                    впечатление, что восстановления в панели нет вовсе.
                    Недоступна она ровно пока копия не готова — восстановить
                    из наполовину склонированного тома значит затереть диск
                    ВМ мусором. */}
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => handleRestoreBackup(b.name)}
                  disabled={actionLoading !== null || !isDone(b)}
                  title={isDone(b)
                    ? 'Заменить диск ВМ содержимым этой копии'
                    : isBusy(b)
                      ? 'Копия ещё создаётся — восстановление будет доступно, когда она завершится'
                      : `Копия не готова (${statusLabel(b)}) — восстанавливать из неё нельзя`}
                  style={{ fontSize: '0.82rem', padding: '7px 12px', display: 'flex', alignItems: 'center', gap: '6px' }}
                >
                  <RotateCcw size={14} />
                  {actionLoading === `restore-${b.name}` ? 'Восстановление...' : 'Восстановить'}
                </button>
                <button 
                  className="btn btn-danger btn-sm btn-icon-only"
                  onClick={() => handleDeleteBackup(b.name)}
                  disabled={actionLoading !== null}
                  style={{ padding: '8px' }}
                >
                  <Trash2 size={14} />
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
