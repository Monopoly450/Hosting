import React, { useEffect, useState } from 'react';
import { Cpu, HardDrive, Server, RefreshCw, Activity } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts';

const HostStats = ({ onMetricsLoaded }) => {
  const [metrics, setMetrics] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const fetchMetrics = async () => {
    try {
      const response = await fetch('/api/host/metrics');
      if (!response.ok) throw new Error('Failed to fetch host metrics');
      const data = await response.json();
      
      setMetrics(data);
      setError(false);
      
      if (onMetricsLoaded) onMetricsLoaded(data);

      setHistory(prev => {
        const newPoint = {
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
          cpu: data.cpu.usage_percent,
          memory: data.memory.usage_percent
        };
        const updated = [...prev, newPoint];
        if (updated.length > 20) updated.shift();
        return updated;
      });
    } catch (err) {
      console.error(err);
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 3000);
    return () => clearInterval(interval);
  }, []);

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
            <span>Текущая: {metrics.cpu.usage_cores} / {metrics.cpu.total_cores} ядер</span>
            <span>Занято ВМ: {metrics.cpu.reserved_cores} (своб. {metrics.cpu.available_cores})</span>
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
            <span>Текущая: {metrics.memory.usage_gb} / {metrics.memory.total_gb} ГБ</span>
            <span>Занято ВМ: {metrics.memory.reserved_gb} ГБ (своб. {metrics.memory.available_gb} ГБ)</span>
          </div>
        </div>

        {/* Disk */}
        <div className="stat-box">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="stat-box-title" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><HardDrive size={16}/> Дисковое пространство</span>
            <span className="stat-box-value">{metrics.disk ? metrics.disk.used_percent : 0}%</span>
          </div>
          <div className="progress-track">
            <div className={`progress-fill ${getProgressClass(metrics.disk ? metrics.disk.used_percent : 0)}`} style={{ width: `${metrics.disk ? metrics.disk.used_percent : 0}%` }} />
          </div>
          <div className="stat-box-meta">
            <span>Свободно на хосте: {metrics.disk ? metrics.disk.free_gb : 0} из {metrics.disk ? metrics.disk.total_gb : 0} ГБ</span>
            <span>Занято ВМ: {metrics.disk ? metrics.disk.reserved_gb : 0} ГБ (своб. {metrics.disk ? metrics.disk.available_gb : 0} ГБ)</span>
          </div>
        </div>
      </div>
      
      {/* Real-time chart */}
      {history.length > 1 && (
        <div style={{ height: '220px', width: '100%', marginBottom: '24px' }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={history} margin={{ top: 5, right: 0, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="colorCpu" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--accent-primary)" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="var(--accent-primary)" stopOpacity={0}/>
                </linearGradient>
                <linearGradient id="colorMem" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--status-success)" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="var(--status-success)" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <XAxis dataKey="time" hide />
              <YAxis domain={[0, 100]} tickLine={false} axisLine={false} style={{ fontSize: '11px', fill: 'var(--text-muted)' }} />
              <Tooltip 
                contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-lg)' }}
                labelStyle={{ color: 'var(--text-secondary)', marginBottom: '4px' }}
                itemStyle={{ fontSize: '0.9rem', fontWeight: 500 }}
              />
              <Area type="monotone" dataKey="cpu" name="CPU Load %" stroke="var(--accent-primary)" fillOpacity={1} fill="url(#colorCpu)" strokeWidth={2} />
              <Area type="monotone" dataKey="memory" name="RAM Usage %" stroke="var(--status-success)" fillOpacity={1} fill="url(#colorMem)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
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
    </div>
  );
};

export default HostStats;
