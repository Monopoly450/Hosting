import re

# 1. Update index.html to prevent translation bugs
html_file = "frontend/index.html"
with open(html_file, "r") as f:
    html = f.read()

html = html.replace('<html lang="ru">', '<html lang="ru" translate="no">')
if '<meta name="google" content="notranslate">' not in html:
    html = html.replace('<meta charset="UTF-8" />', '<meta charset="UTF-8" />\n    <meta name="google" content="notranslate" />')

with open(html_file, "w") as f:
    f.write(html)

# 2. Add fix to index.css
css_file = "frontend/src/index.css"
with open(css_file, "r") as f:
    css = f.read()

fix_css = """
/* Fix for browser translation plugins adding white backgrounds to text */
font {
  background-color: transparent !important;
}
"""
if "Fix for browser" not in css:
    with open(css_file, "w") as f:
        f.write(css + "\n" + fix_css)

print("Translation fix applied!")
