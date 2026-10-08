export function creationName(value) {
  const name = String(value ?? '').trim().toLowerCase();
  if (name.length > 63 || !/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(name)) {
    throw new Error('Имя: 1–63 символа, латинские буквы, цифры и дефис; начало и конец — буква или цифра.');
  }
  return name;
}

export function supportsCreationCloudInit(osType) {
  return !['windows', 'proxmox', 'truenas'].includes(String(osType).trim().toLowerCase());
}

export function vmCreationPayload(vm) {
  const payload = { ...vm };
  // Keep Linux drafts in the form, but never send hidden cloud-init fields
  // when the user switches to an ISO-installed OS.
  if (!supportsCreationCloudInit(vm.os_type)) {
    for (const field of ['packages', 'network_drives', 'ssh_key', 'custom_user_data', 'cloud_init_template']) {
      delete payload[field];
    }
  }
  return payload;
}

const labels = {
  name: 'Имя', os_type: 'ОС', cpu_cores: 'CPU', memory_gb: 'RAM', disk_gb: 'Системный диск',
  packages: 'Пакеты', network_drives: 'Сетевые диски', ssh_key: 'SSH-ключ',
  custom_user_data: 'Cloud-Init', iso_url: 'Образ', custom_image: 'Кастомный образ',
};

export function creationError(detail, fallback = 'Не удалось создать ВМ.') {
  if (typeof detail === 'string') return detail;
  if (!Array.isArray(detail)) return fallback;
  return detail.map(error => {
    const loc = error.loc || [];
    const field = labels[loc.at(-1)] || 'Настройки';
    const index = loc.indexOf('vms');
    const prefix = index >= 0 && typeof loc[index + 1] === 'number' ? `ВМ ${loc[index + 1] + 1} · ` : '';
    const message = (error.msg || 'Некорректное значение').replace(/^Value error, /, '');
    return `${prefix}${field}: ${message}`;
  }).join('\n') || fallback;
}
