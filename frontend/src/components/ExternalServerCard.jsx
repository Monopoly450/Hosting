import React, { useState } from 'react';
import { Globe, Terminal, Trash2, ShieldCheck, ShieldAlert, Network } from 'lucide-react';

/**
 * Карточка внешнего сервера. Свёрстана как VMCard и стоит с ней в одной
 * сетке, поэтому и выглядеть должна так же: раньше она пользовалась старыми
 * классами (card vm-card, status-badge) и переменными-псевдонимами
 * (--bg-card, --success, --danger), держала эмодзи вместо иконки, а данные
 * доступа заворачивала в серый блок моноширинным шрифтом — рядом с обычными
 * карточками ВМ это выбивалось из общего вида.
 */
const ExternalServerCard = ({ server, onClick, onDeleteSuccess }) => {
  const [deleting, setDeleting] = useState(false);
  const online = server.status === 'Online';

  const handleDelete = async (e) => {
    e.stopPropagation(); // Предотвращаем открытие деталей при клике на удаление
    if (!confirm(`Вы действительно хотите отключить сервер "${server.name}" (${server.host})?`)) return;

    setDeleting(true);
    try {
      const response = await fetch(`/api/external-servers/${server.id}`, {
        method: 'DELETE'
      });
      if (!response.ok) throw new Error('Ошибка удаления сервера');
      onDeleteSuccess();
    } catch (err) {
      alert(err.message);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div
      className="glass-card interactive"
      onClick={onClick}
      style={{ cursor: 'pointer', display: 'flex', flexDirection: 'column', padding: '20px' }}
    >
      {/* Шапка: иконка, имя, статус — та же раскладка, что у карточки ВМ */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <Globe size={24} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
          <div>
            <div style={{ fontWeight: 600, color: 'var(--text-heading)', fontSize: '1.05rem', marginBottom: '2px' }}>{server.name}</div>
            <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase' }}>Внешний сервер</div>
          </div>
        </div>
        <span className={`badge ${online ? 'badge-success' : 'badge-danger'}`}>
          <span className="status-dot"></span>
          {online ? 'В сети' : 'Не в сети'}
        </span>
      </div>

      {/* Реквизиты подключения — строками «подпись / значение», как IP у ВМ */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '16px', fontSize: '0.8rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
          <span className="text-muted" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Network size={12} /> Адрес</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--text-heading)' }}>{server.host}:{server.port}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
          <span className="text-muted" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Terminal size={12} /> Пользователь</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--text-heading)' }}>{server.username}</span>
        </div>
        {server.use_bastion && (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
            <span className="text-muted" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Network size={12} /> Бастион</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--text-heading)' }}>{server.bastion_host}</span>
          </div>
        )}
      </div>

      {/* Состояние доступа. Цветом и иконкой, без серой плашки: она была
          единственным таким блоком во всём интерфейсе. */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem',
                    color: online ? 'var(--status-success)' : 'var(--status-danger)' }}>
        {online ? <ShieldCheck size={14} /> : <ShieldAlert size={14} />}
        <span>{online ? 'Доступ по SSH подтверждён' : 'Ошибка авторизации или хост оффлайн'}</span>
      </div>

      <div style={{ marginTop: 'auto', paddingTop: '16px', borderTop: '1px solid var(--border-subtle)',
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="text-muted" style={{ fontSize: '0.75rem' }}>Открыть мониторинг ➔</span>
        <button
          className="btn btn-secondary btn-icon"
          onClick={handleDelete}
          disabled={deleting}
          title="Отключить сервер"
          style={{ color: '#ef4444', borderColor: '#fee2e2' }}
        >
          {deleting ? <span className="spinner" /> : <Trash2 size={14} />}
        </button>
      </div>
    </div>
  );
};

export default ExternalServerCard;
