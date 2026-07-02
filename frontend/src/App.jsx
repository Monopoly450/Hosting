import React, { useEffect, useState } from 'react';
import { Server, Plus, Layers, ShieldCheck, Activity, Terminal, Shield, FolderOpen, LayoutDashboard, Link2, LogOut, Key, Menu, Monitor, Info, ChevronDown, Package, HardDrive, Square, Shuffle, Users, Database, Mail, X } from 'lucide-react';
import HostStats from './components/HostStats';
import VMCard from './components/VMCard';
import VncConsole from './components/VncConsole';
import DockerPanel from './components/DockerPanel';
import ImageManager from './components/ImageManager';
import VMEditModal from './components/VMEditModal';
import VMDetail from './components/VMDetail';
import InfraPanel from './components/InfraPanel';
import ExternalServerCard from './components/ExternalServerCard';
import ExternalServerDetail from './components/ExternalServerDetail';
import ConnectServerModal from './components/ConnectServerModal';
import ClusterPanel from './components/ClusterPanel';
import BalancerPanel from './components/BalancerPanel';
import UsersAdminPanel from './components/UsersAdminPanel';
import DatabasesPanel from './components/DatabasesPanel';
import S3Panel from './components/S3Panel';
import VolumesPanel from './components/VolumesPanel';
import MailPanel from './components/MailPanel';
import CustomSelect from './components/CustomSelect';

const App = () => {
  const [authenticated, setAuthenticated] = useState(!!localStorage.getItem('aegis_admin_token'));
  const [usernameInput, setUsernameInput] = useState('admin');
  const [passwordInput, setPasswordInput] = useState('');
  const [userRole, setUserRole] = useState(localStorage.getItem('aegis_role') || 'student');
  const [username, setUsername] = useState(localStorage.getItem('aegis_username') || '');
  const [quotaUsage, setQuotaUsage] = useState(null);
  
  const [activeTab, setActiveTab] = useState(
    localStorage.getItem('aegis_role') === 'admin' ? 'dashboard' : 'vms'
  ); // 'dashboard' | 'vms' | 'clusters' | 'balancer' | 'images' | 'docker' | 'infra' | 'users'
  const [vms, setVms] = useState([]);
  const [customImages, setCustomImages] = useState([]);
  const [externalServers, setExternalServers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [serversLoading, setServersLoading] = useState(true);
  const [formLoading, setFormLoading] = useState(false);
  
  // Modals & Subpages
  const [openConsoleName, setOpenConsoleName] = useState(null);
  const [editingVM, setEditingVM] = useState(null);
  const [showCreateVM, setShowCreateVM] = useState(false);
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [selectedServerId, setSelectedServerId] = useState(null);
  const [selectedVMDetailName, setSelectedVMDetailName] = useState(null);

  // VM Creation Form
  const [name, setName] = useState('');
  const [osType, setOsType] = useState('ubuntu'); // 'ubuntu' | 'windows' | 'custom'
  const [selectedCustomImage, setSelectedCustomImage] = useState('');
  const [packages, setPackages] = useState("");
  const [networkDrives, setNetworkDrives] = useState("");
  const [cpuCores, setCpuCores] = useState(2);
  const [memoryGb, setMemoryGb] = useState(2);
  const [diskGb, setDiskGb] = useState(20);
  const [isoUrl, setIsoUrl] = useState('');
  const [cloudInitTemplate, setCloudInitTemplate] = useState('');
  const [customUserData, setCustomUserData] = useState('');

  // Default values based on OS
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
      console.error('Error fetching images:', err);
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

  const fetchQuotaUsage = async () => {
    try {
      const response = await fetch('/api/auth/me');
      if (response.ok) {
        const data = await response.json();
        setQuotaUsage(data);
        setUserRole(data.role);
        localStorage.setItem('aegis_role', data.role);
        localStorage.setItem('aegis_username', data.username);
      }
    } catch (err) {
      console.error('Error fetching quota usage:', err);
    }
  };

  useEffect(() => {
    if (authenticated) {
      fetchQuotaUsage();
      fetchVMs();
      fetchCustomImages();
      if (userRole === 'admin') {
        fetchExternalServers();
      }
      
      const vmsInterval = setInterval(() => {
        fetchVMs();
        fetchQuotaUsage();
      }, 5000);
      
      let serversInterval;
      if (userRole === 'admin') {
        serversInterval = setInterval(fetchExternalServers, 10000);
      }
      
      return () => {
        clearInterval(vmsInterval);
        if (serversInterval) clearInterval(serversInterval);
      };
    }
  }, [authenticated, userRole]);

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
        iso_url: osType === 'windows' && isoUrl.trim() ? isoUrl.trim() : undefined,
        cloud_init_template: cloudInitTemplate || undefined,
        custom_user_data: customUserData.trim() || undefined
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
          errMsg = err.detail.map(e => `${e.loc.join('.')}: ${e.msg}`).join(', ');
        }
        throw new Error(errMsg);
      }

      const resData = await response.json();
      setName('');
      setIsoUrl('');
      setCloudInitTemplate('');
      setCustomUserData('');
      fetchVMs();
      
      setSelectedVMDetailName(payload.name);
    } catch (err) {
      alert(`Ошибка: ${err.message}`);
    } finally {
      setFormLoading(false);
    }
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    const usernameVal = usernameInput.trim();
    const passwordVal = passwordInput.trim();
    if (!passwordVal) return;

    try {
      setFormLoading(true);
      // Сначала пробуем войти через новый API авторизации
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: usernameVal, password: passwordVal }),
        _skipAuthRedirect: true
      });
      
      if (response.ok) {
        const data = await response.json();
        localStorage.setItem('aegis_admin_token', data.access_token);
        localStorage.setItem('aegis_role', data.role);
        localStorage.setItem('aegis_username', data.username);
        setAuthenticated(true);
        window.location.reload();
      } else {
        // Если API авторизации вернул ошибку, пробуем старый способ (проверка X-Admin-Token напрямую)
        // Это полезно для обратной совместимости или входа по прямому токену
        const legacyResponse = await fetch('/api/host/metrics', {
          headers: { 'X-Admin-Token': passwordVal },
          _skipAuthRedirect: true
        });
        
        if (legacyResponse.ok) {
          localStorage.setItem('aegis_admin_token', passwordVal);
          localStorage.setItem('aegis_role', 'admin');
          localStorage.setItem('aegis_username', 'admin');
          setAuthenticated(true);
          window.location.reload();
        } else {
          alert('Неверные учетные данные или ключ доступа.');
        }
      }
    } catch (err) {
      alert(`Ошибка связи с сервером: ${err.message}`);
    } finally {
      setFormLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('aegis_admin_token');
    localStorage.removeItem('aegis_role');
    localStorage.removeItem('aegis_username');
    setAuthenticated(false);
    window.location.reload();
  };

  const getTabTitle = () => {
    if (selectedVMDetailName) return `Детали ВМ: ${selectedVMDetailName}`;
    switch (activeTab) {
      case 'dashboard': return 'Обзор инфраструктуры';
      case 'vms': return 'Серверы и Инстансы';
      case 'clusters': return 'Кластеры';
      case 'balancer': return 'Балансировщик ресурсов';
      case 'images': return 'Образы дисков';
      case 'databases': return 'Управляемые базы данных';
      case 's3': return 'S3 Объектное хранилище';
      case 'volumes': return 'Сетевые диски';
      case 'mail': return 'Почтовый хостинг';
      case 'docker': return 'Docker Управление';
      case 'infra': return 'Инфраструктура';
      case 'users': return 'Управление пользователями';
    }
  };

  if (!authenticated) {
    return (
      <div className="login-wrapper">
        <div className="login-card">
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px', marginBottom: '32px' }}>
            <div style={{ background: 'var(--accent-primary-light)', padding: '16px', borderRadius: '16px', color: 'var(--accent-primary)' }}>
              <Monitor size={42} />
            </div>
            <h2 style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--text-heading)', margin: 0 }}>ByteBurnes</h2>
            <p style={{ textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
              Платформа управления облачной инфраструктурой
            </p>
          </div>

          <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div className="input-group">
              <label className="input-label">Имя пользователя / Username</label>
              <input 
                type="text"
                className="form-control"
                value={usernameInput}
                onChange={(e) => setUsernameInput(e.target.value)}
                placeholder="admin"
                required
              />
            </div>

            <div className="input-group">
              <label className="input-label">Пароль или Ключ доступа</label>
              <input 
                type="password"
                className="form-control"
                value={passwordInput}
                onChange={(e) => setPasswordInput(e.target.value)}
                placeholder="Введите пароль или API ключ..."
                required
              />
            </div>

            <button type="submit" className="btn btn-primary" style={{ width: '100%', padding: '12px', fontSize: '1rem', marginTop: '8px' }}>
              {formLoading ? <span className="spinner" /> : 'Войти'}
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
        <div className="sidebar-logo">
          <Layers className="logo-icon" size={28} strokeWidth={2.5} />
          <span className="logo-text">ByteBurnes</span>
        </div>

        <div className="sidebar-nav">
          {userRole === 'admin' && (
            <button 
              className={`nav-item ${activeTab === 'dashboard' && !selectedVMDetailName ? 'active' : ''}`}
              onClick={() => { setActiveTab('dashboard'); setSelectedVMDetailName(null); }}
            >
              <LayoutDashboard size={18} />
              Дашборд
            </button>
          )}

          <button 
            className={`nav-item ${(activeTab === 'vms' || selectedVMDetailName) ? 'active' : ''}`}
            onClick={() => { setActiveTab('vms'); setSelectedVMDetailName(null); }}
          >
            <Activity size={18} />
            Серверы и Инстансы
          </button>

          <button 
            className={`nav-item ${activeTab === 'clusters' && !selectedVMDetailName ? 'active' : ''}`}
            onClick={() => { setActiveTab('clusters'); setSelectedVMDetailName(null); }}
          >
            <Layers size={18} />
            Кластеры
          </button>

          <button 
            className={`nav-item ${activeTab === 'balancer' && !selectedVMDetailName ? 'active' : ''}`}
            onClick={() => { setActiveTab('balancer'); setSelectedVMDetailName(null); }}
          >
            <Shuffle size={18} />
            Балансировщик
          </button>

          {userRole === 'admin' && (
            <button 
              className={`nav-item ${activeTab === 'images' && !selectedVMDetailName ? 'active' : ''}`}
              onClick={() => { setActiveTab('images'); setSelectedVMDetailName(null); }}
            >
              <FolderOpen size={18} />
              Образы ОС
            </button>
          )}

          <button 
            className={`nav-item ${activeTab === 'databases' && !selectedVMDetailName ? 'active' : ''}`}
            onClick={() => { setActiveTab('databases'); setSelectedVMDetailName(null); }}
          >
            <Database size={18} />
            Базы данных
          </button>

          <button 
            className={`nav-item ${activeTab === 's3' && !selectedVMDetailName ? 'active' : ''}`}
            onClick={() => { setActiveTab('s3'); setSelectedVMDetailName(null); }}
          >
            <FolderOpen size={18} />
            S3 Хранилище
          </button>

          <button 
            className={`nav-item ${activeTab === 'volumes' && !selectedVMDetailName ? 'active' : ''}`}
            onClick={() => { setActiveTab('volumes'); setSelectedVMDetailName(null); }}
          >
            <HardDrive size={18} />
            Сетевые диски
          </button>

          <button 
            className={`nav-item ${activeTab === 'mail' && !selectedVMDetailName ? 'active' : ''}`}
            onClick={() => { setActiveTab('mail'); setSelectedVMDetailName(null); }}
          >
            <Mail size={18} />
            Почтовый хостинг
          </button>

          {userRole === 'admin' && (
            <>
              <button 
                className={`nav-item ${activeTab === 'docker' && !selectedVMDetailName ? 'active' : ''}`}
                onClick={() => { setActiveTab('docker'); setSelectedVMDetailName(null); }}
              >
                <Shield size={18} />
                Docker Управление
              </button>

              <button 
                className={`nav-item ${activeTab === 'infra' && !selectedVMDetailName ? 'active' : ''}`}
                onClick={() => { setActiveTab('infra'); setSelectedVMDetailName(null); }}
              >
                <Terminal size={18} />
                Инфраструктура
              </button>

              <button 
                className={`nav-item ${activeTab === 'users' && !selectedVMDetailName ? 'active' : ''}`}
                onClick={() => { setActiveTab('users'); setSelectedVMDetailName(null); }}
              >
                <Users size={18} />
                Пользователи
              </button>
            </>
          )}
        </div>

        {quotaUsage && userRole !== 'admin' && (
          <div style={{ padding: '12px 8px', margin: '12px 0', borderTop: '1px solid var(--border-subtle)', borderBottom: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '8px' }}>
              Квоты студента
            </div>
            {/* VMs */}
            <div style={{ marginBottom: '6px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                <span>Инстансы</span>
                <span>{quotaUsage.used_vms} / {quotaUsage.max_vms}</span>
              </div>
              <div style={{ height: '3px', background: 'var(--bg-surface-hover)', borderRadius: '2px', marginTop: '2px', overflow: 'hidden' }}>
                <div style={{ height: '100%', background: 'var(--accent-primary)', width: `${Math.min(100, (quotaUsage.used_vms / quotaUsage.max_vms) * 100)}%` }}></div>
              </div>
            </div>
            {/* CPU */}
            <div style={{ marginBottom: '6px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                <span>Ядра vCPU</span>
                <span>{quotaUsage.used_vcpus} / {quotaUsage.max_vcpus}</span>
              </div>
              <div style={{ height: '3px', background: 'var(--bg-surface-hover)', borderRadius: '2px', marginTop: '2px', overflow: 'hidden' }}>
                <div style={{ height: '100%', background: 'var(--accent-primary)', width: `${Math.min(100, (quotaUsage.used_vcpus / quotaUsage.max_vcpus) * 100)}%` }}></div>
              </div>
            </div>
            {/* RAM */}
            <div style={{ marginBottom: '6px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                <span>ОЗУ (RAM)</span>
                <span>{quotaUsage.used_ram_mb} / {quotaUsage.max_ram_mb} MB</span>
              </div>
              <div style={{ height: '3px', background: 'var(--bg-surface-hover)', borderRadius: '2px', marginTop: '2px', overflow: 'hidden' }}>
                <div style={{ height: '100%', background: 'var(--accent-primary)', width: `${Math.min(100, (quotaUsage.used_ram_mb / quotaUsage.max_ram_mb) * 100)}%` }}></div>
              </div>
            </div>
            {/* Storage */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                <span>Диски (HDD)</span>
                <span>{quotaUsage.used_storage_gb} / {quotaUsage.max_storage_gb} GB</span>
              </div>
              <div style={{ height: '3px', background: 'var(--bg-surface-hover)', borderRadius: '2px', marginTop: '2px', overflow: 'hidden' }}>
                <div style={{ height: '100%', background: 'var(--accent-primary)', width: `${Math.min(100, (quotaUsage.used_storage_gb / quotaUsage.max_storage_gb) * 100)}%` }}></div>
              </div>
            </div>
          </div>
        )}

        <div style={{ marginTop: 'auto', paddingTop: '16px', borderTop: '1px solid var(--border-subtle)' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginBottom: '16px', padding: '0 8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span className="status-dot" style={{ backgroundColor: 'var(--status-success)', width: '8px', height: '8px' }}></span>
              <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: 600 }}>{username || 'Администратор'}</span>
            </div>
            {quotaUsage && userRole !== 'admin' && (
              <span style={{ fontSize: '0.75rem', color: 'var(--accent-primary)' }}>Баланс: {quotaUsage.balance.toFixed(2)} ₽</span>
            )}
          </div>
          <button 
            className="nav-item" 
            style={{ width: '100%', color: 'var(--status-danger)' }}
            onClick={handleLogout}
          >
            <LogOut size={18} />
            Выйти
          </button>
        </div>
      </aside>

      {/* Main Area */}
      <div className="main-area">
        <header className="top-header">
          <div className="header-title">{getTabTitle()}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            {/* Header widgets could go here */}
          </div>
        </header>

        <main className="content-container">
          
          {selectedVMDetailName ? (
            /* VM Detail Page View */
            <div className="page-view">
              <button 
                className="btn btn-secondary" 
                style={{ marginBottom: '24px' }}
                onClick={() => setSelectedVMDetailName(null)}
              >
                ← Вернуться к списку
              </button>
              <VMDetail 
                vmName={selectedVMDetailName}
                onClose={() => setSelectedVMDetailName(null)}
                onActionSuccess={fetchVMs}
              />
            </div>
          ) : activeTab === 'dashboard' ? (
            /* Dashboard View */
            <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
              <HostStats />
            </div>
          ) : activeTab === 'clusters' ? (
            <ClusterPanel vms={vms} onRefreshVms={fetchVMs} />
          ) : activeTab === 'vms' ? (
            /* Combined Servers List */
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="text-muted">Всего серверов и инстансов: <strong>{vms.length + externalServers.length}</strong></span>
                <div style={{ display: 'flex', gap: '12px' }}>
                  <button className="btn btn-secondary" onClick={() => setShowConnectModal(true)}>
                    <Link2 size={16}/> Внешний сервер
                  </button>
                  <button className="btn btn-primary" onClick={() => setShowCreateVM(!showCreateVM)}>
                    <Plus size={16}/> Локальная ВМ
                  </button>
                </div>
              </div>

              {showCreateVM && (
                <div className="slide-over-overlay" onClick={() => setShowCreateVM(false)}>
                  <div className="slide-over-content" onClick={e => e.stopPropagation()}>
                    <div className="slide-over-header">
                      <h2>Создать новую ВМ</h2>
                      <button className="btn-close" onClick={() => setShowCreateVM(false)} type="button">
                        <X size={18} />
                      </button>
                    </div>
                    <form onSubmit={handleCreateVM} style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
                      <div className="slide-over-body" style={{ display: 'flex', flexDirection: 'column', gap: '20px', flex: 1, overflowY: 'auto' }}>
                        
                        <div className="input-group">
                          <label className="input-label">Имя виртуалки (a-z, 0-9, -)</label>
                          <input 
                            type="text" 
                            className="form-control" 
                            placeholder="Например: web-server-01"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            required
                          />
                        </div>

                        <div className="input-group">
                          <label className="input-label">Операционная система</label>
                          <div className="os-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: '10px' }}>
                            <div className={`os-card ${osType === 'none' ? 'selected' : ''}`} onClick={() => setOsType('none')}>
                              <div className="os-card-icon" style={{ color: '#94a3b8' }}><Info size={24} /></div>
                              <div className="os-card-title">Без ОС</div>
                              <div className="os-card-version">Отдадим быстрее</div>
                            </div>
                            
                            <div className={`os-card ${osType === 'ubuntu' ? 'selected' : ''}`} onClick={() => setOsType('ubuntu')}>
                              <div className="os-card-icon" style={{ color: '#f97316' }}><Server size={24} /></div>
                              <div className="os-card-title">Ubuntu</div>
                              <div className="os-card-version">Ubuntu 24.04 <ChevronDown size={14} /></div>
                            </div>
                            
                            <div className={`os-card ${osType === 'centos' ? 'selected' : ''}`} onClick={() => setOsType('centos')}>
                              <div className="os-card-icon" style={{ color: '#84cc16' }}><Server size={24} /></div>
                              <div className="os-card-title">CentOS</div>
                              <div className="os-card-version">CentOS 10 <ChevronDown size={14} /></div>
                            </div>
                            
                            <div className={`os-card ${osType === 'debian' ? 'selected' : ''}`} onClick={() => setOsType('debian')}>
                              <div className="os-card-icon" style={{ color: '#ef4444' }}><Server size={24} /></div>
                              <div className="os-card-title">Debian</div>
                              <div className="os-card-version">Debian 13 <ChevronDown size={14} /></div>
                            </div>
                            
                            <div className={`os-card ${osType === 'bitrix' ? 'selected' : ''}`} onClick={() => setOsType('bitrix')}>
                              <div className="os-card-icon" style={{ color: '#ef4444' }}><Activity size={24} /></div>
                              <div className="os-card-title">BitrixVM</div>
                              <div className="os-card-version">CentOS 9</div>
                            </div>
                            
                            <div className={`os-card ${osType === 'custom' ? 'selected' : ''}`} style={{ borderColor: osType === 'custom' ? '#6366f1' : 'transparent', backgroundColor: osType === 'custom' ? 'var(--bg-surface-hover)' : 'var(--bg-surface)' }} onClick={() => setOsType('custom')}>
                              <div className="os-card-icon" style={{ color: '#6366f1' }}><Info size={24} /></div>
                              <div className="os-card-title">Свой образ</div>
                              <div className="os-card-version" style={{ opacity: 0 }}>...</div>
                            </div>
                          </div>
                        </div>

                        {osType === 'custom' && (
                          <div className="input-group">
                            <label className="input-label">Выберите загруженный образ</label>
                            <CustomSelect 
                              value={selectedCustomImage}
                              onChange={(e) => setSelectedCustomImage(e.target.value)}
                              placeholder="Выберите загруженный образ"
                              options={customImages.map(img => ({
                                value: img.filename,
                                label: `${img.filename} (${img.size_gb > 1 ? `${img.size_gb} GB` : `${img.size_mb} MB`})`
                              }))}
                            />
                          </div>
                        )}

                        <div className="input-group">
                          <label className="input-label" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><Package size={16}/> Пакеты для установки (через запятую)</label>
                          <input 
                            type="text" 
                            className="form-control" 
                            placeholder="Например: nginx, docker.io, mc, htop"
                            value={packages}
                            onChange={(e) => setPackages(e.target.value)}
                          />
                          <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px' }}>Установятся автоматически при первом запуске (только для Linux).</span>
                        </div>

                        <div className="input-group">
                          <label className="input-label" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><HardDrive size={16}/> Сетевые диски (NFS / PVC)</label>
                          <input 
                            type="text" 
                            className="form-control" 
                            placeholder="Например: 192.168.1.10:/shared или pvc-name"
                            value={networkDrives}
                            onChange={(e) => setNetworkDrives(e.target.value)}
                          />
                          <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px' }}>Сетевая шара будет смонтирована в /mnt/network_drive.</span>
                        </div>

                        <div className="input-group">
                          <label className="input-label">Шаблон окружения (Cloud-Init)</label>
                          <CustomSelect 
                            value={cloudInitTemplate} 
                            onChange={e => setCloudInitTemplate(e.target.value)}
                            placeholder="Без шаблона (Чистая ОС)"
                            options={[
                              { value: '', label: 'Без шаблона (Чистая ОС)' },
                              { value: 'lamp', label: 'LAMP (Nginx, PHP, MariaDB)' },
                              { value: 'docker', label: 'Docker Environment (Engine + CLI)' },
                              { value: 'nodejs', label: 'Node.js Environment (Node.js LTS)' },
                              { value: 'wordpress', label: 'WordPress (Apache + MySQL + PHP + WP)' }
                            ]}
                          />
                        </div>

                        <div className="input-group">
                          <label className="input-label">Кастомный скрипт Cloud-Init (userData)</label>
                          <textarea 
                            className="form-control" 
                            placeholder="#cloud-config..."
                            value={customUserData}
                            onChange={e => setCustomUserData(e.target.value)}
                            style={{ height: '80px', minHeight: '60px', resize: 'vertical' }}
                          />
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginTop: '8px' }}>
                          <div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                              <span className="input-label">CPU Cores</span>
                              <span style={{ fontWeight: 600, color: 'var(--accent-primary)' }}>{cpuCores}</span>
                            </div>
                            <input type="range" min="1" max="16" value={cpuCores} onChange={(e) => setCpuCores(parseInt(e.target.value))} style={{ width: '100%' }} />
                          </div>
                          <div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                              <span className="input-label">Memory</span>
                              <span style={{ fontWeight: 600, color: 'var(--accent-primary)' }}>{memoryGb} GB</span>
                            </div>
                            <input type="range" min="1" max="64" value={memoryGb} onChange={(e) => setMemoryGb(parseInt(e.target.value))} style={{ width: '100%' }} />
                          </div>
                          <div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                              <span className="input-label">Storage</span>
                              <span style={{ fontWeight: 600, color: 'var(--accent-primary)' }}>{diskGb} GB</span>
                            </div>
                            <input type="range" min="10" max="500" step="10" value={diskGb} onChange={(e) => setDiskGb(parseInt(e.target.value))} style={{ width: '100%' }} />
                          </div>
                        </div>

                      </div>
                      <div className="slide-over-actions">
                        <button type="button" className="btn btn-secondary" onClick={() => setShowCreateVM(false)}>
                          Отмена
                        </button>
                        <button type="submit" className="btn btn-primary" disabled={formLoading || (osType === 'custom' && customImages.length === 0)}>
                          {formLoading ? <span className="spinner" /> : 'Создать'}
                        </button>
                      </div>
                    </form>
                  </div>
                </div>
              )}


              {(loading && vms.length === 0) || (serversLoading && externalServers.length === 0) ? (
                <div style={{ display: 'flex', justifyContent: 'center', padding: '100px 0' }}><div className="spinner"></div></div>
              ) : (vms.length === 0 && externalServers.length === 0) ? (
                <div className="glass-card" style={{ textAlign: 'center', padding: '64px 20px' }}>
                  <Server size={48} color="var(--text-muted)" style={{ marginBottom: '16px' }} />
                  <h3 className="section-title" style={{ justifyContent: 'center' }}>Нет серверов и инстансов</h3>
                  <p className="text-muted">Разверните новую виртуальную машину или подключите внешний Linux-сервер.</p>
                </div>
              ) : (
                <div className="grid-cols-3">
                  {vms.map(vm => (
                    <VMCard 
                      key={`vm-${vm.name}`} 
                      vm={vm} 
                      onActionSuccess={fetchVMs}
                      onOpenConsole={(name) => setOpenConsoleName(name)}
                      onOpenEdit={(vmObj) => setEditingVM(vmObj)}
                      onOpenDetail={(name) => setSelectedVMDetailName(name)}
                    />
                  ))}
                  {externalServers.map(server => (
                    <ExternalServerCard 
                      key={`ext-${server.id}`} 
                      server={server} 
                      onClick={() => server.status === 'Online' && setSelectedServerId(server.id)}
                      onDeleteSuccess={fetchExternalServers}
                    />
                  ))}
                </div>
              )}
            </div>
          ) : activeTab === 'balancer' ? (
            <BalancerPanel />
          ) : activeTab === 'images' ? (
            <ImageManager onImagesChanged={setCustomImages} />
          ) : activeTab === 'databases' ? (
            <DatabasesPanel />
          ) : activeTab === 's3' ? (
            <S3Panel />
          ) : activeTab === 'volumes' ? (
            <VolumesPanel />
          ) : activeTab === 'mail' ? (
            <MailPanel />
          ) : activeTab === 'docker' ? (
            <DockerPanel />
          ) : activeTab === 'infra' ? (
            <InfraPanel />
          ) : activeTab === 'users' ? (
            <UsersAdminPanel apiToken={localStorage.getItem('aegis_admin_token')} apiUrl={window.location.origin} />
          ) : null}

        </main>
      </div>

      {/* Modals */}
      {openConsoleName && (
        <VncConsole 
          name={openConsoleName} 
          username={vms.find(v => v.name === openConsoleName)?.credentials?.username || 'root'}
          password={vms.find(v => v.name === openConsoleName)?.credentials?.password || ''}
          onClose={() => setOpenConsoleName(null)} 
        />
      )}

      {editingVM && (
        <VMEditModal 
          vm={editingVM} 
          onClose={() => setEditingVM(null)} 
          onSaveSuccess={fetchVMs} 
        />
      )}

      {showConnectModal && (
        <ConnectServerModal 
          onClose={() => setShowConnectModal(false)}
          onSuccess={fetchExternalServers}
        />
      )}

      {selectedServerId && (
        <ExternalServerDetail 
          serverId={selectedServerId}
          onClose={() => setSelectedServerId(null)}
        />
      )}

    </div>
  );
};

export default App;
