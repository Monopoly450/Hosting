import re
css_file = "frontend/src/index.css"
with open(css_file, "r") as f:
    css = f.read()

# Make top-header have a solid background and z-index to prevent scrolling overlap
top_header_pattern = r'\.top-header\s*\{[^}]*\}'
new_top_header = """.top-header {
  height: 70px;
  background-color: var(--bg-body);
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
  position: sticky;
  top: 0;
  z-index: 50;
}"""
css = re.sub(top_header_pattern, new_top_header, css)

with open(css_file, "w") as f:
    f.write(css)

print("Header fixed!")
