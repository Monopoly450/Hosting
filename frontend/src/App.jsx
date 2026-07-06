import React, { useEffect, useState } from 'react';
import { Server, Plus, Layers, ShieldCheck, Activity, Terminal, Shield, FolderOpen, LayoutDashboard, Link2, LogOut, Key, Menu, Monitor, Info, ChevronDown, ChevronLeft, Package, HardDrive, Square, Shuffle, Users, Database, Mail, X, Sun, Moon, Rocket } from 'lucide-react';
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
import DeploymentsPanel from './components/DeploymentsPanel';
import S3Panel from './components/S3Panel';
import VolumesPanel from './components/VolumesPanel';
import MailPanel from './components/MailPanel';
import CustomSelect from './components/CustomSelect';

const OS_VERSIONS = {
  ubuntu: [
    { label: 'Ubuntu 24.04 LTS', value: 'https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img' },
    { label: 'Ubuntu 22.04 LTS', value: 'https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img' },
    { label: 'Ubuntu 20.04 LTS', value: 'https://cloud-images.ubuntu.com/focal/current/focal-server-cloudimg-amd64.img' }
  ],
  centos: [
    { label: 'CentOS Stream 9', value: 'https://cloud.centos.org/centos/9-stream/x86_64/images/CentOS-Stream-GenericCloud-9-latest.x86_64.qcow2' },
    { label: 'CentOS Stream 10', value: 'https://cloud.centos.org/centos/10-stream/x86_64/images/CentOS-Stream-GenericCloud-10-latest.x86_64.qcow2' }
  ],
  debian: [
    { label: 'Debian 12 (Bookworm)', value: 'https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2' },
    { label: 'Debian 11 (Bullseye)', value: 'https://cloud.debian.org/images/cloud/bullseye/latest/debian-11-generic-amd64.qcow2' }
  ],
  windows: [
    { label: 'Windows Server 2022', value: 'https://go.microsoft.com/fwlink/p/?LinkID=2195280' },
    { label: 'Windows Server 2019', value: 'https://go.microsoft.com/fwlink/p/?LinkID=2195279' },
    { label: 'Windows Server 2016', value: 'https://go.microsoft.com/fwlink/p/?LinkID=2195278' }
  ],
  proxmox: [
    { label: 'Proxmox VE 8.2', value: 'https://download.proxmox.com/iso/proxmox-ve_8.2-1.iso' },
    { label: 'Proxmox VE 8.1', value: 'https://download.proxmox.com/iso/proxmox-ve_8.1-1.iso' },
    { label: 'Proxmox VE 7.4', value: 'https://download.proxmox.com/iso/proxmox-ve_7.4-1.iso' }
  ],
  bitrix: [
    { label: 'BitrixVM (CentOS 9)', value: 'https://cloud.centos.org/centos/9-stream/x86_64/images/CentOS-Stream-GenericCloud-9-latest.x86_64.qcow2' }
  ]
};

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
  const [showChangePasswordModal, setShowChangePasswordModal] = useState(false);
  const [selectedServerId, setSelectedServerId] = useState(null);
  const [selectedVMDetailName, setSelectedVMDetailName] = useState(null);

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [theme, setTheme] = useState(localStorage.getItem('aegis_theme') || 'dark');

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('aegis_theme', theme);
  }, [theme]);

  const navigateToTab = (tab) => {
    setActiveTab(tab);
    setSelectedVMDetailName(null);
    setSidebarOpen(false);
  };

  // VM Creation Form
  const [name, setName] = useState('');
  const [osType, setOsType] = useState('ubuntu'); // 'ubuntu' | 'windows'
  const [selectedVersions, setSelectedVersions] = useState({
    ubuntu: OS_VERSIONS.ubuntu[0].value,
    centos: OS_VERSIONS.centos[0].value,
    debian: OS_VERSIONS.debian[0].value,
    windows: OS_VERSIONS.windows[0].value,
    proxmox: OS_VERSIONS.proxmox[0].value,
    bitrix: OS_VERSIONS.bitrix[0].value
  });
  const [selectedCustomImage, setSelectedCustomImage] = useState('');
  const [packages, setPackages] = useState("");
  const [networkDrives, setNetworkDrives] = useState("");
  const [cpuCores, setCpuCores] = useState(2);
  const [memoryGb, setMemoryGb] = useState(2);
  const [diskGb, setDiskGb] = useState(20);
  const [isoUrl, setIsoUrl] = useState('');
  const [cloudInitTemplate, setCloudInitTemplate] = useState('');
  const [customUserData, setCustomUserData] = useState('');
  const [sshKey, setSshKey] = useState('');

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
    } else if (osType === 'proxmox') {
      setCpuCores(4);
      setMemoryGb(6);
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
        setQuotaUsage({
          max_vms: data.quotas.max_vms,
          used_vms: data.usage.vms,
          max_vcpus: data.quotas.max_vcpus,
          used_vcpus: data.usage.vcpus,
          max_ram_mb: data.quotas.max_ram_mb,
          used_ram_mb: data.usage.ram_mb,
          max_storage_gb: data.quotas.max_storage_gb,
          used_storage_gb: data.usage.storage_gb,
          balance: data.balance || 0,
        });
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
      } else {
        setServersLoading(false);
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
        iso_url: selectedVersions[osType] || undefined,
        cloud_init_template: cloudInitTemplate || undefined,
        custom_user_data: customUserData.trim() || undefined,
        ssh_key: sshKey.trim() || undefined
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
      setSshKey('');
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
      case 'deployments': return 'Деплой приложений';
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
        <div className="login-orb orb-1" />
        <div className="login-orb orb-2" />
        <div className="login-orb orb-3" />

        <div className="login-card">
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '14px', marginBottom: '32px' }}>
            <div className="login-logo-badge">
              <Layers size={38} strokeWidth={2.4} />
            </div>
            <h2 className="login-title" style={{ margin: 0 }}>ByteBurners</h2>
            <p style={{ textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.95rem', maxWidth: '280px' }}>
              Платформа управления облачной инфраструктурой
            </p>
          </div>

          <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
            <div className="input-group" style={{ marginBottom: 0 }}>
              <label className="input-label">Имя пользователя</label>
              <div style={{ position: 'relative' }}>
                <Users size={17} style={{ position: 'absolute', left: '13px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', pointerEvents: 'none' }} />
                <input
                  type="text"
                  className="form-control"
                  style={{ paddingLeft: '40px' }}
                  value={usernameInput}
                  onChange={(e) => setUsernameInput(e.target.value)}
                  placeholder="admin"
                  required
                />
              </div>
            </div>

            <div className="input-group" style={{ marginBottom: 0 }}>
              <label className="input-label">Пароль или ключ доступа</label>
              <div style={{ position: 'relative' }}>
                <Key size={17} style={{ position: 'absolute', left: '13px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', pointerEvents: 'none' }} />
                <input
                  type="password"
                  className="form-control"
                  style={{ paddingLeft: '40px' }}
                  value={passwordInput}
                  onChange={(e) => setPasswordInput(e.target.value)}
                  placeholder="Введите пароль или API ключ..."
                  required
                />
              </div>
            </div>

            <button type="submit" className="btn btn-primary" disabled={formLoading} style={{ width: '100%', padding: '13px', fontSize: '1rem', marginTop: '10px' }}>
              {formLoading ? <span className="spinner" /> : 'Войти в панель'}
            </button>
          </form>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', marginTop: '26px', color: 'var(--text-muted)', fontSize: '0.78rem' }}>
            <span className="status-dot live" style={{ background: 'var(--status-success)', width: '7px', height: '7px' }} />
            Защищённое соединение · ByteBurners Cloud
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="app-layout">
      {/* Sidebar mobile overlay */}
      <div 
        className={`sidebar-overlay ${sidebarOpen ? 'open' : ''}`} 
        onClick={() => setSidebarOpen(false)} 
      />

      {/* Left Sidebar */}
      <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
        <div className="sidebar-logo">
          <Layers className="logo-icon" size={26} strokeWidth={2.5} />
          <span className="logo-text">ByteBurners</span>
        </div>

        <div className="sidebar-nav">
          {userRole === 'admin' && (
            <button 
              className={`nav-item ${activeTab === 'dashboard' && !selectedVMDetailName ? 'active' : ''}`}
              onClick={() => navigateToTab('dashboard')}
            >
              <LayoutDashboard size={18} />
              Дашборд
            </button>
          )}

          <button 
            className={`nav-item ${(activeTab === 'vms' || selectedVMDetailName) ? 'active' : ''}`}
            onClick={() => navigateToTab('vms')}
          >
            <Activity size={18} />
            Серверы и Инстансы
          </button>

          <button 
            className={`nav-item ${activeTab === 'clusters' && !selectedVMDetailName ? 'active' : ''}`}
            onClick={() => navigateToTab('clusters')}
          >
            <Layers size={18} />
            Кластеры
          </button>

          <button 
            className={`nav-item ${activeTab === 'balancer' && !selectedVMDetailName ? 'active' : ''}`}
            onClick={() => navigateToTab('balancer')}
          >
            <Shuffle size={18} />
            Балансировщик
          </button>



          <button 
            className={`nav-item ${activeTab === 'databases' && !selectedVMDetailName ? 'active' : ''}`}
            onClick={() => navigateToTab('databases')}
          >
            <Database size={18} />
            Базы данных
          </button>

          <button
            className={`nav-item ${activeTab === 'deployments' && !selectedVMDetailName ? 'active' : ''}`}
            onClick={() => navigateToTab('deployments')}
          >
            <Rocket size={18} />
            Деплой приложений
          </button>

          <button
            className={`nav-item ${activeTab === 's3' && !selectedVMDetailName ? 'active' : ''}`}
            onClick={() => navigateToTab('s3')}
          >
            <FolderOpen size={18} />
            S3 Хранилище
          </button>

          <button 
            className={`nav-item ${activeTab === 'volumes' && !selectedVMDetailName ? 'active' : ''}`}
            onClick={() => navigateToTab('volumes')}
          >
            <HardDrive size={18} />
            Сетевые диски
          </button>

          <button 
            className={`nav-item ${activeTab === 'mail' && !selectedVMDetailName ? 'active' : ''}`}
            onClick={() => navigateToTab('mail')}
          >
            <Mail size={18} />
            Почтовый хостинг
          </button>

          {userRole === 'admin' && (
            <>
              <button 
                className={`nav-item ${activeTab === 'docker' && !selectedVMDetailName ? 'active' : ''}`}
                onClick={() => navigateToTab('docker')}
              >
                <Shield size={18} />
                Docker Управление
              </button>

              <button 
                className={`nav-item ${activeTab === 'infra' && !selectedVMDetailName ? 'active' : ''}`}
                onClick={() => navigateToTab('infra')}
              >
                <Terminal size={18} />
                Инфраструктура
              </button>

              <button 
                className={`nav-item ${activeTab === 'users' && !selectedVMDetailName ? 'active' : ''}`}
                onClick={() => navigateToTab('users')}
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
                <span>{quotaUsage.used_vms} / {quotaUsage.max_vms} (ост. {Math.max(0, quotaUsage.max_vms - quotaUsage.used_vms)})</span>
              </div>
              <div style={{ height: '3px', background: 'var(--bg-surface-hover)', borderRadius: '2px', marginTop: '2px', overflow: 'hidden' }}>
                <div style={{ height: '100%', background: 'var(--accent-primary)', width: `${Math.min(100, (quotaUsage.used_vms / quotaUsage.max_vms) * 100)}%` }}></div>
              </div>
            </div>
            {/* CPU */}
            <div style={{ marginBottom: '6px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                <span>Ядра vCPU</span>
                <span>{quotaUsage.used_vcpus} / {quotaUsage.max_vcpus} (ост. {Math.max(0, quotaUsage.max_vcpus - quotaUsage.used_vcpus)})</span>
              </div>
              <div style={{ height: '3px', background: 'var(--bg-surface-hover)', borderRadius: '2px', marginTop: '2px', overflow: 'hidden' }}>
                <div style={{ height: '100%', background: 'var(--accent-primary)', width: `${Math.min(100, (quotaUsage.used_vcpus / quotaUsage.max_vcpus) * 100)}%` }}></div>
              </div>
            </div>
            {/* RAM */}
            <div style={{ marginBottom: '6px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                <span>ОЗУ (RAM)</span>
                <span>{quotaUsage.used_ram_mb} / {quotaUsage.max_ram_mb} MB (ост. {Math.max(0, quotaUsage.max_ram_mb - quotaUsage.used_ram_mb)} MB)</span>
              </div>
              <div style={{ height: '3px', background: 'var(--bg-surface-hover)', borderRadius: '2px', marginTop: '2px', overflow: 'hidden' }}>
                <div style={{ height: '100%', background: 'var(--accent-primary)', width: `${Math.min(100, (quotaUsage.used_ram_mb / quotaUsage.max_ram_mb) * 100)}%` }}></div>
              </div>
            </div>
            {/* Storage */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                <span>Диски (HDD)</span>
                <span>{quotaUsage.used_storage_gb} / {quotaUsage.max_storage_gb} GB (ост. {Math.max(0, quotaUsage.max_storage_gb - quotaUsage.used_storage_gb)} GB)</span>
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
          </div>
          <button 
            className="nav-item" 
            style={{ width: '100%', color: 'var(--text-secondary)', marginBottom: '4px' }}
            onClick={() => setShowChangePasswordModal(true)}
          >
            <Key size={18} />
            Сменить пароль
          </button>
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
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            {selectedVMDetailName ? (
              <button 
                className="btn btn-secondary btn-icon" 
                onClick={() => setSelectedVMDetailName(null)}
                style={{ padding: '6px 10px', minWidth: 'auto', display: 'flex', alignItems: 'center', gap: '4px', border: 'none', background: 'transparent', cursor: 'pointer', color: 'var(--text-primary)' }}
              >
                <ChevronLeft size={20} />
                <span className="desktop-only" style={{ fontSize: '0.9rem', fontWeight: 500 }}>Назад</span>
              </button>
            ) : (
              <button className="btn-menu" onClick={() => setSidebarOpen(true)}>
                <Menu size={20} />
              </button>
            )}
            <div className="header-title">{getTabTitle()}</div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <button 
              className="btn btn-secondary btn-icon" 
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              style={{ borderRadius: 'var(--radius-pill)', width: '36px', height: '36px', padding: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
              title="Переключить тему"
            >
              {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
            </button>
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
          ) : activeTab === 'deployments' ? (
            <DeploymentsPanel />
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

      {showChangePasswordModal && (
        <ChangePasswordModal onClose={() => setShowChangePasswordModal(false)} />
      )}

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
                          <div className="os-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '12px' }}>
                            <div className={`os-card ${osType === 'ubuntu' ? 'selected' : ''}`} onClick={() => setOsType('ubuntu')}>
                              <div className="os-card-icon" style={{ color: '#f97316' }}><Server size={24} /></div>
                              <div className="os-card-title">Ubuntu</div>
                              <div className="os-card-version">{OS_VERSIONS.ubuntu.find(v => v.value === selectedVersions.ubuntu)?.label.split(' ')[1] || '24.04'}</div>
                            </div>
                            
                            <div className={`os-card ${osType === 'centos' ? 'selected' : ''}`} onClick={() => setOsType('centos')}>
                              <div className="os-card-icon" style={{ color: '#84cc16' }}><Server size={24} /></div>
                              <div className="os-card-title">CentOS</div>
                              <div className="os-card-version">{OS_VERSIONS.centos.find(v => v.value === selectedVersions.centos)?.label.split(' ')[2] || '9'}</div>
                            </div>
                            
                            <div className={`os-card ${osType === 'debian' ? 'selected' : ''}`} onClick={() => setOsType('debian')}>
                              <div className="os-card-icon" style={{ color: '#ef4444' }}><Server size={24} /></div>
                              <div className="os-card-title">Debian</div>
                              <div className="os-card-version">{OS_VERSIONS.debian.find(v => v.value === selectedVersions.debian)?.label.split(' ')[1] || '12'}</div>
                            </div>
                            
                            <div className={`os-card ${osType === 'windows' ? 'selected' : ''}`} onClick={() => setOsType('windows')}>
                              <div className="os-card-icon" style={{ color: '#0078d4' }}><Server size={24} /></div>
                              <div className="os-card-title">Windows Server</div>
                              <div className="os-card-version">{OS_VERSIONS.windows.find(v => v.value === selectedVersions.windows)?.label.split(' ').slice(1).join(' ') || '2022'}</div>
                            </div>

                            <div className={`os-card ${osType === 'bitrix' ? 'selected' : ''}`} onClick={() => setOsType('bitrix')}>
                              <div className="os-card-icon" style={{ color: '#ef4444' }}><Activity size={24} /></div>
                              <div className="os-card-title">BitrixVM</div>
                              <div className="os-card-version">CentOS 9</div>
                            </div>

                            <div className={`os-card ${osType === 'proxmox' ? 'selected' : ''}`} onClick={() => setOsType('proxmox')}>
                              <div className="os-card-icon" style={{ color: '#e57000' }}><Layers size={24} /></div>
                              <div className="os-card-title">Proxmox VE</div>
                              <div className="os-card-version">{OS_VERSIONS.proxmox.find(v => v.value === selectedVersions.proxmox)?.label.split(' ')[2] || '8.2'}</div>
                            </div>
                          </div>
                        </div>

                        {OS_VERSIONS[osType] && OS_VERSIONS[osType].length > 1 && (
                          <div className="input-group" style={{ marginTop: '4px' }}>
                            <label className="input-label">Версия операционной системы</label>
                            <CustomSelect 
                              value={selectedVersions[osType]}
                              onChange={(e) => setSelectedVersions(prev => ({ ...prev, [osType]: e.target.value }))}
                              options={OS_VERSIONS[osType].map(v => ({ value: v.value, label: v.label }))}
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
                              { value: 'lamp', label: 'LAMP (Apache + PHP + MariaDB)' },
                              { value: 'lemp', label: 'LEMP (Nginx + PHP-FPM + MariaDB)' },
                              { value: 'docker', label: 'Docker (Engine + Compose)' },
                              { value: 'portainer', label: 'Portainer (Docker + веб-UI :9000)' },
                              { value: 'nodejs', label: 'Node.js 20 LTS (+ pm2)' },
                              { value: 'python', label: 'Python 3 (pip + venv + gunicorn)' },
                              { value: 'postgresql', label: 'PostgreSQL сервер' },
                              { value: 'redis', label: 'Redis сервер' },
                              { value: 'wordpress', label: 'WordPress (Apache + MariaDB + PHP)' }
                            ]}
                          />
                        </div>

                        <div className="input-group">
                          <label className="input-label">Публичный SSH-ключ (для безопасного входа)</label>
                          <input 
                            type="text" 
                            className="form-control" 
                            placeholder="ssh-rsa AAAA..."
                            value={sshKey}
                            onChange={e => setSshKey(e.target.value)}
                          />
                          <small style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '4px', display: 'block' }}>
                            Если указан ключ, парольный вход по SSH будет автоматически заблокирован на создаваемой ВМ.
                          </small>
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
                        <button type="submit" className="btn btn-primary" disabled={formLoading}>
                          {formLoading ? <span className="spinner" /> : 'Создать'}
                        </button>
                      </div>
                    </form>
                  </div>
                </div>
              )}

    </div>
  );
};

const ChangePasswordModal = ({ onClose }) => {
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      setError('Новые пароли не совпадают');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('aegis_admin_token')}`
        },
        body: JSON.stringify({
          old_password: oldPassword,
          new_password: newPassword
        })
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Не удалось изменить пароль');
      }
      alert('Пароль успешно изменен');
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="slide-over-overlay" onClick={onClose}>
      <div className="slide-over-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '400px' }}>
        <div className="slide-over-header">
          <h2>Смена пароля</h2>
          <button className="btn-close" onClick={onClose} type="button">
            <X size={18} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="slide-over-body" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {error && <div className="alert alert-danger">{error}</div>}
          <div className="input-group">
            <label className="input-label">Текущий пароль</label>
            <input 
              type="password" 
              className="form-control" 
              value={oldPassword} 
              onChange={e => setOldPassword(e.target.value)} 
              required 
            />
          </div>
          <div className="input-group">
            <label className="input-label">Новый пароль</label>
            <input 
              type="password" 
              className="form-control" 
              value={newPassword} 
              onChange={e => setNewPassword(e.target.value)} 
              required 
            />
          </div>
          <div className="input-group">
            <label className="input-label">Подтвердите новый пароль</label>
            <input 
              type="password" 
              className="form-control" 
              value={confirmPassword} 
              onChange={e => setConfirmPassword(e.target.value)} 
              required 
            />
          </div>
          <div style={{ marginTop: 'auto', display: 'flex', gap: '12px', paddingTop: '20px' }}>
            <button type="button" className="btn btn-secondary" style={{ flex: 1 }} onClick={onClose}>
              Отмена
            </button>
            <button type="submit" className="btn btn-primary" style={{ flex: 1 }} disabled={loading}>
              {loading ? <span className="spinner" /> : 'Сохранить'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default App;
