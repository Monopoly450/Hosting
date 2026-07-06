import React, { useState, useEffect } from 'react';
import { Layers, Plus, Server, Activity, ArrowRight, X, Trash, Info, ChevronDown, ChevronUp, HardDrive, Cpu } from 'lucide-react';

const OSIcon = ({ type, size = 16 }) => {
  const os = type?.toLowerCase() || '';
  if (os.includes('ubuntu')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" title="Ubuntu">
        <circle cx="12" cy="12" r="10" stroke="#f97316" strokeWidth="2" />
        <circle cx="12" cy="6" r="2" fill="#f97316" />
        <circle cx="7" cy="14" r="2" fill="#f97316" />
        <circle cx="17" cy="14" r="2" fill="#f97316" />
      </svg>
    );
  }
  if (os.includes('debian')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" title="Debian">
        <path d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM12 18C8.69 18 6 15.31 6 12C6 8.69 8.69 6 12 6C15.31 6 18 8.69 18 12C18 13 17 14 16 14C15 14 14 15 14 16C14 17 13 18 12 18Z" fill="#ef4444" />
      </svg>
    );
  }
  if (os.includes('centos')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" title="CentOS">
        <rect x="4" y="4" width="16" height="16" rx="2" stroke="#84cc16" strokeWidth="2" />
        <path d="M12 8L16 12L12 16L8 12L12 8Z" fill="#84cc16" />
      </svg>
    );
  }
  if (os.includes('windows')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" title="Windows">
        <path d="M3 5.5L10.5 4.5V11.5H3V5.5ZM3 12.5H10.5V19.5L3 18.5V12.5ZM11.5 4.3L21 3V11.5H11.5V4.3ZM11.5 12.5H21V21L11.5 19.7V12.5Z" fill="#0ea5e9" />
      </svg>
    );
  }
  if (os.includes('bitrix')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" title="BitrixVM">
        <path d="M12 2L2 22H22L12 2ZM12 18C11.4 18 11 17.6 11 17C11 16.4 11.4 16 12 16C12.6 16 13 16.4 13 17C13 17.6 12.6 18 12 18ZM13 14H11V9H13V14Z" fill="#ec4899" />
      </svg>
    );
  }
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" title="Other OS">
      <circle cx="12" cy="12" r="10" stroke="#94a3b8" strokeWidth="2" />
      <path d="M12 16V12M12 8H12.01" stroke="#94a3b8" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
};

const ClusterPanel = ({ vms, onRefreshVms }) => {
  const [clusters, setClusters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [showAttach, setShowAttach] = useState(null);
  const [activeVmIndex, setActiveVmIndex] = useState(0);

  // Form State
  const [clusterName, setClusterName] = useState('');
  const [clusterVms, setClusterVms] = useState([
    { name: '', os_type: 'ubuntu', cpu_cores: 2, memory_gb: 2, disk_gb: 20 }
  ]);
  
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
    const nextIndex = clusterVms.length;
    setClusterVms([...clusterVms, {
      name: `${clusterName || 'cluster'}-vm${nextIndex + 1}`,
      os_type: 'ubuntu',
      cpu_cores: 2,
      memory_gb: 2,
      disk_gb: 20
    }]);
    setActiveVmIndex(nextIndex);
  };

  const removeVmFromForm = (index) => {
    const next = [...clusterVms];
    next.splice(index, 1);
    setClusterVms(next);
    setActiveVmIndex(Math.max(0, index - 1));
  };

  const handleUpdateVm = (index, field, value) => {
    const next = [...clusterVms];
    next[index][field] = value;
    setClusterVms(next);
  };

  const handleCreateCluster = async (e) => {
    e.preventDefault();
    try {
      const sanitizedClusterName = clusterName.toLowerCase().replace(/[^a-z0-9-]/g, '-');
      const sanitizedVms = clusterVms.map(vm => ({
        ...vm,
        name: vm.name.toLowerCase().replace(/[^a-z0-9-]/g, '-')
      }));

      const res = await fetch('/api/clusters', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: sanitizedClusterName,
          vms: sanitizedVms
        })
      });
      if (!res.ok) {
        const data = await res.json();
        let errorMsg = 'Ошибка создания кластера';
        if (typeof data.detail === 'string') {
          errorMsg = data.detail;
        } else if (Array.isArray(data.detail)) {
          errorMsg = data.detail.map(e => `${e.loc.join('.')}: ${e.msg}`).join(', ');
        }
        throw new Error(errorMsg);
      }
      setShowCreate(false);
      setClusterName('');
      setClusterVms([{ name: '', os_type: 'ubuntu', cpu_cores: 2, memory_gb: 2, disk_gb: 20 }]);
      setActiveVmIndex(0);
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

  const getClusterStatusBadge = (status) => {
    const norm = status?.toLowerCase();
    if (norm === 'active' || norm === 'running' || norm === 'ready') {
      return <span className="status-badge status-running">Активен</span>;
    }
    if (norm === 'creating' || norm === 'pending' || norm === 'scheduling' || norm === 'scheduled') {
      return <span className="status-badge status-pending" style={{ animation: 'pulse 1.5s infinite' }}>Создается</span>;
    }
    return <span className="status-badge status-stopped">Ошибка</span>;
  };

  if (loading) return <div className="page-loading"><span className="spinner" /></div>;

  return (
    <div style={{ animation: 'fadeIn 0.3s ease-out' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '24px', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--text-heading)', margin: 0 }}>Кластеры и Изолированные Сети</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', margin: '4px 0 0 0' }}>Управляйте изолированными L2 группами виртуальных машин</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
          <Plus size={16} />
          Создать Кластер
        </button>
      </div>

      <div className="grid-responsive">
        {clusters.map(cluster => (
          <div key={cluster.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{ background: 'var(--accent-primary-light)', padding: '10px', borderRadius: '12px', color: 'var(--accent-primary)' }}>
                  <Layers size={24} />
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-heading)' }}>{cluster.name}</h3>
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '2px' }}>Сеть: <code>{cluster.network_name}</code></div>
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                {getClusterStatusBadge(cluster.status)}
                <button 
                  className="btn-icon" 
                  style={{ color: 'var(--status-danger)', background: 'var(--status-danger-bg)' }}
                  title="Удалить кластер"
                  onClick={async () => {
                    if(window.confirm('Вы уверены, что хотите удалить этот кластер? Все ВМ внутри будут безвозвратно удалены!')) {
                      try {
                        const res = await fetch(`/api/clusters/${cluster.id}`, { method: 'DELETE' });
                        if(!res.ok) throw new Error('Ошибка удаления кластера');
                        fetchClusters();
                        onRefreshVms();
                      } catch(e) {
                        alert(e.message);
                      }
                    }
                  }}
                >
                  <Trash size={16} />
                </button>
              </div>
            </div>

            {/* Детали изолированной приватной сети */}
            <div style={{ background: 'var(--bg-surface-hover)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: '16px', marginBottom: '18px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600, color: 'var(--text-heading)', marginBottom: '12px' }}>
                <Info size={16} style={{ color: 'var(--accent-primary)' }} /> Изолированная приватная сеть
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '12px' }}>
                {[
                  ['Подсеть', '192.168.100.0/24'],
                  ['Шлюз', '192.168.100.1'],
                  ['Тип', 'Multus bridge (L2)'],
                  ['Машин в сети', String((cluster.vms || []).length)],
                  ['Всего vCPU', String((cluster.vms || []).reduce((s, v) => s + (v.cpu_cores || 0), 0))],
                  ['Всего RAM', `${(cluster.vms || []).reduce((s, v) => s + (v.memory_gb || 0), 0)} ГБ`],
                ].map(([k, v]) => (
                  <div key={k}>
                    <div className="text-muted" style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.5px', fontWeight: 600 }}>{k}</div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--text-heading)', marginTop: '2px' }}>{v}</div>
                  </div>
                ))}
              </div>
              <p className="text-muted" style={{ fontSize: '0.78rem', marginTop: '12px', lineHeight: 1.5 }}>
                ВМ этого кластера видят друг друга напрямую по адресам <code>192.168.100.x</code> и полностью изолированы от других кластеров (L3-изоляция мостов через iptables). Доступ в интернет — через NAT хоста.
              </p>
            </div>

            <div>
              <div style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--text-heading)', marginBottom: '12px' }}>Виртуальные машины:</div>
              {cluster.vms && cluster.vms.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {cluster.vms.map(vm => (
                    <div key={vm.name} style={{ 
                      display: 'flex', 
                      flexDirection: 'column',
                      gap: '8px', 
                      padding: '12px', 
                      background: 'var(--bg-secondary)', 
                      borderRadius: '10px', 
                      border: '1px solid var(--border-subtle)',
                      boxShadow: 'var(--shadow-sm)'
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyItems: 'center', justifyContent: 'space-between' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <OSIcon type={vm.os_type} size={16} />
                          <span style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--text-primary)' }}>{vm.name}</span>
                        </div>
                        <span className={`status-badge status-${vm.status?.toLowerCase()}`} style={{ fontSize: '0.75rem', padding: '2px 8px' }}>
                          {vm.status === 'Running' ? 'Запущена' : vm.status === 'Stopped' ? 'Остановлена' : vm.status === 'Starting' ? 'Запуск...' : vm.status === 'Stopping' ? 'Выключение...' : vm.status === 'Scheduled' ? 'Планирование...' : vm.status === 'Pending' ? 'Ожидание' : vm.status === 'Provisioning' ? 'Создание' : vm.status}
                        </span>
                      </div>
                      
                      <div style={{ display: 'flex', gap: '12px', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <Cpu size={12} />
                          <span>{vm.cpu_cores} Cores</span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <Layers size={12} />
                          <span>{vm.memory_gb} GB RAM</span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <HardDrive size={12} />
                          <span>{vm.disk_gb} GB Disk</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ 
                  textAlign: 'center', 
                  padding: '24px', 
                  background: 'var(--bg-secondary)', 
                  borderRadius: '10px', 
                  border: '1px dashed var(--border-subtle)',
                  color: 'var(--text-muted)',
                  fontSize: '0.9rem'
                }}>
                  ВМ отсутствуют
                </div>
              )}
            </div>

            <button 
              className="btn btn-secondary" 
              style={{ width: '100%', justifyContent: 'center', marginTop: 'auto' }}
              onClick={() => setShowAttach(cluster.id)}
            >
              <Plus size={16} />
              Добавить ВМ
            </button>
          </div>
        ))}
      </div>

      {/* Slide-over Side Panel for Cluster Creation */}
      {showCreate && (
        <div className="slide-over-overlay" onClick={() => setShowCreate(false)}>
          <div className="slide-over-content" onClick={e => e.stopPropagation()}>
            <div className="slide-over-header">
              <h2>Создание нового кластера</h2>
              <button className="btn-icon" onClick={() => setShowCreate(false)}><X size={20} /></button>
            </div>
            
            <form onSubmit={handleCreateCluster} style={{ display: 'flex', flexDirection: 'column', height: 'calc(100% - 77px)' }}>
              <div className="slide-over-body">
                <div className="input-group">
                  <label className="input-label">Имя кластера (L2 Сети)</label>
                  <input 
                    type="text" 
                    className="form-control" 
                    placeholder="Например: my-isolated-cluster"
                    value={clusterName} 
                    onChange={(e) => setClusterName(e.target.value)} 
                    required 
                  />
                  <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px' }}>Сеть Multus будет создана автоматически в формате <code>[имя]-net</code></span>
                </div>

                <div style={{ marginTop: '28px', marginBottom: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h3 style={{ fontSize: '1.05rem', fontWeight: 600, color: 'var(--text-heading)', margin: 0 }}>Виртуальные машины в кластере</h3>
                  <button type="button" className="btn btn-secondary btn-sm" onClick={addVmToForm}>
                    <Plus size={14} /> Добавить ВМ
                  </button>
                </div>

                {clusterVms.map((vm, index) => {
                  const isExpanded = activeVmIndex === index;
                  return (
                    <div key={index} style={{ 
                      background: 'var(--bg-secondary)', 
                      borderRadius: '12px', 
                      marginBottom: '16px', 
                      border: isExpanded ? '1px solid var(--accent-primary)' : '1px solid var(--border-subtle)',
                      overflow: 'hidden',
                      transition: 'all 0.2s ease'
                    }}>
                      {/* Accordion Header */}
                      <div 
                        onClick={() => setActiveVmIndex(isExpanded ? null : index)}
                        style={{ 
                          padding: '14px 16px', 
                          display: 'flex', 
                          justifyContent: 'space-between', 
                          alignItems: 'center', 
                          cursor: 'pointer',
                          background: isExpanded ? 'rgba(99, 102, 241, 0.02)' : 'transparent',
                          borderBottom: isExpanded ? '1px solid var(--border-subtle)' : 'none'
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <div style={{
                            background: 'var(--bg-surface)',
                            width: '24px',
                            height: '24px',
                            borderRadius: '50%',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            border: '1px solid var(--border-subtle)',
                            fontSize: '0.8rem',
                            fontWeight: '600',
                            color: 'var(--text-secondary)'
                          }}>{index + 1}</div>
                          <div>
                            <span style={{ fontWeight: 600, color: 'var(--text-heading)', fontSize: '0.95rem' }}>
                              {vm.name || `Виртуальная машина ${index + 1}`}
                            </span>
                            {!isExpanded && (
                              <span style={{ marginLeft: '12px', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                {vm.os_type} • {vm.cpu_cores} CPU • {vm.memory_gb}GB RAM
                              </span>
                            )}
                          </div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }} onClick={e => e.stopPropagation()}>
                          {clusterVms.length > 1 && (
                            <button 
                              type="button" 
                              className="btn-icon" 
                              style={{ color: 'var(--status-danger)', padding: '4px' }} 
                              onClick={() => removeVmFromForm(index)}
                            >
                              <Trash size={16} />
                            </button>
                          )}
                          <button 
                            type="button" 
                            className="btn-icon" 
                            style={{ padding: '4px' }}
                            onClick={() => setActiveVmIndex(isExpanded ? null : index)}
                          >
                            {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                          </button>
                        </div>
                      </div>

                      {/* Accordion Body */}
                      {isExpanded && (
                        <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px', background: 'var(--bg-surface)' }}>
                          <div className="input-group">
                            <label className="input-label">Имя ВМ (a-z, 0-9, -)</label>
                            <input 
                              type="text" 
                              className="form-control" 
                              placeholder="Например: db-node-1"
                              value={vm.name} 
                              onChange={e => handleUpdateVm(index, 'name', e.target.value)} 
                              required 
                            />
                          </div>

                          <div className="input-group">
                            <label className="input-label" style={{ marginBottom: '8px' }}>Операционная система</label>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(100px, 1fr))', gap: '8px' }}>
                              {[
                                { id: 'ubuntu', name: 'Ubuntu', desc: '24.04 LTS', color: '#f97316' },
                                { id: 'centos', name: 'CentOS', desc: 'Stream 9', color: '#84cc16' },
                                { id: 'debian', name: 'Debian', desc: 'Debian 12', color: '#ef4444' },
                                { id: 'windows', name: 'Windows', desc: 'Server', color: '#0ea5e9' },
                                { id: 'bitrix', name: 'BitrixVM', desc: 'CentOS 9', color: '#ec4899' }
                              ].map(os => (
                                <div 
                                  key={os.id}
                                  onClick={() => handleUpdateVm(index, 'os_type', os.id)}
                                  style={{
                                    border: vm.os_type === os.id ? '2px solid var(--accent-primary)' : '1px solid var(--border-subtle)',
                                    background: vm.os_type === os.id ? 'rgba(99, 102, 241, 0.05)' : 'var(--bg-surface)',
                                    borderRadius: '8px',
                                    padding: '10px 6px',
                                    cursor: 'pointer',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    alignItems: 'center',
                                    gap: '6px',
                                    textAlign: 'center',
                                    transition: 'all 0.15s ease'
                                  }}
                                >
                                  <OSIcon type={os.id} size={20} />
                                  <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-heading)' }}>{os.name}</span>
                                  <span style={{ fontSize: '0.65rem', color: 'var(--text-secondary)' }}>{os.desc}</span>
                                </div>
                              ))}
                            </div>
                          </div>

                          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginTop: '8px' }}>
                            <div>
                              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                                <span className="input-label" style={{ fontSize: '0.8rem' }}>Ядра CPU</span>
                                <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--accent-primary)' }}>{vm.cpu_cores} Cores</span>
                              </div>
                              <input 
                                type="range" 
                                min="1" 
                                max="16" 
                                value={vm.cpu_cores} 
                                onChange={e => handleUpdateVm(index, 'cpu_cores', parseInt(e.target.value))} 
                                style={{ width: '100%' }} 
                              />
                            </div>

                            <div>
                              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                                <span className="input-label" style={{ fontSize: '0.8rem' }}>Оперативная память</span>
                                <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--accent-primary)' }}>{vm.memory_gb} GB</span>
                              </div>
                              <input 
                                type="range" 
                                min="1" 
                                max="64" 
                                value={vm.memory_gb} 
                                onChange={e => handleUpdateVm(index, 'memory_gb', parseInt(e.target.value))} 
                                style={{ width: '100%' }} 
                              />
                            </div>

                            <div>
                              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                                <span className="input-label" style={{ fontSize: '0.8rem' }}>Размер диска</span>
                                <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--accent-primary)' }}>{vm.disk_gb} GB</span>
                              </div>
                              <input 
                                type="range" 
                                min="10" 
                                max="500" 
                                step="10"
                                value={vm.disk_gb} 
                                onChange={e => handleUpdateVm(index, 'disk_gb', parseInt(e.target.value))} 
                                style={{ width: '100%' }} 
                              />
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>

              <div className="slide-over-actions">
                <button type="button" className="btn" onClick={() => setShowCreate(false)}>Отмена</button>
                <button type="submit" className="btn btn-primary" disabled={!clusterName || clusterVms.length === 0}>
                  Создать и Запустить
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showAttach && (
        <div className="modal-overlay" onClick={() => setShowAttach(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Добавить ВМ в кластер</h2>
              <button className="btn-icon" onClick={() => setShowAttach(null)}><X size={20} /></button>
            </div>
            <form onSubmit={handleAttachVMs}>
              <div className="input-group" style={{ padding: '0 24px' }}>
                <label className="input-label">Выберите ВМ (зажмите Ctrl/Cmd для выбора нескольких)</label>
                <select name="vm_names" multiple className="form-control" style={{ height: '180px', marginTop: '8px' }} required>
                  {vms.filter(v => !clusters.some(c => c.vms.some(cv => cv.name === v.name))).map(vm => (
                    <option key={vm.name} value={vm.name}>{vm.name} ({vm.status === 'Running' ? 'Запущена' : vm.status})</option>
                  ))}
                </select>
              </div>
              <div style={{ padding: '16px 24px', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                * При добавлении ВМ в кластер, она будет перезагружена для подключения нового приватного сетевого интерфейса (Multus).
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
