import React, { useEffect, useRef, useState } from 'react';
import RFB from '@novnc/novnc';
import { X, RefreshCw, AlertCircle, Monitor } from 'lucide-react';

const VncConsole = ({ name, username, password, onClose, isInline = false }) => {
  const canvasContainerRef = useRef(null);
  const rfbRef = useRef(null);
  const [status, setStatus] = useState('connecting'); // 'connecting' | 'connected' | 'disconnected' | 'error'
  const [errorMsg, setErrorMsg] = useState('');

  useEffect(() => {
    // Ждем, пока смонтируется DOM
    if (!canvasContainerRef.current) return;

    // Определяем URL вебсокета
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const token = localStorage.getItem('aegis_admin_token') || 'aegis-admin-secret-key-2026';
    const wsUrl = `${protocol}//${window.location.host}/api/vnc/${name}?token=${encodeURIComponent(token)}`;
    
    console.log(`Connecting to VNC WebSocket: ${wsUrl}`);

    try {
      // Инициализируем noVNC RFB клиент
      const rfb = new RFB(canvasContainerRef.current, wsUrl, {
        wsProtocols: ['binary']
      });

      rfbRef.current = rfb;

      // Слушатели событий noVNC
      rfb.addEventListener('connect', () => {
        console.log('VNC Connected successfully');
        setStatus('connected');
        rfb.focus(); // Даем фокус для клавиатурного ввода
        
        // Автоматический вход (после небольшой паузы, чтобы экран отрисовался)
        if (username && password) {
          console.log(`Starting autologin for user: ${username}`);
          setTimeout(() => {
            sendString(username + "\n");
            setTimeout(() => {
              sendString(password + "\n");
            }, 1000);
          }, 1800);
        }
      });

      rfb.addEventListener('disconnect', (e) => {
        console.log('VNC Disconnected:', e);
        if (e.detail.clean) {
          setStatus('disconnected');
        } else {
          setStatus('error');
          setErrorMsg('Соединение было разорвано API-сервером.');
        }
      });

      rfb.addEventListener('credentialsrequired', () => {
        // Нам не требуется пароль для самого VNC, так как KubeVirt защищает сессию на уровне API K8s
        rfb.sendCredentials({ password: '' });
      });

      // Авто-масштабирование под размер контейнера
      rfb.scaleViewport = true;
      rfb.resizeSession = true;

    } catch (err) {
      console.error('Failed to create noVNC instance:', err);
      setStatus('error');
      setErrorMsg(err.message || 'Ошибка инициализации RFB-клиента.');
    }

    // Очистка при размонтировании
    return () => {
      if (rfbRef.current) {
        rfbRef.current.disconnect();
        rfbRef.current = null;
      }
    };
  }, [name]);

  const handleSendCtrlAltDel = () => {
    if (rfbRef.current && status === 'connected') {
      rfbRef.current.sendCtrlAltDel();
    }
  };

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
      
      // Проверяем, требует ли символ зажатого Shift
      const needsShift = /[A-Z!@#$%^&*()_+{}:"<>?~|]/.test(char);
      
      if (needsShift) {
        rfbRef.current.sendKey(XK_Shift_L, "ShiftLeft", true);
      }
      
      // Добавим микро-паузу между нажатием и отпусканием клавиши, чтобы VM успела зарегистрировать нажатие
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

  const handleAutoLogin = () => {
    if (!rfbRef.current || status !== 'connected') return;
    rfbRef.current.focus();
    sendString((username || 'root') + "\n");
    setTimeout(() => {
      sendString(password + "\n");
    }, 1000);
  };

  const [copiedField, setCopiedField] = useState(null);

  const handleCopy = (text, field) => {
    navigator.clipboard.writeText(text);
    setCopiedField(field);
    setTimeout(() => setCopiedField(null), 2000);
  };

  if (isInline) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0', flex: 1, minHeight: '400px' }}>
        <div style={{ display: 'flex', gap: '16px', alignItems: 'center', justifyContent: 'flex-start', background: 'var(--terminal-bg)', padding: '12px 16px', borderBottom: '1px solid var(--terminal-border)', flexWrap: 'wrap' }}>
          {status === 'connected' ? (
            <>
              <button className="btn btn-primary btn-sm" onClick={handleSendCtrlAltDel} type="button" style={{ height: '28px' }}>
                Ctrl+Alt+Del
              </button>
              <div style={{ display: 'flex', gap: '16px', color: '#f8fafc', alignItems: 'center', flexWrap: 'wrap', fontSize: '0.85rem' }}>
                <span style={{ color: '#94a3b8' }}>Консоль управления</span>
              </div>
            </>
          ) : (
            <span style={{ fontSize: '0.85rem', color: '#94a3b8' }}>Ожидание подключения к экрану...</span>
          )}
        </div>

        <div className="console-canvas-container" style={{ flex: 1, minHeight: '450px', background: '#000000', display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
          <div 
            ref={canvasContainerRef} 
            id="vnc-canvas"
            style={{ width: '100%', height: '450px', display: status === 'connected' ? 'block' : 'none' }}
          />

          {status !== 'connected' && (
            <div className="console-status-overlay">
              {status === 'connecting' && (
                <>
                  <div className="spinner"></div>
                  <p style={{ fontSize: '0.85rem' }}>Подключение к VNC консоли виртуальной машины...</p>
                </>
              )}
              {status === 'disconnected' && (
                <>
                  <AlertCircle size={32} color="var(--text-secondary)" />
                  <p style={{ fontSize: '0.85rem' }}>Консоль отключена.</p>
                </>
              )}
              {status === 'error' && (
                <>
                  <AlertCircle size={32} color="var(--danger)" />
                  <p style={{ color: 'var(--danger)', fontWeight: 600, fontSize: '0.85rem' }}>Ошибка подключения к консоли</p>
                  <p style={{ fontSize: '0.75rem', opacity: 0.8 }}>{errorMsg || 'Убедитесь, что виртуалка запущена и KVM включен.'}</p>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="console-modal-backdrop">
      <div className="console-container">
        <div className="console-header">
          <div className="console-title">
            <Monitor className="logo-icon" size={20} />
            <span>Консоль управления VM: <strong>{name}</strong></span>
          </div>
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
            {status === 'connected' && (
              <>
                <button className="btn btn-secondary btn-sm" onClick={handleSendCtrlAltDel}>
                  Ctrl+Alt+Del
                </button>
                <div style={{ fontSize: '0.78rem', display: 'flex', gap: '8px', borderLeft: '1px solid var(--border-color)', paddingLeft: '10px', color: '#fff', alignItems: 'center' }}>
                  <span>Логин: <strong style={{ color: 'var(--primary)' }}>{username}</strong></span>
                  <span>Пароль: <strong style={{ fontFamily: 'var(--font-mono)', color: 'var(--primary)' }}>{password}</strong></span>
                </div>
              </>
            )}
            <button className="btn btn-danger btn-icon-only btn-sm" onClick={onClose} title="Закрыть консоль">
              <X size={16} />
            </button>
          </div>
        </div>
        
        <div className="console-canvas-container">
          {/* Контейнер в который noVNC вставит canvas */}
          <div 
            ref={canvasContainerRef} 
            id="vnc-canvas"
            style={{ width: '100%', height: '600px', display: status === 'connected' ? 'block' : 'none' }}
          />

          {status !== 'connected' && (
            <div className="console-status-overlay">
              {status === 'connecting' && (
                <>
                  <div className="spinner"></div>
                  <p>Подключение к VNC консоли виртуальной машины...</p>
                </>
              )}
              {status === 'disconnected' && (
                <>
                  <AlertCircle size={48} color="var(--text-secondary)" />
                  <p>Консоль отключена.</p>
                </>
              )}
              {status === 'error' && (
                <>
                  <AlertCircle size={48} color="var(--danger)" />
                  <p style={{ color: 'var(--danger)', fontWeight: 600 }}>Ошибка подключения к консоли</p>
                  <p style={{ fontSize: '0.9rem', opacity: 0.8 }}>{errorMsg || 'Убедитесь, что виртуалка запущена и KVM включен.'}</p>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default VncConsole;
