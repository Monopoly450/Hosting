export function quantityGi(value, fallback) {
  const match = String(value ?? '').match(/^(\d+(?:\.\d+)?)(Ki|Mi|Gi|Ti|K|M|G|T)?$/);
  if (!match) return fallback;
  const factors = { Ki: 1024, Mi: 1024 ** 2, Gi: 1024 ** 3, Ti: 1024 ** 4,
    K: 1000, M: 1000 ** 2, G: 1000 ** 3, T: 1000 ** 4 };
  return Math.max(1, Math.ceil(Number(match[1]) * (factors[match[2]] ?? 1) / 1024 ** 3));
}

export function initializeVmSettings(ref, vmName, data, apply) {
  if (ref.current === vmName) return false;
  apply(data);
  ref.current = vmName;
  return true;
}

export async function settingsError(response, fallback) {
  try {
    const data = await response.json();
    if (typeof data.detail === 'string') return data.detail;
    if (Array.isArray(data.detail)) return data.detail.map(item => item.msg).filter(Boolean).join('; ') || fallback;
  } catch { /* Прокси может вернуть HTML вместо JSON. */ }
  return fallback;
}
