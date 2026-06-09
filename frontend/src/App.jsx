import React, { useEffect, useState } from 'react';
import { Server, Plus, Layers, ShieldCheck, Activity, Terminal, Shield, FolderOpen, LayoutDashboard, Link2, Cloud, ChevronDown, LogOut, Key } from 'lucide-react';
import HostStats from './components/HostStats';
import VMCard from './components/VMCard';
import VncConsole from './components/VncConsole';
import DockerPanel from './components/DockerPanel';
import ImageManager from './components/ImageManager';
import VMEditModal from './components/VMEditModal';
import VMDetail from './components/VMDetail';
import AegisDashboard from './components/AegisDashboard';
import AwsConsole from './components/AwsConsole';
import InfraPanel from './components/InfraPanel';

// Компоненты для внешних серверов
import ExternalServerCard from './components/ExternalServerCard';
import ExternalServerDetail from './components/ExternalServerDetail';
import ConnectServerModal from './components/ConnectServerModal';

const App = () => {
  const [authenticated, setAuthenticated] = useState(!!localStorage.getItem('aegis_admin_token'));
  const [tokenInput, setTokenInput] = useState('');
  
  const [projectsList, setProjectsList] = useState(['Общий проект', 'Администрирование']);
  const [selectedProject, setSelectedProject] = useState('Общий проект');
  const [showProjectDropdown, setShowProjectDropdown] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');

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

  const handleLogin = (e) => {
    e.preventDefault();
    if (tokenInput.trim() === 'aegis-admin-secret-key-2026') {
      localStorage.setItem('aegis_admin_token', tokenInput.trim());
      setAuthenticated(true);
    } else {
      alert('Неверный ключ доступа (Admin Token). Пожалуйста, введите корректный ключ.');
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('aegis_admin_token');
    setAuthenticated(false);
  };

  const handleCreateProject = (e) => {
    e.preventDefault();
    if (!newProjectName.trim()) return;
    if (projectsList.includes(newProjectName.trim())) {
      alert("Проект с таким названием уже существует.");
      return;
    }
    setProjectsList(prev => [...prev, newProjectName.trim()]);
    setSelectedProject(newProjectName.trim());
    setNewProjectName('');
    setShowProjectDropdown(false);
    alert(`Проект "${newProjectName.trim()}" успешно создан!`);
  };

  if (!authenticated) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '100vh',
        backgroundColor: '#0a0d16',
        backgroundImage: 'radial-gradient(circle at 50% 50%, rgba(92, 100, 236, 0.08) 0%, transparent 50%)',
        fontFamily: 'var(--font-sans)',
        padding: '20px'
      }}>
        <div className="card" style={{
          width: '420px',
          padding: '36px 30px',
          background: '#111522',
          border: '1px solid var(--border-color)',
          borderRadius: '12px',
          boxShadow: '0 24px 64px rgba(0, 0, 0, 0.4)',
          display: 'flex',
          flexDirection: 'column',
          gap: '24px'
        }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px', textAlign: 'center' }}>
            <div style={{ background: 'rgba(92, 100, 236, 0.1)', padding: '14px', borderRadius: '12px', color: '#5c64ec' }}>
              <Shield size={36} />
            </div>
            <h2 style={{ fontSize: '1.4rem', fontWeight: 800, margin: '10px 0 2px 0', color: 'white' }}>Aegis Admin Panel</h2>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
              Для доступа к консоли администрирования гипервизора введите ключ авторизации API-Key
            </p>
          </div>

          <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Admin Token</label>
              <div style={{ position: 'relative' }}>
                <Key size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                <input 
                  type="password"
                  className="form-input"
                  style={{ width: '100%', paddingLeft: '38px', background: '#0a0d16', borderRadius: '8px' }}
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                  placeholder="Введите ключ доступа..."
                  required
                />
              </div>
              <small style={{ color: 'var(--text-muted)', fontSize: '0.72rem', marginTop: '4px', lineHeight: 1.3 }}>
                Подсказка: стандартный демонстрационный ключ: <br/>
                <code style={{ color: '#a3a8ff', fontFamily: 'var(--font-mono)' }}>aegis-admin-secret-key-2026</code>
              </small>
            </div>

            <button type="submit" className="btn btn-primary" style={{ width: '100%', padding: '12px', fontSize: '0.9rem', borderRadius: '8px', marginTop: '8px' }}>
              Авторизоваться
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="app-layout">
      
      {/* Left Sidebar */}
      <aside className="sidebar">
        {/* Logo section */}
        <div className="sidebar-logo">
          <Layers className="logo-icon" size={26} />
          <div className="logo-text-group">
            <span className="logo-text">Aegis Admin</span>
            <span className="logo-badge">KubeVirt Edition</span>
          </div>
        </div>

        {/* Projects dropdown */}
        <div className="projects-dropdown">
          <span className="projects-label">Проекты</span>
          
          <div style={{ position: 'relative' }}>
            <button className="project-selector-btn" onClick={() => setShowProjectDropdown(!showProjectDropdown)}>
              <div className="project-info">
                <span className="project-bullet"></span>
                <span>{selectedProject}</span>
              </div>
              <ChevronDown size={14} />
            </button>
            
            {showProjectDropdown && (
              <div style={{
                position: 'absolute',
                top: '100%',
                left: 0,
                right: 0,
                background: '#161b2a',
                border: '1px solid var(--border-color)',
                borderRadius: '8px',
                marginTop: '4px',
                zIndex: 10,
                boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                padding: '8px'
              }}>
                {projectsList.map(proj => (
                  <button 
                    key={proj}
                    onClick={() => {
                      setSelectedProject(proj);
                      setShowProjectDropdown(false);
                    }}
                    style={{
                      width: '100%',
                      textAlign: 'left',
                      background: proj === selectedProject ? 'rgba(92,100,236,0.1)' : 'transparent',
                      border: 'none',
                      color: proj === selectedProject ? '#a3a8ff' : 'var(--text-secondary)',
                      padding: '6px 10px',
                      fontSize: '0.82rem',
                      cursor: 'pointer',
                      borderRadius: '4px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      transition: 'all 0.15s'
                    }}
                  >
                    <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: proj === selectedProject ? '#5c64ec' : '#64748b' }}></span>
                    {proj}
                  </button>
                ))}
                <div style={{ borderTop: '1px solid var(--border-color)', marginTop: '8px', paddingTop: '8px' }}>
                  <form onSubmit={handleCreateProject} style={{ display: 'flex', gap: '6px' }}>
                    <input 
                      type="text" 
                      placeholder="Новый проект" 
                      value={newProjectName} 
                      onChange={(e) => setNewProjectName(e.target.value)} 
                      style={{
                        flex: 1,
                        background: 'rgba(0,0,0,0.3)',
                        border: '1px solid var(--border-color)',
                        borderRadius: '4px',
                        color: 'white',
                        fontSize: '0.75rem',
                        padding: '4px 6px',
                        outline: 'none'
                      }}
                    />
                    <button type="submit" className="btn btn-primary btn-sm" style={{ padding: '2px 8px', borderRadius: '4px' }}>+</button>
                  </form>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Sidebar Nav Links */}
        <div className="sidebar-nav">
          <button 
            className={`nav-item ${activeTab === 'dashboard' ? 'active' : ''}`}
            onClick={() => setActiveTab('dashboard')}
          >
            <LayoutDashboard size={16} />
            <span>Дашборд</span>
          </button>
          
          <button 
            className={`nav-item ${activeTab === 'aegis' ? 'active' : ''}`}
            onClick={() => setActiveTab('aegis')}
          >
            <Layers size={16} />
            <span>Aegis-HCI</span>
          </button>

          <button 
            className={`nav-item ${activeTab === 'aws' ? 'active' : ''}`}
            onClick={() => setActiveTab('aws')}
          >
            <Cloud size={16} />
            <span>AWS Console</span>
          </button>

          <button 
            className={`nav-item ${activeTab === 'vms' ? 'active' : ''}`}
            onClick={() => setActiveTab('vms')}
          >
            <Activity size={16} />
            <span>Виртуальные машины</span>
          </button>

          <button 
            className={`nav-item ${activeTab === 'images' ? 'active' : ''}`}
            onClick={() => setActiveTab('images')}
          >
            <FolderOpen size={16} />
            <span>Образы дисков</span>
          </button>

          <button 
            className={`nav-item ${activeTab === 'external' ? 'active' : ''}`}
            onClick={() => setActiveTab('external')}
          >
            <Link2 size={16} />
            <span>Внешние серверы</span>
          </button>

          <button 
            className={`nav-item ${activeTab === 'docker' ? 'active' : ''}`}
            onClick={() => setActiveTab('docker')}
          >
            <Shield size={16} />
            <span>Docker Админка</span>
          </button>

          <button 
            className={`nav-item ${activeTab === 'infra' ? 'active' : ''}`}
            onClick={() => setActiveTab('infra')}
          >
            <Terminal size={16} />
            <span>Инфраструктура</span>
          </button>
        </div>

        {/* Sidebar Footer with cluster status and logout */}
        <div className="sidebar-footer">
          <div className="cluster-status" style={{ marginBottom: '12px' }}>
            <span className="status-indicator active"></span>
            <span>K3s Cluster: <strong style={{ color: 'var(--success)' }}>Active</strong></span>
          </div>
          <button 
            className="btn btn-secondary btn-sm" 
            style={{ width: '100%', justifyContent: 'center', gap: '8px', color: 'var(--danger)', borderColor: 'rgba(239, 68, 68, 0.15)', background: 'rgba(239, 68, 68, 0.04)' }}
            onClick={handleLogout}
          >
            <LogOut size={14} />
            Выйти из панели
          </button>
        </div>
      </aside>

      {/* Main Content View */}
      <main className="main-content-layout">
        
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

        {/* Вкладка: Инфраструктура */}
        {activeTab === 'infra' && (
          <InfraPanel />
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
