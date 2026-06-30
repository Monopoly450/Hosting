import re

with open("frontend/src/components/ConnectServerModal.jsx", "r") as f:
    content = f.read()

# Replace classes
content = content.replace('className="console-modal-backdrop"', 'className="modal-overlay"')
content = content.replace('className="console-container"', 'className="modal-content"')
content = content.replace('className="console-header"', 'className="modal-header"')
content = content.replace('className="console-title"', 'style={{ display: "flex", alignItems: "center", gap: "8px", fontWeight: "600", fontSize: "1.1rem" }}')
content = content.replace('className="btn btn-danger btn-icon-only btn-sm"', 'className="btn-icon-only" style={{ background: "transparent", border: "none" }}')

content = content.replace('className="form-group"', 'className="input-group"')
content = content.replace('className="form-label"', 'className="input-label"')
content = content.replace('className="form-input"', 'className="form-control"')

# Change the form div to modal-body
content = content.replace('<form onSubmit={handleSubmit} style={{ padding: \'24px\', display: \'flex\', flexDirection: \'column\', gap: \'20px\' }}>', 
                         '<form onSubmit={handleSubmit} className="modal-body" style={{ display: \'flex\', flexDirection: \'column\', gap: \'20px\', padding: \'24px\' }}>')

with open("frontend/src/components/ConnectServerModal.jsx", "w") as f:
    f.write(content)
