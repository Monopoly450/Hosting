import React, { useState, useEffect, useRef } from 'react';
import { 
  Layers, Plus, Activity, Terminal, Shield, FolderOpen, LayoutDashboard, 
  Play, Square, Trash2, Key, HelpCircle, User, DollarSign, Wallet, Monitor, X, AlertCircle, RefreshCw, Cloud,
  ChevronDown, Globe, Cpu, Wifi, Info, ChevronLeft, ChevronRight, Menu
} from 'lucide-react';
import RFB from '@novnc/novnc';
import AwsConsole from './components/AwsConsole';

// Self-contained VncConsole Component inside App.jsx for portability
const ClientVncConsole = ({ name, username, password, ips = [], onClose }) => {
  const canvasContainerRef = useRef(null);
  const rfbRef = useRef(null);
  const [status, setStatus] = useState('connecting'); // 'connecting' | 'connected' | 'disconnected' | 'error'
  const [errorMsg, setErrorMsg] = useState('');
  const [bypassProgress, setBypassProgress] = useState(false);

  useEffect(() => {
    if (ips.length === 0 && !bypassProgress) return;
    if (!canvasContainerRef.current) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const token = localStorage.getItem('aegis_admin_token') || 'aegis-admin-secret-key-2026';
    const wsUrl = `${protocol}//${window.location.host}/api/vnc/${name}?token=${encodeURIComponent(token)}`;
    
    console.log(`Client VNC connecting to: ${wsUrl}`);

    try {
      const rfb = new RFB(canvasContainerRef.current, wsUrl, {
        wsProtocols: ['binary']
      });

      rfbRef.current = rfb;

      rfb.addEventListener('connect', () => {
        setStatus('connected');
        rfb.focus();
        
        // AutoLogin helper
        if (username && password) {
          setTimeout(() => {
            sendString(username + "\n");
            setTimeout(() => {
              sendString(password + "\n");
            }, 1000);
          }, 1800);
        }
      });

      rfb.addEventListener('disconnect', (e) => {
        if (e.detail.clean) {
          setStatus('disconnected');
        } else {
          setStatus('error');
          setErrorMsg('Сессия разорвана API-сервером.');
        }
      });

      rfb.addEventListener('credentialsrequired', () => {
        rfb.sendCredentials({ password: '' });
      });

      rfb.scaleViewport = true;
      rfb.resizeSession = true;

    } catch (err) {
      console.error(err);
      setStatus('error');
      setErrorMsg(err.message || 'Ошибка запуска консоли.');
    }

    return () => {
      if (rfbRef.current) {
        rfbRef.current.disconnect();
        rfbRef.current = null;
      }
    };
  }, [name, ips, bypassProgress]);

  const sendString = (str) => {
    if (!rfbRef.current || status !== 'connected') return;
    rfbRef.current.focus();

    const XK_Shift_L = 0xffe1;
    const XK_Return = 0xff0d;
    const chars = str.split("");
    
    const processNext = () => {
      if (chars.length === 0) return;
      const char = chars.shift();
      
      if (char === "\n") {
        rfbRef.current.sendKey(XK_Return, "Enter", true);
        setTimeout(() => {
          rfbRef.current.sendKey(XK_Return, "Enter", false);
          setTimeout(processNext, 45);
        }, 45);
        return;
      }
      
      const code = char.charCodeAt(0);
      const needsShift = /[A-Z!@#$%^&*()_+{}:"<>?~|]/.test(char);
      
      if (needsShift) {
        rfbRef.current.sendKey(XK_Shift_L, "ShiftLeft", true);
      }
      
      rfbRef.current.sendKey(code, null, true);
      setTimeout(() => {
        rfbRef.current.sendKey(code, null, false);
        if (needsShift) {
          rfbRef.current.sendKey(XK_Shift_L, "ShiftLeft", false);
        }
        setTimeout(processNext, 45);
      }, 45);
    };
    
    processNext();
  };

  const handleCtrlAltDel = () => {
    if (rfbRef.current && status === 'connected') {
      rfbRef.current.sendCtrlAltDel();
    }
  };

  const showProgress = ips.length === 0 && !bypassProgress;

  return (
    <div className="console-modal-backdrop">
      <div className="console-container" style={{ maxWidth: '600px', width: '90vw' }}>
        <div className="console-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 'bold' }}>
            <Monitor size={18} color="#38bdf8" />
            <span>{showProgress ? 'Развертывание сервера:' : 'Экран сервера:'} <strong style={{ color: '#38bdf8' }}>{name}</strong></span>
          </div>
          <div style={{ display: 'flex', gap: '10px' }}>
            {!showProgress && status === 'connected' && (
              <>
                <button className="btn btn-secondary btn-sm" onClick={() => sendString(password + "\n")}>
                  Вставить пароль
                </button>
                <button className="btn btn-secondary btn-sm" onClick={handleCtrlAltDel}>
                  Ctrl+Alt+Del
                </button>
              </>
            )}
            <button className="btn btn-danger btn-sm" onClick={onClose}>
              <X size={14} />
            </button>
          </div>
        </div>
        <div className="console-canvas-container" style={{ padding: showProgress ? '30px' : '0px', background: 'var(--bg-secondary)', minHeight: showProgress ? 'auto' : '500px' }}>
          {showProgress ? (
            <div style={{ 
              display: 'flex', 
              flexDirection: 'column', 
              alignItems: 'center', 
              justifyContent: 'center', 
              gap: '20px', 
              textAlign: 'center',
              color: '#f8fafc'
            }}>
              <style>{`
                @keyframes spin-circle {
                  0% { transform: rotate(0deg); }
                  100% { transform: rotate(360deg); }
                }
                @keyframes pulse-text {
                  0% { opacity: 0.6; }
                  50% { opacity: 1; }
                  100% { opacity: 0.6; }
                }
              `}</style>
              
              <div style={{ position: 'relative', width: '100px', height: '100px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <svg width="100" height="100" viewBox="0 0 100 100" style={{ transform: 'rotate(-90deg)', animation: 'spin-circle 2s linear infinite' }}>
                  <circle cx="50" cy="50" r="40" fill="transparent" stroke="rgba(255,255,255,0.05)" strokeWidth="5" />
                  <circle cx="50" cy="50" r="40" fill="transparent" stroke="#38bdf8" strokeWidth="5" 
                    strokeDasharray="251.2" strokeDashoffset="80" 
                    style={{ strokeLinecap: 'round' }}
                  />
                </svg>
                <div style={{ position: 'absolute', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                  <Activity size={24} color="#38bdf8" style={{ animation: 'pulse-text 1.5s ease-in-out infinite' }} />
                </div>
              </div>

              <div>
                <h4 style={{ fontSize: '1.1rem', fontWeight: 600, margin: 0 }}>Настройка гостевой операционной системы</h4>
                <p style={{ fontSize: '0.8rem', color: '#94a3b8', marginTop: '6px', maxWidth: '400px', lineHeight: '1.4' }}>
                  Сервер запущен. Пожалуйста, подождите, пока завершится первоначальная настройка сетевого интерфейса и гостевого агента.
                </p>
              </div>

              {/* Реквизиты */}
              <div style={{ 
                display: 'flex', 
                flexDirection: 'column', 
                gap: '6px', 
                padding: '12px 16px', 
                background: 'rgba(255,255,255,0.02)', 
                border: '1px solid var(--border-color)', 
                borderRadius: '6px', 
                width: '100%', 
                maxWidth: '360px', 
                boxSizing: 'border-box',
                textAlign: 'left'
              }}>
                <div style={{ fontSize: '0.8rem', fontWeight: 'bold', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '4px', marginBottom: '4px', color: '#38bdf8' }}>🔑 Реквизиты для входа:</div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem' }}>
                  <span style={{ color: '#94a3b8' }}>Логин:</span>
                  <strong style={{ color: '#f8fafc' }}>{username}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem' }}>
                  <span style={{ color: '#94a3b8' }}>Пароль:</span>
                  <strong style={{ color: '#f8fafc', fontFamily: 'monospace' }}>{password || 'N/A'}</strong>
                </div>
              </div>

              {/* Checklist */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', width: '100%', maxWidth: '360px', borderTop: '1px solid var(--border-color)', paddingTop: '15px', textAlign: 'left', fontSize: '0.75rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: '#94a3b8' }}>1. Создание диска VDS</span>
                  <span style={{ color: '#4ade80', fontWeight: 600 }}>Выполнено ✓</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: '#94a3b8' }}>2. Запуск контейнера виртуализации</span>
                  <span style={{ color: '#4ade80', fontWeight: 600 }}>Выполнено ✓</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: '#f8fafc', fontWeight: 600 }}>3. Настройка сетевого адаптера и агента</span>
                  <span style={{ color: '#38bdf8', fontWeight: 600, animation: 'pulse-text 1s infinite' }}>Ожидание сети...</span>
                </div>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', alignItems: 'center', width: '100%', borderTop: '1px solid var(--border-color)', paddingTop: '15px' }}>
                <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                  Не удается получить IP?
                </span>
                <button 
                  className="btn btn-secondary btn-sm"
                  onClick={() => setBypassProgress(true)}
                  style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#f8fafc', border: '1px solid var(--border-color)', borderRadius: '0px' }}
                >
                  <Monitor size={12} /> Запустить аварийную noVNC консоль
                </button>
              </div>
            </div>
          ) : (
            <>
              <div ref={canvasContainerRef} style={{ width: '100%', height: '500px', display: status === 'connected' ? 'block' : 'none' }} />
              {status !== 'connected' && (
                <div className="console-status-overlay">
                  {status === 'connecting' && (
                    <>
                      <div className="spinner"></div>
                      <p>Подключение к экрану виртуалки...</p>
                    </>
                  )}
                  {status === 'disconnected' && <p>Подключение завершено.</p>}
                  {status === 'error' && (
                    <>
                      <AlertCircle size={32} color="#ef4444" />
                      <p style={{ color: '#ef4444' }}>{errorMsg || 'Ошибка соединения VNC'}</p>
                    </>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

const App = () => {
  const [activeTab, setActiveTab] = useState('landing'); // 'landing' | 'cabinet'
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [cabinetTab, setCabinetTab] = useState('servers'); // 'servers' | 'order' | 'billing' | 'balancers' | 'placeholder'
  const [placeholderTabName, setPlaceholderTabName] = useState('');
  const [authError, setAuthError] = useState(false);
  const [apiTokenInput, setApiTokenInput] = useState('');

  useEffect(() => {
    const handleAuthError = () => {
      setAuthError(true);
    };
    window.addEventListener('aegis-auth-error', handleAuthError);
    return () => window.removeEventListener('aegis-auth-error', handleAuthError);
  }, []);

  const handleSaveApiToken = (e) => {
    e.preventDefault();
    if (!apiTokenInput.trim()) return;
    localStorage.setItem('aegis_admin_token', apiTokenInput.trim());
    setAuthError(false);
    setLoading(true);
    fetchVDS();
  };

  // VDS Lists & Balance
  const [vms, setVms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [balance, setBalance] = useState(4250.0); // Default user balance in Rubles
  const [billingRate, setBillingRate] = useState(0.0); // Cost/sec in Rubles
  
  // Projects State
  const [projectsList, setProjectsList] = useState(['Общий проект', 'Проект Production', 'Проект Staging']);
  const [selectedProject, setSelectedProject] = useState('Общий проект');
  const [showProjectDropdown, setShowProjectDropdown] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');

  // Modals
  const [openConsoleName, setOpenConsoleName] = useState(null);
  const [showPaymentModal, setShowPaymentModal] = useState(false);
  const [paymentAmount, setPaymentAmount] = useState('500');
  const [orderingInProgress, setOrderingInProgress] = useState(false);

  // VDS Configuration state
  const [vdsName, setVdsName] = useState('');
  const [osType, setOsType] = useState('ubuntu'); // 'ubuntu' | 'windows'
  const [cpuCores, setCpuCores] = useState(2);
  const [memoryGb, setMemoryGb] = useState(4);
  const [diskGb, setDiskGb] = useState(30);

  // Load Balancers State
  const [balancers, setBalancers] = useState([
    {
      id: 'lb-mskh492',
      name: 'balancer-moscow-1',
      region: 'Москва',
      region_code: 'moscow',
      tariff_id: 2,
      nodes: 1,
      bandwidth: '1000 Мбит/с',
      price_month: 250,
      price_hour: 0.34,
      maintenance: 'В любое время',
      ip: '185.120.10.84',
      status: 'Running',
      created_at: '08.06.2026, 12:45:20'
    }
  ]);
  const [activeBalancerView, setActiveBalancerView] = useState('list'); // 'list' | 'create'
  
  // Balancer form states
  const [selectedRegion, setSelectedRegion] = useState('moscow');
  const [selectedTariffId, setSelectedTariffId] = useState(2);
  const [selectedMaintenance, setSelectedMaintenance] = useState('anytime');
  const [pricingPeriod, setPricingPeriod] = useState('day'); // 'hour' | 'day' | 'month'
  const [showTerminalModal, setShowTerminalModal] = useState(false);

  useEffect(() => {
    if (activeTab === 'cabinet') {
      fetchVDS();
      const interval = setInterval(fetchVDS, 5000);
      return () => clearInterval(interval);
    }
  }, [activeTab]);

  // Pay-as-you-go ticker loop in frontend (scaled for Rubles)
  useEffect(() => {
    const ticker = setInterval(() => {
      if (activeTab === 'cabinet' && billingRate > 0) {
        setBalance(prev => {
          const next = prev - billingRate;
          return next < 0 ? 0 : next;
        });
      }
    }, 1000);
    return () => clearInterval(ticker);
  }, [activeTab, billingRate]);

  // Recalculate billing rate based on running servers and load balancers
  useEffect(() => {
    let rate = 0;
    vms.forEach(vm => {
      if (vm.status === 'Running') {
        // Rubles pricing: 1 core = 0.002 ₽/sec, 1GB RAM = 0.001 ₽/sec, 1GB SSD = 0.0001 ₽/sec
        rate += vm.cpu * 0.002 + vm.ram * 0.001 + vm.disk * 0.0001;
      }
    });
    balancers.forEach(lb => {
      if (lb.status === 'Running') {
        // Convert hourly price to per-second: price_hour / 3600
        rate += lb.price_hour / 3600;
      }
    });
    setBillingRate(rate);
  }, [vms, balancers]);

  const fetchVDS = async () => {
    try {
      const response = await fetch('/api/vms');
      if (response.ok) {
        const data = await response.json();
        const clientVms = data.filter(vm => 
          (vm.labels && vm.labels["hosting.antigravity.io/owner"] === "client-01") ||
          vm.name.startsWith("client-") ||
          vm.template === "ubuntu" ||
          vm.template === "windows"
        );
        setVms(clientVms);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleOrderVDS = async (e) => {
    e.preventDefault();
    if (!vdsName.trim()) return;

    const cleanName = "client-" + vdsName.toLowerCase().replace(/[^a-z0-9-]/g, '-');
    const costPerMonth = cpuCores * 150 + memoryGb * 50 + diskGb * 3;
    
    if (balance < 350.0) {
      alert("Недостаточно средств. Минимальный баланс для заказа сервера — 350.00 ₽. Пожалуйста, пополните счет во вкладке 'Баланс и платежи'.");
      setCabinetTab('billing');
      return;
    }

    setOrderingInProgress(true);
    try {
      const payload = {
        name: cleanName,
        os_type: osType,
        cpu_cores: parseInt(cpuCores),
        memory_gb: parseInt(memoryGb),
        disk_gb: parseInt(diskGb)
      };

      const response = await fetch('/api/vms', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || "Не удалось заказать сервер.");
      }

      const resData = await response.json();
      
      // Deduct setup fee from balance in Rubles
      setBalance(prev => prev - 150.0); // 150 ₽ setup fee
      setVdsName('');
      fetchVDS();
      setCabinetTab('servers');
      
      alert(`Ваш сервер ${cleanName} успешно заказан и устанавливается!\n\nРеквизиты для входа:\nIP-адрес: Выдается...\nЛогин: ${resData.username}\nПароль: ${resData.password}`);
    } catch (err) {
      alert(`Ошибка при заказе: ${err.message}`);
    } finally {
      setOrderingInProgress(false);
    }
  };

  const handlePowerAction = async (name, action) => {
    try {
      const res = await fetch(`/api/vms/${name}/${action}`, { method: 'POST' });
      if (!res.ok) throw new Error("Ошибка операции питания");
      fetchVDS();
    } catch (err) {
      alert(err.message);
    }
  };

  const handleDeleteVDS = async (name) => {
    if (!confirm(`Вы уверены, что хотите удалить и безвозвратно стереть сервер ${name}?`)) return;
    try {
      const res = await fetch(`/api/vms/${name}`, { method: 'DELETE' });
      if (!res.ok) throw new Error("Ошибка удаления");
      fetchVDS();
    } catch (err) {
      alert(err.message);
    }
  };

  const handlePaymentSubmit = (e) => {
    e.preventDefault();
    const amt = parseFloat(paymentAmount);
    if (isNaN(amt) || amt <= 0) return;
    setBalance(prev => prev + amt);
    setShowPaymentModal(false);
    alert(`Счет успешно пополнен на ${amt.toFixed(2)} ₽!`);
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

  const handleOrderBalancer = (e) => {
    e.preventDefault();
    
    const selectedTariff = [
      { id: 1, nodes: 1, bandwidth: '500 Мбит/с', price_month: 149, price_hour: 0.2 },
      { id: 2, nodes: 1, bandwidth: '1000 Мбит/с', price_month: 250, price_hour: 0.34 },
      { id: 3, nodes: 2, bandwidth: '1000 Мбит/с', price_month: 749, price_hour: 1.02 }
    ].find(t => t.id === selectedTariffId);

    if (balance < 250.0) {
      alert("Недостаточно средств для заказа балансировщика. Минимальный баланс — 250.00 ₽.");
      setCabinetTab('billing');
      return;
    }

    setOrderingInProgress(true);
    
    setTimeout(() => {
      const regionName = selectedRegion === 'moscow' ? 'Москва' : selectedRegion === 'amsterdam' ? 'Амстердам' : 'Франкфурт';
      const newLb = {
        id: 'lb-' + Math.random().toString(36).substr(2, 7),
        name: `balancer-${selectedRegion}-${balancers.length + 1}`,
        region: regionName,
        region_code: selectedRegion,
        tariff_id: selectedTariff.id,
        nodes: selectedTariff.nodes,
        bandwidth: selectedTariff.bandwidth,
        price_month: selectedTariff.price_month,
        price_hour: selectedTariff.price_hour,
        maintenance: selectedMaintenance === 'anytime' ? 'В любое время' : selectedMaintenance === 'night' ? 'Ночью' : 'В выходные',
        ip: '194.87.95.' + Math.floor(Math.random() * 254 + 1),
        status: 'Creating',
        created_at: new Date().toLocaleString('ru-RU')
      };

      setBalancers(prev => [...prev, newLb]);
      setBalance(prev => prev - 50.0); // technical setup / deposit fee (50 ₽)
      setOrderingInProgress(false);
      setActiveBalancerView('list');
      
      // Deploy simulation
      setTimeout(() => {
        setBalancers(prev => prev.map(lb => lb.id === newLb.id ? { ...lb, status: 'Running' } : lb));
      }, 5000);

      alert(`Балансировщик ${newLb.name} успешно заказан и разворачивается в регионе ${regionName}!\nВыделенный IP: ${newLb.ip}\nСписание за первый час (включая инсталляцию): 50.00 ₽.`);
    }, 1200);
  };

  const handleDeleteBalancer = (id, name) => {
    if (!confirm(`Вы уверены, что хотите удалить балансировщик ${name}?`)) return;
    setBalancers(prev => prev.filter(lb => lb.id !== id));
    alert(`Балансировщик ${name} успешно удален, ресурсы освобождены.`);
  };

  const handleSelectPlaceholderTab = (tabName) => {
    setPlaceholderTabName(tabName);
    setCabinetTab('placeholder');
    setSidebarOpen(false);
  };

  return (
    <div className="cabinet-container">
      {authError && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
          backgroundColor: '#0a0d16',
          backgroundImage: 'radial-gradient(circle at 50% 50%, rgba(92, 100, 236, 0.08) 0%, transparent 50%)',
          fontFamily: 'var(--font-sans)',
          padding: '20px',
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          zIndex: 9999
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
              <div style={{ background: 'rgba(239, 68, 68, 0.1)', padding: '14px', borderRadius: '12px', color: 'var(--danger)' }}>
                <Shield size={36} />
              </div>
              <h2 style={{ fontSize: '1.4rem', fontWeight: 800, margin: '10px 0 2px 0', color: 'white' }}>Доступ ограничен</h2>
              <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                Личный кабинет получил ошибку авторизации (401) от бэкенда. Пожалуйста, введите ваш секретный API-токен:
              </p>
            </div>

            <form onSubmit={handleSaveApiToken} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 600 }}>API Token (X-Admin-Token)</label>
                <div style={{ position: 'relative' }}>
                  <Key size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                  <input 
                    type="password"
                    className="form-input"
                    style={{ width: '100%', paddingLeft: '38px', background: '#0a0d16', borderRadius: '8px', border: '1px solid var(--border-color)', height: '40px', color: 'white' }}
                    value={apiTokenInput}
                    onChange={(e) => setApiTokenInput(e.target.value)}
                    placeholder="Введите API-токен..."
                    required
                  />
                </div>
              </div>

              <button type="submit" className="btn btn-primary" style={{ width: '100%', padding: '12px', fontSize: '0.9rem', borderRadius: '8px', marginTop: '8px' }}>
                Сохранить и обновить
              </button>
            </form>
          </div>
        </div>
      )}
      
      {/* Landing / Showcase Tab */}
      {activeTab === 'landing' && (
        <div style={{ background: '#0a0e17', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
          
          {/* Landing Header */}
          <header style={{ padding: '20px 40px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <Layers size={28} color="#38bdf8" />
              <strong style={{ fontSize: '1.3rem', color: '#f8fafc' }}>Aegis Cloud Engine</strong>
            </div>
            <button className="btn btn-primary" onClick={() => setActiveTab('cabinet')}>
              Войти в кабинет
            </button>
          </header>

          {/* Landing Body */}
          <main style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '60px 20px', textAlign: 'center' }}>
            <span style={{ fontSize: '0.8rem', background: 'rgba(56,189,248,0.1)', color: '#38bdf8', padding: '6px 12px', fontWeight: 'bold', letterSpacing: '1px', textTransform: 'uppercase', marginBottom: '20px' }}>
              Гиперконвергентные облачные VDS/VPS
            </span>
            <h1 style={{ fontSize: '3.2rem', fontWeight: 900, letterSpacing: '-1px', maxWidth: '800px', lineHeight: 1.15, color: '#fff' }}>
              Молниеносная производительность NVMe и DPDK
            </h1>
            <p style={{ fontSize: '1.1rem', color: '#94a3b8', maxWidth: '600px', marginTop: '20px', lineHeight: 1.6 }}>
              Виртуальные выделенные серверы корпоративного класса на базе архитектуры Aegis-HCI с гарантированным CPU Pinning без оверселлинга.
            </p>

            <div style={{ display: 'flex', gap: '16px', marginTop: '36px' }}>
              <button className="btn btn-primary" style={{ padding: '12px 28px', fontSize: '1rem' }} onClick={() => setActiveTab('cabinet')}>
                Заказать сервер
              </button>
              <button className="btn btn-secondary" style={{ padding: '12px 28px', fontSize: '1rem' }} onClick={() => alert("Система Aegis-HCI работает в связке с Kubernetes KubeVirt и CNI Multus на целевом сервере.")}>
                Архитектура платформы
              </button>
            </div>

            {/* Plans Grid */}
            <div className="responsive-grid-3" style={{ maxWidth: '1000px', width: '100%', marginTop: '80px' }}>
              
              <div className="pricing-plan-card card">
                <div>
                  <h3 style={{ fontSize: '1.2rem', margin: 0 }}>Aegis-Micro</h3>
                  <p style={{ color: '#94a3b8', fontSize: '0.8rem', marginTop: '6px' }}>Для мелких задач и ботов</p>
                  <div style={{ fontSize: '2rem', fontWeight: 'bold', color: '#38bdf8', margin: '20px 0' }}>
                    $5.00<span style={{ fontSize: '0.9rem', color: '#64748b' }}>/мес</span>
                  </div>
                  <ul style={{ listStyle: 'none', padding: 0, margin: 0, fontSize: '0.85rem', color: '#94a3b8', display: 'flex', flexDirection: 'column', gap: '8px', textAlign: 'left' }}>
                    <li>● 1 ядро CPU (Гарантировано)</li>
                    <li>● 1 ГБ RAM LPDDR5</li>
                    <li>● 20 ГБ NVMe Direct-IO SSD</li>
                    <li>● Сеть DPDK 100 Mbps</li>
                  </ul>
                </div>
              </div>

              <div className="pricing-plan-card card recommended" style={{ border: '1px solid #38bdf8' }}>
                <div>
                  <h3 style={{ fontSize: '1.2rem', margin: 0, display: 'flex', justifyContent: 'space-between' }}>
                    Aegis-Standard 
                    <span style={{ fontSize: '0.65rem', background: '#38bdf8', color: '#0a0e17', padding: '2px 6px', fontWeight: 'bold' }}>POPULAR</span>
                  </h3>
                  <p style={{ color: '#94a3b8', fontSize: '0.8rem', marginTop: '6px' }}>Для сайтов и баз данных</p>
                  <div style={{ fontSize: '2rem', fontWeight: 'bold', color: '#38bdf8', margin: '20px 0' }}>
                    $15.00<span style={{ fontSize: '0.9rem', color: '#64748b' }}>/мес</span>
                  </div>
                  <ul style={{ listStyle: 'none', padding: 0, margin: 0, fontSize: '0.85rem', color: '#94a3b8', display: 'flex', flexDirection: 'column', gap: '8px', textAlign: 'left' }}>
                    <li>● 2 ядра CPU (Pinning)</li>
                    <li>● 4 ГБ RAM LPDDR5</li>
                    <li>● 40 ГБ NVMe Direct-IO SSD</li>
                    <li>● Сеть DPDK 1 Gbps</li>
                  </ul>
                </div>
              </div>

              <div className="pricing-plan-card card">
                <div>
                  <h3 style={{ fontSize: '1.2rem', margin: 0 }}>Aegis-Enterprise</h3>
                  <p style={{ color: '#94a3b8', fontSize: '0.8rem', marginTop: '6px' }}>Для крупных систем под нагрузкой</p>
                  <div style={{ fontSize: '2rem', fontWeight: 'bold', color: '#38bdf8', margin: '20px 0' }}>
                    $45.00<span style={{ fontSize: '0.9rem', color: '#64748b' }}>/мес</span>
                  </div>
                  <ul style={{ listStyle: 'none', padding: 0, margin: 0, fontSize: '0.85rem', color: '#94a3b8', display: 'flex', flexDirection: 'column', gap: '8px', textAlign: 'left' }}>
                    <li>● 4 ядра CPU (Pinning)</li>
                    <li>● 8 ГБ RAM LPDDR5</li>
                    <li>● 100 ГБ NVMe Direct-IO SSD</li>
                    <li>● Сеть DPDK 10 Gbps</li>
                  </ul>
                </div>
              </div>

            </div>
          </main>

          <footer style={{ padding: '24px', borderTop: '1px solid rgba(255,255,255,0.05)', textAlign: 'center', fontSize: '0.8rem', color: '#64748b' }}>
            Aegis Cloud Infrastructure Engine. © 2026. Все права защищены.
          </footer>
        </div>
      )}

      {/* Authenticated Client Cabinet */}
      {activeTab === 'cabinet' && (
        <div className="app-layout">
          {/* Mobile Header */}
          <div className="mobile-header">
            <button className="menu-toggle-btn" onClick={() => setSidebarOpen(true)}>
              <Menu size={24} />
            </button>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Layers size={20} color="#5c64ec" />
              <span style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--text-primary)' }}>Aegis Cabinet</span>
            </div>
            <div style={{ width: 24 }}></div>
          </div>

          {/* Sidebar Overlay */}
          <div className={`sidebar-overlay ${sidebarOpen ? 'visible' : ''}`} onClick={() => setSidebarOpen(false)}></div>

          {/* Left Sidebar */}
          <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '0 8px', marginBottom: '8px' }}>
              <Layers size={26} color="#5c64ec" />
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                <span style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.3px' }}>Aegis Cabinet</span>
                <span style={{ fontSize: '0.6rem', color: '#8c93ff', fontWeight: 700, textTransform: 'uppercase', width: 'max-content' }}>CLIENT PORTAL</span>
              </div>
            </div>

            {/* Projects Dropdown */}
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

            {/* Sidebar Navigation */}
            <div className="sidebar-nav">
              <button 
                className={`nav-item ${cabinetTab === 'placeholder' && placeholderTabName === 'AI-агенты' ? 'active' : ''}`}
                onClick={() => handleSelectPlaceholderTab('AI-агенты')}
              >
                <span>AI-агенты</span>
              </button>
              
              <button 
                className={`nav-item ${cabinetTab === 'placeholder' && placeholderTabName === 'App Platform' ? 'active' : ''}`}
                onClick={() => handleSelectPlaceholderTab('App Platform')}
              >
                <span>App Platform</span>
              </button>

              <button 
                className={`nav-item ${cabinetTab === 'placeholder' && placeholderTabName === 'Облако 5 ГГц' ? 'active' : ''}`}
                onClick={() => handleSelectPlaceholderTab('Облако 5 ГГц')}
              >
                <span>Облако 5 ГГц</span>
                <span className="nav-tag tag-new">НОВОЕ</span>
              </button>

              <button 
                className={`nav-item ${cabinetTab === 'placeholder' && placeholderTabName === 'Облачные серверы' ? 'active' : ''}`}
                onClick={() => handleSelectPlaceholderTab('Облачные серверы')}
              >
                <span>Облачные серверы</span>
              </button>

              <button 
                className={`nav-item ${cabinetTab === 'servers' || cabinetTab === 'order' ? 'active' : ''}`}
                onClick={() => { setCabinetTab('servers'); setSidebarOpen(false); }}
              >
                <span>Выделенные серверы</span>
              </button>

              <button 
                className={`nav-item ${cabinetTab === 'placeholder' && placeholderTabName === 'Облако VMware' ? 'active' : ''}`}
                onClick={() => handleSelectPlaceholderTab('Облако VMware')}
              >
                <span>Облако VMware</span>
              </button>

              <button 
                className={`nav-item ${cabinetTab === 'placeholder' && placeholderTabName === 'Мониторинг' ? 'active' : ''}`}
                onClick={() => handleSelectPlaceholderTab('Мониторинг')}
              >
                <span>Мониторинг</span>
                <span className="nav-tag tag-new">НОВОЕ</span>
              </button>

              <button 
                className={`nav-item ${cabinetTab === 'placeholder' && placeholderTabName === 'Базы данных' ? 'active' : ''}`}
                onClick={() => handleSelectPlaceholderTab('Базы данных')}
              >
                <span>Базы данных</span>
              </button>

              <button 
                className={`nav-item ${cabinetTab === 'placeholder' && placeholderTabName === 'Хранилище S3' ? 'active' : ''}`}
                onClick={() => handleSelectPlaceholderTab('Хранилище S3')}
              >
                <span>Хранилище S3</span>
              </button>

              <button 
                className={`nav-item ${cabinetTab === 'placeholder' && placeholderTabName === 'Kubernetes' ? 'active' : ''}`}
                onClick={() => handleSelectPlaceholderTab('Kubernetes')}
              >
                <span>Kubernetes</span>
              </button>

              <button 
                className={`nav-item ${cabinetTab === 'balancers' ? 'active' : ''}`}
                onClick={() => { setCabinetTab('balancers'); setSidebarOpen(false); }}
              >
                <span>Балансировщики</span>
              </button>

              <button 
                className={`nav-item ${cabinetTab === 'placeholder' && placeholderTabName === 'Сети' ? 'active' : ''}`}
                onClick={() => handleSelectPlaceholderTab('Сети')}
              >
                <span>Сети</span>
              </button>

              <button 
                className={`nav-item ${cabinetTab === 'placeholder' && placeholderTabName === 'CDN' ? 'active' : ''}`}
                onClick={() => handleSelectPlaceholderTab('CDN')}
              >
                <span>CDN</span>
                <span className="nav-tag tag-new">НОВОЕ</span>
              </button>

              <button 
                className={`nav-item ${cabinetTab === 'placeholder' && placeholderTabName === 'Сетевые диски' ? 'active' : ''}`}
                onClick={() => handleSelectPlaceholderTab('Сетевые диски')}
              >
                <span>Сетевые диски</span>
              </button>

              <button 
                className={`nav-item ${cabinetTab === 'placeholder' && placeholderTabName === 'Домены и SSL' ? 'active' : ''}`}
                onClick={() => handleSelectPlaceholderTab('Домены и SSL')}
              >
                <span>Домены и SSL</span>
              </button>

              <button 
                className={`nav-item ${cabinetTab === 'placeholder' && placeholderTabName === 'Почта' ? 'active' : ''}`}
                onClick={() => handleSelectPlaceholderTab('Почта')}
              >
                <span>Почта</span>
              </button>

              <button 
                className={`nav-item ${cabinetTab === 'billing' ? 'active' : ''}`}
                onClick={() => { setCabinetTab('billing'); setSidebarOpen(false); }}
              >
                <span>Баланс и платежи</span>
              </button>

              <button 
                className={`nav-item ${cabinetTab === 'aws' ? 'active' : ''}`}
                onClick={() => { setCabinetTab('aws'); setSidebarOpen(false); }}
              >
                <span>AWS Консоль</span>
              </button>

              <button 
                className={`nav-item ${cabinetTab === 'placeholder' && placeholderTabName === 'Уведомления' ? 'active' : ''}`}
                onClick={() => handleSelectPlaceholderTab('Уведомления')}
              >
                <span>Уведомления</span>
              </button>

              <button 
                className={`nav-item ${cabinetTab === 'placeholder' && placeholderTabName === 'Документация' ? 'active' : ''}`}
                onClick={() => handleSelectPlaceholderTab('Документация')}
              >
                <span>Документация</span>
              </button>
            </div>
          </aside>

          {/* Main Content Area */}
          <main className="main-content-layout">
            
            {/* Left/Middle Column (Page Content) */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '24px' }}>
              
              {/* Sleek Top Bar with Wallet & Account */}
              <div style={{
                display: 'flex',
                justifyContent: 'flex-end',
                alignItems: 'center',
                gap: '16px',
                paddingBottom: '16px',
                borderBottom: '1px solid var(--border-color)',
                marginBottom: '10px'
              }}>
                <div style={{ 
                  display: 'flex', 
                  alignItems: 'center', 
                  gap: '10px', 
                  background: 'rgba(255,255,255,0.02)', 
                  padding: '6px 14px', 
                  border: '1px solid var(--border-color)', 
                  borderRadius: '8px',
                  fontSize: '0.85rem' 
                }}>
                  <Wallet size={15} color="#10b981" />
                  <span style={{ color: 'var(--text-secondary)' }}>Баланс:</span>
                  <strong style={{ color: '#10b981', fontFamily: 'monospace', fontSize: '0.9rem' }}>{balance.toFixed(2)} ₽</strong>
                  {billingRate > 0 && (
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                      (-{(billingRate * 3600).toFixed(2)} ₽/ч)
                    </span>
                  )}
                </div>
                
                <button className="btn btn-secondary btn-sm" onClick={() => setShowPaymentModal(true)}>
                  Пополнить
                </button>
                
                <div style={{ 
                  display: 'flex', 
                  alignItems: 'center', 
                  gap: '8px', 
                  borderLeft: '1px solid var(--border-color)', 
                  paddingLeft: '14px', 
                  fontSize: '0.85rem', 
                  color: 'var(--text-secondary)' 
                }}>
                  <User size={16} color="#5c64ec" />
                  <strong>client-01</strong>
                </div>
                
                <button className="btn btn-danger btn-sm" onClick={() => setActiveTab('landing')}>Выйти</button>
              </div>

              {/* TAB 1: Servers List */}
              {cabinetTab === 'servers' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h2 style={{ fontSize: '1.4rem', fontWeight: 700 }}>Выделенные серверы</h2>
                    <button className="btn btn-primary btn-sm" onClick={() => setCabinetTab('order')}>
                      <Plus size={14} /> Заказать сервер
                    </button>
                  </div>

                  {loading ? (
                    <div className="card" style={{ display: 'flex', justifyContent: 'center', padding: '60px' }}>
                      <div className="spinner"></div>
                    </div>
                  ) : vms.length === 0 ? (
                    <div className="card" style={{ textAlign: 'center', padding: '60px', color: '#94a3b8' }}>
                      <p style={{ fontSize: '1.2rem', marginBottom: '16px' }}>У вас пока нет active выделенных серверов.</p>
                      <button className="btn btn-primary" onClick={() => setCabinetTab('order')}>
                        Заказать первый сервер
                      </button>
                    </div>
                  ) : (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '20px' }}>
                      {vms.map(vm => (
                        <div key={vm.name} className="card" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: '220px' }}>
                          <div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                              <div>
                                <h4 style={{ fontSize: '1.1rem', margin: 0, fontWeight: 'bold' }}>{vm.name}</h4>
                                <span style={{ fontSize: '0.7rem', color: '#64748b', textTransform: 'uppercase', fontWeight: 'bold' }}>
                                  {vm.template} OS
                                </span>
                              </div>
                              <span className={`status-badge ${vm.status === 'Running' ? 'running' : 'stopped'}`}>
                                <span className="status-dot"></span>
                                {vm.status === 'Running' ? 'Активен' : 'Выключен'}
                              </span>
                            </div>

                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px', background: 'rgba(0,0,0,0.2)', padding: '10px', margin: '14px 0', fontSize: '0.8rem' }}>
                              <div style={{ textAlign: 'center' }}>
                                <div style={{ fontSize: '0.65rem', color: '#64748b' }}>CPU</div>
                                <strong>{vm.cpu} Cores</strong>
                              </div>
                              <div style={{ textAlign: 'center' }}>
                                <div style={{ fontSize: '0.65rem', color: '#64748b' }}>RAM</div>
                                <strong>{vm.ram} GB</strong>
                              </div>
                              <div style={{ textAlign: 'center' }}>
                                <div style={{ fontSize: '0.65rem', color: '#64748b' }}>SSD</div>
                                <strong>{vm.disk} GB</strong>
                              </div>
                            </div>

                            <div style={{ fontSize: '0.78rem', color: '#94a3b8', display: 'flex', flexDirection: 'column', gap: '4px', fontFamily: 'monospace' }}>
                              <div>IP-адрес: <strong style={{ color: '#38bdf8' }}>{vm.ips && vm.ips[0] ? vm.ips[0] : 'Назначается...'}</strong></div>
                              <div>Пароль: <strong style={{ color: '#f8fafc' }}>{vm.credentials?.password || '••••••••'}</strong></div>
                            </div>
                          </div>

                          <div style={{ display: 'flex', gap: '6px', borderTop: '1px solid var(--border-color)', paddingTop: '14px', marginTop: '14px' }}>
                            {vm.status === 'Running' ? (
                              <>
                                <button className="btn btn-secondary btn-sm" onClick={() => handlePowerAction(vm.name, 'stop')} style={{ flex: 1 }}>
                                  <Square size={12} /> Стоп
                                </button>
                                <button className="btn btn-primary btn-sm" onClick={() => setOpenConsoleName(vm.name)} style={{ flex: 1, color: '#fff' }}>
                                  <Monitor size={12} /> Консоль (VNC)
                                </button>
                              </>
                            ) : (
                              <button className="btn btn-secondary btn-sm" onClick={() => handlePowerAction(vm.name, 'start')} style={{ flex: 1 }}>
                                <Play size={12} /> Запуск
                              </button>
                            )}
                            <button className="btn btn-danger btn-sm" onClick={() => handleDeleteVDS(vm.name)}>
                              <Trash2 size={12} />
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* TAB: AWS Console */}
              {cabinetTab === 'aws' && (
                <AwsConsole mode="client" />
              )}

              {/* TAB 2: Order VDS */}
              {cabinetTab === 'order' && (
                <div className="card" style={{ maxWidth: '600px', margin: '0 auto', width: '100%' }}>
                  <h3 style={{ fontSize: '1.2rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '10px', marginBottom: '16px' }}>
                    Заказ нового VDS сервера
                  </h3>

                  <form onSubmit={handleOrderVDS} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    
                    {/* OS Selector */}
                    <div>
                      <label style={{ display: 'block', fontSize: '0.85rem', color: '#94a3b8', marginBottom: '8px' }}>Шаблон ОС</label>
                      <div className="template-grid">
                        <div className={`template-option ${osType === 'ubuntu' ? 'selected' : ''}`} onClick={() => setOsType('ubuntu')}>
                          <span className="template-icon">🐧</span>
                          <span style={{ fontSize: '0.8rem', fontWeight: 'bold' }}>Ubuntu 24.04</span>
                        </div>
                        <div className={`template-option ${osType === 'windows' ? 'selected' : ''}`} onClick={() => setOsType('windows')}>
                          <span className="template-icon">🪟</span>
                          <span style={{ fontSize: '0.8rem', fontWeight: 'bold' }}>Windows 2022</span>
                        </div>
                        <div className="template-option" onClick={() => alert("Дополнительные дистрибутивы настраиваются администратором хоста во вкладке 'Образы дисков'.")}>
                          <span className="template-icon">💿</span>
                          <span style={{ fontSize: '0.8rem', fontWeight: 'bold' }}>Свои образы</span>
                        </div>
                      </div>
                    </div>

                    {/* Server Name */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                      <label style={{ fontSize: '0.85rem', color: '#94a3b8' }}>Название сервера (латиница)</label>
                      <input 
                        type="text" 
                        className="form-input"
                        value={vdsName}
                        onChange={(e) => setVdsName(e.target.value)}
                        placeholder="my-db-vds"
                        required
                      />
                    </div>

                    {/* CPU Slider */}
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: '#94a3b8', marginBottom: '6px' }}>
                        <span>CPU Ядер</span>
                        <strong style={{ color: '#38bdf8' }}>{cpuCores} Cores</strong>
                      </div>
                      <input 
                        type="range" min="1" max="8" value={cpuCores}
                        onChange={(e) => setCpuCores(parseInt(e.target.value))}
                        style={{ width: '100%', accentColor: '#5c64ec' }}
                      />
                    </div>

                    {/* RAM Slider */}
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: '#94a3b8', marginBottom: '6px' }}>
                        <span>RAM Объём</span>
                        <strong style={{ color: '#38bdf8' }}>{memoryGb} GB</strong>
                      </div>
                      <input 
                        type="range" min="1" max="16" value={memoryGb}
                        onChange={(e) => setMemoryGb(parseInt(e.target.value))}
                        style={{ width: '100%', accentColor: '#5c64ec' }}
                      />
                    </div>

                    {/* SSD Slider */}
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: '#94a3b8', marginBottom: '6px' }}>
                        <span>SSD Диск</span>
                        <strong style={{ color: '#38bdf8' }}>{diskGb} GB</strong>
                      </div>
                      <input 
                        type="range" min="10" max="150" step="10" value={diskGb}
                        onChange={(e) => setDiskGb(parseInt(e.target.value))}
                        style={{ width: '100%', accentColor: '#5c64ec' }}
                      />
                    </div>

                    <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-color)', padding: '12px', fontSize: '0.82rem', color: '#94a3b8' }}>
                      Стоимость аренды: <strong style={{ color: '#10b981' }}>{(cpuCores * 150 + memoryGb * 50 + diskGb * 3).toFixed(0)} ₽ / месяц</strong> <br />
                      Тарификация: <strong style={{ color: '#38bdf8' }}>Посекундное списание (Pay-as-you-go)</strong>
                    </div>

                    <button className="btn btn-primary" type="submit" style={{ padding: '10px' }} disabled={orderingInProgress}>
                      {orderingInProgress ? "Заказ отправлен..." : "Заказать VDS сервер"}
                    </button>
                  </form>
                </div>
              )}

              {/* TAB 3: Billing & Payments */}
              {cabinetTab === 'billing' && (
                <div className="responsive-grid-1-2">
                  
                  {/* Account overview */}
                  <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    <h3 style={{ fontSize: '1.1rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '8px' }}>Кошелек биллинга</h3>
                    
                    <div style={{ background: 'rgba(0,0,0,0.2)', padding: '16px', textAlign: 'center' }}>
                      <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Баланс ЛК</span>
                      <div style={{ fontSize: '2.2rem', fontWeight: 'bold', color: '#10b981', fontFamily: 'monospace', margin: '6px 0' }}>
                        {balance.toFixed(2)} ₽
                      </div>
                      <span style={{ fontSize: '0.7rem', color: '#64748b' }}>Посекундное списание</span>
                    </div>

                    <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                      Текущий расход ресурсов: <strong style={{ color: '#38bdf8' }}>{(billingRate * 3600).toFixed(2)} ₽/час</strong>
                    </div>

                    <button className="btn btn-primary" onClick={() => setShowPaymentModal(true)}>
                      Пополнить баланс
                    </button>
                  </div>

                  {/* Pricing terms explanation */}
                  <div className="card">
                    <h3 style={{ fontSize: '1.1rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '8px', marginBottom: '14px' }}>Правила тарификации Pay-as-you-go</h3>
                    <div style={{ fontSize: '0.85rem', color: '#94a3b8', display: 'flex', flexDirection: 'column', gap: '10px', lineHeight: 1.5 }}>
                      <p>
                        В нашем облаке Aegis Cloud Engine списание средств происходит **посекундно** только за фактически работающие ресурсы серверов.
                      </p>
                      <ul style={{ paddingLeft: '20px' }}>
                        <li>Если сервер **Выключен (Stopped)**, списания за CPU и RAM прекращаются. Вы платите только за хранение SSD-диска.</li>
                        <li>При создании сервера списывается разовый технический сбор за инсталляцию образа (150 ₽).</li>
                        <li>При нулевом балансе все серверы клиента автоматически выключаются во избежание образования задолженности.</li>
                      </ul>
                      <div style={{ background: 'rgba(56,189,248,0.04)', border: '1px solid #38bdf8', padding: '10px', color: '#38bdf8', fontSize: '0.8rem', marginTop: '10px' }}>
                        <strong>Техподдержка:</strong> Для решения вопросов с оплатой обратитесь на support@aegis-cloud.io
                      </div>
                    </div>
                  </div>

                </div>
              )}

              {/* TAB 4: Balancers (Mock Load Balancers Dashboard & Order Form) */}
              {cabinetTab === 'balancers' && (
                <div>
                  
                  {activeBalancerView === 'list' && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <h2 style={{ fontSize: '1.4rem', fontWeight: 700 }}>Балансировщики нагрузки</h2>
                        <button className="btn btn-primary btn-sm" onClick={() => setActiveBalancerView('create')}>
                          <Plus size={14} /> Создать балансировщик
                        </button>
                      </div>

                      {balancers.length === 0 ? (
                        <div className="card" style={{ textAlign: 'center', padding: '60px', color: '#94a3b8' }}>
                          <p style={{ fontSize: '1.2rem', marginBottom: '16px' }}>У вас пока нет активных балансировщиков.</p>
                          <button className="btn btn-primary" onClick={() => setActiveBalancerView('create')}>
                            Создать балансировщик
                          </button>
                        </div>
                      ) : (
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '20px' }}>
                          {balancers.map(lb => (
                            <div key={lb.id} className="card" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: '220px' }}>
                              <div>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                  <div>
                                    <h4 style={{ fontSize: '1.1rem', margin: 0, fontWeight: 'bold' }}>{lb.name}</h4>
                                    <span style={{ fontSize: '0.7rem', color: '#64748b', textTransform: 'uppercase', fontWeight: 'bold' }}>
                                      Регион: {lb.region}
                                    </span>
                                  </div>
                                  <span className={`status-badge ${lb.status === 'Running' ? 'running' : 'pending'}`}>
                                    <span className="status-dot"></span>
                                    {lb.status === 'Running' ? 'Активен' : 'Создание'}
                                  </span>
                                </div>

                                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', margin: '14px 0', padding: '10px', background: 'rgba(0,0,0,0.2)', fontSize: '0.8rem' }}>
                                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                    <span style={{ color: 'var(--text-secondary)' }}>Ноды:</span>
                                    <strong>{lb.nodes} {lb.nodes === 1 ? 'нода' : 'ноды'}</strong>
                                  </div>
                                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                    <span style={{ color: 'var(--text-secondary)' }}>Канал:</span>
                                    <strong>{lb.bandwidth}</strong>
                                  </div>
                                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                    <span style={{ color: 'var(--text-secondary)' }}>Окно обслуж.:</span>
                                    <strong>{lb.maintenance}</strong>
                                  </div>
                                </div>

                                <div style={{ fontSize: '0.78rem', color: '#94a3b8', display: 'flex', flexDirection: 'column', gap: '4px', fontFamily: 'monospace' }}>
                                  <div>Публичный IP: <strong style={{ color: '#38bdf8' }}>{lb.ip}</strong></div>
                                  <div>Тариф: <strong style={{ color: '#f8fafc' }}>{lb.price_month} ₽/мес ({lb.price_hour} ₽/час)</strong></div>
                                </div>
                              </div>

                              <div style={{ display: 'flex', gap: '6px', borderTop: '1px solid var(--border-color)', paddingTop: '14px', marginTop: '14px' }}>
                                <button className="btn btn-secondary btn-sm" style={{ flex: 1 }} onClick={() => alert(`Правила балансировки для ${lb.name} (IP: ${lb.ip}):\n\nPort 80 -> Target Group: client-web-app (Port 8080)\nPort 443 -> Target Group: client-web-app (Port 8443)`)}>
                                  Настройки
                                </button>
                                <button className="btn btn-danger btn-sm" onClick={() => handleDeleteBalancer(lb.id, lb.name)}>
                                  <Trash2 size={12} />
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {activeBalancerView === 'create' && (
                    <div>
                      {/* Back breadcrumb */}
                      <button className="back-button" onClick={() => setActiveBalancerView('list')}>
                        <ChevronLeft size={16} /> Назад
                      </button>
                      
                      <div className="balancer-creation-container">
                        
                        {/* Left Side creation panels */}
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                          <h2 className="balancer-title">Создать балансировщик</h2>
                          
                          {/* SECTION 1: Region */}
                          <div className="section-card">
                            <span className="section-title">1. Регион</span>
                            
                            <div className="regions-grid">
                              {/* Saint Petersburg */}
                              <div className="region-card disabled">
                                <div className="region-header">
                                  <span style={{ fontSize: '1.4rem' }}>🇷🇺</span>
                                  <span className="latency-badge gray">Распродано</span>
                                </div>
                                <div className="region-info">
                                  <span className="region-name">Санкт-Петербург</span>
                                  <span className="region-country">Россия</span>
                                </div>
                              </div>
                              
                              {/* Moscow */}
                              <div 
                                className={`region-card ${selectedRegion === 'moscow' ? 'selected' : ''}`}
                                onClick={() => setSelectedRegion('moscow')}
                              >
                                <div className="region-header">
                                  <span style={{ fontSize: '1.4rem' }}>🇷🇺</span>
                                  <span className="latency-badge green">
                                    <span style={{ width: '5px', height: '5px', borderRadius: '50%', background: '#10b981' }}></span>
                                    48 мсек
                                  </span>
                                </div>
                                <div className="region-info">
                                  <span className="region-name">Москва</span>
                                  <span className="region-country">Россия · MSK-1</span>
                                </div>
                              </div>

                              {/* Amsterdam */}
                              <div 
                                className={`region-card ${selectedRegion === 'amsterdam' ? 'selected' : ''}`}
                                onClick={() => setSelectedRegion('amsterdam')}
                              >
                                <div className="region-header">
                                  <span style={{ fontSize: '1.4rem' }}>🇳🇱</span>
                                  <span className="latency-badge green">
                                    <span style={{ width: '5px', height: '5px', borderRadius: '50%', background: '#10b981' }}></span>
                                    85 мсек
                                  </span>
                                </div>
                                <div className="region-info">
                                  <span className="region-name">Амстердам</span>
                                  <span className="region-country">Нидерланды · AMS-1</span>
                                </div>
                              </div>

                              {/* Frankfurt */}
                              <div 
                                className={`region-card ${selectedRegion === 'frankfurt' ? 'selected' : ''}`}
                                onClick={() => setSelectedRegion('frankfurt')}
                              >
                                <div className="region-header">
                                  <span style={{ fontSize: '1.4rem' }}>🇩🇪</span>
                                  <span className="latency-badge green">
                                    <span style={{ width: '5px', height: '5px', borderRadius: '50%', background: '#10b981' }}></span>
                                    89 мсек
                                  </span>
                                </div>
                                <div className="region-info">
                                  <span className="region-name">Франкфурт</span>
                                  <span className="region-country">Германия · FRA-1</span>
                                </div>
                              </div>

                            </div>
                          </div>

                          {/* SECTION 2: Tariff */}
                          <div className="section-card">
                            <span className="section-title">2. Тариф</span>
                            
                            <div className="tariffs-list">
                              {/* Row 1 */}
                              <div 
                                className={`tariff-row ${selectedTariffId === 1 ? 'selected' : ''}`}
                                onClick={() => setSelectedTariffId(1)}
                              >
                                <span className="tariff-nodes">1 нода</span>
                                <span className="tariff-bandwidth">500 Мбит/с</span>
                                <span className="tariff-price-month">149 ₽/мес</span>
                                <span className="tariff-price-hour">0,2 ₽/час</span>
                              </div>

                              {/* Row 2 */}
                              <div 
                                className={`tariff-row ${selectedTariffId === 2 ? 'selected' : ''}`}
                                onClick={() => setSelectedTariffId(2)}
                              >
                                <span className="tariff-nodes">1 нода</span>
                                <span className="tariff-bandwidth">1000 Мбит/с</span>
                                <span className="tariff-price-month">250 ₽/мес</span>
                                <span className="tariff-price-hour">0,34 ₽/час</span>
                              </div>

                              {/* Row 3 */}
                              <div 
                                className={`tariff-row ${selectedTariffId === 3 ? 'selected' : ''}`}
                                onClick={() => setSelectedTariffId(3)}
                              >
                                <span className="tariff-nodes">2 ноды</span>
                                <span className="tariff-bandwidth">1000 Мбит/с</span>
                                <span className="tariff-price-month">749 ₽/мес</span>
                                <span className="tariff-price-hour">1,02 ₽/час</span>
                              </div>

                            </div>
                            
                            {/* Maintenance window selector */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '10px' }}>
                              <label style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                                Окно обслуживания балансировщика
                                <HelpCircle size={14} style={{ color: 'var(--text-muted)', cursor: 'pointer' }} onClick={() => alert("Время проведения технических регламентов и обновлений ПО балансировщика.")} />
                              </label>
                              <select 
                                className="form-input form-select"
                                value={selectedMaintenance}
                                onChange={(e) => setSelectedMaintenance(e.target.value)}
                                style={{ background: '#161b2a', borderRadius: '8px' }}
                              >
                                <option value="anytime">В любое время</option>
                                <option value="night">Только ночью (с 02:00 до 06:00)</option>
                                <option value="weekend">В выходные дни (Сб-Вс)</option>
                              </select>
                            </div>

                          </div>

                          {/* SECTION 3: Network */}
                          <div className="section-card">
                            <span className="section-title">3. Сеть</span>
                            <div className="info-banner">
                              <Info size={18} className="info-banner-icon" />
                              <span>Приватная сеть нужна, чтобы изолировать ресурсы друг от друга или запретить к ним доступ из интернета</span>
                            </div>
                          </div>

                        </div>

                        {/* Right Pricing Sidebar */}
                        <div className="pricing-sidebar">
                          <span className="pricing-sidebar-title font-bold">Цена</span>
                          
                          {/* Period Selector Tabs */}
                          <div className="period-toggle">
                            <button 
                              className={`period-btn ${pricingPeriod === 'hour' ? 'active' : ''}`}
                              onClick={() => setPricingPeriod('hour')}
                            >
                              Час
                            </button>
                            <button 
                              className={`period-btn ${pricingPeriod === 'day' ? 'active' : ''}`}
                              onClick={() => setPricingPeriod('day')}
                            >
                              День
                            </button>
                            <button 
                              className={`period-btn ${pricingPeriod === 'month' ? 'active' : ''}`}
                              onClick={() => setPricingPeriod('month')}
                            >
                              Мес
                            </button>
                          </div>

                          {/* Pricing breakdown */}
                          <div className="pricing-details">
                            <div className="pricing-detail-row">
                              <span className="pricing-detail-label">Регион</span>
                              <span className="pricing-detail-value">
                                {selectedRegion === 'moscow' ? 'Москва' : selectedRegion === 'amsterdam' ? 'Амстердам' : 'Франкфурт'}
                              </span>
                            </div>
                            <div className="pricing-detail-row">
                              <span className="pricing-detail-label">Ноды</span>
                              <span className="pricing-detail-value">
                                {selectedTariffId === 3 ? 2 : 1}
                              </span>
                            </div>
                            <div className="pricing-detail-row">
                              <span className="pricing-detail-label">Канал</span>
                              <span className="pricing-detail-value">
                                {selectedTariffId === 1 ? '500 Мбит/с' : '1000 Мбит/с'}
                              </span>
                            </div>
                            <div className="pricing-detail-row">
                              <span className="pricing-detail-label">Конфигурация</span>
                              <span className="pricing-detail-value font-mono">
                                {pricingPeriod === 'hour' && `${selectedTariffId === 1 ? '0,20' : selectedTariffId === 2 ? '0,34' : '1,02'} ₽/час`}
                                {pricingPeriod === 'day' && `${selectedTariffId === 1 ? '4,90' : selectedTariffId === 2 ? '8,20' : '24,50'} ₽/день`}
                                {pricingPeriod === 'month' && `${selectedTariffId === 1 ? '149' : selectedTariffId === 2 ? '250' : '749'} ₽/мес`}
                              </span>
                            </div>
                            <div className="pricing-detail-row">
                              <span className="pricing-detail-label">Публичный IP</span>
                              <span className="pricing-detail-value font-mono">
                                {pricingPeriod === 'hour' && '0,24 ₽/час'}
                                {pricingPeriod === 'day' && '5,9 ₽/день'}
                                {pricingPeriod === 'month' && '180 ₽/мес'}
                              </span>
                            </div>
                          </div>

                          {/* Total pricing */}
                          <div className="pricing-total-container">
                            <span className="pricing-total-label">Итого</span>
                            <span className="pricing-total-value font-mono text-xl">
                              {pricingPeriod === 'hour' && `${(selectedTariffId === 1 ? 0.44 : selectedTariffId === 2 ? 0.58 : 1.26).toFixed(2)} ₽/час`}
                              {pricingPeriod === 'day' && `${(selectedTariffId === 1 ? 10.8 : selectedTariffId === 2 ? 14.1 : 30.4).toFixed(1)} ₽/день`}
                              {pricingPeriod === 'month' && `${(selectedTariffId === 1 ? 329 : selectedTariffId === 2 ? 430 : 929)} ₽/мес`}
                            </span>
                          </div>

                          {/* Action button */}
                          <div className="action-buttons-group">
                            <button className="order-btn" onClick={handleOrderBalancer} disabled={orderingInProgress}>
                              {orderingInProgress ? "Секунду..." : "Заказать"}
                            </button>
                            <button className="terminal-icon-btn" onClick={() => setShowTerminalModal(true)}>
                              <Terminal size={18} />
                            </button>
                          </div>

                          <span className="pricing-discount-text">
                            Скидки до 10% — при пополнении сразу на несколько месяцев
                          </span>

                        </div>

                      </div>
                    </div>
                  )}

                </div>
              )}

              {/* TAB 5: Placeholder for features not in demo */}
              {cabinetTab === 'placeholder' && (
                <div className="card" style={{ padding: '40px', textAlign: 'center', maxWidth: '600px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '20px', width: '100%' }}>
                  <Globe size={48} style={{ color: 'var(--primary)', margin: '0 auto', opacity: 0.8 }} />
                  <h3 style={{ fontSize: '1.3rem', fontWeight: 'bold' }}>Раздел "{placeholderTabName}" в разработке</h3>
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', lineHeight: 1.6 }}>
                    В рамках демонстрационной версии **Aegis Cloud Engine** этот раздел пока закрыт. 
                    Вы можете опробовать работу других, полностью интерактивных разделов платформы:
                  </p>
                  
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', justifyContent: 'center', marginTop: '10px' }}>
                    <button className="btn btn-secondary btn-sm" onClick={() => setCabinetTab('servers')}>
                      Выделенные серверы
                    </button>
                    <button className="btn btn-secondary btn-sm" onClick={() => { setCabinetTab('balancers'); setActiveBalancerView('create'); }}>
                      Балансировщики
                    </button>
                    <button className="btn btn-secondary btn-sm" onClick={() => setCabinetTab('aws')}>
                      AWS Консоль
                    </button>
                    <button className="btn btn-secondary btn-sm" onClick={() => setCabinetTab('billing')}>
                      Баланс и платежи
                    </button>
                  </div>
                </div>
              )}

            </div>
          </main>
        </div>
      )}

      {/* VNC Console Modal */}
      {openConsoleName && (
        <ClientVncConsole 
          name={openConsoleName}
          username="root"
          password={vms.find(v => v.name === openConsoleName)?.credentials?.password || ''}
          ips={vms.find(v => v.name === openConsoleName)?.ips || []}
        />
      )}

      {/* Mock Payment Modal */}
      {showPaymentModal && (
        <div className="console-modal-backdrop">
          <div className="card" style={{ width: '400px', maxWidth: '90vw', background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: '12px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '10px', marginBottom: '16px' }}>
              <h3 style={{ fontSize: '1.1rem', margin: 0 }}>Пополнение счета (Mock Pay)</h3>
              <button className="btn btn-secondary btn-sm" onClick={() => setShowPaymentModal(false)}>
                <X size={14} />
              </button>
            </div>

            <form onSubmit={handlePaymentSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Сумма пополнения (RUB)</label>
                <input 
                  type="number" 
                  min="100" 
                  max="10000"
                  className="form-input" 
                  value={paymentAmount}
                  onChange={(e) => setPaymentAmount(e.target.value)}
                  required 
                />
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Номер карты (Тест)</label>
                <input 
                  type="text" 
                  className="form-input" 
                  placeholder="4000 1234 5678 9010" 
                  defaultValue="4000 1234 5678 9010"
                  disabled
                />
              </div>

              <button className="btn btn-primary" type="submit" style={{ padding: '10px', marginTop: '10px', borderRadius: '8px' }}>
                Оплатить {parseFloat(paymentAmount || 0).toFixed(2)} ₽
              </button>
            </form>
          </div>
        </div>
      )}

      {/* IaC & API Terminal Modal */}
      {showTerminalModal && (
        <div className="console-modal-backdrop">
          <div className="card" style={{ width: '600px', maxWidth: '90vw', background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: '12px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '10px', marginBottom: '16px' }}>
              <h3 style={{ fontSize: '1.1rem', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Terminal size={18} color="#5c64ec" />
                <span>Интеграция API и Terraform</span>
              </h3>
              <button className="btn btn-secondary btn-sm" onClick={() => setShowTerminalModal(false)}>
                <X size={14} />
              </button>
            </div>

            <div style={{ fontSize: '0.85rem', color: '#94a3b8', marginBottom: '16px', lineHeight: 1.4 }}>
              Вы можете управлять инфраструктурой Aegis Cloud Engine автоматически. 
              Ниже приведены примеры для развертывания выбранного балансировщика.
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <strong style={{ fontSize: '0.82rem', color: '#f8fafc' }}>Terraform (aegis.tf):</strong>
              <pre style={{
                background: '#0a0d16',
                border: '1px solid var(--border-color)',
                padding: '12px',
                borderRadius: '8px',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.78rem',
                color: '#38bdf8',
                overflowX: 'auto',
                margin: 0
              }}>
{`resource "aegis_load_balancer" "lb_${selectedRegion}" {
  name        = "balancer-${selectedRegion}"
  region      = "${selectedRegion === 'moscow' ? 'ru-msk-1' : selectedRegion === 'amsterdam' ? 'nl-ams-1' : 'de-fra-1'}"
  nodes_count = ${selectedTariffId === 3 ? 2 : 1}
  bandwidth   = ${selectedTariffId === 1 ? 500 : 1000}
  maintenance = "${selectedMaintenance}"
}`}
              </pre>

              <strong style={{ fontSize: '0.82rem', color: '#f8fafc', marginTop: '8px' }}>cURL API запрос:</strong>
              <pre style={{
                background: '#0a0d16',
                border: '1px solid var(--border-color)',
                padding: '12px',
                borderRadius: '8px',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.78rem',
                color: '#10b981',
                overflowX: 'auto',
                margin: 0
              }}>
{`curl -X POST https://api.aegis-cloud.io/v1/balancers \\
  -H "Authorization: Bearer \${AEGIS_API_TOKEN}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "balancer-${selectedRegion}",
    "region": "${selectedRegion === 'moscow' ? 'ru-msk-1' : selectedRegion === 'amsterdam' ? 'nl-ams-1' : 'de-fra-1'}",
    "nodes_count": ${selectedTariffId === 3 ? 2 : 1},
    "bandwidth_mbps": ${selectedTariffId === 1 ? 500 : 1000},
    "maintenance_window": "${selectedMaintenance}"
  }'`}
              </pre>
            </div>

            <button className="btn btn-secondary" style={{ width: '100%', marginTop: '20px', borderRadius: '8px' }} onClick={() => setShowTerminalModal(false)}>
              Закрыть окно
            </button>
          </div>
        </div>
      )}

    </div>
  );
};

export default App;

