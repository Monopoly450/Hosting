import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'

// Глобальный перехватчик fetch для авторизации в API
const originalFetch = window.fetch;
window.fetch = async (url, options = {}) => {
  const token = localStorage.getItem('aegis_admin_token') || 'aegis-admin-secret-key-2026';
  if (token) {
    options.headers = {
      ...options.headers,
      'X-Admin-Token': token
    };
  }
  const response = await originalFetch(url, options);
  if (response.status === 401 && !options._skipAuthRedirect) {
    window.dispatchEvent(new CustomEvent('aegis-auth-error'));
  }
  return response;
};

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
