import React, { useState, useEffect, useRef } from 'react';
import { ChevronDown } from 'lucide-react';

export default function CustomSelect({ value, onChange, options, placeholder = 'Выберите значение', className = '', style = {}, disabled = false }) {
    const [isOpen, setIsOpen] = useState(false);
    const containerRef = useRef(null);

    const selectedOption = options.find(opt => String(opt.value) === String(value));
    const displayLabel = selectedOption ? selectedOption.label : placeholder;

    useEffect(() => {
        const handleClickOutside = (event) => {
            if (containerRef.current && !containerRef.current.contains(event.target)) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const handleSelect = (val) => {
        if (disabled) return;
        onChange({ target: { value: val } });
        setIsOpen(false);
    };

    return (
        <div 
            className={`custom-select-container ${className}`} 
            ref={containerRef}
            style={{ position: 'relative', width: '100%', ...style }}
        >
            <button
                type="button"
                className="custom-select-trigger form-control"
                onClick={() => !disabled && setIsOpen(!isOpen)}
                disabled={disabled}
                style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    cursor: disabled ? 'not-allowed' : 'pointer',
                    textAlign: 'left',
                    width: '100%',
                    opacity: disabled ? 0.6 : 1
                }}
            >
                <span>{displayLabel}</span>
                <ChevronDown size={16} style={{ 
                    opacity: 0.7, 
                    transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
                    transition: 'transform 0.2s ease'
                }} />
            </button>
            
            {isOpen && (
                <ul className="custom-select-options">
                    {options.map((opt) => (
                        <li
                            key={opt.value}
                            className={`custom-select-option ${String(opt.value) === String(value) ? 'selected' : ''} ${opt.disabled ? 'disabled' : ''}`}
                            onClick={() => !opt.disabled && handleSelect(opt.value)}
                            style={{
                                cursor: opt.disabled ? 'not-allowed' : 'pointer',
                                opacity: opt.disabled ? 0.5 : 1
                            }}
                        >
                            {opt.label}
                        </li>
                    ))}
                    {options.length === 0 && (
                        <li className="custom-select-option text-muted" style={{ pointerEvents: 'none' }}>
                            Нет доступных вариантов
                        </li>
                    )}
                </ul>
            )}
        </div>
    );
}
