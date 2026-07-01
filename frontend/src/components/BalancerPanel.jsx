import React, { useEffect, useState } from 'react';
import { Layers, Activity, Server, Shuffle, Settings, Plus, Trash2, Cpu, HardDrive } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

const BalancerPanel = () => {
  const [stats, setStats] = useState([]);
  const [loading, setLoading] = useState(true);
  const [pools, setPools] = useState([]);
  const [poolsLoading, setPoolsLoading] = useState(true);
  const [showCreatePool, setShowCreatePool] = useState(false);
  const [newPoolName, setNewPoolName] = useState('');
  const [newPoolPort, setNewPoolPort] = useState(80);
  const [newPoolMethod, setNewPoolMethod] = useState('Round Robin');
  const [selectedVms, setSelectedVms] = useState([]);

  const fetchPools = async () => {
    try {
      const response = await fetch('/api/vms/balancer/pools');
      if (response.ok) {
        const data = await response.json();
        setPools(data);
      }
    } catch (e) {
      console.error("Error fetching pools:", e);
    } finally {
      setPoolsLoading(false);
    }
  };

  const fetchBalancerStats = async () => {
    try {
      const response = await fetch('/api/vms/balancer/resources');
      if (response.ok) {
        const data = await response.json();
        setStats(data);
      }
    } catch (e) {
      console.error("Error fetching balancer stats:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBalancerStats();
    fetchPools();
    const statsInterval = setInterval(fetchBalancerStats, 5000);
    const poolsInterval = setInterval(fetchPools, 8000);
    return () => {
      clearInterval(statsInterval);
      clearInterval(poolsInterval);
    };
  }, []);

  const handleCreatePool = async (e) => {
    e.preventDefault();
    if (!newPoolName.trim()) return;
    
    const payload = {
      name: newPoolName.trim(),
      port: parseInt(newPoolPort),
      method: newPoolMethod,
      vms: selectedVms,
      backend_port: 80
    };
    
    try {
      const response = await fetch('/api/vms/balancer/pools', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (response.ok) {
        fetchPools();
        setNewPoolName('');
        setSelectedVms([]);
        setShowCreatePool(false);
      } else {
        const errData = await response.json();
        alert(`Ошибка: ${errData.detail || 'Не удалось создать пул'}`);
      }
    } catch (err) {
      alert(`Ошибка сети: ${err.message}`);
    }
  };

  const handleDeletePool = async (name) => {
    if (!confirm(`Вы действительно хотите удалить пул балансировки ${name}?`)) return;
    try {
      const response = await fetch(`/api/vms/balancer/pools/${name}`, {
        method: 'DELETE'
      });
      if (response.ok) {
        fetchPools();
      } else {
        const errData = await response.json();
        alert(`Ошибка: ${errData.detail || 'Не удалось удалить пул'}`);
      }
    } catch (err) {
      alert(`Ошибка сети: ${err.message}`);
    }
  };

  const toggleVmSelection = (vmName) => {
    setSelectedVms(prev => 
      prev.includes(vmName) ? prev.filter(name => name !== vmName) : [...prev, vmName]
    );
  };

  // Generate data for Recharts Bar Chart
  const chartData = stats.map(s => ({
    name: s.vm_name,
    'CPU %': s.cpu_usage_percent,
    'RAM %': s.memory_usage_percent
  }));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* Top Resource Distribution Summary */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '24px' }}>
        
        {/* Comparative Chart */}
        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <h3 className="section-title" style={{ margin: 0 }}><Activity size={18}/> Сравнение потребления ресурсов ВМ</h3>
          
          {loading && stats.length === 0 ? (
            <div style={{ padding: '64px 0', textAlign: 'center', color: 'var(--text-secondary)' }}>
              <span className="spinner" style={{ marginBottom: '12px' }}/> <br/>
              Загрузка показателей балансировщика...
            </div>
          ) : stats.length === 0 ? (
            <div style={{ padding: '64px 0', textAlign: 'center', color: 'var(--text-muted)' }}>
              Нет активных запущенных виртуальных машин для анализа распределения ресурсов.
            </div>
          ) : (
            <div style={{ height: '300px', width: '100%', marginTop: '10px' }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 20, right: 30, left: -10, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" />
                  <XAxis dataKey="name" style={{ fontSize: '11px', fill: 'var(--text-muted)' }} />
                  <YAxis domain={[0, 100]} style={{ fontSize: '11px', fill: 'var(--text-muted)' }} />
                  <Tooltip 
                    contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}
                    itemStyle={{ fontSize: '0.85rem' }}
                  />
                  <Legend wrapperStyle={{ fontSize: '0.85rem' }} />
                  <Bar dataKey="CPU %" fill="var(--accent-primary)" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="RAM %" fill="var(--status-success)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {/* Load Balancer Overview Stats */}
        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <h3 className="section-title" style={{ margin: 0 }}><Shuffle size={18}/> Балансировщик трафика</h3>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', justifyContent: 'center', height: '100%' }}>
            <div style={{ background: 'var(--card-bg-subtle)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Активные балансировочные пулы</div>
              <div style={{ fontSize: '2rem', fontWeight: 700, margin: '8px 0', color: 'var(--accent-primary)' }}>{pools.length}</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Включая апстримы Nginx</div>
            </div>

            <div style={{ background: 'var(--card-bg-subtle)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Запросы в секунду (всего)</div>
              <div style={{ fontSize: '2rem', fontWeight: 700, margin: '8px 0', color: 'var(--status-success)' }}>
                {pools.reduce((sum, p) => sum + p.requestsPerSec, 0)} RPS
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Распределено между ВМ в реальном времени</div>
            </div>
          </div>
        </div>

      </div>

      {/* Grid: VM List on the Left, Pools Configuration on the Right */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1.8fr', gap: '24px' }}>
        
        {/* Resource details per VM */}
        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <h3 className="section-title" style={{ margin: 0 }}><Cpu size={18}/> Распределение ресурсов</h3>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', overflowY: 'auto', maxH: '450px' }}>
            {stats.length === 0 ? (
              <div style={{ padding: '24px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                Показатели ВМ отсутствуют.
              </div>
            ) : (
              stats.map(vm => (
                <div key={vm.vm_name} style={{ background: 'var(--card-bg-subtle)', padding: '14px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                    <span style={{ fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-heading)' }}>{vm.vm_name}</span>
                    <span className="badge badge-success" style={{ fontSize: '0.7rem' }}>Online</span>
                  </div>
                  
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: '4px' }}>
                        <span className="text-muted">CPU: {vm.cpu_usage_cores} / {vm.cpu_limit_cores} ядер</span>
                        <span>{vm.cpu_usage_percent}%</span>
                      </div>
                      <div className="progress-track" style={{ height: '6px' }}>
                        <div className="progress-fill primary" style={{ width: `${vm.cpu_usage_percent}%` }} />
                      </div>
                    </div>

                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: '4px' }}>
                        <span className="text-muted">RAM: {vm.memory_usage_mb} MB / {vm.memory_limit_mb} MB</span>
                        <span>{vm.memory_usage_percent}%</span>
                      </div>
                      <div className="progress-track" style={{ height: '6px' }}>
                        <div className="progress-fill" style={{ width: `${vm.memory_usage_percent}%`, background: 'var(--status-success)' }} />
                      </div>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Load Balancer Pools Section */}
        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 className="section-title" style={{ margin: 0 }}><Shuffle size={18}/> Балансировочные пулы (Nginx Upstream)</h3>
            <button className="btn btn-primary" style={{ padding: '6px 12px', fontSize: '0.8rem' }} onClick={() => setShowCreatePool(!showCreatePool)}>
              <Plus size={14} /> Создать пул
            </button>
          </div>

          {showCreatePool && (
            <form onSubmit={handleCreatePool} style={{ background: 'var(--card-bg-subtle)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'flex', gap: '12px' }}>
                <div style={{ flex: 1 }}>
                  <label className="input-label" style={{ fontSize: '0.75rem' }}>Имя пула</label>
                  <input type="text" className="form-control" style={{ fontSize: '0.85rem' }} value={newPoolName} onChange={(e) => setNewPoolName(e.target.value)} placeholder="Например: app-upstream" required />
                </div>
                <div style={{ width: '80px' }}>
                  <label className="input-label" style={{ fontSize: '0.75rem' }}>Порт</label>
                  <input type="number" className="form-control" style={{ fontSize: '0.85rem' }} value={newPoolPort} onChange={(e) => setNewPoolPort(parseInt(e.target.value))} required />
                </div>
                <div style={{ flex: 1 }}>
                  <label className="input-label" style={{ fontSize: '0.75rem' }}>Метод балансировки</label>
                  <select className="form-control" style={{ fontSize: '0.85rem' }} value={newPoolMethod} onChange={(e) => setNewPoolMethod(e.target.value)}>
                    <option value="Round Robin">Round Robin (по очереди)</option>
                    <option value="Least Connections">Least Connections (наименее нагруженный)</option>
                    <option value="IP Hash">IP Hash (по IP клиента)</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="input-label" style={{ fontSize: '0.75rem', marginBottom: '8px', display: 'block' }}>Выберите виртуальные машины в пул</label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                  {stats.length === 0 ? (
                    <span className="text-muted" style={{ fontSize: '0.8rem' }}>Нет запущенных ВМ</span>
                  ) : (
                    stats.map(vm => (
                      <button 
                        type="button" 
                        key={vm.vm_name} 
                        className={`btn ${selectedVms.includes(vm.vm_name) ? 'btn-primary' : 'btn-secondary'}`}
                        style={{ padding: '4px 10px', fontSize: '0.8rem' }}
                        onClick={() => toggleVmSelection(vm.vm_name)}
                      >
                        {vm.vm_name}
                      </button>
                    ))
                  )}
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                <button type="button" className="btn btn-secondary" style={{ padding: '6px 12px', fontSize: '0.8rem' }} onClick={() => setShowCreatePool(false)}>Отмена</button>
                <button type="submit" className="btn btn-primary" style={{ padding: '6px 12px', fontSize: '0.8rem' }}>Добавить пул</button>
              </div>
            </form>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {pools.map(pool => (
              <div key={pool.name} style={{ background: 'var(--card-bg-subtle)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <span style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--text-heading)' }}>{pool.name}</span>
                    <span className="text-muted" style={{ fontSize: '0.8rem', marginLeft: '10px' }}>Порт: {pool.port} | {pool.method}</span>
                  </div>
                  <button className="btn btn-secondary" style={{ padding: '4px', color: 'var(--status-danger)' }} onClick={() => handleDeletePool(pool.name)}>
                    <Trash2 size={14} />
                  </button>
                </div>

                <div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '6px' }}>Апстримы (Целевые машины):</div>
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                    {pool.vms.map(vm => (
                      <span key={vm} style={{ background: 'var(--bg-surface)', padding: '4px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', fontSize: '0.8rem', fontWeight: 500, display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                        <Server size={12} color="var(--accent-primary)"/> {vm}
                      </span>
                    ))}
                    {pool.vms.length === 0 && (
                      <span className="text-muted" style={{ fontSize: '0.8rem' }}>Нет подключенных ВМ. Добавьте машины в пул.</span>
                    )}
                  </div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.8rem', borderTop: '1px solid var(--border-subtle)', paddingTop: '8px', marginTop: '4px' }}>
                  <span className="text-secondary">Распределенный трафик:</span>
                  <span style={{ fontWeight: 600, color: 'var(--status-success)' }}>{pool.requestsPerSec} RPS (активно)</span>
                </div>
              </div>
            ))}
          </div>

        </div>

      </div>

    </div>
  );
};

export default BalancerPanel;
