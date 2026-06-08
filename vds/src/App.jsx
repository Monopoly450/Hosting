import React, { useState, useEffect, useRef } from 'react';
import { 
  Layers, Plus, Activity, Terminal, Shield, FolderOpen, LayoutDashboard, 
  Play, Square, Trash2, Key, HelpCircle, User, DollarSign, Wallet, Monitor, X, AlertCircle, RefreshCw, Cloud
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
    const wsUrl = `${protocol}//${window.location.host}/api/vnc/${name}`;
    
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
  const [cabinetTab, setCabinetTab] = useState('servers'); // 'servers' | 'order' | 'billing'
  
  // VDS Lists & Balance
  const [vms, setVms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [balance, setBalance] = useState(50.0); // Default user balance
  const [billingRate, setBillingRate] = useState(0.0); // Cost/sec
  
  // Modals
  const [openConsoleName, setOpenConsoleName] = useState(null);
  const [showPaymentModal, setShowPaymentModal] = useState(false);
  const [paymentAmount, setPaymentAmount] = useState('20');
  const [orderingInProgress, setOrderingInProgress] = useState(false);

  // VDS Configuration state
  const [vdsName, setVdsName] = useState('');
  const [osType, setOsType] = useState('ubuntu'); // 'ubuntu' | 'windows'
  const [cpuCores, setCpuCores] = useState(2);
  const [memoryGb, setMemoryGb] = useState(4);
  const [diskGb, setDiskGb] = useState(30);

  useEffect(() => {
    if (activeTab === 'cabinet') {
      fetchVDS();
      const interval = setInterval(fetchVDS, 5000);
      return () => clearInterval(interval);
    }
  }, [activeTab]);

  // Pay-as-you-go ticker loop in frontend
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

  // Recalculate billing rate based on running servers
  useEffect(() => {
    let rate = 0;
    vms.forEach(vm => {
      if (vm.status === 'Running') {
        // Mock client pricing: 1 core = $0.00003/sec, 1GB RAM = $0.00001/sec, 1GB SSD = $0.0000001/sec
        rate += vm.cpu * 0.00003 + vm.ram * 0.00001 + vm.disk * 0.0000001;
      }
    });
    setBillingRate(rate);
  }, [vms]);

  const fetchVDS = async () => {
    try {
      const response = await fetch('/api/vms');
      if (response.ok) {
        const data = await response.json();
        // Filter VDS: only client-created servers or template-based vms for client demonstration
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
    const costPerHour = cpuCores * 0.1 + memoryGb * 0.04 + diskGb * 0.002;
    
    if (balance < 5.0) {
      alert("Недостаточно средств. Минимальный баланс для заказа сервера — $5.00. Пожалуйста, пополните счет во вкладке 'Оплата'.");
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
      
      // Deduct setup fee from balance
      setBalance(prev => prev - 2.50); // $2.50 setup fee
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
    alert(`Счет успешно пополнен на $${amt.toFixed(2)}!`);
  };

  return (
    <div className="cabinet-container">
      
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
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '24px', maxWidth: '1000px', width: '100%', marginTop: '80px' }}>
              
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
        <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
          
          {/* Cabinet Header */}
          <header className="header">
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <Layers size={22} color="#38bdf8" />
              <strong style={{ fontSize: '1.1rem', color: '#f8fafc' }}>Aegis Cabinet</strong>
              <span style={{ fontSize: '0.65rem', background: 'rgba(56,189,248,0.1)', color: '#38bdf8', border: '1px solid rgba(56,189,248,0.2)', padding: '2px 6px' }}>CLIENT PORTAL</span>
            </div>

            <div style={{ display: 'flex', gap: '14px', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', background: 'rgba(255,255,255,0.02)', padding: '6px 12px', border: '1px solid var(--border-color)', fontSize: '0.85rem' }}>
                <Wallet size={14} color="#10b981" />
                <span>Баланс: <strong style={{ color: '#10b981', fontFamily: 'monospace' }}>${balance.toFixed(4)}</strong></span>
              </div>
              <button className="btn btn-secondary btn-sm" onClick={() => setShowPaymentModal(true)}>
                Пополнить
              </button>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', borderLeft: '1px solid var(--border-color)', paddingLeft: '14px', fontSize: '0.85rem', color: '#94a3b8' }}>
                <User size={16} />
                <span>client-01</span>
              </div>
              <button className="btn btn-danger btn-sm" onClick={() => setActiveTab('landing')}>Выйти</button>
            </div>
          </header>

          <div className="main-content" style={{ display: 'grid', gridTemplateColumns: '250px 1fr', gap: '30px' }}>
            
            {/* Sidebar Navigation */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <button 
                className={`btn btn-secondary`} 
                onClick={() => setCabinetTab('servers')}
                style={{ 
                  justifyContent: 'flex-start', 
                  background: cabinetTab === 'servers' ? 'rgba(56, 189, 248, 0.08)' : 'transparent',
                  borderColor: cabinetTab === 'servers' ? '#38bdf8' : 'transparent',
                  color: cabinetTab === 'servers' ? '#38bdf8' : '#94a3b8'
                }}
              >
                <Activity size={16} />
                Мои VDS серверы
              </button>
              
              <button 
                className={`btn btn-secondary`} 
                onClick={() => setCabinetTab('aws')}
                style={{ 
                  justifyContent: 'flex-start', 
                  background: cabinetTab === 'aws' ? 'rgba(56, 189, 248, 0.08)' : 'transparent',
                  borderColor: cabinetTab === 'aws' ? '#38bdf8' : 'transparent',
                  color: cabinetTab === 'aws' ? '#38bdf8' : '#94a3b8'
                }}
              >
                <Cloud size={16} />
                AWS Консоль
              </button>
              
              <button 
                className={`btn btn-secondary`} 
                onClick={() => setCabinetTab('order')}
                style={{ 
                  justifyContent: 'flex-start', 
                  background: cabinetTab === 'order' ? 'rgba(56, 189, 248, 0.08)' : 'transparent',
                  borderColor: cabinetTab === 'order' ? '#38bdf8' : 'transparent',
                  color: cabinetTab === 'order' ? '#38bdf8' : '#94a3b8'
                }}
              >
                <Plus size={16} />
                Заказать VDS
              </button>

              <button 
                className={`btn btn-secondary`} 
                onClick={() => setCabinetTab('billing')}
                style={{ 
                  justifyContent: 'flex-start', 
                  background: cabinetTab === 'billing' ? 'rgba(56, 189, 248, 0.08)' : 'transparent',
                  borderColor: cabinetTab === 'billing' ? '#38bdf8' : 'transparent',
                  color: cabinetTab === 'billing' ? '#38bdf8' : '#94a3b8'
                }}
              >
                <DollarSign size={16} />
                Оплата и Баланс
              </button>
            </div>

            {/* Cabinet Page Content */}
            <div>
              
              {/* TAB 1: Servers List */}
              {cabinetTab === 'servers' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h2 style={{ fontSize: '1.3rem', fontWeight: 'bold' }}>Ваши виртуальные серверы</h2>
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
                      <p style={{ fontSize: '1.2rem', marginBottom: '16px' }}>У вас пока нет активных VDS серверов.</p>
                      <button className="btn btn-primary" onClick={() => setCabinetTab('order')}>
                        Заказать первый сервер
                      </button>
                    </div>
                  ) : (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(350px, 1fr))', gap: '20px' }}>
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
                                <button className="btn btn-primary btn-sm" onClick={() => setOpenConsoleName(vm.name)} style={{ flex: 1, color: '#000' }}>
                                  <Monitor size={12} /> Экран (VNC)
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
                <div className="card" style={{ maxWidth: '600px', margin: '0 auto' }}>
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
                        style={{ width: '100%', accentColor: '#38bdf8' }}
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
                        style={{ width: '100%', accentColor: '#38bdf8' }}
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
                        style={{ width: '100%', accentColor: '#38bdf8' }}
                      />
                    </div>

                    <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-color)', padding: '12px', fontSize: '0.82rem', color: '#94a3b8' }}>
                      Стоимость аренды: <strong style={{ color: '#10b981' }}>${(cpuCores * 0.1 + memoryGb * 0.04 + diskGb * 0.002).toFixed(2)} / месяц</strong> <br />
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
                <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1.8fr', gap: '24px' }}>
                  
                  {/* Account overview */}
                  <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    <h3 style={{ fontSize: '1.1rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '8px' }}>Кошелек биллинга</h3>
                    
                    <div style={{ background: 'rgba(0,0,0,0.2)', padding: '16px', textAlign: 'center' }}>
                      <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Баланс ЛК</span>
                      <div style={{ fontSize: '2.2rem', fontWeight: 'bold', color: '#10b981', fontFamily: 'monospace', margin: '6px 0' }}>
                        ${balance.toFixed(4)}
                      </div>
                      <span style={{ fontSize: '0.7rem', color: '#64748b' }}>Посекундное списание</span>
                    </div>

                    <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                      Текущий расход ресурсов: <strong style={{ color: '#38bdf8' }}>${(billingRate * 3600).toFixed(4)}/час</strong>
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
                        <li>При создании сервера списывается разовый технический сбор за инсталляцию образа ($2.50).</li>
                        <li>При нулевом балансе все серверы клиента автоматически выключаются во избежание образования задолженности.</li>
                      </ul>
                      <div style={{ background: 'rgba(56,189,248,0.04)', border: '1px solid #38bdf8', padding: '10px', color: '#38bdf8', fontSize: '0.8rem', marginTop: '10px' }}>
                        <strong>Техподдержка:</strong> Для решения вопросов с оплатой обратитесь на support@aegis-cloud.io
                      </div>
                    </div>
                  </div>

                </div>
              )}

            </div>
          </div>
        </div>
      )}

      {/* VNC Console Modal */}
      {openConsoleName && (
        <ClientVncConsole 
          name={openConsoleName}
          username="root"
          password={vms.find(v => v.name === openConsoleName)?.credentials?.password || ''}
          ips={vms.find(v => v.name === openConsoleName)?.ips || []}
          onClose={() => setOpenConsoleName(null)}
        />
      )}

      {/* Mock Payment Modal */}
      {showPaymentModal && (
        <div className="console-modal-backdrop">
          <div className="card" style={{ width: '400px', background: 'var(--bg-secondary)', border: '1px solid var(--border-color)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-color)', paddingBottom: '10px', marginBottom: '16px' }}>
              <h3 style={{ fontSize: '1.1rem', margin: 0 }}>Пополнение счета (Mock Pay)</h3>
              <button className="btn btn-secondary btn-sm" onClick={() => setShowPaymentModal(false)}>
                <X size={14} />
              </button>
            </div>

            <form onSubmit={handlePaymentSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Сумма пополнения (USD)</label>
                <input 
                  type="number" 
                  min="5" 
                  max="500"
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

              <button className="btn btn-primary" type="submit" style={{ padding: '10px', marginTop: '10px' }}>
                Оплатить ${parseFloat(paymentAmount || 0).toFixed(2)}
              </button>
            </form>
          </div>
        </div>
      )}

    </div>
  );
};

export default App;
