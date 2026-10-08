import React, { useState } from 'react';
import { Settings, X, AlertTriangle } from 'lucide-react';
import DiskStorageNotice from './DiskStorageNotice';
import { quantityGi, settingsError } from '../utils/vmSettings';

const VMEditModal = ({ vm, onClose, onSaveSuccess }) => {
  const [cpuCores, setCpuCores] = useState(vm.cpu_cores);
  const currentRamGb = vm.memory_gb || quantityGi(vm.memory, 2);
  const currentDiskGb = vm.disk_gb || quantityGi(vm.disks?.[0]?.size, 20);

  const [memoryGb, setMemoryGb] = useState(currentRamGb);
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
          disk_gb: currentDiskGb
        })
      });

      if (!response.ok) {
        throw new Error(await settingsError(response, 'Не удалось сохранить настройки.'));
      }

      alert('Настройки обновлены. Для применения CPU/RAM полностью остановите ВМ и запустите её снова.');
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
            borderRadius: 'var(--radius-md)',
            fontSize: '0.8rem',
            color: 'var(--warning)',
            alignItems: 'flex-start'
          }}>
            <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: '2px' }} />
            <div>
              Для применения CPU/RAM полностью остановите ВМ и запустите её снова.
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
              <span>Системный диск</span>
              <span className="slider-value">{currentDiskGb} GB</span>
            </div>
            <DiskStorageNotice />
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
