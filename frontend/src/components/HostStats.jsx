import React, { useEffect, useState } from 'react';
import { Cpu, HardDrive, Server, RefreshCw } from 'lucide-react';
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
      
      if (onMetricsLoaded) {
        onMetricsLoaded(data);
      }

      // Обновляем историю для графиков (храним последние 15 точек)
      setHistory(prev => {
        const newPoint = {
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
          cpu: data.cpu.usage_percent,
          memory: data.memory.usage_percent
        };
        const updated = [...prev, newPoint];
        if (updated.length > 15) {
          updated.shift();
        }
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
    // Опрашиваем сервер каждые 3 секунды
    const interval = setInterval(fetchMetrics, 3000);
    return () => clearInterval(interval);
  }, []);

  if (loading && !metrics) {
    return (
      <div className="card" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '300px' }}>
        <div className="spinner"></div>
      </div>
    );
  }

  if (error && !metrics) {
    return (
      <div className="card" style={{ color: 'var(--danger)', textAlign: 'center', padding: '40px' }}>
        <p>Не удалось загрузить метрики хоста.</p>
        <p style={{ fontSize: '0.8rem', opacity: 0.8 }}>Убедитесь, что бэкенд и API Kubernetes доступны.</p>
        <button className="btn btn-secondary btn-sm" style={{ marginTop: '15px' }} onClick={fetchMetrics}>
          <RefreshCw size={14} /> Повторить
        </button>
      </div>
    );
  }

  const cpuPercent = metrics.cpu.usage_percent;
  const memoryPercent = metrics.memory.usage_percent;

  // Функция для определения цвета шкалы в зависимости от нагрузки
  const getProgressColor = (val) => {
    if (val < 70) return 'success';
    if (val < 90) return 'warning';
    return 'danger';
  };

  return (
    <div className="card">
      <div className="card-title">
        <Server className="logo-icon" size={20} />
        <span>Мониторинг Гипервизора</span>
      </div>

      <div className="host-stats-list">
        {/* CPU */}
        <div className="stat-item">
          <div className="stat-label-container">
            <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Cpu size={14} /> CPU (Ядра)
            </span>
            <span className="stat-value">
              {metrics.cpu.usage_cores} / {metrics.cpu.total_cores} ({cpuPercent}%)
            </span>
          </div>
          <div className="progress-bar-bg">
            <div 
              className={`progress-bar-fill ${getProgressColor(cpuPercent)}`}
              style={{ width: `${cpuPercent}%` }}
            />
          </div>
        </div>

        {/* RAM */}
        <div className="stat-item">
          <div className="stat-label-container">
            <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <HardDrive size={14} /> Оперативная память
            </span>
            <span className="stat-value">
              {metrics.memory.usage_gb} / {metrics.memory.total_gb} ГБ ({memoryPercent}%)
            </span>
          </div>
          <div className="progress-bar-bg">
            <div 
              className={`progress-bar-fill ${getProgressColor(memoryPercent)}`}
              style={{ width: `${memoryPercent}%` }}
            />
          </div>
        </div>
        
        {/* График реального времени */}
        {history.length > 1 && (
          <div style={{ height: '140px', marginTop: '15px', width: '100%' }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={history} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorCpu" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--primary)" stopOpacity={0.4}/>
                    <stop offset="95%" stopColor="var(--primary)" stopOpacity={0}/>
                  </linearGradient>
                  <linearGradient id="colorMem" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--success)" stopOpacity={0.4}/>
                    <stop offset="95%" stopColor="var(--success)" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <XAxis dataKey="time" hide />
                <YAxis domain={[0, 100]} tickLine={false} axisLine={false} style={{ fontSize: '10px', fill: 'var(--text-muted)' }} />
                <Tooltip 
                  contentStyle={{ background: 'var(--bg-secondary)', borderColor: 'var(--border-color)', borderRadius: '0px' }}
                  labelStyle={{ color: 'var(--text-secondary)' }}
                />
                <Area type="monotone" dataKey="cpu" name="CPU %" stroke="var(--primary)" fillOpacity={1} fill="url(#colorCpu)" strokeWidth={2} />
                <Area type="monotone" dataKey="memory" name="RAM %" stroke="var(--success)" fillOpacity={1} fill="url(#colorMem)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Метаданные хоста */}
        <div className="host-meta">
          <div>Имя ноды: {metrics.node_name}</div>
          <div>ОС: {metrics.os_info}</div>
          <div>Ядро: {metrics.kernel_version}</div>
          <div>Версия K8s: {metrics.kubelet_version}</div>
        </div>
      </div>
    </div>
  );
};

export default HostStats;
