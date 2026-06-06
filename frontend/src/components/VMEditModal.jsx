import React, { useState } from 'react';
import { Settings, X, RefreshCw, AlertTriangle } from 'lucide-react';

const VMEditModal = ({ vm, onClose, onSaveSuccess }) => {
  const [cpuCores, setCpuCores] = useState(vm.cpu_cores);
  // Парсим текущие RAM и Disk в числа (например "2Gi" -> 2, "30Gi" -> 30)
  const currentRamGb = parseInt(vm.memory) || 2;
  const currentDiskGb = vm.disks && vm.disks[0] ? parseInt(vm.disks[0].size) || 20 : 20;

  const [memoryGb, setMemoryGb] = useState(currentRamGb);
  const [diskGb, setDiskGb] = useState(currentDiskGb);
  const [saving, setSaving] = useState(false);

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const response = await fetch(`/api/vms/${vm.name}/resize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cpu_cores: parseInt(cpuCores),
          memory_gb: parseInt(memoryGb),
          disk_gb: parseInt(diskGb)
        })
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Не удалось сохранить настройки.');
      }

      alert('Настройки успешно обновлены! Изменения CPU и RAM вступят в силу после перезапуска виртуалки.');
      onSaveSuccess();
      onClose();
    } catch (err) {
      alert(`Ошибка настройки ресурсов: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="console-modal-backdrop">
      <div className="console-container" style={{ maxWidth: '500px' }}>
        <div className="console-header">
          <div className="console-title">
            <Settings className="logo-icon" size={20} />
            <span>Настройка ресурсов: <strong>{vm.name}</strong></span>
          </div>
          <button className="btn btn-danger btn-icon-only btn-sm" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSave} style={{ padding: '24px', display: 'flex', flexType: 'column', flexDirection: 'column', gap: '20px' }}>
          
          {/* Предупреждение о перезапуске */}
          <div style={{
            display: 'flex',
            gap: '10px',
            padding: '12px',
            background: 'rgba(245, 158, 11, 0.1)',
            border: '1px solid rgba(245, 158, 11, 0.25)',
            borderRadius: '8px',
            fontSize: '0.8rem',
            color: 'var(--warning)',
            alignItems: 'flex-start'
          }}>
            <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: '2px' }} />
            <div>
              Изменения ядер CPU и оперативной памяти требуют перезагрузки виртуальной машины.
              <strong> Уменьшение размера диска невозможно.</strong>
            </div>
          </div>

          {/* CPU */}
          <div className="slider-container">
            <div className="slider-header">
              <span>CPU Cores</span>
              <span className="slider-value">{cpuCores} Cores</span>
            </div>
            <input 
              type="range" 
              min="1" 
              max="8" 
              className="range-input"
              value={cpuCores}
              onChange={(e) => setCpuCores(parseInt(e.target.value))}
              disabled={saving}
            />
          </div>

          {/* RAM */}
          <div className="slider-container">
            <div className="slider-header">
              <span>Оперативная память (RAM)</span>
              <span className="slider-value">{memoryGb} GB</span>
            </div>
            <input 
              type="range" 
              min="1" 
              max="32" 
              className="range-input"
              value={memoryGb}
              onChange={(e) => setMemoryGb(parseInt(e.target.value))}
              disabled={saving}
            />
          </div>

          {/* Disk */}
          <div className="slider-container">
            <div className="slider-header">
              <span>Объем системного диска (NVMe/SSD)</span>
              <span className="slider-value">{diskGb} GB</span>
            </div>
            <input 
              type="range" 
              min={currentDiskGb} // Уменьшить нельзя, ползунок начинается от текущего размера!
              max="200" 
              step="10"
              className="range-input"
              value={diskGb}
              onChange={(e) => setDiskGb(parseInt(e.target.value))}
              disabled={saving}
            />
            <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
              Текущий размер диска: {currentDiskGb} GB. Можно только увеличить.
            </span>
          </div>

          <div style={{ display: 'flex', gap: '12px', marginTop: '10px' }}>
            <button 
              type="button" 
              className="btn btn-secondary" 
              style={{ flex: 1 }}
              onClick={onClose}
              disabled={saving}
            >
              Отмена
            </button>
            <button 
              type="submit" 
              className="btn btn-primary" 
              style={{ flex: 1 }}
              disabled={saving}
            >
              {saving ? <span className="spinner" style={{ width: '14px', height: '14px', borderWidth: '2px' }} /> : 'Сохранить'}
            </button>
          </div>

        </form>
      </div>
    </div>
  );
};

export default VMEditModal;
