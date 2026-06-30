import re

with open("frontend/src/components/VMDetail.jsx", "r") as f:
    content = f.read()

# Add new states
imports = "import { X, RefreshCw, Cpu, HardDrive, ShieldAlert, Terminal, Activity, Layers, ListFilter, Play, Square, RotateCw, Monitor, Settings, Trash2, Copy, Check, Eye, EyeOff, AlertTriangle, Key, Shield, Network, Send } from 'lucide-react';"
content = re.sub(r"import \{ X, RefreshCw, .* from 'lucide-react';", imports, content)

states_hook = """  const [activeTab, setActiveTab] = useState('overview'); // 'overview', 'vnc', 'backups'

  // Migration state
  const [showMigrateModal, setShowMigrateModal] = useState(false);
  const [externalServers, setExternalServers] = useState([]);
  const [selectedTargetServer, setSelectedTargetServer] = useState('');
  const [migrating, setMigrating] = useState(false);

  const fetchExternalServersForMigration = async () => {
    try {
      const response = await fetch('/api/external-servers');
      if (response.ok) {
        const data = await response.json();
        setExternalServers(data);
        if (data.length > 0) setSelectedTargetServer(data[0].id);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleMigrate = async () => {
    if (!selectedTargetServer) {
      alert("Выберите сервер назначения");
      return;
    }
    if (!window.confirm("Вы уверены? Виртуальная машина будет перенесена на внешний сервер и удалена из локального кластера. Процесс может занять несколько минут.")) {
      return;
    }
    setMigrating(true);
    try {
      const response = await fetch(`/api/vms/${vmName}/migrate?target_server_id=${selectedTargetServer}`, {
        method: 'POST'
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || "Ошибка миграции");
      }
      alert("Миграция успешно завершена! Машина теперь доступна в списке как внешний сервер.");
      setShowMigrateModal(false);
      onClose();
      if (onActionSuccess) onActionSuccess();
    } catch (err) {
      alert(`Ошибка: ${err.message}`);
    } finally {
      setMigrating(false);
    }
  };
"""
content = content.replace("  const [activeTab, setActiveTab] = useState('overview'); // 'overview', 'vnc', 'backups'", states_hook)

# Add Migrate button
btn_group_old = """            <button className={`btn ${activeTab === 'backups' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setActiveTab('backups')}>
              💾 Бэкапы
            </button>
          </div>
        </div>
      </div>"""

btn_group_new = """            <button className={`btn ${activeTab === 'backups' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setActiveTab('backups')}>
              💾 Бэкапы
            </button>
            <div style={{ width: '1px', background: 'var(--border-subtle)', margin: '0 8px' }}></div>
            <button className="btn btn-secondary" onClick={() => { setShowMigrateModal(true); fetchExternalServersForMigration(); }}>
              <Send size={14} /> Перенести
            </button>
          </div>
        </div>
      </div>"""
content = content.replace(btn_group_old, btn_group_new)

# Add Migrate Modal
modal_code = """      {activeTab === 'overview' && (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(450px, 1fr))', gap: '24px' }}>"""

new_modal_code = """
      {showMigrateModal && (
        <div className="modal-overlay">
          <div className="modal-content" style={{ maxWidth: '500px' }}>
            <div className="modal-header">
              <h3>Миграция ВМ на Внешний сервер</h3>
              <button className="btn-icon-only" onClick={() => setShowMigrateModal(false)}><X size={20} /></button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ background: 'var(--status-warning-bg)', color: 'var(--status-warning)', padding: '16px', borderRadius: 'var(--radius-md)', fontSize: '0.9rem' }}>
                <AlertTriangle size={18} style={{ marginBottom: '8px' }} />
                <p style={{ margin: 0 }}>ВМ будет выключена, а её диск отправлен по SSH на выбранный внешний сервер. После миграции она продолжит работу там, а локальная копия будет удалена.</p>
              </div>
              
              <div className="input-group">
                <label className="input-label">Выберите внешний сервер (Target)</label>
                <select 
                  className="form-control" 
                  value={selectedTargetServer} 
                  onChange={e => setSelectedTargetServer(e.target.value)}
                  disabled={migrating}
                >
                  {externalServers.length === 0 && <option disabled value="">Нет доступных внешних серверов</option>}
                  {externalServers.map(s => (
                    <option key={s.id} value={s.id}>{s.name} ({s.ip})</option>
                  ))}
                </select>
              </div>
              
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setShowMigrateModal(false)} disabled={migrating}>Отмена</button>
              <button className="btn btn-primary" onClick={handleMigrate} disabled={migrating || externalServers.length === 0}>
                {migrating ? <span className="spinner" /> : <><Send size={16} /> Начать миграцию</>}
              </button>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'overview' && (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(450px, 1fr))', gap: '24px' }}>"""

content = content.replace(modal_code, new_modal_code)

with open("frontend/src/components/VMDetail.jsx", "w") as f:
    f.write(content)
