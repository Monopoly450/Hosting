import re

with open("backend/app/api/vms.py", "r") as f:
    content = f.read()

# I will rewrite the whole migrate_vm endpoint to use a thread for the blocking parts
migrate_block_pattern = r'@router\.post\("/\{name\}/migrate"\).*?return \{"status": "success", "message": f"ВМ \{name\} успешно мигрирована", "new_server_id": new_server\.id\}'

replacement = """@router.post("/{name}/migrate")
async def migrate_vm(name: str, target_server_id: str = Query(...), k8s: K8sClient = Depends(get_k8s_client), db: AsyncSession = Depends(get_db)):
    from app.models.models import ExternalServer
    from sqlalchemy import select
    import asyncio
    import base64
    import paramiko
    import uuid
    import random
    import subprocess
    
    # 1. Получаем внешний сервер асинхронно
    res = await db.execute(select(ExternalServer).filter_by(id=target_server_id))
    target_server = res.scalars().first()
    
    if not target_server:
        raise HTTPException(status_code=404, detail="Внешний сервер не найден")
        
    # Блокирующая часть выносится в отдельный поток, чтобы не завешивать event loop FastAPI
    def blocking_migration_task():
        # 2. Получаем ВМ
        vms = k8s.list_vms()
        vm = next((v for v in vms if v["name"] == name), None)
        if not vm:
            raise Exception("Виртуальная машина не найдена")
            
        # Учетные данные
        try:
            secret = k8s.core_api.read_namespaced_secret(f"vm-{name}-auth", "default")
            vm_user = base64.b64decode(secret.data.get("username", b"")).decode("utf-8") if secret.data.get("username") else "root"
            vm_pass = base64.b64decode(secret.data.get("password", b"")).decode("utf-8") if secret.data.get("password") else ""
        except:
            vm_user = "root"
            vm_pass = ""

        # 3. Находим путь к диску
        try:
            pvc = k8s.core_api.read_namespaced_persistent_volume_claim(f"default-disk-{name}", "default")
            pv_name = pvc.spec.volume_name
            pv = k8s.core_api.read_persistent_volume(pv_name)
            
            host_path = pv.spec.local.path if pv.spec.local else None
            if not host_path and pv.spec.host_path:
                host_path = pv.spec.host_path.path
                
            if not host_path:
                raise Exception("Не удалось определить host_path для диска.")
                
            disk_path = f"{host_path}/disk.img"
        except Exception as e:
            raise Exception(f"Ошибка поиска диска: {e}")

        # 4. Останавливаем ВМ
        k8s.stop_vm(name)
        
        # 5. Подключаемся
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                target_server.host, 
                port=target_server.port, 
                username=target_server.username, 
                password=target_server.password,
                timeout=10
            )
            
            ssh.exec_command("apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y qemu-system-x86 qemu-utils")
            ssh.exec_command(f"mkdir -p /opt/antigravity/vms/{name}")
            
            # 6. Ключ для SCP
            key_path = f"/tmp/mig_key_{uuid.uuid4().hex}"
            nsenter_prefix = ["nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid"]
            
            subprocess.run(nsenter_prefix + ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", key_path], check=True)
            pub_key_res = subprocess.run(nsenter_prefix + ["cat", f"{key_path}.pub"], capture_output=True, text=True)
            pub_key = pub_key_res.stdout.strip()
            
            ssh.exec_command(f"mkdir -p ~/.ssh && echo '{pub_key}' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys")
            
            # 7. SCP
            scp_cmd = f"scp -o StrictHostKeyChecking=no -i {key_path} {disk_path} {target_server.username}@{target_server.host}:/opt/antigravity/vms/{name}/disk.img"
            scp_res = subprocess.run(nsenter_prefix + ["sh", "-c", scp_cmd], capture_output=True, text=True)
            
            subprocess.run(nsenter_prefix + ["rm", "-f", key_path, f"{key_path}.pub"])
            
            if scp_res.returncode != 0:
                raise Exception(f"SCP failed: {scp_res.stderr}")
                
            # 8. Service
            ext_ssh_port = random.randint(22000, 30000)
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
            stdin, stdout, stderr = ssh.exec_command(f"cat << 'EOF' > /etc/systemd/system/vm-{name}.service\\n{service_content}\\nEOF")
            stdout.channel.recv_exit_status()
            
            ssh.exec_command("systemctl daemon-reload")
            ssh.exec_command(f"systemctl enable --now vm-{name}.service")
            
        except Exception as e:
            raise Exception(f"Ошибка миграции SSH/SCP: {e}")
        finally:
            ssh.close()
            
        # 9. Удаляем ВМ
        try:
            k8s.delete_vm(name)
        except:
            pass
            
        return vm_user, vm_pass, ext_ssh_port

    # Выполняем длительную блокирующую операцию в пуле потоков
    try:
        vm_user, vm_pass, ext_ssh_port = await asyncio.to_thread(blocking_migration_task)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    # 10. Сохраняем результат
    new_id = str(uuid.uuid4())[:8]
    new_server = ExternalServer(
        id=new_id,
        name=f"{name} (Migrated)",
        host=target_server.host,
        port=ext_ssh_port,
        username=vm_user,
        password=vm_pass
    )
    db.add(new_server)
    await db.commit()
    
    return {"status": "success", "message": f"ВМ {name} успешно мигрирована", "new_server_id": new_server.id}"""

new_content = re.sub(migrate_block_pattern, replacement.replace('\\n', '\\\\n'), content, flags=re.DOTALL)
with open("backend/app/api/vms.py", "w") as f:
    f.write(new_content)
