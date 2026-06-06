import React, { useEffect, useState } from 'react';
import { HardDrive, Upload, Trash2, CheckCircle, AlertCircle, RefreshCw } from 'lucide-react';

const ImageManager = ({ onImagesChanged }) => {
  const [images, setImages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [dragActive, setDragActive] = useState(false);

  const fetchImages = async () => {
    try {
      const response = await fetch('/api/images');
      if (!response.ok) throw new Error('Failed to fetch images');
      const data = await response.json();
      setImages(data);
      if (onImagesChanged) onImagesChanged(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchImages();
  }, []);

  const handleDelete = async (filename) => {
    if (!confirm(`Вы действительно хотите удалить образ "${filename}"?`)) return;
    try {
      const response = await fetch(`/api/images/${filename}`, {
        method: 'DELETE'
      });
      if (!response.ok) throw new Error('Delete failed');
      fetchImages();
    } catch (err) {
      alert(`Ошибка удаления: ${err.message}`);
    }
  };

  const uploadFile = (file) => {
    if (!file) return;
    
    // Проверка разрешений
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['qcow2', 'img', 'iso', 'raw'].includes(ext)) {
      alert('Недопустимый формат файла. Разрешены только: .qcow2, .img, .iso, .raw');
      return;
    }

    setUploading(true);
    setUploadProgress(0);

    const formData = new FormData();
    formData.append('file', file);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/images/upload', true);

    // Слушатель прогресса загрузки
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        const percentComplete = Math.round((event.loaded / event.total) * 100);
        setUploadProgress(percentComplete);
      }
    };

    xhr.onload = () => {
      setUploading(false);
      if (xhr.status === 201 || xhr.status === 200) {
        fetchImages();
      } else {
        let errMessage = 'Ошибка загрузки образа на сервер.';
        try {
          const res = JSON.parse(xhr.responseText);
          errMessage = res.detail || errMessage;
        } catch(e) {}
        alert(errMessage);
      }
    };

    xhr.onerror = () => {
      setUploading(false);
      alert('Сетевая ошибка при загрузке файла.');
    };

    xhr.send(formData);
  };

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      uploadFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileInput = (e) => {
    if (e.target.files && e.target.files[0]) {
      uploadFile(e.target.files[0]);
    }
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '30px' }} className="image-manager-container">
      {/* Сетка колонок на десктопе */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '20px' }}>
        
        {/* Загрузчик файлов */}
        <div className="card">
          <div className="card-title">
            <Upload className="logo-icon" size={20} />
            <span>Загрузить образ операционной системы (.qcow2 / .img / .iso)</span>
          </div>

          <div 
            style={{
              border: `2px dashed ${dragActive ? 'var(--primary)' : 'var(--border-color)'}`,
              borderRadius: '0px',
              padding: '40px',
              textAlign: 'center',
              cursor: 'pointer',
              background: dragActive ? 'rgba(0, 168, 255, 0.05)' : 'rgba(0, 0, 0, 0.15)',
              transition: 'all 0.2s ease',
              position: 'relative',
              overflow: 'hidden'
            }}
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
            onClick={() => document.getElementById('file-upload-input').click()}
          >
            <input 
              id="file-upload-input" 
              type="file" 
              style={{ display: 'none' }} 
              onChange={handleFileInput}
              disabled={uploading}
            />

            {!uploading ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
                <Upload size={36} color="var(--primary)" />
                <p style={{ fontWeight: 600 }}>Перетащите файл сюда или кликните для выбора</p>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  Поддерживаются форматы: QCOW2 (рекомендуется для Linux), IMG, ISO (для Windows), RAW
                </p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '15px' }}>
                <div className="spinner"></div>
                <p style={{ fontWeight: 600 }}>Загрузка файла образа на сервер...</p>
                <div style={{ width: '100%', maxWidth: '300px' }}>
                  <div className="progress-bar-bg" style={{ height: '6px', marginBottom: '8px' }}>
                    <div 
                      className="progress-bar-fill primary"
                      style={{ width: `${uploadProgress}%` }}
                    />
                  </div>
                  <span className="slider-value" style={{ fontSize: '0.8rem' }}>{uploadProgress}%</span>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Список образов */}
        <div className="card">
          <div className="card-title" style={{ justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <HardDrive className="logo-icon" size={20} />
              <span>Хранилище кастомных образов</span>
            </div>
            <button className="btn btn-secondary btn-sm" onClick={fetchImages} disabled={loading}>
              <RefreshCw size={12} className={loading ? 'spinner' : ''} />
            </button>
          </div>

          {loading && images.length === 0 ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: '30px' }}>
              <div className="spinner"></div>
            </div>
          ) : images.length === 0 ? (
            <div style={{ padding: '30px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.9rem' }}>
              Нет загруженных файлов. Загрузите образ выше, чтобы использовать его.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {images.map((img) => (
                <div 
                  key={img.filename}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '16px',
                    borderRadius: '0px',
                    background: 'rgba(255, 255, 255, 0.02)',
                    border: '1px solid var(--border-color)'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <span style={{ fontSize: '1.5rem' }}>{img.extension === 'iso' ? '💿' : '💾'}</span>
                    <div>
                      <div style={{ fontWeight: 600, color: 'var(--text-primary)', wordBreak: 'break-all' }}>{img.filename}</div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        Размер: {img.size_gb > 1 ? `${img.size_gb} GB` : `${img.size_mb} MB`} | Тип: {img.extension.toUpperCase()}
                      </div>
                    </div>
                  </div>
                  <button 
                    className="btn btn-danger btn-sm btn-icon-only"
                    onClick={() => handleDelete(img.filename)}
                    title="Удалить образ"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

      </div>
    </div>
  );
};

export default ImageManager;
