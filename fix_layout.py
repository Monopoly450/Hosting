import re

css_file = "frontend/src/index.css"
with open(css_file, "r") as f:
    css = f.read()

# 1. Fix .top-header to have a glass background so scrolling under it looks good
top_header_new = """
.top-header {
  height: 70px;
  background: rgba(253, 250, 246, 0.85);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.5);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
  position: sticky;
  top: 0;
  z-index: 50; /* Ensure it stays above everything */
}
"""
css = re.sub(r'\.top-header\s*\{[^}]*\}', top_header_new, css, flags=re.MULTILINE)

# 2. Add flex-shrink: 0 to .sidebar to prevent it from collapsing
css = css.replace('width: 280px;', 'width: 280px;\n  flex-shrink: 0;')

with open(css_file, "w") as f:
    f.write(css)

print("Layout fixed!")
