import React from 'react';
import { networkDiskState } from '../utils/networkDisks';

export default function NetworkDiskStatus({ volume }) {
    const state = networkDiskState(volume);
    return (
        <>
            <span className={`status-badge ${state.active ? 'status-active' : 'status-pending'}`}>
                {state.label}
            </span>
            {state.note && (
                <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: '6px' }}>
                    {state.note}
                </div>
            )}
        </>
    );
}
