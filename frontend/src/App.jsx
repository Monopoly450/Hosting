import React, { useEffect, useState } from 'react';
import { Server, Plus, Layers, ShieldCheck, Activity, Terminal } from 'lucide-react';
import HostStats from './components/HostStats';
import VMCard from './components/VMCard';
import VncConsole from './components/VncConsole';

const App = () => {
  const [vms, setVms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [formLoading, setFormLoading] = useState(false);
  const [openConsoleName, setOpenConsoleName] = useState(null);

  // Состояние формы создания VM
  const [name, setName] = useState('');
  const [osType, setOsType] = useState('ubuntu'); // 'ubuntu' | 'windows'
  const [cpuCores, setCpuCores] = useState(2);
  const [memoryGb, setMemoryGb] = useState(2);
  const [diskGb, setDiskGb] = useState(20);
  const [password, setPassword] = useState('ubuntu');
  const [isoUrl, setIsoUrl] = useState('');

  // Подгрузка дефолтных значений в зависимости от ОС
  useEffect(() => {
    if (osType === 'ubuntu') {
      setCpuCores(2);
      setMemoryGb(2);
      setDiskGb(20);
      setPassword('ubuntu');
    } else {
      setCpuCores(4);
      setMemoryGb(4);
      setDiskGb(60);
      setPassword(''); // Пароль не используется для Windows ISO напрямую (установка через VNC)
    }
  }, [osType]);

  const fetchVMs = async () => {
    try {
      const response = await fetch('/api/vms');
      if (!response.ok) throw new Error('Failed to fetch VMs');
      const data = await response.json();
      setVms(data);
    } catch (err) {
      console.error('Error fetching VMs:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchVMs();
    // Опрашиваем список виртуалок каждые 5 секунд для обновления статусов/IP
    const interval = setInterval(fetchVMs, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleCreateVM = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;

    setFormLoading(true);
    try {
      const payload = {
        name: name.toLowerCase().replace(/[^a-z0-9-]/g, '-'), // Приведение имени к требованиям K8s DNS
        os_type: osType,
        cpu_cores: parseInt(cpuCores),
        memory_gb: parseInt(memoryGb),
        disk_gb: parseInt(diskGb),
        password: password || undefined,
        iso_url: isoUrl.trim() || undefined
      };

      const response = await fetch('/api/vms', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Не удалось создать ВМ.');
      }

      // Очистка формы
      setName('');
      setIsoUrl('');
      fetchVMs();
      alert(`Виртуальная машина ${payload.name} успешно отправлена на создание!`);
    } catch (err) {
      alert(`Ошибка при создании VM: ${err.message}`);
    } finally {
      setFormLoading(false);
    }
  };

  return (
    <div className="app-container">
      {/* Шапка */}
      <header className="header">
        <div className="logo-section">
          <Layers className="logo-icon" size={26} />
          <span className="logo-text">Antigravity Hosting</span>
          <span className="logo-badge">KubeVirt Edition</span>
        </div>
        <div style={{ display: 'flex', gap: '20px', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            <ShieldCheck size={16} color="var(--success)" />
            <span>Kubernetes Кластер: <strong>Активен</strong></span>
          </div>
        </div>
      </header>

      {/* Основной контент */}
      <main className="main-content">
        <div className="dashboard-grid">
          
          {/* Левая панель: Статистика хоста и форма создания */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '30px' }}>
            
            {/* Метрики гипервизора */}
            <HostStats />

            {/* Панель создания новой VM */}
            <div className="card">
              <div className="card-title">
                <Plus className="logo-icon" size={20} />
                <span>Создать виртуальную машину</span>
              </div>
              
              <form onSubmit={handleCreateVM} className="create-form">
                
                {/* Выбор операционной системы */}
                <div className="form-group">
                  <span className="form-label">Шаблон операционной системы</span>
                  <div className="template-grid">
                    <div 
                      className={`template-option ${osType === 'ubuntu' ? 'selected' : ''}`}
                      onClick={() => !formLoading && setOsType('ubuntu')}
                    >
                      <span className="template-icon">🐧</span>
                      <span className="template-name">Ubuntu Server</span>
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>LTS 24.04 Cloud</span>
                    </div>
                    <div 
                      className={`template-option ${osType === 'windows' ? 'selected' : ''}`}
                      onClick={() => !formLoading && setOsType('windows')}
                    >
                      <span className="template-icon">🪟</span>
                      <span className="template-name">Windows Server</span>
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>2022 Evaluation</span>
                    </div>
                  </div>
                </div>

                {/* Название */}
                <div className="form-group">
                  <label className="form-label" htmlFor="vm-name">Имя виртуалки</label>
                  <input 
                    id="vm-name"
                    type="text" 
                    className="form-input" 
                    placeholder="e.g. web-server-01"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                    disabled={formLoading}
                  />
                </div>

                {/* CPU Слайдер */}
                <div className="slider-container">
                  <div className="slider-header">
                    <span>Выделено CPU</span>
                    <span className="slider-value">{cpuCores} {cpuCores === 1 ? 'ядро' : cpuCores < 5 ? 'ядра' : 'ядер'}</span>
                  </div>
                  <input 
                    type="range" 
                    min="1" 
                    max="8" 
                    className="range-input"
                    value={cpuCores}
                    onChange={(e) => setCpuCores(e.target.value)}
                    disabled={formLoading}
                  />
                </div>

                {/* RAM Слайдер */}
                <div className="slider-container">
                  <div className="slider-header">
                    <span>Выделено RAM</span>
                    <span className="slider-value">{memoryGb} ГБ</span>
                  </div>
                  <input 
                    type="range" 
                    min="1" 
                    max="32" 
                    className="range-input"
                    value={memoryGb}
                    onChange={(e) => setMemoryGb(e.target.value)}
                    disabled={formLoading}
                  />
                </div>

                {/* Disk Слайдер */}
                <div className="slider-container">
                  <div className="slider-header">
                    <span>Объем диска (NVMe/SSD)</span>
                    <span className="slider-value">{diskGb} ГБ</span>
                  </div>
                  <input 
                    type="range" 
                    min="10" 
                    max="200" 
                    step="10"
                    className="range-input"
                    value={diskGb}
                    onChange={(e) => setDiskGb(e.target.value)}
                    disabled={formLoading}
                  />
                </div>

                {/* Доп поля в зависимости от ОС */}
                {osType === 'ubuntu' ? (
                  <div className="form-group">
                    <label className="form-label" htmlFor="ubuntu-pass">Пароль по умолчанию (пользователь ubuntu)</label>
                    <input 
                      id="ubuntu-pass"
                      type="text" 
                      className="form-input"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="Введите пароль для cloud-init"
                      required
                      disabled={formLoading}
                    />
                  </div>
                ) : (
                  <div className="form-group">
                    <label className="form-label" htmlFor="win-iso">Пользовательская ссылка на ISO (необязательно)</label>
                    <input 
                      id="win-iso"
                      type="url" 
                      className="form-input"
                      value={isoUrl}
                      onChange={(e) => setIsoUrl(e.target.value)}
                      placeholder="Оставьте пустым для дефолтного образа"
                      disabled={formLoading}
                    />
                  </div>
                )}

                <button 
                  type="submit" 
                  className="btn btn-primary"
                  style={{ width: '100%', marginTop: '10px' }}
                  disabled={formLoading}
                >
                  {formLoading ? <span className="spinner" style={{ width: '16px', height: '16px', borderWidth: '2px' }} /> : <Plus size={16} />}
                  Создать виртуальную машину
                </button>
              </form>
            </div>
          </div>

          {/* Правая панель: Список виртуалных машин */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div className="vms-section-header">
              <h2 style={{ fontSize: '1.4rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Activity className="logo-icon" size={22} />
                Ваши виртуальные машины
              </h2>
              <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                Всего развернуто: {vms.length}
              </span>
            </div>

            {loading && vms.length === 0 ? (
              <div className="card" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '400px' }}>
                <div className="spinner"></div>
              </div>
            ) : vms.length === 0 ? (
              <div className="empty-state">
                <span className="empty-state-icon">🖥️</span>
                <h3>Виртуальных машин нет</h3>
                <p style={{ maxWidth: '350px', textAlign: 'center', fontSize: '0.9rem' }}>
                  Создайте свою первую виртуальную машину на Ubuntu или Windows Server, выбрав необходимые ресурсы слева.
                </p>
              </div>
            ) : (
              <div className="vms-grid">
                {vms.map((vm) => (
                  <VMCard 
                    key={vm.name} 
                    vm={vm} 
                    onActionSuccess={fetchVMs}
                    onOpenConsole={(name) => setOpenConsoleName(name)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Модальное окно VNC-консоли */}
      {openConsoleName && (
        <VncConsole 
          name={openConsoleName} 
          onClose={() => setOpenConsoleName(null)} 
        />
      )}
    </div>
  );
};

export default App;
