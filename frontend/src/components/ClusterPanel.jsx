import React, { useState, useEffect } from 'react';
import { Layers, Plus, Server, Activity, ArrowRight, X } from 'lucide-react';

const ClusterPanel = ({ vms, onRefreshVms }) => {
  const [clusters, setClusters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [showAttach, setShowAttach] = useState(null);

  // Form State
  const [clusterName, setClusterName] = useState('');
  const [clusterVms, setClusterVms] = useState([]);
  
  const fetchClusters = async () => {
    try {
      const res = await fetch('/api/clusters');
      if (res.ok) {
        setClusters(await res.json());
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchClusters();
  }, []);

  const addVmToForm = () => {
    setClusterVms([...clusterVms, {
      name: `${clusterName}-vm${clusterVms.length + 1}`,
      os_type: 'ubuntu',
      cpu_cores: 2,
      memory_gb: 2,
      disk_gb: 20
    }]);
  };

  const removeVmFromForm = (index) => {
    const next = [...clusterVms];
    next.splice(index, 1);
    setClusterVms(next);
  };

  const handleUpdateVm = (index, field, value) => {
    const next = [...clusterVms];
    next[index][field] = value;
    setClusterVms(next);
  };

  const handleCreateCluster = async (e) => {
    e.preventDefault();
    try {
      const res = await fetch('/api/clusters', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: clusterName,
          vms: clusterVms
        })
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Ошибка создания кластера');
      }
      setShowCreate(false);
      setClusterName('');
      setClusterVms([]);
      fetchClusters();
      if (onRefreshVms) onRefreshVms();
    } catch (err) {
      alert(err.message);
    }
  };

  const handleAttachVMs = async (e) => {
    e.preventDefault();
    const formData = new FormData(e.target);
    const selectedVMs = formData.getAll('vm_names');
    if (selectedVMs.length === 0) return;
    
    try {
      const res = await fetch(`/api/clusters/${showAttach}/attach`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vm_names: selectedVMs })
      });
      if (!res.ok) throw new Error('Ошибка объединения ВМ');
      setShowAttach(null);
      fetchClusters();
      if (onRefreshVms) onRefreshVms();
    } catch (err) {
      alert(err.message);
    }
  };

  if (loading) return <div className="page-loading"><span className="spinner" /></div>;

  return (
    <div style={{ animation: 'fade-in 0.3s ease-out' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '24px' }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: 600, color: 'var(--text-heading)' }}>Кластеры и Изолированные Сети</h2>
        <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
          <Plus size={16} />
          Создать Кластер
        </button>
      </div>

      <div className="grid-responsive">
        {clusters.map(cluster => (
          <div key={cluster.id} className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{ background: 'var(--accent-primary-light)', padding: '10px', borderRadius: '12px', color: 'var(--accent-primary)' }}>
                  <Layers size={24} />
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-heading)' }}>{cluster.name}</h3>
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Сеть: {cluster.network_name}</div>
                </div>
              </div>
              <span className={`status-badge status-${cluster.status.toLowerCase()}`}>{cluster.status}</span>
            </div>

            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '8px' }}>Виртуальные машины:</div>
              {cluster.vms.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {cluster.vms.map(vm => (
                    <div key={vm.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px', background: 'var(--bg-card)', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <Server size={14} color="var(--accent-primary)" />
                        <span style={{ fontSize: '0.9rem', color: 'var(--text-primary)' }}>{vm.name}</span>
                      </div>
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{vm.status}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: '0.9rem', color: 'var(--text-muted)' }}>ВМ отсутствуют</div>
              )}
            </div>

            <button 
              className="btn" 
              style={{ width: '100%', justifyContent: 'center' }}
              onClick={() => setShowAttach(cluster.id)}
            >
              <Plus size={16} />
              Добавить ВМ
            </button>
          </div>
        ))}
      </div>

      {showCreate && (
        <div className="modal-overlay">
          <div className="modal-content" style={{ maxWidth: '700px' }}>
            <div className="modal-header">
              <h2>Создание нового кластера</h2>
              <button className="btn-icon" onClick={() => setShowCreate(false)}><X size={20} /></button>
            </div>
            <form onSubmit={handleCreateCluster}>
              <div className="input-group">
                <label className="input-label">Имя кластера</label>
                <input 
                  type="text" 
                  className="form-control" 
                  value={clusterName} 
                  onChange={(e) => setClusterName(e.target.value)} 
                  required 
                />
              </div>

              <div style={{ marginTop: '24px', marginBottom: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h3 style={{ fontSize: '1.1rem', margin: 0 }}>Виртуальные машины в кластере</h3>
                <button type="button" className="btn btn-secondary btn-sm" onClick={addVmToForm}>
                  <Plus size={14} /> Добавить ВМ
                </button>
              </div>

              {clusterVms.map((vm, index) => (
                <div key={index} style={{ padding: '16px', background: 'var(--bg-secondary)', borderRadius: '12px', marginBottom: '16px', border: '1px solid var(--border-subtle)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                    <div style={{ fontWeight: 600 }}>ВМ {index + 1}</div>
                    <button type="button" className="btn-icon" style={{ color: 'var(--status-danger)' }} onClick={() => removeVmFromForm(index)}>
                      <X size={16} />
                    </button>
                  </div>
                  
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                    <div className="input-group">
                      <label className="input-label">Имя ВМ</label>
                      <input type="text" className="form-control" value={vm.name} onChange={e => handleUpdateVm(index, 'name', e.target.value)} required />
                    </div>
                    <div className="input-group">
                      <label className="input-label">ОС</label>
                      <select className="form-control" value={vm.os_type} onChange={e => handleUpdateVm(index, 'os_type', e.target.value)}>
                        <option value="ubuntu">Ubuntu 24.04</option>
                        <option value="windows">Windows Server</option>
                        <option value="centos">CentOS Stream 9</option>
                        <option value="debian">Debian 12</option>
                        <option value="bitrix">1C-Bitrix</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label className="input-label">Ядра CPU</label>
                      <input type="number" className="form-control" value={vm.cpu_cores} onChange={e => handleUpdateVm(index, 'cpu_cores', parseInt(e.target.value))} required />
                    </div>
                    <div className="input-group">
                      <label className="input-label">Память (ГБ)</label>
                      <input type="number" className="form-control" value={vm.memory_gb} onChange={e => handleUpdateVm(index, 'memory_gb', parseInt(e.target.value))} required />
                    </div>
                  </div>
                </div>
              ))}

              <div className="modal-actions">
                <button type="button" className="btn" onClick={() => setShowCreate(false)}>Отмена</button>
                <button type="submit" className="btn btn-primary" disabled={!clusterName}>Создать и Запустить</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showAttach && (
        <div className="modal-overlay">
          <div className="modal-content">
            <div className="modal-header">
              <h2>Добавить ВМ в кластер</h2>
              <button className="btn-icon" onClick={() => setShowAttach(null)}><X size={20} /></button>
            </div>
            <form onSubmit={handleAttachVMs}>
              <div className="input-group">
                <label className="input-label">Выберите ВМ (зажми Ctrl для выбора нескольких)</label>
                <select name="vm_names" multiple className="form-control" style={{ height: '150px' }} required>
                  {vms.map(vm => (
                    <option key={vm.name} value={vm.name}>{vm.name} ({vm.status})</option>
                  ))}
                </select>
              </div>
              <div style={{ marginTop: '16px', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                * При добавлении ВМ в кластер, она будет перезагружена для подключения нового сетевого интерфейса (Multus).
              </div>
              <div className="modal-actions">
                <button type="button" className="btn" onClick={() => setShowAttach(null)}>Отмена</button>
                <button type="submit" className="btn btn-primary">Объединить</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default ClusterPanel;
