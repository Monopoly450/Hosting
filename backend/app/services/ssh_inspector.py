import logging
import paramiko
import re

logger = logging.getLogger("app.ssh_inspector")

class SSHInspector:
    def __init__(self, host: str, username: str, password: str = None, port: int = 22):
        self.host = host
        self.username = username
        self.password = password
        self.port = port

    def test_connection(self) -> bool:
        """Проверяет возможность подключения к серверу по SSH с таймаутом 5 секунд"""
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=5,
                banner_timeout=5
            )
            ssh.close()
            return True
        except Exception as e:
            logger.warning(f"Тест подключения SSH к {self.host} не удался: {e}")
            return False

    def execute_command(self, client: paramiko.SSHClient, command: str) -> str:
        """Выполняет команду на удаленном сервере и возвращает вывод"""
        try:
            stdin, stdout, stderr = client.exec_command(command, timeout=5)
            # Ждем завершения
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                err = stderr.read().decode('utf-8', errors='ignore')
                logger.debug(f"Команда '{command}' завершилась с кодом {exit_status}. Ошибка: {err}")
            return stdout.read().decode('utf-8', errors='ignore').strip()
        except Exception as e:
            logger.error(f"Ошибка выполнения команды '{command}' на {self.host}: {e}")
            return ""

    def inspect(self) -> dict:
        """Подключается к удаленному хосту и собирает полную системную информацию"""
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            ssh.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=5
            )
        except Exception as e:
            logger.error(f"Не удалось подключиться к {self.host}: {e}")
            return {"status": "Offline", "error": str(e)}

        try:
            # 1. Системная информация
            os_release = self.execute_command(ssh, "cat /etc/os-release")
            os_name = "Linux"
            os_match = re.search(r'PRETTY_NAME="([^"]+)"', os_release)
            if os_match:
                os_name = os_match.group(1)
            else:
                os_match = re.search(r'NAME="([^"]+)"', os_release)
                if os_match:
                    os_name = os_match.group(1)
            
            kernel_version = self.execute_command(ssh, "uname -r")
            uptime = self.execute_command(ssh, "uptime -p")
            cpu_cores_str = self.execute_command(ssh, "nproc")
            cpu_cores = int(cpu_cores_str) if cpu_cores_str.isdigit() else 1

            # 2. Нагрузка CPU
            # vmstat 1 2 собирает данные за 1 секунду, берем последнюю строчку
            vmstat_out = self.execute_command(ssh, "vmstat 1 2 | tail -n 1")
            cpu_usage_pct = 0.0
            if vmstat_out:
                cols = vmstat_out.split()
                # В стандартном выводе vmstat: 15-я колонка (индекс 14) - это 'id' (idle cpu)
                if len(cols) >= 15:
                    try:
                        idle = int(cols[14])
                        cpu_usage_pct = float(100 - idle)
                    except ValueError:
                        pass

            # 3. RAM (в мегабайтах)
            free_out = self.execute_command(ssh, "free -m")
            mem_total = 0
            mem_used = 0
            mem_pct = 0.0
            if free_out:
                # Ищем строку Mem:
                for line in free_out.split('\n'):
                    if line.startswith("Mem:"):
                        cols = line.split()
                        if len(cols) >= 3:
                            mem_total = int(cols[1])
                            mem_used = int(cols[2])
                            mem_pct = round((mem_used / mem_total) * 100, 1) if mem_total else 0.0
                            break

            # 4. Диск (DF в мегабайтах)
            df_out = self.execute_command(ssh, "df -m / | tail -n 1")
            disk_total_gb = 0.0
            disk_used_gb = 0.0
            disk_pct = 0.0
            if df_out:
                cols = df_out.split()
                # Вывод: Filesystem 1M-blocks Used Available Use% MountedOn
                if len(cols) >= 5:
                    try:
                        total_mb = int(cols[1])
                        used_mb = int(cols[2])
                        disk_total_gb = round(total_mb / 1024, 1)
                        disk_used_gb = round(used_mb / 1024, 1)
                        # Парсим Use% (например, "45%")
                        pct_str = cols[4].replace('%', '')
                        disk_pct = float(pct_str)
                    except ValueError:
                        pass

            # 5. Активные процессы (Топ-10 по CPU)
            ps_out = self.execute_command(ssh, "ps aux --sort=-%cpu | head -n 11")
            processes = []
            if ps_out:
                lines = ps_out.split('\n')
                headers = lines[0].split()
                for line in lines[1:]:
                    cols = line.split(None, 10)
                    if len(cols) >= 11:
                        processes.append({
                            "user": cols[0],
                            "pid": cols[1],
                            "cpu": cols[2],
                            "mem": cols[3],
                            "command": cols[10]
                        })

            # 6. Systemd Службы (Только активные)
            systemctl_out = self.execute_command(ssh, "systemctl list-units --type=service --state=running --no-legend | head -n 15")
            services = []
            if systemctl_out:
                for line in systemctl_out.split('\n'):
                    cols = line.split(None, 4)
                    if len(cols) >= 5:
                        services.append({
                            "unit": cols[0],
                            "status": cols[3],
                            "description": cols[4]
                        })

            # 7. Контейнеры Docker
            docker_installed = True
            docker_containers = []
            docker_check = self.execute_command(ssh, "which docker")
            if not docker_check:
                docker_installed = False
            else:
                # docker ps с разделителем-табуляцией
                docker_out = self.execute_command(ssh, 'docker ps --format "{{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Image}}"')
                if docker_out:
                    for line in docker_out.split('\n'):
                        cols = line.split('\t')
                        if len(cols) >= 4:
                            docker_containers.append({
                                "id": cols[0],
                                "name": cols[1],
                                "status": cols[2],
                                "image": cols[3]
                            })

            return {
                "status": "Online",
                "os_name": os_name,
                "kernel": kernel_version,
                "uptime": uptime,
                "cpu": {
                    "cores": cpu_cores,
                    "usage_percent": cpu_usage_pct
                },
                "memory": {
                    "total_mb": mem_total,
                    "used_mb": mem_used,
                    "usage_percent": mem_pct
                },
                "disk": {
                    "total_gb": disk_total_gb,
                    "used_gb": disk_used_gb,
                    "usage_percent": disk_pct
                },
                "processes": processes,
                "services": services,
                "docker": {
                    "installed": docker_installed,
                    "containers": docker_containers
                }
            }
        except Exception as e:
            logger.error(f"Ошибка парсинга метрик с {self.host}: {e}")
            return {"status": "Online", "error": f"Ошибка сбора метрик: {str(e)}"}
        finally:
            ssh.close()
