import React, { useEffect, useState } from 'react';
import { Server, Plus, Layers, ShieldCheck, Activity, Terminal, Shield, FolderOpen, LayoutDashboard, Link2, Cloud } from 'lucide-react';
import HostStats from './components/HostStats';
import VMCard from './components/VMCard';
import VncConsole from './components/VncConsole';
import DockerPanel from './components/DockerPanel';
import ImageManager from './components/ImageManager';
import VMEditModal from './components/VMEditModal';
import VMDetail from './components/VMDetail';
import AegisDashboard from './components/AegisDashboard';
import AwsConsole from './components/AwsConsole';

// Компоненты для внешних серверов
import ExternalServerCard from './components/ExternalServerCard';
import ExternalServerDetail from './components/ExternalServerDetail';
import ConnectServerModal from './components/ConnectServerModal';

const App = () => {
  const [activeTab, setActiveTab] = useState('dashboard'); // 'dashboard' | 'images' | 'docker' | 'external'
  const [vms, setVms] = useState([]);
  const [customImages, setCustomImages] = useState([]);
  const [externalServers, setExternalServers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [serversLoading, setServersLoading] = useState(true);
  const [formLoading, setFormLoading] = useState(false);
  
  // Модальные окна
  const [openConsoleName, setOpenConsoleName] = useState(null);
  const [editingVM, setEditingVM] = useState(null);
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [selectedServerId, setSelectedServerId] = useState(null);
  const [selectedVMDetailName, setSelectedVMDetailName] = useState(null);

  // Состояние формы создания VM
  const [name, setName] = useState('');
  const [osType, setOsType] = useState('ubuntu'); // 'ubuntu' | 'windows' | 'custom'
  const [selectedCustomImage, setSelectedCustomImage] = useState('');
  const [cpuCores, setCpuCores] = useState(2);
  const [memoryGb, setMemoryGb] = useState(2);
  const [diskGb, setDiskGb] = useState(20);
  const [isoUrl, setIsoUrl] = useState('');

  // Подгрузка дефолтных значений в зависимости от ОС
  useEffect(() => {
    if (osType === 'ubuntu') {
      setCpuCores(2);
      setMemoryGb(2);
      setDiskGb(20);
    } else if (osType === 'windows') {
      setCpuCores(4);
      setMemoryGb(4);
      setDiskGb(60);
    } else {
      setCpuCores(2);
      setMemoryGb(2);
      setDiskGb(30);
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

  const fetchCustomImages = async () => {
    try {
      const response = await fetch('/api/images');
      if (!response.ok) throw new Error('Failed to fetch custom images');
      const data = await response.json();
      setCustomImages(data);
      if (data.length > 0 && !selectedCustomImage) {
        setSelectedCustomImage(data[0].filename);
      }
    } catch (err) {
      console.error('Error fetching custom images:', err);
    }
  };

  const fetchExternalServers = async () => {
    try {
      const response = await fetch('/api/external-servers');
      if (!response.ok) throw new Error('Failed to fetch external servers');
      const data = await response.json();
      setExternalServers(data);
    } catch (err) {
      console.error('Error fetching external servers:', err);
    } finally {
      setServersLoading(false);
    }
  };

  useEffect(() => {
    fetchVMs();
    fetchCustomImages();
    fetchExternalServers();
    
    // Опрашиваем списки периодически
    const vmsInterval = setInterval(fetchVMs, 5000);
    const serversInterval = setInterval(fetchExternalServers, 10000); // статус серверов реже
    
    return () => {
      clearInterval(vmsInterval);
      clearInterval(serversInterval);
    };
  }, []);

  // Обновляем списки при переключении вкладок
  useEffect(() => {
    if (activeTab === 'dashboard') {
      fetchVMs();
      fetchCustomImages();
    } else if (activeTab === 'vms') {
      fetchVMs();
    } else if (activeTab === 'images') {
      fetchCustomImages();
    } else if (activeTab === 'external') {
      fetchExternalServers();
    }
  }, [activeTab]);

  const handleCreateVM = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;

    if (osType === 'custom' && !selectedCustomImage) {
      alert('Пожалуйста, выберите кастомный образ из списка. Если список пуст, загрузите образ во вкладке "Образы дисков".');
      return;
    }

    setFormLoading(true);
    try {
      const payload = {
        name: name.toLowerCase().replace(/[^a-z0-9-]/g, '-'),
        os_type: osType,
        custom_image: osType === 'custom' ? selectedCustomImage : undefined,
        cpu_cores: parseInt(cpuCores),
        memory_gb: parseInt(memoryGb),
        disk_gb: parseInt(diskGb),
        iso_url: osType === 'windows' && isoUrl.trim() ? isoUrl.trim() : undefined
      };

      const response = await fetch('/api/vms', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        const err = await response.json();
        let errMsg = 'Не удалось создать ВМ.';
        if (typeof err.detail === 'string') {
          errMsg = err.detail;
        } else if (Array.isArray(err.detail)) {
          // Форматируем валидационные ошибки FastAPI
          errMsg = err.detail.map(d => {
            if (d.loc.includes('name')) {
              return 'Имя виртуальной машины должно состоять только из строчных латинских букв, цифр и знака дефиса (без пробелов и спецсимволов).';
            }
            return `${d.loc.join('.')}: ${d.msg}`;
          }).join('\n');
        }
        throw new Error(errMsg);
      }

      const resData = await response.json();
      
      setName('');
      setIsoUrl('');
      fetchVMs();
      
      alert(`Виртуальная машина ${payload.name} отправлена на развертывание!\n\nЛогин пользователя: ${resData.username || 'root'}\nСгенерированный пароль: ${resData.password}\n\nПароль также будет доступен в карточке виртуалки.`);
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
        
        {/* Кнопки переключения вкладок */}
        <div style={{ display: 'flex', gap: '8px', background: 'rgba(0, 0, 0, 0.04)', padding: '4px', borderRadius: '0px', border: '1px solid var(--border-color)' }}>
          <button 
            className={`btn btn-sm ${activeTab === 'dashboard' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ color: activeTab === 'dashboard' ? '#ffffff' : 'var(--text-primary)', borderRadius: '0px' }}
            onClick={() => setActiveTab('dashboard')}
          >
            <LayoutDashboard size={14} />
            Дашборд
          </button>
          <button 
            className={`btn btn-sm ${activeTab === 'aegis' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ color: activeTab === 'aegis' ? '#ffffff' : 'var(--text-primary)', borderRadius: '0px' }}
            onClick={() => setActiveTab('aegis')}
          >
            <Layers size={14} />
            Aegis-HCI
          </button>
          <button 
            className={`btn btn-sm ${activeTab === 'aws' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ color: activeTab === 'aws' ? '#ffffff' : 'var(--text-primary)', borderRadius: '0px' }}
            onClick={() => setActiveTab('aws')}
          >
            <Cloud size={14} />
            AWS Console
          </button>
          <button 
            className={`btn btn-sm ${activeTab === 'vms' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ color: activeTab === 'vms' ? '#ffffff' : 'var(--text-primary)', borderRadius: '0px' }}
            onClick={() => setActiveTab('vms')}
          >
            <Activity size={14} />
            Виртуальные машины
          </button>
          <button 
            className={`btn btn-sm ${activeTab === 'images' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ color: activeTab === 'images' ? '#ffffff' : 'var(--text-primary)', borderRadius: '0px' }}
            onClick={() => setActiveTab('images')}
          >
            <FolderOpen size={14} />
            Образы дисков
          </button>
          <button 
            className={`btn btn-sm ${activeTab === 'external' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ color: activeTab === 'external' ? '#ffffff' : 'var(--text-primary)', borderRadius: '0px' }}
            onClick={() => setActiveTab('external')}
          >
            <Link2 size={14} />
            Внешние серверы
          </button>
          <button 
            className={`btn btn-sm ${activeTab === 'docker' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ color: activeTab === 'docker' ? '#ffffff' : 'var(--text-primary)', borderRadius: '0px' }}
            onClick={() => setActiveTab('docker')}
          >
            <Shield size={14} />
            Docker Админка
          </button>
        </div>

        <div style={{ display: 'flex', gap: '20px', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            <ShieldCheck size={16} color="var(--success)" />
            <span>K3s Cluster: <strong style={{ color: 'var(--success)' }}>Active</strong></span>
          </div>
        </div>
      </header>

      {/* Основной контент */}
      <main className="main-content">
        
        {/* Вкладка 1: Дашборд */}
        {activeTab === 'dashboard' && (
          <div className="dashboard-grid">
            <HostStats />

            {/* Форма создания ВМ */}
            <div className="card">
              <div className="card-title">
                <Plus className="logo-icon" size={20} />
                <span>Создать виртуальную машину</span>
              </div>
              
              <form onSubmit={handleCreateVM} className="create-form">
                
                {/* Селектор ОС */}
                <div className="form-group">
                  <span className="form-label">Тип операционной системы</span>
                  <div className="template-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
                    <div 
                      className={`template-option ${osType === 'ubuntu' ? 'selected' : ''}`}
                      onClick={() => !formLoading && setOsType('ubuntu')}
                      style={{ padding: '12px 6px' }}
                    >
                      <span className="template-icon" style={{ fontSize: '1.5rem' }}>🐧</span>
                      <span className="template-name" style={{ fontSize: '0.8rem' }}>Ubuntu Cloud</span>
                    </div>
                    <div 
                      className={`template-option ${osType === 'windows' ? 'selected' : ''}`}
                      onClick={() => !formLoading && setOsType('windows')}
                      style={{ padding: '12px 6px' }}
                    >
                      <span className="template-icon" style={{ fontSize: '1.5rem' }}>🪟</span>
                      <span className="template-name" style={{ fontSize: '0.8rem' }}>Windows ISO</span>
                    </div>
                    <div 
                      className={`template-option ${osType === 'custom' ? 'selected' : ''}`}
                      onClick={() => !formLoading && setOsType('custom')}
                      style={{ padding: '12px 6px' }}
                    >
                      <span className="template-icon" style={{ fontSize: '1.5rem' }}>💿</span>
                      <span className="template-name" style={{ fontSize: '0.8rem' }}>Свой образ</span>
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
                    placeholder="e.g. database-node-01"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                    disabled={formLoading}
                  />
                  <small style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginTop: '4px', display: 'block' }}>
                    Только латинские строчные буквы, цифры и дефис (например: `my-server-1`).
                  </small>
                </div>

                {/* Список кастомных образов */}
                {osType === 'custom' && (
                  <div className="form-group">
                    <label className="form-label" htmlFor="custom-image-select">Выберите загруженный образ</label>
                    {customImages.length === 0 ? (
                      <div style={{ fontSize: '0.8rem', color: 'var(--danger)', padding: '6px 0' }}>
                        Нет загруженных образов! Пожалуйста, сначала загрузите файл на вкладке "Образы дисков".
                      </div>
                    ) : (
                      <select 
                        id="custom-image-select"
                        className="form-input form-select"
                        value={selectedCustomImage}
                        onChange={(e) => setSelectedCustomImage(e.target.value)}
                        disabled={formLoading}
                      >
                        {customImages.map((img) => (
                          <option key={img.filename} value={img.filename}>
                            {img.filename} ({img.size_gb > 1 ? `${img.size_gb} GB` : `${img.size_mb} MB`})
                          </option>
                        ))}
                      </select>
                    )}
                  </div>
                )}

                {/* CPU Слайдер */}
                <div className="slider-container">
                  <div className="slider-header">
                    <span>Выделено CPU</span>
                    <span className="slider-value">{cpuCores} Cores</span>
                  </div>
                  <input 
                    type="range" 
                    min="1" 
                    max="8" 
                    className="range-input"
                    value={cpuCores}
                    onChange={(e) => setCpuCores(parseInt(e.target.value))}
                    disabled={formLoading}
                  />
                </div>

                {/* RAM Слайдер */}
                <div className="slider-container">
                  <div className="slider-header">
                    <span>Выделено RAM</span>
                    <span className="slider-value">{memoryGb} GB</span>
                  </div>
                  <input 
                    type="range" 
                    min="1" 
                    max="32" 
                    className="range-input"
                    value={memoryGb}
                    onChange={(e) => setMemoryGb(parseInt(e.target.value))}
                    disabled={formLoading}
                  />
                </div>

                {/* Disk Слайдер */}
                <div className="slider-container">
                  <div className="slider-header">
                    <span>Объем жесткого диска</span>
                    <span className="slider-value">{diskGb} GB</span>
                  </div>
                  <input 
                    type="range" 
                    min="10" 
                    max="200" 
                    step="10"
                    className="range-input"
                    value={diskGb}
                    onChange={(e) => setDiskGb(parseInt(e.target.value))}
                    disabled={formLoading}
                  />
                </div>

                {/* Windows ISO URL */}
                {osType === 'windows' && (
                  <div className="form-group">
                    <label className="form-label" htmlFor="win-iso-url">Собственная ссылка на ISO (необязательно)</label>
                    <input 
                      id="win-iso-url"
                      type="url" 
                      className="form-input"
                      value={isoUrl}
                      onChange={(e) => setIsoUrl(e.target.value)}
                      placeholder="Оставьте пустым для Windows Server 2022"
                      disabled={formLoading}
                    />
                  </div>
                )}

                <button 
                  type="submit" 
                  className="btn btn-primary"
                  style={{ width: '100%', marginTop: '10px' }}
                  disabled={formLoading || (osType === 'custom' && customImages.length === 0)}
                >
                  {formLoading ? <span className="spinner" style={{ width: '16px', height: '16px', borderWidth: '2px' }} /> : <Plus size={16} />}
                  Создать виртуальную машину
                </button>
              </form>
            </div>
          </div>
        )}

        {/* Вкладка: Виртуальные машины */}
        {activeTab === 'vms' && (
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
                  Создайте виртуалку с индивидуальными ресурсами во вкладке "Дашборд" или загрузите собственные образы во вкладке "Образы дисков".
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
                    onOpenEdit={(vmObj) => setEditingVM(vmObj)}
                    onOpenDetail={(name) => setSelectedVMDetailName(name)}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Вкладка 2: Кастомные образы */}
        {activeTab === 'images' && (
          <ImageManager onImagesChanged={setCustomImages} />
        )}

        {/* Вкладка 3: Внешние серверы */}
        {activeTab === 'external' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div className="vms-section-header">
              <h2 style={{ fontSize: '1.4rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Server className="logo-icon" size={22} />
                Внешние подключенные серверы
              </h2>
              <button className="btn btn-primary btn-sm" onClick={() => setShowConnectModal(true)}>
                <Plus size={14} /> Подключить сервер
              </button>
            </div>

            {serversLoading && externalServers.length === 0 ? (
              <div className="card" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '300px' }}>
                <div className="spinner"></div>
              </div>
            ) : externalServers.length === 0 ? (
              <div className="empty-state">
                <span className="empty-state-icon">🌐</span>
                <h3>Нет подключенных внешних серверов</h3>
                <p style={{ maxWidth: '350px', textAlign: 'center', fontSize: '0.9rem' }}>
                  Вы можете подключить любой внешний Linux-сервер по его IP-адресу, логину и паролю SSH для отслеживания его метрик и процессов.
                </p>
                <button className="btn btn-primary" style={{ marginTop: '10px' }} onClick={() => setShowConnectModal(true)}>
                  Подключить первый сервер
                </button>
              </div>
            ) : (
              <div className="vms-grid">
                {externalServers.map((server) => (
                  <ExternalServerCard 
                    key={server.id} 
                    server={server} 
                    onClick={() => server.status === 'Online' && setSelectedServerId(server.id)}
                    onDeleteSuccess={fetchExternalServers}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Вкладка: Aegis-HCI */}
        {activeTab === 'aegis' && (
          <AegisDashboard />
        )}

        {/* Вкладка: AWS Console */}
        {activeTab === 'aws' && (
          <AwsConsole mode="admin" />
        )}

        {/* Вкладка 4: Docker Админка */}
        {activeTab === 'docker' && (
          <DockerPanel />
        )}


      </main>

      {/* Модальное окно VNC-консоли */}
      {openConsoleName && (
        <VncConsole 
          name={openConsoleName} 
          username={vms.find(v => v.name === openConsoleName)?.credentials?.username || 'root'}
          password={vms.find(v => v.name === openConsoleName)?.credentials?.password || ''}
          onClose={() => setOpenConsoleName(null)} 
        />
      )}

      {/* Модальное окно настройки ресурсов */}
      {editingVM && (
        <VMEditModal 
          vm={editingVM} 
          onClose={() => setEditingVM(null)} 
          onSaveSuccess={fetchVMs} 
        />
      )}

      {/* Модальное окно подключения внешнего сервера */}
      {showConnectModal && (
        <ConnectServerModal 
          onClose={() => setShowConnectModal(false)}
          onSuccess={fetchExternalServers}
        />
      )}

      {/* Модальное окно детального мониторинга внешнего сервера */}
      {selectedServerId && (
        <ExternalServerDetail 
          serverId={selectedServerId}
          onClose={() => setSelectedServerId(null)}
        />
      )}

      {/* Модальное окно детального мониторинга виртуальной машины */}
      {selectedVMDetailName && (
        <VMDetail 
          vmName={selectedVMDetailName}
          onClose={() => setSelectedVMDetailName(null)}
          onActionSuccess={fetchVMs}
        />
      )}
    </div>
  );
};

export default App;
