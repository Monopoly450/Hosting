with open("/Users/vladislavkarasev/.gemini/antigravity/brain/55e4cec9-34bd-4eea-88a8-15be11090fcc/task.md", "r") as f:
    content = f.read()

content = content.replace("[ ]", "[x]")

with open("/Users/vladislavkarasev/.gemini/antigravity/brain/55e4cec9-34bd-4eea-88a8-15be11090fcc/task.md", "w") as f:
    f.write(content)
