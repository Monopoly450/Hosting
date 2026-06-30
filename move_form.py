import re

app_file = "frontend/src/App.jsx"
with open(app_file, "r") as f:
    app = f.read()

# The form chunk is between <div className="glass-card interactive"> containing "Создать новую ВМ"
# and the end of that div (before </div>\n            </div>\n          ) : activeTab === 'vms')

# Let's find the exact chunk
start_marker = '              <div className="glass-card interactive">\n                <h3 className="section-title"><Plus size={18} /> Создать новую ВМ</h3>'
end_marker = '              </div>\n            </div>\n          ) : activeTab === \'vms\' ? ('

start_idx = app.find(start_marker)
end_idx = app.find(end_marker, start_idx)

if start_idx != -1 and end_idx != -1:
    form_chunk = app[start_idx:end_idx + 20] # include the </div>
    
    # Remove it from dashboard
    new_dashboard = '            <div style={{ display: \'flex\', flexDirection: \'column\', gap: \'32px\' }}>\n              <HostStats />\n            </div>\n          ) : activeTab === \'vms\' ? ('
    
    app = app[:start_idx - 15] + new_dashboard + app[end_idx + len(end_marker):]
    
    # Now insert it into vms tab
    # In vms tab, we have:
    #             <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
    #               <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
    
    vms_insert_marker = '<div style={{ display: \'flex\', flexDirection: \'column\', gap: \'24px\' }}>\n              <div style={{ display: \'flex\', justifyContent: \'space-between\', alignItems: \'center\' }}>'
    
    vms_insert_idx = app.find(vms_insert_marker)
    if vms_insert_idx != -1:
        # We will add state for showing the form
        if 'const [showCreateVM, setShowCreateVM] = useState(false);' not in app:
            state_insert_idx = app.find('const [showConnectModal, setShowConnectModal] = useState(false);')
            app = app[:state_insert_idx] + 'const [showCreateVM, setShowCreateVM] = useState(false);\n  ' + app[state_insert_idx:]
            
        # Modify the button in vms tab
        app = app.replace("onClick={() => setActiveTab('dashboard')}", "onClick={() => setShowCreateVM(!showCreateVM)}")
        
        # Insert the form chunk
        form_chunk_conditional = f"{{showCreateVM && (\n{form_chunk}\n)}}\n"
        
        # Insert after the top buttons div in vms tab
        buttons_end_marker = '</div>\n              </div>'
        buttons_end_idx = app.find(buttons_end_marker, vms_insert_idx)
        
        if buttons_end_idx != -1:
            insert_pos = buttons_end_idx + len(buttons_end_marker)
            app = app[:insert_pos] + '\n\n              ' + form_chunk_conditional + app[insert_pos:]
            
        with open(app_file, "w") as f:
            f.write(app)
        print("Moved successfully!")
    else:
        print("Could not find vms tab marker")
else:
    print("Could not find form chunk")
