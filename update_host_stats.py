import re

app_file = "frontend/src/components/HostStats.jsx"
with open(app_file, "r") as f:
    app = f.read()

replacement = """
      {/* Meta Info */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '24px', padding: '20px', background: 'var(--bg-surface-hover)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
        <div>
          <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '4px' }}>Host Node</div>
          <div style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{metrics.node_name}</div>
        </div>
        <div>
          <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '4px' }}>Architecture</div>
          <div style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{metrics.architecture}</div>
        </div>
        <div>
          <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '4px' }}>Operating System</div>
          <div style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{metrics.operating_system}</div>
        </div>
        <div>
          <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '4px' }}>OS Image</div>
          <div style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{metrics.os_info}</div>
        </div>
        <div>
          <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '4px' }}>Kernel Version</div>
          <div style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{metrics.kernel_version}</div>
        </div>
        <div>
          <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '4px' }}>Container Runtime</div>
          <div style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{metrics.container_runtime}</div>
        </div>
        <div>
          <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '4px' }}>Kubelet Version</div>
          <div style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{metrics.kubelet_version}</div>
        </div>
        <div>
          <div className="text-muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', marginBottom: '4px' }}>System UUID</div>
          <div style={{ fontWeight: 600, color: 'var(--text-heading)', fontSize: '0.8rem' }}>{metrics.system_uuid}</div>
        </div>
      </div>
"""

start_marker = "      {/* Meta Info */}"
end_marker = "    </div>\n  );\n};"

start_idx = app.find(start_marker)
end_idx = app.find(end_marker)

if start_idx != -1 and end_idx != -1:
    app = app[:start_idx] + replacement + app[end_idx:]
    with open(app_file, "w") as f:
        f.write(app)
    print("Updated HostStats!")
else:
    print("Could not find Meta Info block")
