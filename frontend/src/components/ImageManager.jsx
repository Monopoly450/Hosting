import React, { useEffect, useState } from 'react';
import { HardDrive, Upload, Trash2, RefreshCw } from 'lucide-react';

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
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: '24px' }}>
      
      {/* Upload Zone */}
      <div className="glass-card" style={{ display: 'flex', flexDirection: 'column' }}>
        <h3 className="section-title">
          <Upload size={18} /> Загрузить новый ISO / QCOW2
        </h3>
        
        <div 
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            alignItems: 'center',
            border: `2px dashed ${dragActive ? 'var(--accent-primary)' : 'var(--border-subtle)'}`,
            borderRadius: 'var(--radius-lg)',
            padding: '40px 24px',
            textAlign: 'center',
            cursor: 'pointer',
            background: dragActive ? 'rgba(56, 189, 248, 0.05)' : 'var(--bg-body)',
            transition: 'all 0.2s ease'
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
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
              <div style={{ padding: '16px', background: 'var(--bg-surface)', borderRadius: '50%', boxShadow: 'var(--shadow-sm)' }}>
                <Upload size={32} color="var(--accent-primary)" />
              </div>
              <div>
                <p style={{ fontWeight: 600, fontSize: '1.05rem', margin: '0 0 4px', color: 'var(--text-heading)' }}>
                  Перетащите файл сюда
                </p>
                <p className="text-muted" style={{ margin: 0, fontSize: '0.85rem' }}>или кликните для выбора с диска</p>
              </div>
              <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', background: 'var(--bg-surface)', padding: '6px 12px', borderRadius: 'var(--radius-pill)', border: '1px solid var(--border-subtle)' }}>
                Поддерживаются: .qcow2, .img, .iso, .raw
              </p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px', width: '100%', maxWidth: '280px' }}>
              <div className="spinner" style={{ width: '28px', height: '28px', borderWidth: '3px' }} />
              <div style={{ textAlign: 'center' }}>
                <p style={{ fontWeight: 600, margin: '0 0 4px', color: 'var(--text-heading)' }}>Загрузка образа...</p>
                <p className="text-muted" style={{ margin: 0, fontSize: '0.85rem' }}>Пожалуйста, подождите</p>
              </div>
              <div style={{ width: '100%' }}>
                <div className="progress-track" style={{ height: '6px', marginBottom: '8px' }}>
                  <div className="progress-fill primary" style={{ width: `${uploadProgress}%` }} />
                </div>
                <div style={{ textAlign: 'right', fontSize: '0.8rem', fontWeight: 600 }}>{uploadProgress}%</div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Image List */}
      <div className="glass-card" style={{ display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
          <h3 className="section-title" style={{ margin: 0 }}>
            <HardDrive size={18} /> Хранилище образов
          </h3>
          <button className="btn btn-secondary btn-icon" onClick={fetchImages} disabled={loading}>
            <RefreshCw size={14} className={loading ? 'spinner' : ''} />
          </button>
        </div>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto', maxHeight: '400px', paddingRight: '8px' }}>
          {loading && images.length === 0 ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}><span className="spinner" /></div>
          ) : images.length === 0 ? (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
              <HardDrive size={32} style={{ margin: '0 auto 12px', opacity: 0.5 }} />
              <p>Нет загруженных образов</p>
            </div>
          ) : (
            images.map((img) => (
              <div key={img.filename} className="interactive" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px', background: 'var(--bg-surface)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                  <div style={{ fontSize: '1.8rem' }}>{img.extension === 'iso' ? '💿' : '💾'}</div>
                  <div>
                    <div style={{ fontWeight: 600, color: 'var(--text-heading)', wordBreak: 'break-all', marginBottom: '4px' }}>{img.filename}</div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      Размер: <span style={{ fontWeight: 500, color: 'var(--text-secondary)' }}>{img.size_gb > 1 ? `${img.size_gb} GB` : `${img.size_mb} MB`}</span>
                      <span style={{ margin: '0 8px', color: 'var(--border-subtle)' }}>|</span>
                      Тип: <span style={{ fontWeight: 500, color: 'var(--text-secondary)' }}>{img.extension.toUpperCase()}</span>
                    </div>
                  </div>
                </div>
                <button className="btn btn-danger btn-icon" onClick={() => handleDelete(img.filename)} title="Удалить образ">
                  <Trash2 size={14} />
                </button>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

export default ImageManager;
