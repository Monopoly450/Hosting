app_file = "frontend/src/App.jsx"
with open(app_file, "r") as f:
    app = f.read()

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

custom_idx = app.find("{osType === 'custom' && (")
if custom_idx != -1:
    end_idx = app.find(")}", custom_idx)
    if end_idx != -1:
        app = app[:end_idx + 2] + packages_and_drives + app[end_idx + 2:]
        with open(app_file, "w") as f:
            f.write(app)
        print("Fields added back")
