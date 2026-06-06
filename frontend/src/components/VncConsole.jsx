import React, { useEffect, useRef, useState } from 'react';
import RFB from '@novnc/novnc';
import { X, RefreshCw, AlertCircle, Monitor } from 'lucide-react';

const VncConsole = ({ name, password, onClose }) => {
  const canvasContainerRef = useRef(null);
  const rfbRef = useRef(null);
  const [status, setStatus] = useState('connecting'); // 'connecting' | 'connected' | 'disconnected' | 'error'
  const [errorMsg, setErrorMsg] = useState('');

  useEffect(() => {
    // Ждем, пока смонтируется DOM
    if (!canvasContainerRef.current) return;

    // Определяем URL вебсокета
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/vnc/${name}`;
    
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
          setTimeout(processNext, 15);
        }, 15);
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
        setTimeout(processNext, 15);
      }, 15);
    };
    
    processNext();
  };

  return (
    <div className="console-modal-backdrop">
      <div className="console-container">
        <div className="console-header">
          <div className="console-title">
            <Monitor className="logo-icon" size={20} />
            <span>Консоль управления VM: <strong>{name}</strong></span>
          </div>
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            {status === 'connected' && (
              <>
                {password && (
                  <button 
                    className="btn btn-primary btn-sm" 
                    onClick={() => sendString(password + "\n")}
                    title="Ввести сгенерированный пароль посимвольно"
                  >
                    Вставить пароль
                  </button>
                )}
                <div style={{ display: 'flex', alignItems: 'center', gap: '5px', borderLeft: '1px solid var(--border-color)', paddingLeft: '10px', marginRight: '5px' }}>
                  <input
                    type="text"
                    placeholder="Вставить текст..."
                    id="vnc-type-input"
                    className="form-control form-control-sm"
                    style={{ width: '130px', height: '28px', padding: '2px 8px', fontSize: '0.8rem', background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        const val = e.target.value;
                        if (val) {
                          sendString(val + "\n");
                          e.target.value = '';
                        }
                      }
                    }}
                  />
                  <button 
                    className="btn btn-secondary btn-sm"
                    style={{ height: '28px', padding: '0 8px', fontSize: '0.8rem' }}
                    onClick={() => {
                      const input = document.getElementById('vnc-type-input');
                      if (input && input.value) {
                        sendString(input.value + "\n");
                        input.value = '';
                      }
                    }}
                  >
                    Ввести
                  </button>
                </div>
                <button className="btn btn-secondary btn-sm" onClick={handleSendCtrlAltDel}>
                  Ctrl+Alt+Del
                </button>
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
