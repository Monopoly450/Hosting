import React from 'react';

export default function DiskStorageNotice() {
  return (
    <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: '8px 0 0', lineHeight: 1.6 }}>
      Нужно больше места? Зайдите в раздел «Сетевые диски», создайте диск нужного
      размера и подключите его к этой ВМ. Это дополнительный диск; размер
      системного диска не изменится.
    </p>
  );
}
