import re

app_file = "backend/app/api/vms.py"
with open(app_file, "r") as f:
    app = f.read()

# Replace ping security.ubuntu.com with ping 8.8.8.8
app = app.replace("ping -c 1 -W 2 security.ubuntu.com", "ping -c 1 -W 2 8.8.8.8")

# Replace agetty --autologin ubuntu with agetty --autologin {default_user}
app = app.replace("agetty --autologin ubuntu", "agetty --autologin {default_user}")

# Replace echo "ubuntu:{password}" with echo "{default_user}:{password}"
app = app.replace("echo \\"ubuntu:{password}\\" | chpasswd", "echo \\"{default_user}:{password}\\" | chpasswd")

with open(app_file, "w") as f:
    f.write(app)

print("OS logic replaced")
