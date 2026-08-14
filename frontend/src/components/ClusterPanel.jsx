import React, { useState, useEffect } from 'react';
import { Layers, Plus, Server, Activity, ArrowRight, X, Trash, Info, ChevronDown, ChevronUp, HardDrive, Cpu, Package, Key } from 'lucide-react';
import Portal from './Portal';
import CustomSelect from './CustomSelect';

const OS_VERSIONS = {
  ubuntu: [
    { label: 'Ubuntu 24.04 LTS', value: 'https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img' },
    { label: 'Ubuntu 22.04 LTS', value: 'https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img' },
    { label: 'Ubuntu 20.04 LTS', value: 'https://cloud-images.ubuntu.com/focal/current/focal-server-cloudimg-amd64.img' }
  ],
  centos: [
    { label: 'CentOS Stream 9', value: 'https://cloud.centos.org/centos/9-stream/x86_64/images/CentOS-Stream-GenericCloud-9-latest.x86_64.qcow2' },
    { label: 'CentOS Stream 10', value: 'https://cloud.centos.org/centos/10-stream/x86_64/images/CentOS-Stream-GenericCloud-10-latest.x86_64.qcow2' }
  ],
  debian: [
    { label: 'Debian 12 (Bookworm)', value: 'https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2' },
    { label: 'Debian 11 (Bullseye)', value: 'https://cloud.debian.org/images/cloud/bullseye/latest/debian-11-generic-amd64.qcow2' }
  ],
  windows: [
    { label: 'Windows Server 2022', value: 'https://go.microsoft.com/fwlink/p/?LinkID=2195280' },
    { label: 'Windows Server 2019', value: 'https://go.microsoft.com/fwlink/p/?LinkID=2195279' },
    { label: 'Windows Server 2016', value: 'https://go.microsoft.com/fwlink/p/?LinkID=2195278' }
  ],
  proxmox: [
    { label: 'Proxmox VE 9.2', value: 'https://enterprise.proxmox.com/iso/proxmox-ve_9.2-1.iso' },
    { label: 'Proxmox VE 8.2', value: 'https://enterprise.proxmox.com/iso/proxmox-ve_8.2-1.iso' },
    { label: 'Proxmox VE 8.1', value: 'https://enterprise.proxmox.com/iso/proxmox-ve_8.1-1.iso' },
    { label: 'Proxmox VE 7.4', value: 'https://enterprise.proxmox.com/iso/proxmox-ve_7.4-1.iso' }
  ],
  bitrix: [
    { label: 'BitrixVM (CentOS 9)', value: 'https://cloud.centos.org/centos/9-stream/x86_64/images/CentOS-Stream-GenericCloud-9-latest.x86_64.qcow2' }
  ],
  almalinux: [
    { label: 'AlmaLinux 9', value: 'https://repo.almalinux.org/almalinux/9/cloud/x86_64/images/AlmaLinux-9-GenericCloud-latest.x86_64.qcow2' },
    { label: 'AlmaLinux 8', value: 'https://repo.almalinux.org/almalinux/8/cloud/x86_64/images/AlmaLinux-8-GenericCloud-latest.x86_64.qcow2' }
  ],
  rocky: [
    { label: 'Rocky Linux 9', value: 'https://download.rockylinux.org/pub/rocky/9/images/x86_64/Rocky-9-GenericCloud.latest.x86_64.qcow2' },
    { label: 'Rocky Linux 8', value: 'https://download.rockylinux.org/pub/rocky/8/images/x86_64/Rocky-8-GenericCloud.latest.x86_64.qcow2' }
  ],
  fedora: [
    { label: 'Fedora 41', value: 'https://download.fedoraproject.org/pub/fedora/linux/releases/41/Cloud/x86_64/images/Fedora-Cloud-Base-Generic-41-1.4.x86_64.qcow2' }
  ],
  opensuse: [
    { label: 'openSUSE Leap 15.6', value: 'https://download.opensuse.org/repositories/Cloud:/Images:/Leap_15.6/images/openSUSE-Leap-15.6.x86_64-NoCloud.qcow2' }
  ],
  arch: [
    { label: 'Arch Linux (latest)', value: 'https://geo.mirror.pkgbuild.com/images/latest/Arch-Linux-x86_64-cloudimg.qcow2' }
  ],
  alpine: [
    { label: 'Alpine Linux 3.21', value: 'https://dl-cdn.alpinelinux.org/alpine/v3.21/releases/cloud/generic_alpine-3.21.3-x86_64-bios-cloudinit-r0.qcow2' }
  ],
  truenas: [
    { label: 'TrueNAS SCALE 24.04', value: 'https://download.truenas.com/TrueNAS-SCALE-Dragonfish/24.04.2.5/TrueNAS-SCALE-24.04.2.5.iso' }
  ]
};

// Запасной список — только на случай, если /api/vms/os-catalog не ответил.
// В обычной работе список приходит с бэкенда: он там один на всю систему и
// уже отфильтрован по совместимости с выбранной ОС.
const CLUSTER_TEMPLATE_FALLBACK = [
  { value: 'lamp', label: 'LAMP (Apache + PHP + MariaDB)' },
  { value: 'lemp', label: 'LEMP (Nginx + PHP-FPM + MariaDB)' },
  { value: 'docker', label: 'Docker (Engine + Compose)' },
  { value: 'portainer', label: 'Portainer (Docker + веб-UI :9000)' },
  { value: 'grafana', label: 'Grafana (дашборды и графики :3000)' },
  { value: 'nodejs', label: 'Node.js 20 LTS (+ pm2)' },
  { value: 'python', label: 'Python 3 (pip + venv + gunicorn)' },
  { value: 'postgresql', label: 'PostgreSQL сервер' },
  { value: 'redis', label: 'Redis сервер' },
  { value: 'wordpress', label: 'WordPress (Apache + MariaDB + PHP)' },
  { value: 'zabbix', label: 'Zabbix (мониторинг, веб-интерфейс /zabbix)' },
];

const OSIcon = ({ type, size = 16 }) => {
  const os = type?.toLowerCase() || '';
  if (os.includes('ubuntu')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" title="Ubuntu">
        <circle cx="12" cy="12" r="10" stroke="#f97316" strokeWidth="2" />
        <circle cx="12" cy="6" r="2" fill="#f97316" />
        <circle cx="7" cy="14" r="2" fill="#f97316" />
        <circle cx="17" cy="14" r="2" fill="#f97316" />
      </svg>
    );
  }
  if (os.includes('debian')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" title="Debian">
        <path d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM12 18C8.69 18 6 15.31 6 12C6 8.69 8.69 6 12 6C15.31 6 18 8.69 18 12C18 13 17 14 16 14C15 14 14 15 14 16C14 17 13 18 12 18Z" fill="#ef4444" />
      </svg>
    );
  }
  if (os.includes('centos')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" title="CentOS">
        <rect x="4" y="4" width="16" height="16" rx="2" stroke="#84cc16" strokeWidth="2" />
        <path d="M12 8L16 12L12 16L8 12L12 8Z" fill="#84cc16" />
      </svg>
    );
  }
  if (os.includes('windows')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" title="Windows">
        <path d="M3 5.5L10.5 4.5V11.5H3V5.5ZM3 12.5H10.5V19.5L3 18.5V12.5ZM11.5 4.3L21 3V11.5H11.5V4.3ZM11.5 12.5H21V21L11.5 19.7V12.5Z" fill="#0ea5e9" />
      </svg>
    );
  }
  if (os.includes('bitrix')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" title="BitrixVM">
        <path d="M12 2L2 22H22L12 2ZM12 18C11.4 18 11 17.6 11 17C11 16.4 11.4 16 12 16C12.6 16 13 16.4 13 17C13 17.6 12.6 18 12 18ZM13 14H11V9H13V14Z" fill="#ec4899" />
      </svg>
    );
  }
  if (os.includes('proxmox')) {
    return <Layers size={size} color="#e57000" />;
  }
  if (os.includes('almalinux')) {
    return <Server size={size} color="#0a3d91" />;
  }
  if (os.includes('rocky')) {
    return <Server size={size} color="#10b981" />;
  }
  if (os.includes('fedora')) {
    return <Server size={size} color="#3c6eb4" />;
  }
  if (os.includes('opensuse')) {
    return <Server size={size} color="#73ba25" />;
  }
  if (os.includes('arch')) {
    return <Server size={size} color="#1793d1" />;
  }
  if (os.includes('alpine')) {
    return <Server size={size} color="#0d597f" />;
  }
  if (os.includes('truenas')) {
    return <HardDrive size={size} color="#0095d5" />;
  }
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" title="Other OS">
      <circle cx="12" cy="12" r="10" stroke="#94a3b8" strokeWidth="2" />
      <path d="M12 16V12M12 8H12.01" stroke="#94a3b8" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
};

const ClusterPanel = ({ vms, onRefreshVms }) => {
  const [clusters, setClusters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [showAttach, setShowAttach] = useState(null);
  const [activeVmIndex, setActiveVmIndex] = useState(0);

  // Form State
  const [clusterName, setClusterName] = useState('');
  const [clusterVms, setClusterVms] = useState([
    { name: '', os_type: 'ubuntu', cpu_cores: 2, memory_gb: 2, disk_gb: 20, packages: '', network_drives: '', cloud_init_template: '', custom_user_data: '', ssh_key: '', iso_url: OS_VERSIONS.ubuntu[0].value }
  ]);
  
  const fetchClusters = async () => {
    try {
      const res = await fetch('/api/clusters');
      if (res.ok) {
        setClusters(await res.json());
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  // Каталог шаблонов берём с бэкенда, а не держим второй захардкоженный
  // список рядом с тем, что в App.jsx: такой список неизбежно отстаёт (так
  // здесь и не появился Zabbix) и вдобавок ничего не знает про совместимость
  // с ОС — предлагал, например, LAMP на Alpine, где его нет.
  const [osCatalog, setOsCatalog] = useState(null);

  // Свободные ресурсы хоста. Бэкенд отказывает в создании кластера, который
  // не влезает (ensure_host_capacity), но узнать об этом можно было только
  // после отправки формы — заполнив её целиком. Показываем заранее: кластер
  // просит СУММУ ресурсов всех своих ВМ, и по отдельности каждая проходит, а
  // вместе не влезают, что совсем не очевидно на глаз.
  const [hostFree, setHostFree] = useState(null);

  useEffect(() => {
    fetchClusters();
    fetch('/api/vms/os-catalog')
      .then(r => (r.ok ? r.json() : null))
      .then(setOsCatalog)
      .catch(() => setOsCatalog(null));
    // Только админу: /api/host/* закрыт verify_admin_token, и студент
    // получал оттуда 401. Глобальный перехватчик в main.jsx считает 401
    // протухшей сессией — стирал токен и перезагружал страницу, то есть
    // выкидывал студента на вход при простом открытии вкладки «Кластеры».
    // Сами цифры свободных ресурсов хоста студенту и не нужны: это про
    // железо сервера, а его ограничивает квота.
    if (localStorage.getItem('aegis_role') === 'admin') {
      fetch('/api/host/metrics')
        .then(r => (r.ok ? r.json() : null))
        .then(m => setHostFree(m ? {
          cpu: m.cpu?.available_cores,
          ram: m.memory?.available_gb,
          disk: m.disk?.available_gb,
        } : null))
        .catch(() => setHostFree(null));
    }
  }, []);

  // Сумма запрошенного кластером и чего именно не хватает.
  const requested = clusterVms.reduce((acc, vm) => ({
    cpu: acc.cpu + (Number(vm.cpu_cores) || 0),
    ram: acc.ram + (Number(vm.memory_gb) || 0),
    disk: acc.disk + (Number(vm.disk_gb) || 0),
  }), { cpu: 0, ram: 0, disk: 0 });

  const shortages = !hostFree ? [] : [
    ['ядер CPU', requested.cpu, hostFree.cpu, ''],
    ['ОЗУ', requested.ram, hostFree.ram, ' ГБ'],
    ['места на диске', requested.disk, hostFree.disk, ' ГБ'],
  ].filter(([, need, free]) => typeof free === 'number' && need > free);

  // Шаблоны, применимые к ОС конкретной ВМ кластера. Каталог не загрузился —
  // показываем всё: урезанный список хуже неотфильтрованного, несовместимую
  // пару бэкенд отклонит сам, с внятным сообщением.
  const templatesForOs = (osType) => {
    const fallback = [{ value: '', label: 'Без шаблона (Чистая ОС)' }];
    // Шаблоны проверены только на Ubuntu (TEMPLATE_OFFERED_OS на бэкенде).
    // Проверка продублирована здесь намеренно: раньше при недоступном
    // каталоге запасной список показывался для ЛЮБОЙ ОС, и шаблон можно было
    // выбрать, например, для Alpine — установка потом молча не срабатывала.
    if (osType !== 'ubuntu') return fallback;
    if (!osCatalog?.templates) return fallback.concat(CLUSTER_TEMPLATE_FALLBACK);
    const allowed = osCatalog.supported?.[osType];
    const list = allowed
      ? osCatalog.templates.filter(t => allowed.includes(t.value))
      : osCatalog.templates;
    return fallback.concat(list);
  };

  const addVmToForm = () => {
    const nextIndex = clusterVms.length;
    setClusterVms([...clusterVms, {
      name: `${clusterName || 'cluster'}-vm${nextIndex + 1}`,
      os_type: 'ubuntu',
      cpu_cores: 2,
      memory_gb: 2,
      disk_gb: 20,
      packages: '',
      network_drives: '',
      cloud_init_template: '',
      custom_user_data: '',
      ssh_key: '',
      iso_url: OS_VERSIONS.ubuntu[0].value
    }]);
    setActiveVmIndex(nextIndex);
  };

  const removeVmFromForm = (index) => {
    const next = [...clusterVms];
    next.splice(index, 1);
    setClusterVms(next);
    setActiveVmIndex(Math.max(0, index - 1));
  };

  const handleUpdateVm = (index, field, value) => {
    const next = [...clusterVms];
    next[index][field] = value;
    setClusterVms(next);
  };

  const handleSelectOs = (index, osId) => {
    const next = [...clusterVms];
    next[index].os_type = osId;
    next[index].iso_url = OS_VERSIONS[osId] ? OS_VERSIONS[osId][0].value : '';
    setClusterVms(next);
  };

  const handleCreateCluster = async (e) => {
    e.preventDefault();
    try {
      const sanitizedClusterName = clusterName.toLowerCase().replace(/[^a-z0-9-]/g, '-');
      const sanitizedVms = clusterVms.map(vm => ({
        ...vm,
        name: vm.name.toLowerCase().replace(/[^a-z0-9-]/g, '-')
      }));

      const res = await fetch('/api/clusters', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: sanitizedClusterName,
          vms: sanitizedVms
        })
      });
      if (!res.ok) {
        const data = await res.json();
        let errorMsg = 'Ошибка создания кластера';
        if (typeof data.detail === 'string') {
          errorMsg = data.detail;
        } else if (Array.isArray(data.detail)) {
          errorMsg = data.detail.map(e => `${e.loc.join('.')}: ${e.msg}`).join(', ');
        }
        throw new Error(errorMsg);
      }
      setShowCreate(false);
      setClusterName('');
      setClusterVms([{ name: '', os_type: 'ubuntu', cpu_cores: 2, memory_gb: 2, disk_gb: 20, packages: '', network_drives: '', cloud_init_template: '', custom_user_data: '', ssh_key: '', iso_url: OS_VERSIONS.ubuntu[0].value }]);
      setActiveVmIndex(0);
      fetchClusters();
      if (onRefreshVms) onRefreshVms();
    } catch (err) {
      alert(err.message);
    }
  };

  const handleAttachVMs = async (e) => {
    e.preventDefault();
    const formData = new FormData(e.target);
    const selectedVMs = formData.getAll('vm_names');
    if (selectedVMs.length === 0) return;
    
    try {
      const res = await fetch(`/api/clusters/${showAttach}/attach`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vm_names: selectedVMs })
      });
      if (!res.ok) throw new Error('Ошибка объединения ВМ');
      setShowAttach(null);
      fetchClusters();
      if (onRefreshVms) onRefreshVms();
    } catch (err) {
      alert(err.message);
    }
  };

  const getVmStatusLabel = (status) => {
    const norm = status?.toLowerCase();
    if (norm === 'running') return 'Запущена';
    if (norm === 'stopped') return 'Остановлена';
    if (norm === 'starting') return 'Запуск...';
    if (norm === 'stopping') return 'Выключение...';
    if (norm === 'scheduled') return 'Планирование...';
    if (norm === 'pending') return 'В очереди...';
    if (norm === 'provisioning') return 'Создание...';
    if (norm === 'importing') return 'Импорт...';
    if (norm === 'error') return 'Ошибка';
    return status || 'Неизвестно';
  };

  const getClusterStatusBadge = (status) => {
    const norm = status?.toLowerCase();
    if (norm === 'active' || norm === 'running' || norm === 'ready') {
      return <span className="status-badge status-running">Активен</span>;
    }
    if (norm === 'creating' || norm === 'pending' || norm === 'scheduling' || norm === 'scheduled' || norm === 'starting' || norm === 'provisioning') {
      return <span className="status-badge status-pending" style={{ animation: 'pulse 1.5s infinite' }}>Создается</span>;
    }
    if (norm === 'updating' || norm === 'stopping') {
      return <span className="status-badge status-pending">Обновляется</span>;
    }
    if (norm === 'stopped') {
      return <span className="status-badge status-stopped">Остановлен</span>;
    }
    return <span className="status-badge status-stopped">Ошибка</span>;
  };

  // Шапка на общих классах, а не на inline-стилях: своя вёрстка здесь
  // отличалась отступами от всех прочих вкладок, да ещё и повторяла
  // заголовок, который уже показывает верхняя панель. И рисуется она в том
  // числе во время загрузки — иначе контент прыгает вниз, когда данные
  // приходят.
  const header = (
    <div className="panel-header">
      <div>
        <p className="panel-subtitle">Управляйте изолированными L2 группами виртуальных машин</p>
      </div>
      <button className="btn btn-primary" onClick={() => setShowCreate(true)} disabled={loading}>
        <Plus size={16} />
        Создать Кластер
      </button>
    </div>
  );

  if (loading) return (
    <div className="panel-container">{header}<div className="panel-loading"><span className="spinner spinner-lg" /></div></div>
  );

  return (
    <div className="panel-container" style={{ animation: 'fadeIn 0.3s ease-out' }}>
      {header}

      <div className="grid-responsive">
        {clusters.map(cluster => (
          <div key={cluster.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{ background: 'var(--accent-primary-light)', padding: '10px', borderRadius: '12px', color: 'var(--accent-primary)' }}>
                  <Layers size={24} />
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-heading)' }}>{cluster.name}</h3>
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '2px' }}>Сеть: <code>{cluster.network_name}</code></div>
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                {getClusterStatusBadge(cluster.status)}
                <button 
                  className="btn-icon" 
                  style={{ color: 'var(--status-danger)', background: 'var(--status-danger-bg)' }}
                  title="Удалить кластер"
                  onClick={async () => {
                    if(window.confirm('Вы уверены, что хотите удалить этот кластер? Все ВМ внутри будут безвозвратно удалены!')) {
                      try {
                        const res = await fetch(`/api/clusters/${cluster.id}`, { method: 'DELETE' });
                        if(!res.ok) throw new Error('Ошибка удаления кластера');
                        fetchClusters();
                        onRefreshVms();
                      } catch(e) {
                        alert(e.message);
                      }
                    }
                  }}
                >
                  <Trash size={16} />
                </button>
              </div>
            </div>

            {/* Детали изолированной приватной сети */}
            <div style={{ background: 'var(--bg-surface-hover)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: '16px', marginBottom: '18px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600, color: 'var(--text-heading)', marginBottom: '12px' }}>
                <Info size={16} style={{ color: 'var(--accent-primary)' }} /> Изолированная приватная сеть
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '12px' }}>
                {[
                  ['Подсеть', '192.168.100.0/24'],
                  ['Шлюз', '192.168.100.1'],
                  ['Тип', 'Multus bridge (L2)'],
                  ['Машин в сети', String((cluster.vms || []).length)],
                  ['Всего vCPU', String((cluster.vms || []).reduce((s, v) => s + (v.cpu_cores || 0), 0))],
                  ['Всего RAM', `${(cluster.vms || []).reduce((s, v) => s + (v.memory_gb || 0), 0)} ГБ`],
                ].map(([k, v]) => (
                  <div key={k}>
                    <div className="text-muted" style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.5px', fontWeight: 600 }}>{k}</div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--text-heading)', marginTop: '2px' }}>{v}</div>
                  </div>
                ))}
              </div>
              <p className="text-muted" style={{ fontSize: '0.78rem', marginTop: '12px', lineHeight: 1.5 }}>
                ВМ этого кластера видят друг друга напрямую по адресам <code>192.168.100.x</code> и полностью изолированы от других кластеров (L3-изоляция мостов через iptables). Доступ в интернет — через NAT хоста.
              </p>
            </div>

            <div>
              <div style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--text-heading)', marginBottom: '12px' }}>Виртуальные машины:</div>
              {cluster.vms && cluster.vms.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {cluster.vms.map(vm => (
                    <div key={vm.name} style={{ 
                      display: 'flex', 
                      flexDirection: 'column',
                      gap: '8px', 
                      padding: '12px', 
                      background: 'var(--bg-secondary)', 
                      borderRadius: '10px', 
                      border: '1px solid var(--border-subtle)',
                      boxShadow: 'var(--shadow-sm)'
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyItems: 'center', justifyContent: 'space-between' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <OSIcon type={vm.os_type} size={16} />
                          <span style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--text-primary)' }}>{vm.name}</span>
                        </div>
                        <span className={`status-badge status-${vm.status?.toLowerCase()}`} style={{ fontSize: '0.75rem', padding: '2px 8px' }}>
                          {getVmStatusLabel(vm.status)}
                        </span>
                      </div>
                      
                      <div style={{ display: 'flex', gap: '12px', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <Cpu size={12} />
                          <span>{vm.cpu_cores} Cores</span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <Layers size={12} />
                          <span>{vm.memory_gb} GB RAM</span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <HardDrive size={12} />
                          <span>{vm.disk_gb} GB Disk</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ 
                  textAlign: 'center', 
                  padding: '24px', 
                  background: 'var(--bg-secondary)', 
                  borderRadius: '10px', 
                  border: '1px dashed var(--border-subtle)',
                  color: 'var(--text-muted)',
                  fontSize: '0.9rem'
                }}>
                  ВМ отсутствуют
                </div>
              )}
            </div>

            <button 
              className="btn btn-secondary" 
              style={{ width: '100%', justifyContent: 'center', marginTop: 'auto' }}
              onClick={() => setShowAttach(cluster.id)}
            >
              <Plus size={16} />
              Добавить ВМ
            </button>
          </div>
        ))}
      </div>

      {/* Slide-over Side Panel for Cluster Creation */}
      {showCreate && (
        <div className="slide-over-overlay" onClick={() => setShowCreate(false)}>
          <div className="slide-over-content" onClick={e => e.stopPropagation()}>
            <div className="slide-over-header">
              <h2>Создание нового кластера</h2>
              <button className="btn-icon" onClick={() => setShowCreate(false)}><X size={20} /></button>
            </div>
            
            <form onSubmit={handleCreateCluster} style={{ display: 'flex', flexDirection: 'column', height: 'calc(100% - 77px)' }}>
              <div className="slide-over-body">
                {/* Ресурсы хоста — до отправки формы, а не после отказа.
                    Кластер запрашивает СУММУ всех своих ВМ: по отдельности
                    каждая проходит проверку, а вместе не влезают. */}
                {hostFree && (
                  <div className={shortages.length ? 'alert alert-danger' : 'glass-card'}
                       style={{ marginBottom: '16px', padding: '12px 14px', fontSize: '0.82rem' }}>
                    {shortages.length > 0 ? (
                      <>
                        <b>Не хватает ресурсов хоста — кластер не создастся.</b>
                        <div style={{ marginTop: '6px' }}>
                          {shortages.map(([what, need, free, unit]) => (
                            <div key={what}>
                              {what}: запрошено {need}{unit}, свободно {free}{unit}
                            </div>
                          ))}
                        </div>
                        <div style={{ marginTop: '6px' }}>
                          Уменьшите ресурсы ВМ или их количество, либо удалите ненужные ВМ.
                        </div>
                      </>
                    ) : (
                      <span className="text-muted">
                        Свободно на хосте: {hostFree.cpu} ядер, {hostFree.ram} ГБ ОЗУ, {hostFree.disk} ГБ диска.
                        {' '}Кластер запросит: {requested.cpu} ядер, {requested.ram} ГБ ОЗУ, {requested.disk} ГБ диска.
                      </span>
                    )}
                  </div>
                )}
                <div className="input-group">
                  <label className="input-label">Имя кластера (L2 Сети)</label>
                  <input 
                    type="text" 
                    className="form-control" 
                    placeholder="Например: my-isolated-cluster"
                    value={clusterName} 
                    onChange={(e) => setClusterName(e.target.value)} 
                    required 
                  />
                  <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px' }}>Сеть Multus будет создана автоматически в формате <code>[имя]-net</code></span>
                </div>

                <div style={{ marginTop: '28px', marginBottom: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h3 style={{ fontSize: '1.05rem', fontWeight: 600, color: 'var(--text-heading)', margin: 0 }}>Виртуальные машины в кластере</h3>
                  <button type="button" className="btn btn-secondary btn-sm" onClick={addVmToForm}>
                    <Plus size={14} /> Добавить ВМ
                  </button>
                </div>

                {clusterVms.map((vm, index) => {
                  const isExpanded = activeVmIndex === index;
                  return (
                    <div key={index} style={{ 
                      background: 'var(--bg-secondary)', 
                      borderRadius: '12px', 
                      marginBottom: '16px', 
                      border: isExpanded ? '1px solid var(--accent-primary)' : '1px solid var(--border-subtle)',
                      overflow: 'hidden',
                      transition: 'all 0.2s ease'
                    }}>
                      {/* Accordion Header */}
                      <div 
                        onClick={() => setActiveVmIndex(isExpanded ? null : index)}
                        style={{ 
                          padding: '14px 16px', 
                          display: 'flex', 
                          justifyContent: 'space-between', 
                          alignItems: 'center', 
                          cursor: 'pointer',
                          background: isExpanded ? 'rgba(99, 102, 241, 0.02)' : 'transparent',
                          borderBottom: isExpanded ? '1px solid var(--border-subtle)' : 'none'
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <div style={{
                            background: 'var(--bg-surface)',
                            width: '24px',
                            height: '24px',
                            borderRadius: '50%',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            border: '1px solid var(--border-subtle)',
                            fontSize: '0.8rem',
                            fontWeight: '600',
                            color: 'var(--text-secondary)'
                          }}>{index + 1}</div>
                          <div>
                            <span style={{ fontWeight: 600, color: 'var(--text-heading)', fontSize: '0.95rem' }}>
                              {vm.name || `Виртуальная машина ${index + 1}`}
                            </span>
                            {!isExpanded && (
                              <span style={{ marginLeft: '12px', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                {vm.os_type} • {vm.cpu_cores} CPU • {vm.memory_gb}GB RAM
                              </span>
                            )}
                          </div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }} onClick={e => e.stopPropagation()}>
                          {clusterVms.length > 1 && (
                            <button 
                              type="button" 
                              className="btn-icon" 
                              style={{ color: 'var(--status-danger)', padding: '4px' }} 
                              onClick={() => removeVmFromForm(index)}
                            >
                              <Trash size={16} />
                            </button>
                          )}
                          <button 
                            type="button" 
                            className="btn-icon" 
                            style={{ padding: '4px' }}
                            onClick={() => setActiveVmIndex(isExpanded ? null : index)}
                          >
                            {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                          </button>
                        </div>
                      </div>

                      {/* Accordion Body */}
                      {isExpanded && (
                        <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px', background: 'var(--bg-surface)' }}>
                          <div className="input-group">
                            <label className="input-label">Имя ВМ (a-z, 0-9, -)</label>
                            <input 
                              type="text" 
                              className="form-control" 
                              placeholder="Например: db-node-1"
                              value={vm.name} 
                              onChange={e => handleUpdateVm(index, 'name', e.target.value)} 
                              required 
                            />
                          </div>

                          <div className="input-group">
                            <label className="input-label" style={{ marginBottom: '8px' }}>Операционная система</label>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(100px, 1fr))', gap: '8px' }}>
                              {[
                                { id: 'ubuntu', name: 'Ubuntu', desc: '24.04 LTS', color: '#f97316' },
                                { id: 'debian', name: 'Debian', desc: 'Debian 12', color: '#ef4444' },
                                { id: 'centos', name: 'CentOS', desc: 'Stream 9', color: '#84cc16' },
                                { id: 'almalinux', name: 'AlmaLinux', desc: 'v9', color: '#0a3d91' },
                                { id: 'rocky', name: 'Rocky', desc: 'Linux 9', color: '#10b981' },
                                { id: 'fedora', name: 'Fedora', desc: 'v41', color: '#3c6eb4' },
                                { id: 'opensuse', name: 'openSUSE', desc: 'Leap 15.6', color: '#73ba25' },
                                { id: 'arch', name: 'Arch', desc: 'rolling', color: '#1793d1' },
                                { id: 'alpine', name: 'Alpine', desc: '3.21', color: '#0d597f' },
                                { id: 'bitrix', name: 'BitrixVM', desc: 'CentOS 9', color: '#ec4899' },
                                { id: 'windows', name: 'Windows', desc: 'Server 2022', color: '#0ea5e9' },
                                { id: 'proxmox', name: 'Proxmox', desc: 'VE 9.2', color: '#e57000' },
                                { id: 'truenas', name: 'TrueNAS', desc: 'SCALE', color: '#0095d5' }
                              ].map(os => (
                                <div 
                                  key={os.id}
                                  onClick={() => handleSelectOs(index, os.id)}
                                  style={{
                                    border: vm.os_type === os.id ? '2px solid var(--accent-primary)' : '1px solid var(--border-subtle)',
                                    background: vm.os_type === os.id ? 'rgba(99, 102, 241, 0.05)' : 'var(--bg-surface)',
                                    borderRadius: '8px',
                                    padding: '10px 6px',
                                    cursor: 'pointer',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    alignItems: 'center',
                                    gap: '6px',
                                    textAlign: 'center',
                                    transition: 'all 0.15s ease'
                                  }}
                                >
                                  <OSIcon type={os.id} size={20} />
                                  <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-heading)' }}>{os.name}</span>
                                  <span style={{ fontSize: '0.65rem', color: 'var(--text-secondary)' }}>{os.desc}</span>
                                </div>
                              ))}
                            </div>
                          </div>

                          {/* OS Version Selector */}
                          {OS_VERSIONS[vm.os_type] && OS_VERSIONS[vm.os_type].length > 1 && (
                            <div className="input-group" style={{ marginTop: '4px' }}>
                              <label className="input-label">Версия операционной системы</label>
                              <CustomSelect 
                                value={vm.iso_url}
                                onChange={e => handleUpdateVm(index, 'iso_url', e.target.value)}
                                options={OS_VERSIONS[vm.os_type].map(v => ({ value: v.value, label: v.label }))}
                              />
                            </div>
                          )}

                          {/* Windows ISO URL */}
                          {vm.os_type === 'windows' && (
                            <div className="input-group">
                              <label className="input-label">Ссылка на собственный ISO-образ Windows (необязательно)</label>
                              <input 
                                type="url" 
                                className="form-control" 
                                placeholder="https://example.com/windows.iso"
                                value={vm.iso_url || ''}
                                onChange={e => handleUpdateVm(index, 'iso_url', e.target.value)}
                              />
                            </div>
                          )}

                          {/* Advanced Linux Settings */}
                          {!['windows', 'proxmox', 'truenas'].includes(vm.os_type) && (
                            <>
                              <div className="input-group">
                                <label className="input-label" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                  <Package size={16}/> Пакеты для установки (через запятую)
                                </label>
                                <input 
                                  type="text" 
                                  className="form-control" 
                                  placeholder="Например: nginx, docker.io, mc, htop"
                                  value={vm.packages || ''}
                                  onChange={e => handleUpdateVm(index, 'packages', e.target.value)}
                                />
                                <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px' }}>Установятся автоматически при первом запуске (только для Linux).</span>
                              </div>

                              <div className="input-group">
                                <label className="input-label" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                  <HardDrive size={16}/> Сетевые диски (NFS / PVC)
                                </label>
                                <input 
                                  type="text" 
                                  className="form-control" 
                                  placeholder="Например: 192.168.1.10:/shared или pvc-name"
                                  value={vm.network_drives || ''}
                                  onChange={e => handleUpdateVm(index, 'network_drives', e.target.value)}
                                />
                                <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px' }}>Сетевая шара будет смонтирована в /mnt/network_drive.</span>
                              </div>

                              <div className="input-group">
                                <label className="input-label">Шаблон окружения (Cloud-Init)</label>
                                <CustomSelect
                                  value={vm.cloud_init_template || ''}
                                  onChange={e => handleUpdateVm(index, 'cloud_init_template', e.target.value)}
                                  placeholder="Без шаблона (Чистая ОС)"
                                  options={templatesForOs(vm.os_type)}
                                />
                                {vm.os_type !== 'ubuntu' && (
                                  <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px' }}>
                                    Шаблоны окружения проверены на Ubuntu — для остальных ОС список пуст.
                                    Выберите Ubuntu, если нужен готовый стек.
                                  </span>
                                )}
                              </div>

                              <div className="input-group">
                                <label className="input-label" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                  <Key size={16}/> Публичный SSH-ключ (для безопасного входа)
                                </label>
                                <input 
                                  type="text" 
                                  className="form-control" 
                                  placeholder="ssh-rsa AAAA..."
                                  value={vm.ssh_key || ''}
                                  onChange={e => handleUpdateVm(index, 'ssh_key', e.target.value)}
                                />
                                <small style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '4px', display: 'block' }}>
                                  Если указан ключ, парольный вход по SSH будет автоматически заблокирован на создаваемой ВМ.
                                </small>
                              </div>

                              <div className="input-group">
                                <label className="input-label">Кастомный скрипт Cloud-Init (userData)</label>
                                <textarea 
                                  className="form-control" 
                                  placeholder="#cloud-config..."
                                  value={vm.custom_user_data || ''}
                                  onChange={e => handleUpdateVm(index, 'custom_user_data', e.target.value)}
                                  style={{ height: '80px', minHeight: '60px', resize: 'vertical' }}
                                />
                              </div>
                            </>
                          )}

                          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginTop: '8px' }}>
                            <div>
                              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                                <span className="input-label" style={{ fontSize: '0.8rem' }}>Ядра CPU</span>
                                <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--accent-primary)' }}>{vm.cpu_cores} Cores</span>
                              </div>
                              <input 
                                type="range" 
                                min="1" 
                                max="16" 
                                value={vm.cpu_cores} 
                                onChange={e => handleUpdateVm(index, 'cpu_cores', parseInt(e.target.value))} 
                                style={{ width: '100%' }} 
                              />
                            </div>

                            <div>
                              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                                <span className="input-label" style={{ fontSize: '0.8rem' }}>Оперативная память</span>
                                <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--accent-primary)' }}>{vm.memory_gb} GB</span>
                              </div>
                              <input 
                                type="range" 
                                min="1" 
                                max="64" 
                                value={vm.memory_gb} 
                                onChange={e => handleUpdateVm(index, 'memory_gb', parseInt(e.target.value))} 
                                style={{ width: '100%' }} 
                              />
                            </div>

                            <div>
                              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                                <span className="input-label" style={{ fontSize: '0.8rem' }}>Размер диска</span>
                                <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--accent-primary)' }}>{vm.disk_gb} GB</span>
                              </div>
                              <input 
                                type="range" 
                                min="10" 
                                max="500" 
                                step="10"
                                value={vm.disk_gb} 
                                onChange={e => handleUpdateVm(index, 'disk_gb', parseInt(e.target.value))} 
                                style={{ width: '100%' }} 
                              />
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>

              <div className="slide-over-actions">
                <button type="button" className="btn" onClick={() => setShowCreate(false)}>Отмена</button>
                <button type="submit" className="btn btn-primary" disabled={!clusterName || clusterVms.length === 0}>
                  Создать и Запустить
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showAttach && (
        <Portal>
            <div className="modal-overlay" onClick={() => setShowAttach(null)}>
              <div className="modal-content" onClick={e => e.stopPropagation()}>
                <div className="modal-header">
                  <h2>Добавить ВМ в кластер</h2>
                  <button className="btn-icon" onClick={() => setShowAttach(null)}><X size={20} /></button>
                </div>
                <form onSubmit={handleAttachVMs}>
                  <div className="input-group" style={{ padding: '0 24px' }}>
                    <label className="input-label">Выберите ВМ (зажмите Ctrl/Cmd для выбора нескольких)</label>
                    <select name="vm_names" multiple className="form-control" style={{ height: '180px', marginTop: '8px' }} required>
                      {vms.filter(v => !clusters.some(c => c.vms.some(cv => cv.name === v.name))).map(vm => (
                        <option key={vm.name} value={vm.name}>{vm.name} ({getVmStatusLabel(vm.status)})</option>
                      ))}
                    </select>
                  </div>
                  <div style={{ padding: '16px 24px', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                    * При добавлении ВМ в кластер, она будет перезагружена для подключения нового приватного сетевого интерфейса (Multus).
                  </div>
                  <div className="modal-actions">
                    <button type="button" className="btn" onClick={() => setShowAttach(null)}>Отмена</button>
                    <button type="submit" className="btn btn-primary">Объединить</button>
                  </div>
                </form>
              </div>
            </div>
        </Portal>
      )}
    </div>
  );
};

export default ClusterPanel;
