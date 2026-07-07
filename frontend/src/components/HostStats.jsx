import React, { useEffect, useState } from 'react';
import { Cpu, HardDrive, Server, RefreshCw, Activity, Settings, Clock } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, ResponsiveContainer, Tooltip, CartesianGrid } from 'recharts';
import Portal from './Portal';

const HostStats = ({ onMetricsLoaded }) => {
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [selectedStorageTab, setSelectedStorageTab] = useState(null);

  const [showResize, setShowResize] = useState(false);
  const [newSizeGb, setNewSizeGb] = useState('');
  const [resizing, setResizing] = useState(false);
  const [resizeStatus, setResizeStatus] = useState(null);

  const [promHistory, setPromHistory] = useState(null);
  const [promRange, setPromRange] = useState(3);
  const [promLoading, setPromLoading] = useState(false);

  const handleResizeLvm = async (e) => {
    e.preventDefault();
    const size = parseInt(newSizeGb);
    if (isNaN(size) || size <= 0) {
      alert("Пожалуйста, введите корректный размер в ГБ.");
      return;
    }
    
    setResizing(true);
    setResizeStatus(null);
    try {
      const response = await fetch('/api/host/storage/resize', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('aegis_admin_token')}`
        },
        body: JSON.stringify({ size_gb: size })
      });
      
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Не удалось расширить хранилище");
      }
      
      setResizeStatus({ success: true, message: data.message });
      setNewSizeGb('');
      fetchMetrics();
      setTimeout(() => setShowResize(false), 3000);
    } catch (err) {
      setResizeStatus({ success: false, message: err.message });
    } finally {
      setResizing(false);
    }
  };

  const fetchMetrics = async () => {
    try {
      const response = await fetch('/api/host/metrics');
      if (!response.ok) throw new Error('Failed to fetch host metrics');
      const data = await response.json();
      
      setMetrics(data);
      setError(false);
      
      if (!selectedStorageTab) {
        if (data.shared_disk && data.shared_disk.active) {
          setSelectedStorageTab('nfs');
        } else if (data.lvm && data.lvm.active) {
          setSelectedStorageTab('lvm');
        } else {
          setSelectedStorageTab('local');
        }
      }
      
      if (onMetricsLoaded) onMetricsLoaded(data);
    } catch (err) {
      console.error(err);
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  const fetchPromHistory = async (hours) => {
    setPromLoading(true);
    try {
      const response = await fetch(`/api/host/prometheus/history?hours=${hours}`);
      if (!response.ok) throw new Error('Failed');
      const data = await response.json();
      
      // Merge CPU and RAM data by timestamp
      const merged = [];
      const cpuMap = {};
      for (const p of (data.cpu || [])) {
        cpuMap[p.timestamp] = p.value;
      }
      for (const p of (data.ram || [])) {
        merged.push({
          time: new Date(p.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          cpu: cpuMap[p.timestamp] ?? null,
          ram: p.value
        });
      }
      // If RAM was empty, use CPU data alone
      if (merged.length === 0) {
        for (const p of (data.cpu || [])) {
          merged.push({
            time: new Date(p.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            cpu: p.value,
            ram: null
          });
        }
      }
      setPromHistory(merged.length > 0 ? merged : null);
    } catch (err) {
      console.error('Prometheus history error:', err);
      setPromHistory(null);
    } finally {
      setPromLoading(false);
    }
  };

  useEffect(() => {
    fetchMetrics();
    fetchPromHistory(promRange);
    const interval = setInterval(fetchMetrics, 3000);
    const promInterval = setInterval(() => fetchPromHistory(promRange), 60000);
    return () => { clearInterval(interval); clearInterval(promInterval); };
  }, [promRange]);

  if (loading && !metrics) {
    return (
      <div className="glass-card" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '300px' }}>
        <div className="spinner"></div>
      </div>
    );
  }

  if (error && !metrics) {
    return (
      <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px', padding: '40px' }}>
        <Activity size={40} color="var(--status-danger)" />
        <h3 className="section-title" style={{ margin: 0, color: 'var(--status-danger)' }}>Сбой подключения</h3>
        <p className="text-muted">Не удалось загрузить метрики хоста. Сервер недоступен.</p>
        <button className="btn btn-secondary" onClick={fetchMetrics}>
          <RefreshCw size={16} /> Повторить
        </button>
      </div>
    );
  }

  const cpuPercent = metrics.cpu.usage_percent;
  const memoryPercent = metrics.memory.usage_percent;

  const getProgressClass = (val) => {
    if (val < 70) return 'success';
    if (val < 90) return 'warning';
    return 'danger';
  };

  return (
    <div className="glass-card interactive">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <h3 className="section-title" style={{ margin: 0 }}><Server size={20} /> Гипервизор и Кластер</h3>
        <span className="badge badge-success"><span className="status-dot"></span> Online</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '24px', marginBottom: '32px' }}>
        {/* CPU */}
        <div className="stat-box">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="stat-box-title" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><Cpu size={16}/> Load CPU</span>
            <span className="stat-box-value">{cpuPercent}%</span>
          </div>
          <div className="progress-track">
            <div className={`progress-fill ${getProgressClass(cpuPercent)}`} style={{ width: `${cpuPercent}%` }} />
          </div>
          <div className="stat-box-meta">
            <span>Использовано хостом: {metrics.cpu.usage_cores} из {metrics.cpu.total_cores} ядер</span>
            <span>Занято ВМ (резерв): {metrics.cpu.reserved_cores} ядер</span>
            <span>Доступно для новых ВМ: {metrics.cpu.available_cores} ядер</span>
          </div>
          {metrics.cpu.model && (
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '6px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={metrics.cpu.model}>
              ЦП: {metrics.cpu.sockets > 1 ? `${metrics.cpu.sockets}x ` : ''}{metrics.cpu.model}
            </div>
          )}
        </div>

        {/* RAM */}
        <div className="stat-box">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="stat-box-title" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><HardDrive size={16}/> ОЗУ (Memory)</span>
            <span className="stat-box-value">{memoryPercent}%</span>
          </div>
          <div className="progress-track">
            <div className={`progress-fill ${getProgressClass(memoryPercent)}`} style={{ width: `${memoryPercent}%` }} />
          </div>
          <div className="stat-box-meta">
            <span>Использовано хостом: {metrics.memory.usage_gb} из {metrics.memory.total_gb} ГБ</span>
            <span>Занято ВМ (резерв): {metrics.memory.reserved_gb} ГБ</span>
            <span>Доступно для новых ВМ: {metrics.memory.available_gb} ГБ</span>
          </div>
        </div>

        {/* Local SSD */}
        <div className="stat-box">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="stat-box-title" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><HardDrive size={16}/> Локальный SSD (Панель)</span>
            <span className="stat-box-value">
              {metrics.local_disk ? metrics.local_disk.used_percent : (metrics.disk ? metrics.disk.used_percent : 0)}%
            </span>
          </div>
          <div className="progress-track">
            <div 
              className={`progress-fill ${getProgressClass(metrics.local_disk ? metrics.local_disk.used_percent : (metrics.disk ? metrics.disk.used_percent : 0))}`} 
              style={{ width: `${metrics.local_disk ? metrics.local_disk.used_percent : (metrics.disk ? metrics.disk.used_percent : 0)}%` }} 
            />
          </div>
          <div className="stat-box-meta">
            <span>Использовано хостом: {metrics.local_disk ? metrics.local_disk.used_gb : (metrics.disk ? metrics.disk.used_gb : 0)} из {metrics.local_disk ? metrics.local_disk.total_gb : (metrics.disk ? metrics.disk.total_gb : 0)} ГБ</span>
            {metrics.is_cluster ? (
              <span>Выделено ВМ: {metrics.local_reserved ? `${metrics.local_reserved.cpu_cores} vCPU / ${metrics.local_reserved.memory_gb} ГБ ОЗУ / ${metrics.local_reserved.disk_gb} ГБ диск` : '0'}</span>
            ) : (
              <span>Занято ВМ (резерв): {metrics.disk ? metrics.disk.reserved_gb : 0} ГБ</span>
            )}
            <span>Доступно для новых ВМ: {metrics.disk ? metrics.disk.available_gb : 0} ГБ</span>
          </div>
        </div>

        {/* Network СХД / NFS */}
        {metrics.shared_disk && metrics.shared_disk.active && (
          <div className="stat-box">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span className="stat-box-title" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><HardDrive size={16}/> Сетевая СХД (NFS)</span>
              <span className="stat-box-value">{metrics.shared_disk.used_percent}%</span>
            </div>
            <div className="progress-track">
              <div 
                className={`progress-fill ${getProgressClass(metrics.shared_disk.used_percent)}`} 
                style={{ width: `${metrics.shared_disk.used_percent}%` }} 
              />
            </div>
            <div className="stat-box-meta">
              <span>Использовано: {metrics.shared_disk.used_gb} из {metrics.shared_disk.total_gb} ГБ</span>
              <span>Свободно на СХД: {metrics.shared_disk.free_gb} ГБ</span>
              {metrics.is_cluster ? (
                <span>Выделено ВМ: {metrics.nfs_reserved ? `${metrics.nfs_reserved.cpu_cores} vCPU / ${metrics.nfs_reserved.memory_gb} ГБ ОЗУ / ${metrics.nfs_reserved.disk_gb} ГБ диск` : '0'}</span>
              ) : (
                <span>Занято ВМ (резерв): {metrics.nfs_reserved ? metrics.nfs_reserved.disk_gb : 0} ГБ</span>
              )}
            </div>
          </div>
        )}

        {/* LVM Pool */}
        {metrics.lvm && (
          <div className="stat-box">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span className="stat-box-title" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><HardDrive size={16}/> LVM Хранилище (PaaS)</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                {localStorage.getItem('aegis_role') === 'admin' && metrics.lvm.active && (
                  <button 
                    className="btn btn-secondary btn-icon-only" 
                    style={{ 
                      width: '28px', 
                      height: '28px', 
                      padding: 0, 
                      display: 'flex', 
                      alignItems: 'center', 
                      justifyContent: 'center', 
                      borderRadius: '50%',
                      border: '1px solid var(--border-subtle)',
                      background: 'var(--bg-surface-hover)',
                      cursor: 'pointer',
                      transition: 'all 0.2s'
                    }}
                    onClick={() => { setShowResize(!showResize); setResizeStatus(null); }}
                    title="Управление пулом LVM"
                  >
                    <Settings size={14} style={{ color: showResize ? 'var(--accent-primary)' : 'var(--text-secondary)' }} />
                  </button>
                )}
                <span className="stat-box-value">
                  {metrics.lvm.total_gb > 0 ? Math.round((metrics.lvm.used_gb / metrics.lvm.total_gb) * 100) : 0}%
                </span>
              </div>
            </div>
            <div className="progress-track">
              <div 
                className={`progress-fill ${getProgressClass(metrics.lvm.total_gb > 0 ? (metrics.lvm.used_gb / metrics.lvm.total_gb) * 100 : 0)}`} 
                style={{ width: `${metrics.lvm.total_gb > 0 ? (metrics.lvm.used_gb / metrics.lvm.total_gb) * 100 : 0}%` }} 
              />
            </div>
            <div className="stat-box-meta">
              <span>Общая емкость пула: {metrics.lvm.total_gb} ГБ | Занято: {metrics.lvm.used_gb} ГБ</span>
              <span>Зарезервировано сетевыми дисками: {metrics.lvm.reserved_gb ?? 0} ГБ</span>
              <span style={{ fontWeight: 600, color: 'var(--accent-primary)' }}>Свободно (доступно): {metrics.lvm.free_gb} ГБ</span>
            </div>
          </div>
        )}
      </div>
      


      {/* Prometheus Historical Chart */}
      <div style={{ marginBottom: '24px', padding: '20px', background: 'var(--bg-surface-hover)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h4 style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-heading)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Clock size={16} /> Статистика загрузки (Prometheus)
          </h4>
          <div style={{ display: 'flex', gap: '6px' }}>
            {[1, 3, 6, 12, 24].map(h => (
              <button
                key={h}
                type="button"
                className={`btn btn-sm ${promRange === h ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setPromRange(h)}
                style={{ padding: '4px 10px', fontSize: '0.75rem', borderRadius: 'var(--radius-sm)', cursor: 'pointer', minWidth: '40px' }}
              >
                {h}ч
              </button>
            ))}
          </div>
        </div>
        {promLoading && !promHistory ? (
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '200px' }}>
            <div className="spinner" />
          </div>
        ) : promHistory && promHistory.length > 0 ? (
          <div style={{ height: '220px', width: '100%' }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={promHistory} margin={{ top: 5, right: 10, left: -15, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorPromCpu" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#FF5C00" stopOpacity={0.25}/>
                    <stop offset="95%" stopColor="#FF5C00" stopOpacity={0}/>
                  </linearGradient>
                  <linearGradient id="colorPromRam" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10B981" stopOpacity={0.25}/>
                    <stop offset="95%" stopColor="#10B981" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" opacity={0.5} />
                <XAxis 
                  dataKey="time" 
                  tick={{ fontSize: 11, fill: 'var(--text-muted)' }} 
                  tickLine={false}
                  axisLine={{ stroke: 'var(--border-subtle)' }}
                  interval={Math.max(0, Math.floor(promHistory.length / 8))}
                />
                <YAxis 
                  domain={[0, 100]} 
                  tickLine={false} 
                  axisLine={false} 
                  tick={{ fontSize: 11, fill: 'var(--text-muted)' }}
                  tickFormatter={v => `${v}%`}
                />
                <Tooltip 
                  contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-lg)', fontSize: '0.85rem' }}
                  labelStyle={{ color: 'var(--text-secondary)', marginBottom: '4px', fontWeight: 600 }}
                  formatter={(value) => [`${value}%`]}
                />
                <Area type="monotone" dataKey="cpu" name="CPU" stroke="#FF5C00" fillOpacity={1} fill="url(#colorPromCpu)" strokeWidth={2} dot={false} />
                <Area type="monotone" dataKey="ram" name="RAM" stroke="#10B981" fillOpacity={1} fill="url(#colorPromRam)" strokeWidth={2} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', padding: '40px 0', color: 'var(--text-muted)' }}>
            <Clock size={32} opacity={0.4} />
            <span style={{ fontSize: '0.85rem' }}>Нет данных Prometheus за выбранный период</span>
            <span style={{ fontSize: '0.75rem' }}>Убедитесь, что Prometheus установлен в кластере</span>
          </div>
        )}
        <div style={{ display: 'flex', gap: '16px', marginTop: '12px', justifyContent: 'center' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ width: '12px', height: '3px', background: '#FF5C00', borderRadius: '2px', display: 'inline-block' }} /> CPU Load
          </span>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ width: '12px', height: '3px', background: '#10B981', borderRadius: '2px', display: 'inline-block' }} /> RAM Usage
          </span>
        </div>
      </div>

      {/* Cluster Nodes Status */}
      {metrics.is_cluster && metrics.nodes_list && (
        <div style={{ marginTop: '24px', marginBottom: '24px', paddingTop: '20px', borderTop: '1px solid var(--border-subtle)' }}>
          <h4 style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-heading)', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Server size={16} /> Состояние узлов кластера (Nodes)
          </h4>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '20px' }}>
            {metrics.nodes_list.map((node) => (
              <div className="glass-card" key={node.name} style={{ padding: '16px', border: '1px solid var(--border-subtle)', background: 'var(--bg-surface-hover)', borderRadius: 'var(--radius-md)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                  <span style={{ fontWeight: 600, color: 'var(--text-heading)', fontSize: '0.9rem' }}>{node.name}</span>
                  <span style={{ 
                    fontSize: '0.75rem', 
                    padding: '2px 8px', 
                    borderRadius: '4px', 
                    fontWeight: 600,
                    background: node.status === 'Ready' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)', 
                    color: node.status === 'Ready' ? 'var(--status-success)' : 'var(--status-danger)' 
                  }}>
                    {node.status}
                  </span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>Роль:</span> <span style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>{node.role}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>IP-адрес:</span> <span style={{ fontFamily: 'monospace' }}>{node.ip}</span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '4px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Нагрузка ЦП:</span> <span>{node.cpu.usage_percent}% ({node.cpu.usage_cores} из {node.cpu.total_cores} ядер)</span>
                    </div>
                    <div className="progress-track" style={{ height: '6px' }}>
                      <div className={`progress-fill ${getProgressClass(node.cpu.usage_percent)}`} style={{ width: `${node.cpu.usage_percent}%` }} />
                    </div>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '4px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Использование ОЗУ:</span> <span>{node.memory.usage_percent}% ({node.memory.usage_gb} из {node.memory.total_gb} ГБ)</span>
                    </div>
                    <div className="progress-track" style={{ height: '6px' }}>
                      <div className={`progress-fill ${getProgressClass(node.memory.usage_percent)}`} style={{ width: `${node.memory.usage_percent}%` }} />
                    </div>
                  </div>
                  {node.disk && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '4px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span>{node.role.includes('Storage') ? 'Диск (СХД):' : 'Диск ноды (Локальный):'}</span> <span>{node.disk.used_percent}% ({node.disk.used_gb} из {node.disk.total_gb} ГБ)</span>
                      </div>
                      <div className="progress-track" style={{ height: '6px' }}>
                        <div className={`progress-fill ${getProgressClass(node.disk.used_percent)}`} style={{ width: `${node.disk.used_percent}%` }} />
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {/* VM Resource Breakdown by Storage */}
      {metrics.is_cluster && metrics.vms_resources && metrics.vms_resources.length > 0 && (
        <div style={{ marginTop: '24px', marginBottom: '24px', paddingTop: '20px', borderTop: '1px solid var(--border-subtle)' }}>
          <h4 style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-heading)', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <HardDrive size={16} /> Распределение ресурсов виртуальных машин по хранилищам
          </h4>
          
          <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
            {metrics.shared_disk && metrics.shared_disk.active && (
              <button 
                type="button" 
                className={`btn btn-sm ${selectedStorageTab === 'nfs' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setSelectedStorageTab('nfs')}
                style={{ padding: '6px 12px', fontSize: '0.8rem', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }}
              >
                Сетевая СХД (NFS) ({metrics.vms_resources.filter(v => v.storage_class.toLowerCase().includes('nfs')).length})
              </button>
            )}
            <button 
              type="button" 
              className={`btn btn-sm ${selectedStorageTab === 'lvm' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setSelectedStorageTab('lvm')}
              style={{ padding: '6px 12px', fontSize: '0.8rem', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }}
            >
              LVM Хранилище (PaaS) ({metrics.vms_resources.filter(v => v.storage_class.toLowerCase().includes('lvm') || v.storage_class.toLowerCase().includes('vg-')).length})
            </button>
            <button 
              type="button" 
              className={`btn btn-sm ${selectedStorageTab === 'local' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setSelectedStorageTab('local')}
              style={{ padding: '6px 12px', fontSize: '0.8rem', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }}
            >
              Локальный SSD ({metrics.vms_resources.filter(v => !v.storage_class.toLowerCase().includes('nfs') && !v.storage_class.toLowerCase().includes('lvm') && !v.storage_class.toLowerCase().includes('vg-')).length})
            </button>
          </div>

          <div className="table-responsive" style={{ background: 'var(--bg-surface-hover)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
            <table className="table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
              <thead>
                <tr style={{ textAlign: 'left', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-secondary)' }}>
                  <th style={{ padding: '8px' }}>Имя ВМ</th>
                  <th style={{ padding: '8px' }}>Статус</th>
                  <th style={{ padding: '8px' }}>Размещение (Нода)</th>
                  <th style={{ padding: '8px', textAlign: 'center' }}>Ядра vCPU</th>
                  <th style={{ padding: '8px', textAlign: 'center' }}>ОЗУ (RAM)</th>
                  <th style={{ padding: '8px', textAlign: 'center' }}>Диск (Storage)</th>
                </tr>
              </thead>
              <tbody>
                {metrics.vms_resources
                  .filter(v => {
                    const sc = v.storage_class.toLowerCase();
                    if (selectedStorageTab === 'nfs') return sc.includes('nfs');
                    if (selectedStorageTab === 'lvm') return sc.includes('lvm') || sc.includes('vg-');
                    return !sc.includes('nfs') && !sc.includes('lvm') && !sc.includes('vg-');
                  })
                  .map(vm => (
                    <tr key={vm.name} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', color: 'var(--text-primary)' }}>
                      <td style={{ padding: '10px 8px', fontWeight: 600 }}>{vm.name}</td>
                      <td style={{ padding: '10px 8px' }}>
                        <span style={{ 
                          fontSize: '0.75rem', 
                          padding: '2px 8px', 
                          borderRadius: '4px',
                          fontWeight: 500,
                          background: vm.status === 'Running' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                          color: vm.status === 'Running' ? 'var(--status-success)' : 'var(--status-danger)'
                        }}>
                          {(() => {
                            const norm = vm.status?.toLowerCase();
                            if (norm === 'running') return 'Запущена';
                            if (norm === 'stopped') return 'Остановлена';
                            if (norm === 'starting') return 'Запуск...';
                            if (norm === 'stopping') return 'Выключение...';
                            if (norm === 'scheduled') return 'Планирование...';
                            if (norm === 'pending') return 'В очереди...';
                            if (norm === 'provisioning') return 'Создание...';
                            if (norm === 'importing') return 'Импорт...';
                            if (norm === 'error') return 'Ошибка';
                            return vm.status || 'Остановлена';
                          })()}
                        </span>
                      </td>
                      <td style={{ padding: '10px 8px', fontFamily: 'monospace' }}>{vm.node || 'Unknown'}</td>
                      <td style={{ padding: '10px 8px', textAlign: 'center', fontWeight: 600 }}>{vm.cpu_cores}</td>
                      <td style={{ padding: '10px 8px', textAlign: 'center' }}>{vm.memory_gb} ГБ</td>
                      <td style={{ padding: '10px 8px', textAlign: 'center' }}>{vm.disk_gb} ГБ</td>
                    </tr>
                  ))}
                {metrics.vms_resources.filter(v => {
                  const sc = v.storage_class.toLowerCase();
                  if (selectedStorageTab === 'nfs') return sc.includes('nfs');
                  if (selectedStorageTab === 'lvm') return sc.includes('lvm') || sc.includes('vg-');
                  return !sc.includes('nfs') && !sc.includes('lvm') && !sc.includes('vg-');
                }).length === 0 && (
                  <tr>
                    <td colSpan="6" style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>
                      Нет виртуальных машин на этом типе хранилища
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Meta Info */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '24px', padding: '20px', background: 'var(--bg-surface-hover)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
        <div>
          <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '4px' }}>Host Node</div>
          <div style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{metrics.node_name}</div>
        </div>
        {metrics.cpu.model && (
          <div>
            <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '4px' }}>Processor</div>
            <div style={{ fontWeight: 600, color: 'var(--text-heading)', fontSize: '0.85rem' }}>
              {metrics.cpu.sockets > 1 ? `${metrics.cpu.sockets}x ` : ''}{metrics.cpu.model}
            </div>
          </div>
        )}
        <div>
          <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '4px' }}>Architecture</div>
          <div style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{metrics.architecture}</div>
        </div>
        <div>
          <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '4px' }}>Operating System</div>
          <div style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{metrics.operating_system}</div>
        </div>
        <div>
          <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '4px' }}>OS Image</div>
          <div style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{metrics.os_info}</div>
        </div>
        <div>
          <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '4px' }}>Kernel Version</div>
          <div style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{metrics.kernel_version}</div>
        </div>
        <div>
          <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '4px' }}>Container Runtime</div>
          <div style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{metrics.container_runtime}</div>
        </div>
        <div>
          <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '4px' }}>Kubelet Version</div>
          <div style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{metrics.kubelet_version}</div>
        </div>
        <div>
          <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '4px' }}>System UUID</div>
          <div style={{ fontWeight: 600, color: 'var(--text-heading)', fontSize: '0.8rem' }}>{metrics.system_uuid}</div>
        </div>
      </div>

      {/* LVM Pool Resize Slide-over Panel */}
      {showResize && (
        <Portal>
          <div className="slide-over-overlay" onClick={() => setShowResize(false)}>
            <div className="slide-over-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '450px' }}>
              <div className="slide-over-header">
                <h2>Настройки пула LVM</h2>
                <button className="btn-close" onClick={() => setShowResize(false)}>&times;</button>
              </div>
              
              <form onSubmit={handleResizeLvm} className="slide-over-body" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <label className="input-label">Текущий пул хранения (vg-aegis)</label>
                  <div style={{ padding: '12px', background: 'var(--bg-surface-hover)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem', marginBottom: '6px' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Выделено под пул LVM:</span>
                      <span style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{metrics.lvm ? metrics.lvm.total_gb : 0} ГБ</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Зарезервировано ВМ:</span>
                      <span style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{metrics.lvm ? metrics.lvm.reserved_gb : 0} ГБ</span>
                    </div>
                  </div>
                </div>

                <div className="input-group">
                  <label className="input-label">Новый размер пула (в ГБ)</label>
                  <input 
                    type="number" 
                    className="form-control" 
                    placeholder="Например: 60" 
                    value={newSizeGb}
                    onChange={e => setNewSizeGb(e.target.value)}
                    disabled={resizing}
                    required
                  />
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '6px', lineHeight: '1.4' }}>
                    Вы можете расширить объем пула или безопасно уменьшить его. Уменьшение сработает только в том случае, если новый размер больше, чем суммарный объем дисков созданных ВМ ({metrics.lvm ? metrics.lvm.reserved_gb : 0} ГБ).
                  </span>
                </div>

                {resizeStatus && (
                  <div style={{ 
                    padding: '12px', 
                    borderRadius: 'var(--radius-md)', 
                    fontSize: '0.85rem',
                    background: resizeStatus.success ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)', 
                    color: resizeStatus.success ? 'var(--status-success)' : 'var(--status-danger)', 
                    border: `1px solid ${resizeStatus.success ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)'}` 
                  }}>
                    {resizeStatus.success ? "✓ " : "✗ "} {resizeStatus.message}
                  </div>
                )}

                <div style={{ marginTop: 'auto', display: 'flex', gap: '12px', paddingTop: '20px', borderTop: '1px solid var(--border-subtle)' }}>
                  <button type="button" className="btn btn-secondary" style={{ flex: 1 }} onClick={() => setShowResize(false)} disabled={resizing}>
                    Отмена
                  </button>
                  <button type="submit" className="btn btn-primary" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }} disabled={resizing}>
                    {resizing ? <span className="spinner" /> : "Сохранить"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        </Portal>
      )}
    </div>
  );
};

export default HostStats;
