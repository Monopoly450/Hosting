css_file = "frontend/src/index.css"
with open(css_file, "r") as f:
    css = f.read()

new_css = """
/* OS Selection Grid */
.os-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.os-card {
  background-color: var(--bg-surface);
  border: 2px solid transparent;
  border-radius: var(--radius-md);
  padding: 16px;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
  position: relative;
}

.os-card:hover {
  background-color: var(--bg-surface-hover);
  border-color: var(--border-subtle);
}

.os-card.selected {
  background-color: rgba(99, 102, 241, 0.1);
  border-color: var(--accent-primary);
}

.os-card-icon {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
}

.os-card-title {
  font-weight: 600;
  font-size: 1rem;
  color: var(--text-heading);
  margin: 0;
}

.os-card-version {
  font-size: 0.85rem;
  color: var(--text-muted);
  display: flex;
  justify-content: space-between;
  width: 100%;
  align-items: center;
}
"""

if ".os-grid" not in css:
    with open(css_file, "a") as f:
        f.write(new_css)
    print("CSS added.")
else:
    print("CSS already exists.")
