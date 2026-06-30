import re

app_file = "frontend/src/App.jsx"
with open(app_file, "r") as f:
    app = f.read()

# Add states for packages and network_drives
if 'const [packages, setPackages] = useState("");' not in app:
    state_insert_idx = app.find('const [cpuCores, setCpuCores] = useState(2);')
    state_code = """  const [packages, setPackages] = useState("");
  const [networkDrives, setNetworkDrives] = useState("");
  """
    app = app[:state_insert_idx] + state_code + app[state_insert_idx:]

# Also we need to import some icons: Info, ChevronDown
if 'import { Plus, Server, LogOut, Terminal, Link2, Activity, Play, Square, Loader, Settings, Edit2, Trash2, Shield, FolderOpen } from \'lucide-react\';' in app:
    app = app.replace(
        "import { Plus, Server, LogOut, Terminal, Link2, Activity, Play, Square, Loader, Settings, Edit2, Trash2, Shield, FolderOpen } from 'lucide-react';",
        "import { Plus, Server, LogOut, Terminal, Link2, Activity, Play, Square, Loader, Settings, Edit2, Trash2, Shield, FolderOpen, Info, ChevronDown, Package, HardDrive } from 'lucide-react';"
    )
elif 'ChevronDown' not in app:
    app = app.replace("from 'lucide-react';", ", Info, ChevronDown, Package, HardDrive } from 'lucide-react';")

# Find the form and replace the OS select with the grid
# We also need to update the handleCreateVM function
submit_func_start = app.find('const handleCreateVM = async (e) => {')
submit_func_end = app.find('} catch (err) {', submit_func_start)
submit_func_chunk = app[submit_func_start:submit_func_end]
new_submit_func_chunk = submit_func_chunk.replace(
    'disk_gb: diskGb',
    'disk_gb: diskGb, packages: packages, network_drives: networkDrives'
)
app = app[:submit_func_start] + new_submit_func_chunk + app[submit_func_end:]

# Now replace the OS type select and add the new fields
# The current osType is a <select>
# Let's find this chunk:
old_os_select = """                    <div style={{ flex: '1 1 300px' }} className="input-group">
                      <label className="input-label">Операционная система</label>
                      <select className="form-control" value={osType} onChange={(e) => setOsType(e.target.value)}>
                        <option value="ubuntu">Ubuntu Cloud</option>
                        <option value="windows">Windows ISO</option>
                        <option value="custom">Пользовательский образ</option>
                      </select>
                    </div>"""

grid_code = """
                  <div className="input-group" style={{ marginTop: '16px' }}>
                    <label className="input-label">3. Операционная система</label>
                    <div className="os-grid">
                      <div className={`os-card ${osType === 'none' ? 'selected' : ''}`} onClick={() => setOsType('none')}>
                        <div className="os-card-icon" style={{ color: '#94a3b8' }}><Info size={24} /></div>
                        <div className="os-card-title">Без ОС</div>
                        <div className="os-card-version">Отдадим быстрее</div>
                      </div>
                      
                      <div className={`os-card ${osType === 'ubuntu' ? 'selected' : ''}`} onClick={() => setOsType('ubuntu')}>
                        <div className="os-card-icon" style={{ color: '#f97316' }}><Server size={24} /></div>
                        <div className="os-card-title">Ubuntu</div>
                        <div className="os-card-version">Ubuntu 24.04 <ChevronDown size={14} /></div>
                      </div>
                      
                      <div className={`os-card ${osType === 'centos' ? 'selected' : ''}`} onClick={() => setOsType('centos')}>
                        <div className="os-card-icon" style={{ color: '#84cc16' }}><Server size={24} /></div>
                        <div className="os-card-title">CentOS</div>
                        <div className="os-card-version">CentOS 10 <ChevronDown size={14} /></div>
                      </div>
                      
                      <div className={`os-card ${osType === 'debian' ? 'selected' : ''}`} onClick={() => setOsType('debian')}>
                        <div className="os-card-icon" style={{ color: '#ef4444' }}><Server size={24} /></div>
                        <div className="os-card-title">Debian</div>
                        <div className="os-card-version">Debian 13 <ChevronDown size={14} /></div>
                      </div>
                      
                      <div className={`os-card ${osType === 'bitrix' ? 'selected' : ''}`} onClick={() => setOsType('bitrix')}>
                        <div className="os-card-icon" style={{ color: '#ef4444' }}><Activity size={24} /></div>
                        <div className="os-card-title">BitrixVM</div>
                        <div className="os-card-version">CentOS 9</div>
                      </div>
                      
                      <div className={`os-card ${osType === 'vmware' ? 'selected' : ''}`} onClick={() => setOsType('vmware')}>
                        <div className="os-card-icon" style={{ color: '#eab308' }}><Square size={24} /></div>
                        <div className="os-card-title">VMWare ESXi</div>
                        <div className="os-card-version">VMware ESXi 8 <ChevronDown size={14} /></div>
                      </div>
                      
                      <div className={`os-card ${osType === 'proxmox' ? 'selected' : ''}`} onClick={() => setOsType('proxmox')}>
                        <div className="os-card-icon" style={{ color: '#f97316' }}><Activity size={24} /></div>
                        <div className="os-card-title">Proxmox</div>
                        <div className="os-card-version">Proxmox 8 <ChevronDown size={14} /></div>
                      </div>
                      
                      <div className={`os-card ${osType === 'custom' ? 'selected' : ''}`} style={{ borderColor: osType === 'custom' ? '#6366f1' : 'transparent', backgroundColor: osType === 'custom' ? 'var(--bg-surface-hover)' : 'var(--bg-surface)' }} onClick={() => setOsType('custom')}>
                        <div className="os-card-icon" style={{ color: '#6366f1' }}><Info size={24} /></div>
                        <div className="os-card-title">Свой образ</div>
                        <div className="os-card-version" style={{ opacity: 0 }}>...</div>
                      </div>
                      
                      <div className={`os-card ${osType === 'other' ? 'selected' : ''}`} onClick={() => setOsType('other')}>
                        <div className="os-card-icon" style={{ color: '#94a3b8' }}><Info size={24} /></div>
                        <div className="os-card-title">Хочу другое ПО</div>
                        <div className="os-card-version">Оставить заявку</div>
                      </div>
                    </div>
                  </div>
"""

app = app.replace(old_os_select, "")

# We need to insert grid_code before the custom image select
custom_image_select = "{osType === 'custom' && ("
custom_idx = app.find(custom_image_select)
if custom_idx != -1:
    app = app[:custom_idx] + grid_code + "\n                  " + app[custom_idx:]

# Now add the packages and network_drives fields right after the custom image select block
packages_and_drives = """
                  <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', marginTop: '8px' }}>
                    <div style={{ flex: '1 1 300px' }} className="input-group">
                      <label className="input-label" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><Package size={16}/> Пакеты для установки (через запятую)</label>
                      <input 
                        type="text" 
                        className="form-control" 
                        placeholder="Например: nginx, docker.io, mc, htop"
                        value={packages}
                        onChange={(e) => setPackages(e.target.value)}
                      />
                      <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px' }}>Установятся автоматически при первом запуске (только для Linux).</span>
                    </div>
                    <div style={{ flex: '1 1 300px' }} className="input-group">
                      <label className="input-label" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><HardDrive size={16}/> Сетевые диски (NFS / PVC)</label>
                      <input 
                        type="text" 
                        className="form-control" 
                        placeholder="Например: 192.168.1.10:/shared или pvc-name"
                        value={networkDrives}
                        onChange={(e) => setNetworkDrives(e.target.value)}
                      />
                      <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px' }}>Сетевая шара будет смонтирована в /mnt/network_drive.</span>
                    </div>
                  </div>
"""

custom_end_idx = app.find(')}', custom_idx)
if custom_end_idx != -1:
    app = app[:custom_end_idx+2] + packages_and_drives + app[custom_end_idx+2:]

with open(app_file, "w") as f:
    f.write(app)
print("Frontend updated!")
