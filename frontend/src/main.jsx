import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'

// Глобальный перехватчик fetch для авторизации в API
const originalFetch = window.fetch;
window.fetch = async (url, options = {}) => {
  const token = localStorage.getItem('aegis_admin_token') || '';
  if (token) {
    options.headers = {
      ...options.headers
    };
    if (token.includes('.')) {
      // Это JWT-подобный токен сессии
      options.headers['Authorization'] = `Bearer ${token}`;
    } else {
      // Это обратная совместимость со старым X-Admin-Token
      options.headers['X-Admin-Token'] = token;
    }
  }
  const response = await originalFetch(url, options);
  if (response.status === 401 && !options._skipAuthRedirect && localStorage.getItem('aegis_admin_token')) {
    localStorage.removeItem('aegis_admin_token');
    localStorage.removeItem('aegis_role');
    localStorage.removeItem('aegis_username');
    window.location.reload();
  }
  return response;
};

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
