import React from 'react';
import { supportsCreationCloudInit } from '../utils/vmCreation';

export default function CreationCloudInitFields({ osType, children }) {
    if (supportsCreationCloudInit(osType)) return <>{children}</>;
    if (osType !== 'truenas') return null;
    return (
        <div className="alert alert-info">
            TrueNAS устанавливается из ISO через VNC. Настройки дисков, сети и SSH
            задаются после установки в интерфейсе TrueNAS; поля Linux Cloud-Init здесь не применяются.
        </div>
    );
}
