import React, { useEffect, useRef, useState } from 'react';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';
import { AlertCircle, RefreshCw } from 'lucide-react';

const SshTerminal = ({ name, isInline = false }) => {
  const terminalRef = useRef(null);
  const xtermRef = useRef(null);
  const socketRef = useRef(null);
  const fitAddonRef = useRef(null);
  const [status, setStatus] = useState('connecting'); // 'connecting' | 'connected' | 'disconnected' | 'error'
  const [errorMsg, setErrorMsg] = useState('');

  useEffect(() => {
    if (!terminalRef.current) return;

    // Инициализируем Xterm
    const term = new Terminal({
      cursorBlink: true,
      theme: {
        // Литералы, а не var(--terminal-*): xterm рисует на canvas и CSS-переменную
        // не разрешит. Значения совпадают с токенами --terminal-bg/--terminal-fg.
        background: '#0b0f19',
        foreground: '#f8fafc',
        cursor: '#38bdf8',
        selectionBackground: 'rgba(56, 189, 248, 0.3)',
      },
      fontSize: 14,
      fontFamily: 'Consolas, Monaco, "Andale Mono", "Ubuntu Mono", monospace',
    });
    xtermRef.current = term;

    // Подключаем FitAddon
    const fitAddon = new FitAddon();
    fitAddonRef.current = fitAddon;
    term.loadAddon(fitAddon);

    term.open(terminalRef.current);
    
    // Небольшая задержка перед fit(), чтобы элемент успел полностью отобразиться и вычислить размеры
    const fitTimeout = setTimeout(() => {
      try {
        fitAddon.fit();
      } catch (e) {
        console.error('Fit error:', e);
      }
    }, 100);

    // Вебсокет для SSH
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const token = localStorage.getItem('aegis_admin_token') || 'aegis-admin-secret-key-2026';
    const wsUrl = `${protocol}//${window.location.host}/api/ssh-terminal/${name}?token=${encodeURIComponent(token)}`;

    const socket = new WebSocket(wsUrl);
    socketRef.current = socket;
    socket.binaryType = 'arraybuffer';

    socket.onopen = () => {
      setStatus('connected');
      term.focus();
      // Отправляем начальные размеры
      try {
        const dims = fitAddon.proposeDimensions();
        if (dims) {
          socket.send(JSON.stringify({
            type: 'resize',
            cols: dims.cols,
            rows: dims.rows
          }));
        }
      } catch (e) {
        console.error('Error proposing dimensions:', e);
      }
    };

    socket.onmessage = (event) => {
      if (typeof event.data === 'string') {
        term.write(event.data);
      } else {
        const bytes = new Uint8Array(event.data);
        term.write(bytes);
      }
    };

    socket.onclose = (event) => {
      if (event.code === 1008) {
        setStatus('error');
        setErrorMsg('Ошибка авторизации. Доступ к терминалу заблокирован.');
      } else if (event.code === 1011) {
        setStatus('error');
        setErrorMsg(event.reason || 'Ошибка подключения по SSH на стороне сервера.');
      } else {
        setStatus('disconnected');
      }
    };

    socket.onerror = () => {
      setStatus('error');
      setErrorMsg('Не удалось подключиться к вебсокету терминала.');
    };

    // Ввод пользователя -> WebSocket
    const onDataDisposable = term.onData((data) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(data);
      }
    });

    // Обработчик изменения размеров
    const handleResize = () => {
      try {
        fitAddon.fit();
        const dims = fitAddon.proposeDimensions();
        if (dims && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({
            type: 'resize',
            cols: dims.cols,
            rows: dims.rows
          }));
        }
      } catch (err) {
        console.error('Resize error:', err);
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      clearTimeout(fitTimeout);
      window.removeEventListener('resize', handleResize);
      onDataDisposable.dispose();
      term.dispose();
      if (socket) {
        socket.close();
      }
    };
  }, [name]);

  const handleReconnect = () => {
    setStatus('connecting');
    setErrorMsg('');
    // Простой триггер перезапуска websocket сессии: пересоздание компонента
    window.location.reload();
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: isInline ? '360px' : '520px', background: 'var(--terminal-bg)', borderRadius: 'var(--radius-md)', position: 'relative', overflow: 'hidden', border: '1px solid var(--border-subtle)' }}>
      <style>{`
        @keyframes terminal-spin {
          to { transform: rotate(360deg); }
        }
        .term-spinner {
          animation: terminal-spin 1s linear infinite;
        }
        .xterm {
          padding: 8px;
          height: 100%;
        }
        .xterm-viewport {
          background-color: #0b0f19 !important;
        }
      `}</style>

      {status === 'connecting' && (
        <div style={{ position: 'absolute', inset: 0, background: 'rgba(11, 15, 25, 0.85)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', zIndex: 10 }}>
          <RefreshCw size={24} className="term-spinner" style={{ marginBottom: '12px', color: 'var(--accent)' }} />
          <span style={{ fontSize: '0.95rem' }}>Установка безопасного SSH соединения...</span>
        </div>
      )}
      
      {status === 'error' && (
        <div style={{ position: 'absolute', inset: 0, background: 'rgba(11, 15, 25, 0.98)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#f87171', zIndex: 10, padding: '24px', textAlign: 'center' }}>
          <AlertCircle size={36} style={{ marginBottom: '16px' }} />
          <span style={{ fontWeight: 600, fontSize: '1.1rem', marginBottom: '8px', color: '#fca5a5' }}>Ошибка сессии терминала</span>
          <span style={{ fontSize: '0.9rem', color: '#94a3b8', marginBottom: '20px', maxWidth: '400px' }}>{errorMsg}</span>
          <button className="btn btn-secondary" onClick={handleReconnect} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 16px', borderRadius: 'var(--radius-sm)' }}>
            <RefreshCw size={14} /> Переподключиться
          </button>
        </div>
      )}

      {status === 'disconnected' && (
        <div style={{ position: 'absolute', inset: 0, background: 'rgba(11, 15, 25, 0.9)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', zIndex: 10 }}>
          <span style={{ marginBottom: '16px', fontSize: '1rem' }}>SSH сессия была завершена удаленным хостом.</span>
          <button className="btn btn-secondary" onClick={handleReconnect} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 16px', borderRadius: 'var(--radius-sm)' }}>
            <RefreshCw size={14} /> Запустить новый сеанс
          </button>
        </div>
      )}

      <div ref={terminalRef} style={{ flex: 1, minHeight: 0, height: '100%' }} />
    </div>
  );
};

export default SshTerminal;
