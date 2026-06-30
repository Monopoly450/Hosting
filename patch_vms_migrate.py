import re

with open("backend/app/api/vms.py", "r") as f:
    content = f.read()

# Add the new POST /vms/{name}/migrate endpoint
new_endpoint = """
@router.post("/{name}/migrate")
def migrate_vm(name: str, target_server_id: str = Query(...), k8s: K8sClient = Depends(get_k8s_client)):
    # 1. Получаем внешний сервер
    from app.api.external_servers import db as ext_db
    target_server = next((s for s in ext_db.get_all() if s.id == target_server_id), None)
    if not target_server:
        raise HTTPException(status_code=404, detail="Внешний сервер не найден")
        
    # 2. Получаем ВМ
    vms = k8s.list_vms()
    vm = next((v for v in vms if v["name"] == name), None)
    if not vm:
        raise HTTPException(status_code=404, detail="Виртуальная машина не найдена")
        
    # Получаем учетные данные ВМ для регистрации ее как внешнего сервера потом
    try:
        secret = k8s.core_api.read_namespaced_secret(f"vm-{name}-auth", "default")
        import base64
        vm_user = base64.b64decode(secret.data.get("username", b"")).decode("utf-8") if secret.data.get("username") else "root"
        vm_pass = base64.b64decode(secret.data.get("password", b"")).decode("utf-8") if secret.data.get("password") else ""
    except:
        vm_user = "root"
        vm_pass = ""

    # 3. Находим путь к диску на хосте
    try:
        pvc = k8s.core_api.read_namespaced_persistent_volume_claim(f"default-disk-{name}", "default")
        pv_name = pvc.spec.volume_name
        pv = k8s.core_api.read_persistent_volume(pv_name)
        
        # Разные provisioner'ы могут хранить путь по-разному.
        # Для local-path provisioner (k3s):
        host_path = pv.spec.local.path if pv.spec.local else None
        
        # Для hostPath:
        if not host_path and pv.spec.host_path:
            host_path = pv.spec.host_path.path
            
        if not host_path:
            raise Exception("Не удалось определить host_path для диска.")
            
        disk_path = f"{host_path}/disk.img"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка поиска диска: {e}")

    # 4. Останавливаем ВМ
    k8s.stop_vm(name)
    
    # 5. Подключаемся к внешнему серверу
    import paramiko
    import time
    import random
    import subprocess
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(
            target_server.ip, 
            port=target_server.port, 
            username=target_server.username, 
            password=target_server.password,
            timeout=10
        )
        
        # Создаем папку и ставим qemu
        ssh.exec_command("apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y qemu-system-x86 qemu-utils")
        ssh.exec_command(f"mkdir -p /opt/antigravity/vms/{name}")
        
        # 6. Генерируем ключ на хосте для переноса без пароля
        # nsenter 
        import uuid
        key_path = f"/tmp/mig_key_{uuid.uuid4().hex}"
        nsenter_prefix = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid"]
        
        subprocess.run(nsenter_prefix + ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", key_path], check=True)
        pub_key_res = subprocess.run(nsenter_prefix + ["cat", f"{key_path}.pub"], capture_output=True, text=True)
        pub_key = pub_key_res.stdout.strip()
        
        # Добавляем ключ на внешний сервер
        ssh.exec_command(f"mkdir -p ~/.ssh && echo '{pub_key}' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys")
        
        # 7. Запускаем копирование через SCP с хоста!
        # Мы используем scp -i {key_path} -o StrictHostKeyChecking=no
        scp_cmd = f"scp -o StrictHostKeyChecking=no -i {key_path} {disk_path} {target_server.username}@{target_server.ip}:/opt/antigravity/vms/{name}/disk.img"
        scp_res = subprocess.run(nsenter_prefix + ["sh", "-c", scp_cmd], capture_output=True, text=True)
        
        # Удаляем временный ключ
        subprocess.run(nsenter_prefix + ["rm", "-f", key_path, f"{key_path}.pub"])
        
        if scp_res.returncode != 0:
            raise Exception(f"SCP failed: {scp_res.stderr}")
            
        # 8. Создаем systemd сервис
        # Генерируем случайный порт для SSH мигрированной ВМ (22000 - 30000)
        ext_ssh_port = random.randint(22000, 30000)
        # Узнаем размер ОЗУ из настроек ВМ, либо дадим 2048
        ram_mb = 2048
        cpu_cores = 2
        try:
            vmi_info = k8s.custom_api.get_namespaced_custom_object("kubevirt.io", "v1", "default", "virtualmachines", name)
            memory_str = vmi_info.get("spec", {}).get("template", {}).get("spec", {}).get("domain", {}).get("resources", {}).get("requests", {}).get("memory", "2G")
            if "G" in memory_str:
                ram_mb = int(memory_str.replace("G", "")) * 1024
            elif "M" in memory_str:
                ram_mb = int(memory_str.replace("M", ""))
                
            cpu_cores = vmi_info.get("spec", {}).get("template", {}).get("spec", {}).get("domain", {}).get("cpu", {}).get("cores", 2)
        except:
            pass
            
        service_content = f\"\"\"[Unit]
Description=Migrated VM {name}
After=network.target

[Service]
ExecStart=/usr/bin/qemu-system-x86_64 -enable-kvm -m {ram_mb} -smp {cpu_cores} -drive file=/opt/antigravity/vms/{name}/disk.img,format=raw,if=virtio -net nic,model=virtio -net user,hostfwd=tcp::{ext_ssh_port}-:22 -nographic
Restart=always

[Install]
WantedBy=multi-user.target
\"\"\"
        stdin, stdout, stderr = ssh.exec_command(f"cat << 'EOF' > /etc/systemd/system/vm-{name}.service\n{service_content}\nEOF")
        stdout.channel.recv_exit_status()
        
        ssh.exec_command("systemctl daemon-reload")
        ssh.exec_command(f"systemctl enable --now vm-{name}.service")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка миграции: {e}")
    finally:
        ssh.close()
        
    # 9. Удаляем старую ВМ из KubeVirt
    try:
        k8s.delete_vm(name)
    except:
        pass
        
    # 10. Регистрируем перенесенную ВМ как новый Внешний Сервер
    from app.api.external_servers import ExternalServer
    import uuid
    new_server = ExternalServer(
        id=str(uuid.uuid4()),
        name=f"{name} (Migrated)",
        ip=target_server.ip,
        port=ext_ssh_port,
        username=vm_user,
        password=vm_pass
    )
    ext_db.add_server(new_server)
    
    return {"status": "success", "message": f"ВМ {name} успешно мигрирована", "new_server_id": new_server.id}
"""

content = content + new_endpoint

with open("backend/app/api/vms.py", "w") as f:
    f.write(content)
