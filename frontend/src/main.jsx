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
      ...options.headers,
      'X-Admin-Token': token
    };
  }
  const response = await originalFetch(url, options);
  if (response.status === 401 && !options._skipAuthRedirect && localStorage.getItem('aegis_admin_token')) {
    localStorage.removeItem('aegis_admin_token');
    window.location.reload();
  }
  return response;
};

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
