import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';

/* Ручка на правой кромке боковой панели: тянешь — панель шире или уже.

   Ширина уезжает в CSS-переменную на <html>, а не в inline-стиль <aside>:
   так её видит и мобильный блок стилей (который эту переменную намеренно
   игнорирует — там панель работает выезжающей шторкой), и любое правило,
   которому в будущем понадобится знать, сколько места занято слева. */

export const STORAGE_KEY = 'aegis.sidebarWidth';
export const DEFAULT_WIDTH = 280;
/* Нижняя граница — не вкусовая: замер по всем пунктам меню показал, что
   первая ширина, на которой ни один не обрезается, — 248px («Двухфакторная
   защита», «Бэкапы по расписанию», «Контейнерный реестр», «Серверы и
   Инстансы» упираются раньше всех). 252 — тот же порог с запасом на другую
   метрику шрифта: Inter может не подгрузиться, и подстановочный шрифт шире.
   Верхняя граница ограничивает не панель, а то, что от неё остаётся
   контенту. */
export const MIN_WIDTH = 252;
export const MAX_WIDTH = 460;
const STEP = 16;

export const clampWidth = (px) => Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(px)));

/* Хранилище недоступно в приватном режиме Safari и при отключённых cookie —
   там обращение к нему бросает исключение, а не возвращает null. */
const safeStorage = () => {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null;
  } catch {
    return null;
  }
};

export function readWidth(storage) {
  try {
    const raw = storage && storage.getItem(STORAGE_KEY);
    if (raw === null || raw === undefined || raw === '') return DEFAULT_WIDTH;
    const px = Number(raw);
    return Number.isFinite(px) ? clampWidth(px) : DEFAULT_WIDTH;
  } catch {
    return DEFAULT_WIDTH;
  }
}

export function writeWidth(storage, px) {
  try {
    if (storage) storage.setItem(STORAGE_KEY, String(px));
  } catch {
    /* Ширина панели не стоит того, чтобы падать из-за переполненной квоты. */
  }
}

export default function SidebarResizer() {
  const [width, setWidth] = useState(() => readWidth(safeStorage()));
  const handleRef = useRef(null);
  const dragging = useRef(false);
  const widthRef = useRef(width);

  /* useLayoutEffect, а не useEffect: переменную надо выставить до отрисовки,
     иначе на каждой загрузке страницы панель успевает моргнуть дефолтными
     280px и только потом прыгнуть на сохранённую ширину. */
  useLayoutEffect(() => {
    widthRef.current = width;
    document.documentElement.style.setProperty('--sidebar-width', `${width}px`);
  }, [width]);

  const stopDrag = useCallback(() => {
    if (!dragging.current) return;
    dragging.current = false;
    document.body.classList.remove('resizing-sidebar');
    /* Пишем один раз в конце, а не на каждый pointermove: иначе за одно
       протаскивание в хранилище улетают сотни записей. */
    writeWidth(safeStorage(), widthRef.current);
  }, []);

  /* Кнопку могут размонтировать посреди перетаскивания (переход на мобильную
     ширину прячет ручку) — класс на body тогда останется навсегда, и вся
     страница застынет с курсором col-resize. */
  useEffect(() => stopDrag, [stopDrag]);

  const onPointerDown = (e) => {
    e.preventDefault();
    dragging.current = true;
    document.body.classList.add('resizing-sidebar');
    if (e.currentTarget.setPointerCapture) e.currentTarget.setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e) => {
    if (!dragging.current) return;
    /* Считаем от левого края самой панели, а не от края окна: так ручка не
       разъедется, если у раскладки когда-нибудь появится внешний отступ. */
    const panel = handleRef.current && handleRef.current.parentElement;
    const left = panel ? panel.getBoundingClientRect().left : 0;
    setWidth(clampWidth(e.clientX - left));
  };

  const onPointerUp = (e) => {
    if (e.currentTarget.releasePointerCapture && e.currentTarget.hasPointerCapture?.(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    stopDrag();
  };

  const nudge = (px) => {
    const next = clampWidth(px);
    setWidth(next);
    writeWidth(safeStorage(), next);
  };

  const onKeyDown = (e) => {
    const keys = {
      ArrowLeft: () => nudge(widthRef.current - STEP),
      ArrowRight: () => nudge(widthRef.current + STEP),
      Home: () => nudge(MIN_WIDTH),
      End: () => nudge(MAX_WIDTH),
    };
    const act = keys[e.key];
    if (!act) return;
    e.preventDefault();
    act();
  };

  return (
    <div
      ref={handleRef}
      className="sidebar-resizer"
      role="separator"
      aria-orientation="vertical"
      aria-label="Ширина боковой панели"
      aria-valuenow={width}
      aria-valuemin={MIN_WIDTH}
      aria-valuemax={MAX_WIDTH}
      tabIndex={0}
      title="Потяните, чтобы изменить ширину. Двойной клик — вернуть исходную"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onDoubleClick={() => nudge(DEFAULT_WIDTH)}
      onKeyDown={onKeyDown}
    />
  );
}
