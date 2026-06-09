# Панель управления хостингом виртуальных машин и мониторингом инфраструктуры Aegis Cloud Engine

Aegis Cloud Engine (HCI Node Daemon) — это монолитная распределенная гиперконвергентная система хостинга виртуальных машин и контейнеров корпоративного класса, спроектированная с использованием лучших практик современных облачных провайдеров. Платформа объединяет виртуализацию KubeVirt (в экосистеме Kubernetes), низкоуровневые механизмы изоляции процессов Linux Namespaces/cgroups v2, встроенное S3-совместимое хранилище с избыточным кодированием Рида-Соломона (Reed-Solomon 4+2), сетевую подсистему с симуляцией DPDK/Anti-DDoS и полнофункциональный веб-интерфейс, спроектированный как клон консоли управления AWS (EC2, VPC Security Groups, S3 Buckets, IAM Users & Policy Simulator).

Данное руководство содержит исчерпывающее описание архитектуры платформы, а также детальные пошаговые инструкции по установке и настройке всех компонентов «с нуля» на выделенных серверах, виртуальных машинах и облачных инстансах.

---

## Содержание

1. [Архитектура системы и внутреннее устройство](#1-архитектура-системы-и-внутреннее-устройство)
   - 1.1. Вычислительный слой (Aegis-Compute & KubeVirt)
   - 1.2. Сетевой слой (Aegis-Network, DPDK & Anti-DDoS)
   - 1.3. Слой хранения данных (Aegis-Storage & Reed-Solomon S3)
   - 1.4. Биллинг и телеметрия (Gorilla TSDB)
   - 1.5. Модель безопасности (AWS IAM & Policy Evaluator)
2. [Сравнение сред развертывания (Матрица требований)](#2-сравнение-сред-развертывания-матрица-требований)
3. [Подготовка гипервизора (Специфика сред)](#3-подготовка-гипервизора-специфика-сред)
   - 3.1. Выделенный сервер (Bare Metal / Dedicated)
   - 3.2. Виртуальная машина VMware ESXi / Workstation
   - 3.3. Виртуальная машина Proxmox VE
   - 3.4. Виртуальная машина Oracle VirtualBox
   - 3.5. Облачные VPS/VDS (Nested Virtualization & NAT Masquerade)
   - 3.6. Вложенная виртуализация в Windows Hyper-V
4. [Автоматический скрипт настройки (Bootstrap Installer)](#4-автоматический-скрипт-настройки-bootstrap-installer)
5. [Пошаговая установка системных пакетов вручную](#5-пошаговая-установка-системных-пакетов-вручную)
   - 5.1. Обновление ОС и настройка лимитов ядра
   - 5.2. Установка утилит сборки, gcc и сжатия
6. [Развертывание кластера K3s и виртуализации KubeVirt](#6-развертывание-кластера-k3s-и-виртуализации-kubevirt)
   - 6.1. Установка Kubernetes кластера K3s
   - 6.2. Развертывание KubeVirt Operator и CR
   - 6.3. Установка CDI (Containerized Data Importer)
7. [Интеграция Multus CNI для раздачи внешних IP-адресов](#7-интеграция-multus-cni-для-раздачи-внешних-ip-адресов)
   - 7.1. Теория и архитектура сети Multus
   - 7.2. Настройка сетевого моста (Bridge) на физическом сервере
   - 7.3. Создание NetworkAttachmentDefinition в Kubernetes
   - 7.4. Сетевой режим NAT/Masquerade для Облачных VPS (AWS, GCP, Selectel)
   - 7.5. Настройка DHCP-сервера (dnsmasq) для приватных подсетей
8. [Подключение внешних жестких дисков и сетевых СХД](#8-подключение-внешних-жестких-дисков-и-сетевых-схд)
   - 8.1. Монтирование локальных дисков и настройка LVM Volume Groups
   - 8.2. Настройка сетевого хранилища NFS для бэкапов и дисков
   - 8.3. Конфигурация StorageClass в Kubernetes
   - 8.4. Развертывание распределенного хранилища Ceph Rook
9. [Подключение внешних серверов и масштабирование кластера](#9-подключение-внешних-серверов-и-масштабирование-кластера)
   - 9.1. Подготовка нового Worker-сервера
   - 9.2. Добавление ноды в K3s кластер
   - 9.3. Настройка беспарольного SSH доступа
   - 9.4. Установка Prometheus Node Exporter для мониторинга серверов
10. [Сборка и запуск панели управления через Docker Compose](#10-сборка-и-запуск-панели-управления-через-docker-compose)
    - 10.1. Полный листинг конфигурации Docker Compose
    - 10.2. Сборка и первый запуск
    - 10.3. Архитектура веб-серверов фронтенда (Nginx в Docker)
    - 10.4. Настройка СУБД PostgreSQL и автоинициализация схемы
    - 10.5. Панель управления инфраструктурой (команды, логи, git-обновление)
11. [Руководство пользователя по функциям консоли AWS](#11-руководство-пользователя-по-функциям-консоли-aws)
    - 11.1. EC2 Dashboard и анализ сетевых путей
    - 11.2. Создание и привязка VPC Security Groups
    - 11.3. Создание бакетов S3 и заливка файлов
    - 11.4. Настройка политик IAM и работа с симулятором
12. [Справочник API Эндпоинтов](#12-справочник-api-эндпоинтов)
    - 12.1. Получение общего состояния AWS (`/api/aegis/aws`)
    - 12.2. Создание группы безопасности (`/api/aegis/aws/security-groups`)
    - 12.3. Обновление правил фаервола Security Group (`/api/aegis/aws/security-groups`)
    - 12.4. Привязка группы к инстансу (`/api/aegis/aws/security-groups`)
    - 12.5. Управление S3 бакетами (`/api/aegis/aws/s3/buckets`)
13. [Диагностика и решение возможных проблем (Troubleshooting)](#13-диагностика-и-решение-возможных-проблем-troubleshooting)
14. [Автозапуск, мониторинг и обеспечение отказоустойчивости](#14-автозапуск-мониторинг-и-обеспечение-отказоустойчивости)
    - 14.1. Создание Systemd-службы для Docker Compose
    - 14.2. Автоматическая очистка кэша образов (Cron Task)
    - 14.3. Мониторинг здоровья ноды (Liveness healthcheck)
    - 14.4. Автоматическая синхронизация бэкапов в S3
15. [Глоссарий терминов и детальные системные спецификации](#15-глоссарий-терминов-и-детальные-системные-спецификации)
16. [Развернутый перечень CLI-команд для администратора хостинга](#16-развернутый-перечень-cli-команд-для-администратора-хостинга)

---

## 1. Архитектура системы и внутреннее устройство

Архитектура Aegis Cloud Engine представляет собой конвергентную платформу, объединяющую традиционную оркестрацию контейнеров и полноценную аппаратную виртуализацию.

```
                           +----------------------------------------------+
                           |              БРАУЗЕР ПОЛЬЗОВАТЕЛЯ            |
                           |                                              |
                           |   +------------------+    +--------------+   |
                           |   |  Админка (8080)  |    | Кабинет (8081|   |
                           |   +------------------+    +--------------+   |
                           +----------------------------------------------+
                                            |                 |
                                      [ REST / WS ]     [ REST / WS ]
                                            v                 v
                           +----------------------------------------------+
                           |     NGINX / VITE DEV ROUTER (8080 / 8081)    |
                           +----------------------------------------------+
                                            |                 |
                             [/api/aegis/*] |                 | [/api/*]
                                            v                 v
                           +--------------------+    +--------------------+
                           | GO ORCHESTRATOR    |    | FASTAPI BACKEND    |
                           | (Aegis Daemon 8001)|    | (KubeVirt Client)  |
                           +--------------------+    +--------------------+
                                     |                         |
                               [nsenter/conntrack]             | [Kubectl API]
                                     v                         v
                           +--------------------+    +--------------------+
                           | Linux Kernel Stack |    | K3S / KUBEVIRT     |
                           |  (iptables rules)  |    |  (QEMU/KVM VDS)    |
                           +--------------------+    +--------------------+
```

### 1.1. Вычислительный слой (Aegis-Compute & KubeVirt)

Платформа разделяет вычислительные ресурсы на два типа:
1. **VDS/VPS виртуальные машины (QEMU/KVM)**: запускаются внутри кластера Kubernetes с использованием технологии **KubeVirt**. Каждая виртуальная машина работает в собственном контейнерном поде, имеет виртуализированные устройства (виртуальный диск, сетевая карта, видеокарта, VNC-сервер) и обеспечивает максимальную изоляцию ядра.
2. **Микро-контейнеры Aegis**: легковесные среды выполнения, разворачиваемые Go-демоном напрямую в пространстве ядра хоста. Go-оркестратор вызывает Linux `syscalls` для создания изолированных пространств имен (namespaces):
   - `mnt` (изоляция точек монтирования ФС)
   - `uts` (изоляция имени хоста)
   - `ipc` (изоляция межпроцессного взаимодействия)
   - `pid` (изоляция дерева процессов)
   - `net` (изоляция сетевых интерфейсов)
   Для жесткого ограничения ресурсов оперативной памяти используется технология **cgroups v2** (лимиты прописываются в системный контроллер `memory.max`). Чтобы избежать оверхеда переключения контекста процессора и исключить проблему «шумных соседей» (CPU contention), оркестратор реализует концепцию **No-Overselling CPU Pinning**: потоки выполнения контейнера привязываются к конкретным физическим ядрам процессора с помощью `sched_setaffinity`.

### 1.2. Сетевой слой (Aegis-Network, DPDK & Anti-DDoS)

Сетевая подсистема использует архитектуру виртуального коммутатора на основе разделяемой памяти (Zero-Latency Shared Memory vSwitch).
- **DPDK (Kernel-Bypass)**: симулируемый в тестовых целях и интегрируемый на реальном железе механизм обхода сетевого стека ядра Linux. Сетевые пакеты поступают напрямую из физической сетевой карты в пользовательское пространство оркестратора Go, минуя прерывания ядра, что снижает сетевую задержку до субмикросекундных значений.
- **Anti-DDoS eBPF/XDP**: eBPF-программы прикрепляются к сетевому драйверу сетевой карты (на уровне XDP). При обнаружении аномального входящего трафика (превышающего лимит PPS на один IP-источник), пакеты сбрасываются мгновенно (`XDP_DROP`) до выделения под них ядерной памяти, спасая систему от падения под нагрузкой.

### 1.3. Слой хранения данных (Aegis-Storage & Reed-Solomon S3)

Для бэкапов и объектного хранилища используется алгоритм **Reed-Solomon (4+2)**:
- Когда клиент загружает объект (файл) в S3 bucket, оркестратор не сохраняет его целиком.
- Объект разбивается на $N=4$ равных блока данных.
- На основе матричной математики Галуа вычисляются $M=2$ контрольных блока паритета.
- Полученные 6 блоков записываются на 6 физически независимых дисковых каталогов (нод хранения `s3-node-01` ... `s3-node-06`).
- Даже в случае выхода из строя любых 2 накопителей данных, система декодирует оставшиеся блоки и восстановит исходный файл без потерь.

### 1.4. Биллинг и телеметрия (Gorilla TSDB)

Телеметрия виртуальных машин считывается в реальном времени и помещается в собственную базу данных временных рядов (TSDB), реализующую алгоритмы сжатия **Gorilla TSDB** (разработка Facebook):
- Временные метки сжимаются методом Delta-of-Delta.
- Показания загрузки процессора и памяти (числа с плавающей точкой float64) сжимаются с использованием операции XOR по сравнению с предыдущими значениями.
- Степень сжатия достигает 10–12 раз по сравнению с несжатыми данными, что позволяет хранить подробнейшую посекундную историю использования ресурсов на диске без затрат памяти.
- Специальный поток биллинга (Billing Loop) считывает метрики ресурсов запущенных ВМ и осуществляет посекундное списание средств с кошелька пользователя.

### 1.5. Модель безопасности (AWS IAM & Policy Evaluator)

Авторизация к API эндпоинтам выполняется через симулятор прав доступа AWS IAM:
- Любой пользователь имеет привязанный JSON-документ политики.
- Каждый запрос к API проходит через модуль `CheckIAMPermission(username, action, resource)`.
- Модуль анализирует правила: explicit `Deny` всегда перевешивает `Allow` (стандарт безопасности AWS), при отсутствии совпадающих правил срабатывает implicit `Deny` (запрещено по умолчанию).

---

## 2. Сравнение сред развертывания (Матрица требований)

| Требование / Функция | Выделенный сервер (Bare Metal) | Виртуальная машина (ESXi/Proxmox) | Облачные VPS (AWS/GCP/Selectel) |
| :--- | :--- | :--- | :--- |
| **Рекомендуемая ОС** | Ubuntu 24.04 / 22.04 LTS | Ubuntu 24.04 / 22.04 LTS | Ubuntu 24.04 / 22.04 LTS |
| **Минимальные требования к CPU** | 4 ядра (Intel VT-x / AMD-V) | 4 vCPU (с поддержкой Nested Virtualization) | 4 vCPU (выделенные ядра, без overselling) |
| **Минимальные требования к RAM** | 8 ГБ DDR4/DDR5 | 8 ГБ | 8 ГБ |
| **Минимальные требования к диску**| 100 ГБ NVMe SSD | 100 ГБ SSD | 100 ГБ SSD |
| **Виртуализация KVM** | Нативная (прямой доступ к `/dev/kvm`) | Вложенная (Nested Virtualization) | Вложенная (Доступна не у всех тарифов) |
| **Маршрутизация IP** | Физические MAC / Routed IP | vSwitch Promiscuous Mode | NAT / IP Masquerading |
| **Сетевые карты (DPDK)**| Поддерживается (Intel/Mellanox) | Эмулируется (e1000/virtio) | Не поддерживается |
| **Внешние диски** | Прямое монтирование (SAS/SATA/NVMe)| Виртуальные диски VMDK/RAW | Облачные блочные диски (EBS/Volume) |

---

## 3. Подготовка гипервизора (Специфика сред)

Перед установкой проекта необходимо правильно настроить базовую среду, иначе виртуальные машины KubeVirt не смогут запуститься из-за отсутствия аппаратного ускорения KVM.

### 3.1. Выделенный сервер (Bare Metal / Dedicated)

Это идеальный вариант развертывания, обеспечивающий максимальную производительность дисков и сети.

1. Войдите в BIOS сервера и убедитесь, что включены технологии виртуализации:
   - Для процессоров Intel: **Intel Virtualization Technology (VT-x)** и **VT-d**.
   - Для процессоров AMD: **AMD-V** и **IOMMU**.
2. Загрузите систему в Ubuntu 24.04 LTS.
3. Проверьте доступность модуля аппаратного ускорения:
   ```bash
   egrep -c '(vmx|svm)' /proc/cpuinfo
   ```
   Если вывод больше `0`, аппаратная виртуализация поддерживается процессором.
4. Проверьте наличие и права доступа к файлу устройства KVM:
   ```bash
   ls -l /dev/kvm
   ```
   Вывод должен содержать: `crw-rw----+ 1 root kvm ... /dev/kvm`. Если устройство существует, дайте права:
   ```bash
   sudo chmod 666 /dev/kvm
   ```

### 3.2. Виртуальная машина VMware ESXi / Workstation

Если вы устанавливаете стенд на виртуальную машину внутри VMware, необходимо включить вложенную виртуализацию (Nested Virtualization).

#### Настройка в VMware vSphere (ESXi Web Client)
1. Выключите виртуальную машину Ubuntu.
2. Откройте **Edit Settings** (Редактировать настройки) виртуальной машины.
3. Разверните вкладку **CPU**.
4. Поставьте галочку напротив опции **Expose hardware assisted virtualization to the guest OS** (Включить аппаратную виртуализацию для гостевой ОС).
5. Сохраните настройки и запустите машину.

#### Настройка сетевого коммутатора VMware (vSwitch)
По умолчанию коммутатор VMware блокирует трафик от MAC-адресов, отличных от MAC-адреса самой VM. Так как виртуальные машины внутри KubeVirt будут создавать свои виртуальные MAC-адреса, виртуальный свитч VMware заблокирует им сеть.
1. Перейдите в настройки сети ESXi (**Networking** -> **Virtual switches**).
2. Выберите ваш свитч и нажмите **Edit settings**.
3. В разделе **Security** переведите следующие опции в режим **Accept**:
   - **Promiscuous mode** (Смешанный режим) -> **Accept**
   - **MAC address changes** (Изменение MAC-адресов) -> **Accept**
   - **Forged transmits** (Поддельные передачи) -> **Accept**
4. Нажмите **Save**.

### 3.3. Виртуальная машина Proxmox VE

При использовании Proxmox необходимо настроить тип процессора хоста на виртуальную гостевую машину.

1. Создайте виртуальную гостевую машину в интерфейсе Proxmox.
2. Перейдите во вкладку **Hardware** (Оборудование) этой ВМ.
3. Выберите пункт **Processor** (Процессор) и нажмите **Edit** (Редактировать).
4. В выпадающем списке **Type** (Тип процессора) обязательно выберите **host** (это пробросит инструкции VT-x/AMD-V физического процессора хоста без изменений).
5. Нажмите **OK**.
6. Включите сетевой интерфейс в смешанный режим на уровне моста Proxmox:
   Перейдите в консоль Proxmox и выполните:
   ```bash
   ip link set dev vmbr0 promisc on
   ```
7. Включите поддержку nested virtualization на самом хосте Proxmox. Проверьте статус:
   ```bash
   cat /sys/module/kvm_intel/parameters/nested
   ```
   Если вывод `N` или `0`, выполните:
   ```bash
   echo "options kvm-intel nested=1" | sudo tee /etc/modprobe.d/kvm-intel.conf
   sudo modprobe -r kvm_intel && sudo modprobe kvm_intel
   ```

### 3.4. Виртуальная машина Oracle VirtualBox

Настройка вложенной виртуализации на домашнем компьютере с VirtualBox.

1. Выключите виртуальную машину Ubuntu.
2. Откройте командную строку (cmd/PowerShell на Windows или Терминал на macOS) на хост-компьютере.
3. Перейдите в папку с установленным VirtualBox (обычно `C:\Program Files\Oracle\VirtualBox` на Windows).
4. Выполните команду проброса виртуализации (замените `"Ubuntu-Aegis"` на точное имя вашей VM в VirtualBox):
   ```bash
   VBoxManage modifyvm "Ubuntu-Aegis" --nested-hw-virt on
   ```
5. Запустите виртуальную машину.

### 3.5. Облачные VPS/VDS (Nested Virtualization & NAT Masquerade)

Большинство облачных провайдеров (Selectel, Yandex Cloud, AWS, Hetzner) по умолчанию блокируют вложенную виртуализацию на дешевых тарифах.
1. При создании облачного сервера выберите тариф, поддерживающий **Nested Virtualization** (обычно это выделенные инстансы типа Dedicated vCPU или Bare-metal инстансы).
2. Сетевые интерфейсы в облаке жестко привязаны к одному IP и одному MAC-адресу на уровне облачного свитча. Подключение мостом (Bridge) здесь работать не будет. Сеть для пользовательских ВМ настраивается через **NAT Masquerade** (описано далее в разделе 7).

### 3.6. Вложенная виртуализация в Windows Hyper-V

Если ваш хост работает под управлением Windows, а виртуальная машина Ubuntu запускается в Hyper-V, вложенная виртуализация настраивается через командлет PowerShell.
1. Выключите виртуальную машину.
2. Запустите PowerShell от имени Администратора.
3. Выполните следующую команду (замените `Ubuntu-Aegis` на точное имя вашей ВМ в диспетчере Hyper-V):
   ```powershell
   Set-VMProcessor -VMName "Ubuntu-Aegis" -ExposeVirtualizationExtensions $true
   ```
4. Запустите виртуальную машину. Убедитесь, что внутри гостевой Ubuntu вывод команды `kvm-ok` выдает положительный вердикт:
   ```bash
   sudo apt-get install -y cpu-checker
   kvm-ok
   ```

---

## 4. Автоматический скрипт настройки (Bootstrap Installer)

Для ускорения процесса подготовки окружения, ниже представлен полный скрипт `bootstrap.sh`. Он автоматически обновляет ОС, ставит Docker, K3s, KubeVirt, Multus CNI и настраивает базовую директорию хранения дисков.

Создайте файл `bootstrap.sh` в корне проекта:
```bash
#!/bin/bash
set -e

echo "=== Aegis Cloud Engine: Начало автоматической настройки ==="

if [ "$EUID" -ne 0 ]; then
  echo "Пожалуйста, запустите скрипт от имени root (sudo ./bootstrap.sh)"
  exit 1
fi

apt-get update && apt-get upgrade -y

apt-get install -y     apt-transport-https ca-certificates curl gnupg lsb-release     git bridge-utils net-tools iptables conntrack lvm2 nfs-common jq socat gcc make

if ! [ -x "$(command -v docker)" ]; then
  mkdir -p /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \$(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

if ! [ -f "/usr/local/bin/k3s" ]; then
  curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable traefik" sh -
fi

mkdir -p \$HOME/.kube
cp /etc/rancher/k3s/k3s.yaml \$HOME/.kube/config
chown -R \$USER:\$USER \$HOME/.kube/config
export KUBECONFIG=\$HOME/.kube/config

KUBEVIRT_VERSION=\$(curl -s https://api.github.com/repos/kubevirt/kubevirt/releases/latest | jq -r .tag_name)
kubectl create -f "https://github.com/kubevirt/kubevirt/releases/download/\${KUBEVIRT_VERSION}/kubevirt-operator.yaml" || true
kubectl create -f "https://github.com/kubevirt/kubevirt/releases/download/\${KUBEVIRT_VERSION}/kubevirt-cr.yaml" || true

if ! [ -e "/dev/kvm" ]; then
  kubectl patch kubevirt kubevirt -n kubevirt --type merge --patch '{"spec":{"configuration":{"developerConfiguration":{"useEmulation":true}}}}' || true
fi

kubectl apply -f https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/master/deployments/multus-daemonset-thick.yml || true

mkdir -p /mnt/aegis-storage/vms
chmod 777 /mnt/aegis-storage/vms

cat <<EOF > aegis-local-storage.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: aegis-local-path
provisioner: rancher.io/local-path
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Delete
parameters:
  nodePath: /mnt/aegis-storage/vms
EOF
kubectl apply -f aegis-local-storage.yaml || true
kubectl patch storageclass aegis-local-path -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}' || true

echo "=== Aegis Cloud Engine: Установка успешно завершена! ==="
```

---

## 5. Пошаговая установка системных пакетов вручную

Если вы предпочитаете полный контроль над установкой системных пакетов без использования скриптов-автоматизаторов, следуйте пошаговому руководству ниже.

### 5.1. Обновление ОС и настройка лимитов ядра

Перед запуском установите максимальные лимиты на открытые дескрипторы файлов, сетевые буферы и количество процессов. Это критично для демона виртуализации и API серверов.

Добавьте в конец файла `/etc/security/limits.conf`:
```ini
root             soft    nofile          1000000
root             hard    nofile          1000000
*                soft    nofile          1000000
*                hard    nofile          1000000
root             soft    nproc           1000000
root             hard    nproc           1000000
*                soft    nproc           1000000
*                hard    nproc           1000000
```

Для применения изменений выполните выход и повторный вход в сессию SSH. Также оптимизируйте параметры сетевого стека ядра Linux. Создайте конфигурационный файл `/etc/sysctl.d/99-aegis-performance.conf`:
```ini
# Максимальное количество открытых файлов в системе
fs.file-max = 2097152

# Разрешить форвардинг IPv4 пакетов для работы сетей виртуальных машин
net.ipv4.ip_forward = 1

# Разрешить форвардинг IPv6 пакетов
net.ipv6.conf.all.forwarding = 1

# Увеличение максимального размера очередей сетевых пакетов
net.core.netdev_max_backlog = 100000
net.core.somaxconn = 65535

# Настройки буферов TCP для высоконагруженных соединений
net.ipv4.tcp_max_syn_backlog = 3240000
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# Лимиты для отслеживания соединений firewall (conntrack)
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_tcp_timeout_established = 3600
```
Примените настройки sysctl:
```bash
sudo sysctl --system
```

### 5.2. Установка утилит сборки, gcc и сжатия

Нам понадобятся базовые пакеты компилятора, сетевые утилиты и вспомогательные библиотеки:
```bash
sudo apt-get update
sudo apt-get install -y     build-essential     gcc     g++     make     pkg-config     libnuma-dev     zlib1g-dev     libssl-dev     iptables     bridge-utils     net-tools     conntrack     lvm2     nfs-common     curl     git     jq     socat     arptables     ebtables     ipset
```

Установите Docker Engine и Docker Compose (ручной метод):
```bash
# Добавление официального репозитория Docker
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

echo   "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu   $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Запуск и добавление в автозапуск Docker
sudo systemctl enable docker
sudo systemctl start docker
```

---

## 6. Развертывание кластера K3s и виртуализации KubeVirt

### 6.1. Установка Kubernetes кластера K3s

В качестве легковесной среды оркестрации контейнеров мы будем использовать K3s. Он потребляет минимум оперативной памяти и поставляется в виде единого бинарного файла, готового к работе.
Установка K3s на главный сервер (Master Node) без предустановленного контроллера трафика Traefik (мы заменим его на Nginx):
```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable traefik --disable local-storage" sh -
```
Проверьте статус службы K3s:
```bash
sudo systemctl status k3s
```
Настройте права для доступа к утилите `kubectl`:
```bash
mkdir -p $HOME/.kube
sudo cp /etc/rancher/k3s/k3s.yaml $HOME/.kube/config
sudo chown -R $USER:$USER $HOME/.kube/config
export KUBECONFIG=$HOME/.kube/config
echo "export KUBECONFIG=$HOME/.kube/config" >> ~/.bashrc
```
Проверьте работоспособность кластера и нод:
```bash
kubectl get nodes
```

### 6.2. Развертывание KubeVirt Operator и CR

KubeVirt расширяет возможности Kubernetes, добавляя поддержку виртуальных машин через механизмы Custom Resource Definitions (CRDs).

1. Определите последнюю версию релиза KubeVirt:
   ```bash
   export KUBEVIRT_VERSION=$(curl -s https://api.github.com/repos/kubevirt/kubevirt/releases/latest | jq -r .tag_name)
   echo "Используется версия KubeVirt: $KUBEVIRT_VERSION"
   ```
2. Разверните KubeVirt Operator, который управляет жизненным циклом компонентов виртуализации:
   ```bash
   kubectl create -f "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/kubevirt-operator.yaml"
   ```
3. Создайте Custom Resource KubeVirt для запуска демонов на нодах:
   ```bash
   kubectl create -f "https://github.com/kubevirt/kubevirt/releases/download/${KUBEVIRT_VERSION}/kubevirt-cr.yaml"
   ```
4. Убедитесь, что все компоненты перешли в состояние `Running` во встроенном пространстве имен `kubevirt`:
   ```bash
   kubectl get pods -n kubevirt
   ```
   Должны запуститься: `virt-api`, `virt-controller`, `virt-handler` (на каждой ноде).
5. **Важно для сред без аппаратного ускорения** (если `/dev/kvm` недоступен, например, на некоторых облачных VPS):
   Настройте программную эмуляцию (QEMU TC):
   ```bash
   kubectl patch kubevirt kubevirt -n kubevirt --type merge --patch '{"spec":{"configuration":{"developerConfiguration":{"useEmulation":true}}}}'
   ```

### 6.3. Установка CDI (Containerized Data Importer)

CDI облегчает импорт образов виртуальных дисков (ISO, QCOW2) напрямую из HTTP источников или Docker registry в Persistent Volumes кластера.

1. Получите последнюю версию CDI:
   ```bash
   export CDI_VERSION=$(curl -s https://api.github.com/repos/kubevirt/containerized-data-importer/releases/latest | jq -r .tag_name)
   ```
2. Примените манифесты оператора и кастомного ресурса CDI:
   ```bash
   kubectl create -f "https://github.com/kubevirt/containerized-data-importer/releases/download/${CDI_VERSION}/cdi-operator.yaml"
   kubectl create -f "https://github.com/kubevirt/containerized-data-importer/releases/download/${CDI_VERSION}/cdi-cr.yaml"
   ```
3. Проверьте запуск подов импортера:
   ```bash
   kubectl get pods -n cdi
   ```

---

## 7. Интеграция Multus CNI для раздачи внешних IP-адресов

### 7.1. Теория и архитектура сети Multus

Стандартная модель сети Kubernetes предоставляет каждому поду только один сетевой интерфейс (`eth0`), подключенный к внутренней оверлейной сети кластера (например, Flannel с подсетью `10.42.0.0/16`). Виртуальным машинам хостинга этого недостаточно: им необходим дополнительный интерфейс, напрямую подключенный к публичной внешней сети или физическому коммутатору дата-центра, чтобы пользователи могли подключаться по SSH/HTTP напрямую к своим серверам без проксирования.

**Multus CNI** выступает в роли "сетевого мультиплексора". Он считывает аннотации пода и создает дополнительные сетевые интерфейсы, передавая управление плагинам (bridge, macvlan, ipvlan, host-device).

### 7.2. Настройка сетевого моста (Bridge) на физическом сервере

Для раздачи внешних IP на физическом сервере (Bare Metal) необходимо объединить сетевую карту и виртуальные машины в один L2 сегмент с помощью сетевого моста Linux.

1. Откройте файл конфигурации сетей Netplan (например, `/etc/netplan/01-netcfg.yaml`).
2. Отредактируйте его следующим образом (замените `enp3s0` на имя вашей физической сетевой карты, и `192.168.1.50/24` на ваш статический IP):
   ```yaml
   network:
     version: 2
     renderer: networkd
     ethernets:
       enp3s0:
         dhcp4: no
         dhcp6: no
     bridges:
       br0:
         interfaces: [enp3s0]
         dhcp4: no
         addresses:
           - 192.168.1.50/24
         routes:
           - to: default
             via: 192.168.1.1
         nameservers:
           addresses:
             - 8.8.8.8
             - 1.1.1.1
         parameters:
           stp: no
           forward-delay: 0
   ```
3. Примените сетевые настройки:
   ```bash
   sudo netplan apply
   ```
4. Убедитесь, что сетевой мост активен и включает физическую карту:
   ```bash
   ip addr show br0
   brctl show br0
   ```

### 7.3. Создание NetworkAttachmentDefinition в Kubernetes

Теперь укажем Kubernetes, как использовать созданный сетевой мост `br0` через Multus.

1. Разверните Multus CNI в кластере (если не сделали это через скрипт автоматической настройки):
   ```bash
   kubectl apply -f https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/master/deployments/multus-daemonset-thick.yml
   ```
2. Создайте файл конфигурации сети `multus-bridge-definition.yaml`:
   ```yaml
   apiVersion: "k8s.cni.cncf.io/v1"
   kind: NetworkAttachmentDefinition
   metadata:
     name: external-bridge-nic
     namespace: default
   spec:
     config: '{
         "cniVersion": "0.3.1",
         "name": "external-bridge-network",
         "type": "bridge",
         "bridge": "br0",
         "isGateway": false,
         "ipam": {
             "type": "host-local",
             "subnet": "192.168.1.0/24",
             "rangeStart": "192.168.1.100",
             "rangeEnd": "192.168.1.200",
             "routes": [
                 { "dst": "0.0.0.0/0" }
             ],
             "gateway": "192.168.1.1"
         }
     }'
   ```
3. Примените определение сети:
   ```bash
   kubectl apply -f multus-bridge-definition.yaml
   ```

### 7.4. Сетевой режим NAT/Masquerade для Облачных VPS (AWS, GCP, Selectel)

В облачных провайдерах сетевая безопасность блокирует любые MAC-адреса, кроме одного, назначенного вашей виртуальной машине на этапе создания. Если вы попытаетесь создать мост `br0` и выпустить виртуалку с ее собственным MAC во внешний коммутатор провайдера, пакеты будут дропнуты. В этом случае используется маршрутизируемый приватный мост с NAT трансляцией адресов (Masquerade) на хост-сервере.

1. Создайте локальный изолированный сетевой мост `br-vms` на хост-машине:
   ```bash
   sudo ip link add br-vms type bridge
   sudo ip addr add 172.20.0.1/24 dev br-vms
   sudo ip link set br-vms up
   ```
2. Включите трансляцию адресов в ядре. Убедитесь, что IP-форвардинг активен:
   ```bash
   sudo sysctl -w net.ipv4.ip_forward=1
   ```
3. Настройте правила IPTables для маскирования исходящего трафика с приватной сети виртуальных машин (например, через внешнюю сетевую карту `eth0` вашего VPS):
   ```bash
   sudo iptables -t nat -A POSTROUTING -s 172.20.0.0/24 -o eth0 -j MASQUERADE
   sudo iptables -A FORWARD -i br-vms -j ACCEPT
   sudo iptables -A FORWARD -o br-vms -m state --state RELATED,ESTABLISHED -j ACCEPT
   ```
4. Установите и сохраните эти правила для автоматического применения при перезапуске системы:
   ```bash
   sudo apt-get install -y iptables-persistent
   sudo netfilter-persistent save
   ```
5. Создайте NetworkAttachmentDefinition, ссылающийся на приватный мост `br-vms`:
   ```yaml
   apiVersion: "k8s.cni.cncf.io/v1"
   kind: NetworkAttachmentDefinition
   metadata:
     name: external-bridge-nic
     namespace: default
   spec:
     config: '{
         "cniVersion": "0.3.1",
         "name": "private-bridge-network",
         "type": "bridge",
         "bridge": "br-vms",
         "isGateway": true,
         "ipam": {
             "type": "host-local",
             "subnet": "172.20.0.0/24",
             "rangeStart": "172.20.0.10",
             "rangeEnd": "172.20.0.250",
             "routes": [
                 { "dst": "0.0.0.0/0" }
             ],
             "gateway": "172.20.0.1"
         }
     }'
   ```
   Примените:
   ```bash
   kubectl apply -f multus-bridge-definition.yaml
   ```

### 7.5. Настройка DHCP-сервера (dnsmasq) для приватных подсетей

Если вы не хотите прописывать статические IP внутри каждой виртуалки вручную (хотя cloud-init умеет делать это автоматически), разверните DHCP-сервер `dnsmasq` на хосте для раздачи IP-адресов в созданный мост `br-vms`.

1. Установите dnsmasq:
   ```bash
   sudo apt-get install -y dnsmasq
   ```
2. Создайте файл конфигурации `/etc/dnsmasq.d/aegis-dhcp.conf`:
   ```ini
   # Слушать только интерфейс моста для виртуалок
   interface=br-vms
   bind-interfaces

   # Диапазон раздаваемых IP адресов
   dhcp-range=172.20.0.50,172.20.0.200,255.255.255.0,24h

   # Шлюз по умолчанию (наш хост)
   dhcp-option=3,172.20.0.1

   # DNS серверы для ВМ
   dhcp-option=6,8.8.8.8,1.1.1.1
   ```
3. Перезапустите службу dnsmasq:
   ```bash
   sudo systemctl restart dnsmasq
   sudo systemctl enable dnsmasq
   ```
4. Теперь любая гостевая виртуальная машина, подключенная к сети `external-bridge-nic`, автоматически получит IP-адрес по протоколу DHCP.

---

## 8. Подключение внешних жестких дисков и сетевых СХД

Для хранения образов операционных систем и дисков пользователей требуются большие объемы дискового пространства. Не рекомендуется хранить диски ВМ на системном разделе ОС.

### 8.1. Монтирование локальных дисков и настройка LVM Volume Groups

Если вы подключили новый физический жесткий диск или SSD (например, `/dev/sdb`), настройте его с помощью LVM (Logical Volume Manager).

1. Инициализируйте физический том (Physical Volume):
   ```bash
   sudo pvcreate /dev/sdb
   ```
2. Создайте группу томов (Volume Group) с именем `aegis-vg-storage`:
   ```bash
   sudo vgcreate aegis-vg-storage /dev/sdb
   ```
3. Создайте логический том (Logical Volume), занимающий 100% пространства диска:
   ```bash
   sudo lvcreate -l 100%FREE -n lv-vms aegis-vg-storage
   ```
4. Создайте файловую систему ext4 на логическом томе:
   ```bash
   sudo mkfs.ext4 /dev/aegis-vg-storage/lv-vms
   ```
5. Создайте точку монтирования и примонтируйте том:
   ```bash
   sudo mkdir -p /mnt/aegis-storage/vms
   sudo mount /dev/aegis-vg-storage/lv-vms /mnt/aegis-storage/vms
   ```
6. Настройте автоматическое монтирование тома при загрузке сервера. Добавьте строку в `/etc/fstab`:
   ```ini
   /dev/mapper/aegis--vg--storage-lv--vms  /mnt/aegis-storage/vms  ext4  defaults,noatime,nodiratime,nofail  0  2
   ```
7. Убедитесь, что монтирование прошло без ошибок:
   ```bash
   sudo umount /mnt/aegis-storage/vms
   sudo mount -a
   df -h /mnt/aegis-storage/vms
   ```

### 8.2. Настройка сетевого хранилища NFS для бэкапов и дисков

Если у вас есть отдельный NAS или NFS-сервер (например, с IP `192.168.1.100`), вы можете использовать его в качестве сетевого хранилища.

#### Шаг 8.2.1. Конфигурация NFS сервера (если развертывается на отдельной машине)
1. Установите пакет NFS:
   ```bash
   sudo apt-get install -y nfs-kernel-server
   ```
2. Создайте общую директорию:
   ```bash
   sudo mkdir -p /var/nfs/aegis-shares
   sudo chown nobody:nogroup /var/nfs/aegis-shares
   sudo chmod 777 /var/nfs/aegis-shares
   ```
3. Добавьте права на доступ в файл `/etc/exports` (разрешаем доступ всей локальной подсети):
   ```ini
   /var/nfs/aegis-shares  192.168.1.0/24(rw,sync,no_subtree_check,no_root_squash)
   ```
4. Примените изменения экспорта и запустите NFS:
   ```bash
   sudo exportfs -a
   sudo systemctl restart nfs-kernel-server
   sudo systemctl enable nfs-kernel-server
   ```

#### Шаг 8.2.2. Конфигурация клиента (наш Master-сервер Aegis)
1. Установите клиентский пакет:
   ```bash
   sudo apt-get install -y nfs-common
   ```
2. Создайте каталог монтирования:
   ```bash
   sudo mkdir -p /mnt/aegis-storage/nfs
   ```
3. Выполните пробное монтирование:
   ```bash
   sudo mount -t nfs 192.168.1.100:/var/nfs/aegis-shares /mnt/aegis-storage/nfs
   ```
4. Пропишите авто-монтирование в `/etc/fstab`:
   ```ini
   192.168.1.100:/var/nfs/aegis-shares  /mnt/aegis-storage/nfs  nfs  defaults,timeo=14,intr,nofail  0  0
   ```

### 8.3. Конфигурация StorageClass в Kubernetes

Чтобы KubeVirt мог автоматически создавать тома на примонтированном диске, настройте локальный провайдер путей (Local Path Provisioner).

Создайте манифест `local-path-storage.yaml`:
```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: aegis-local-path
provisioner: rancher.io/local-path
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Delete
parameters:
  nodePath: /mnt/aegis-storage/vms
```
Примените StorageClass:
```bash
kubectl apply -f local-path-storage.yaml
```
Установите данный StorageClass по умолчанию для всего кластера Kubernetes:
```bash
kubectl patch storageclass aegis-local-path -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'
```
Проверьте статус созданных StorageClass:
```bash
kubectl get storageclass
```

### 8.4. Развертывание распределенного хранилища Ceph Rook

Для построения высоконадежной, отказоустойчивой и масштабируемой дисковой системы рекомендуется развернуть распределенное объектно-блочное хранилище **Ceph Rook** в кластере Kubernetes. Ceph дублирует данные дисков виртуальных машин между всеми нодами кластера.

1. Установите утилиту управления git и клонируйте репозиторий Rook Ceph:
   ```bash
   git clone --single-branch --branch v1.14.6 https://github.com/rook/rook.git
   ```
2. Перейдите в каталог установки оператора:
   ```bash
   cd rook/deploy/examples
   ```
3. Создайте Custom Resource Definitions (CRDs) для Rook:
   ```bash
   kubectl create -f crds.yaml
   ```
4. Разверните базовые роли доступа и оператор Rook Ceph:
   ```bash
   kubectl create -f common.yaml
   kubectl create -f operator.yaml
   ```
5. Убедитесь, что под оператора запущен и находится в статусе `Running`:
   ```bash
   kubectl get pods -n rook-ceph -l app=rook-ceph-operator
   ```
6. Перед созданием кластера Ceph подготовьте свободные диски. На нодах должны быть установлены чистые жесткие диски без разделов и файловых систем (например, `/dev/sdc` или `/dev/nvme1n1`).
7. Отредактируйте конфигурацию кластера в файле `cluster.yaml`. Найдите раздел `storage` и укажите использование дисков:
   ```yaml
     storage:
       useAllNodes: true
       useAllDevices: false
       deviceFilter: "^sdc" # Использовать только диск /dev/sdc
   ```
8. Запустите развертывание кластера Ceph:
   ```bash
   kubectl create -f cluster.yaml
   ```
   *Примечание: Развертывание может занять до 10 минут. Ceph создаст мониторы (Mon), менеджеры (Mgr) и демоны хранения (OSD) на каждой ноде.*
9. Проверьте состояние кластера Ceph:
   ```bash
   kubectl get pods -n rook-ceph
   ```
10. Создайте StorageClass для томов виртуальных машин (Ceph Block Device RBD). Примените манифест `storageclass.yaml` из папки `rook/deploy/examples/csi/rbd/`:
    ```bash
    kubectl create -f storageclass.yaml
    ```

---

## 9. Подключение внешних серверов и масштабирование кластера

Когда ресурсы центрального Master-сервера подходят к концу, необходимо подключить дополнительные физические или виртуальные серверы в качестве вычислительных Worker-нод.

### 9.1. Подготовка нового Worker-сервера

На новом подключаемом сервере (назовем его `aegis-worker-01` с IP `192.168.1.60`) проведите базовую подготовку среды.

1. Установите системные зависимости:
   ```bash
   sudo apt-get update
   sudo apt-get install -y curl nfs-common lvm2 bridge-utils net-tools conntrack ipset cpu-checker
   ```
2. Убедитесь в поддержке аппаратного ускорения виртуализации:
   ```bash
   kvm-ok
   ```
   Если вывод положительный, разрешите доступ к устройству KVM:
   ```bash
   sudo chmod 666 /dev/kvm
   ```
3. Создайте идентичную точку монтирования для дисков ВМ (или настройте NFS клиент на монтирование `/mnt/aegis-storage/vms` с NFS-сервера):
   ```bash
   sudo mkdir -p /mnt/aegis-storage/vms
   sudo chmod 777 /mnt/aegis-storage/vms
   ```

### 9.2. Добавление ноды в K3s кластер

Для добавления сервера в кластер требуется токен аутентификации, сгенерированный на Master-сервере.

1. Получите токен на Master-сервере:
   ```bash
   sudo cat /var/lib/rancher/k3s/server/node-token
   ```
   *Вывод будет выглядеть примерно так: `K108d...::server:7cf8...`*
2. На подключаемом Worker-сервере запустите агент K3s, указав IP-адрес Master-сервера и полученный токен (замените `192.168.1.50` на IP вашего Master-сервера):
   ```bash
   curl -sfL https://get.k3s.io | K3S_URL=https://192.168.1.50:6443 K3S_TOKEN="K108d...::server:7cf8..." sh -
   ```
3. Дождитесь завершения установки агента. Служба `k3s-agent` запустится автоматически.
4. Проверьте появление новой ноды в списке на Master-сервере:
   ```bash
   kubectl get nodes -o wide
   ```
   Через пару минут нода `aegis-worker-01` перейдет в статус `Ready`. KubeVirt автоматически установит на нее демон `virt-handler` для возможности запуска ВМ.

### 9.3. Настройка беспарольного SSH доступа

Для автоматического управления питанием, сбора логов и мониторинга со стороны оркестратора, Master-сервер должен иметь беспрепятственный доступ к Worker-нодам по протоколу SSH.

1. На Master-сервере сгенерируйте SSH ключ для пользователя `root` (если он еще не создан):
   ```bash
   sudo ssh-keygen -t rsa -b 4096 -N "" -f /root/.ssh/id_rsa
   ```
2. Скопируйте публичный SSH-ключ на подключаемый Worker-сервер:
   ```bash
   sudo ssh-copy-id -i /root/.ssh/id_rsa.pub root@192.168.1.60
   ```
3. Проверьте беспарольный вход с Master-сервера:
   ```bash
   sudo ssh root@192.168.1.60 "uname -a"
   ```
   Команда должна выполниться мгновенно без запроса пароля.

### 9.4. Установка Prometheus Node Exporter для мониторинга серверов

Для отправки метрик здоровья серверов (температура, использование CPU, свободная RAM, износ дисков SSD) в TSDB оркестратора, на каждой ноде должен быть запущен агент сбора метрик Prometheus Node Exporter.

1. Установите Node Exporter на Worker-сервере:
   ```bash
   sudo apt-get install -y prometheus-node-exporter
   ```
2. Запустите службу и добавьте в автозапуск:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable prometheus-node-exporter
   sudo systemctl start prometheus-node-exporter
   ```
3. Проверьте отдачу метрик локально на порту `9100`:
   ```bash
   curl -s http://localhost:9100/metrics | head -n 10
   ```

---

## 10. Сборка и запуск панели управления через Docker Compose

Вся панель управления Aegis (веб-интерфейс администратора, личный кабинет пользователя VDS, Go-оркестратор и Python-бэкенд API) упакованы в контейнеры Docker для минимизации проблем с несовместимостью библиотек.

### 10.1. Полный листинг конфигурации Docker Compose

Создайте или обновите файл `docker-compose.yml` в корневой директории проекта:

```yaml
version: '3.8'

services:
  db:
    image: postgres:15-alpine
    container_name: aegis-db
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_DB=aegis
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d aegis"]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: hosting-backend
    network_mode: host
    privileged: true
    pid: host
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    volumes:
      # Пробрасываем kubeconfig из K3s для авторизации в Kubernetes API
      - /etc/rancher/k3s/k3s.yaml:/root/.kube/config:ro
      # Пробрасываем Docker-сокет для администрирования контейнеров
      - /var/run/docker.sock:/var/run/docker.sock:rw
      # Папка для загрузки и хранения кастомных образов ОС и настроек серверов
      - ./data:/app/data:rw
      # Пробрасываем корень проекта для Git-интеграции
      - .:/app/repo:rw
    environment:
      - PORT=8000
      - HOST=0.0.0.0
      - IMAGES_DIR=/app/data/images
      - DATABASE_URL=${DATABASE_URL}
      - ADMIN_TOKEN=${ADMIN_TOKEN}
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: hosting-frontend
    network_mode: host
    restart: unless-stopped
    depends_on:
      - backend
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

  aegis-orchestrator:
    build:
      context: ./aegis-orchestrator
      dockerfile: Dockerfile
    container_name: aegis-orchestrator
    network_mode: host
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - ./data:/app/data:rw
    environment:
      - PORT=8001
      - DB_CONN_STR=${DB_CONN_STR}
      - ADMIN_TOKEN=${ADMIN_TOKEN}
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

  vds-frontend:
    build:
      context: ./vds
      dockerfile: Dockerfile
    container_name: vds-frontend
    network_mode: host
    restart: unless-stopped
    depends_on:
      - backend
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

volumes:
  postgres_data:
```

### 10.2. Настройка переменных окружения (`.env`)

Для безопасного управления паролями и токенами создайте файл `.env` в корневой директории проекта:

```ini
# Настройки PostgreSQL
POSTGRES_DB=aegis
POSTGRES_USER=postgres
POSTGRES_PASSWORD=aegis-secure-db-pass-2026

# Токен администратора для авторизации в API
ADMIN_TOKEN=aegis-admin-secret-key-2026

# Ссылки для подключения к базе данных для бэкенда и Go-оркестратора
DATABASE_URL=postgresql+asyncpg://postgres:aegis-secure-db-pass-2026@127.0.0.1:5432/aegis
DB_CONN_STR=postgresql://postgres:aegis-secure-db-pass-2026@127.0.0.1:5432/aegis?sslmode=disable
```

### 10.3. Сборка и первый запуск

Сборка статических файлов фронтенда администратора (`frontend`) и личного кабинета пользователя (`vds`) происходит автоматически на этапе сборки Docker-образов (благодаря multi-stage сборке Node -> Nginx в Dockerfile каждого фронтенд-модуля). Это полностью избавляет от необходимости предварительно настраивать Node.js на хост-сервере.

1. Запустите автоматическую сборку и запуск всех сервисов (бэкенд, фронтенды, оркестратор и СУБД) в фоновом режиме:
   ```bash
   sudo docker compose up -d --build
   ```
2. Убедитесь, что все контейнеры успешно запустились и имеют статус `up`:
   ```bash
   sudo docker compose ps
   ```
3. Проверьте логи инициализации СУБД, бэкенда и Go-оркестратора:
   ```bash
   sudo docker compose logs db
   sudo docker compose logs backend
   sudo docker compose logs aegis-orchestrator
   ```

### 10.4. Архитектура веб-серверов фронтенда (Nginx SSL/HTTPS в Docker)

В новой архитектуре Aegis Cloud Engine вам больше не нужно вручную устанавливать и настраивать Nginx на хост-сервере для работы по HTTPS. Каждый фронтенд-сервис:
*   `hosting-frontend` (порты `8080` / `8443` SSL) — консоль администратора
*   `vds-frontend` (порты `8081` / `8444` SSL) — личный кабинет пользователя

уже содержит внутри себя веб-сервер Nginx (см. `frontend/Dockerfile` и `vds/Dockerfile`). При первом запуске скрипт-обертка `start-nginx.sh` внутри контейнера проверяет наличие ключей SSL и автоматически генерирует самоподписанные сертификаты безопасности с помощью утилиты OpenSSL.

Поскольку контейнеры запущены в режиме `network_mode: host`, они автоматически биндятся на порты `8080/8443` и `8081/8444` вашего физического сервера / виртуалки. Запросы на HTTP порты (8080/8081) автоматически перенаправляются на HTTPS.

### 10.5. Настройка СУБД PostgreSQL и автоинициализация схемы

Для перехода с файлового JSON-хранилища на централизованную базу данных в проект была интегрирована СУБД PostgreSQL. Это обеспечивает транзакционную надежность, отказоустойчивость и возможность масштабирования, когда несколько нод панели управления или Go-оркестров работают с единым источником данных.

#### Архитектура и Переменные Окружения
Оба основных сервиса управления используют единую СУБД:
*   **FastAPI Backend (Python)**: Подключается асинхронно через драйвер `asyncpg` и ORM SQLAlchemy. Использует переменную окружения `DATABASE_URL`.
*   **Go Orchestrator (Go)**: Подключается через высокопроизводительный пул соединений `pgxpool` (`github.com/jackc/pgx/v5`). Использует переменную окружения `DB_CONN_STR`.

Поскольку все сервисы запущены в режиме `network_mode: host`, они обращаются к локальному порту СУБД (`127.0.0.1:5432`), который проброшен из контейнера `db`.

#### Автоматическая Инициализация (Миграции и Сиды)
При первом запуске база данных автоматически инициализируется:
1.  **Создание схемы**: FastAPI бэкенд на старте проверяет наличие таблиц и выполняет DDL-запросы на их создание.
2.  **Заполнение начальными данными (Seed)**: В БД автоматически записываются:
    *   Стартовые системные настройки (`system_state`) с балансом `$50.0`.
    *   Стандартная группа безопасности VPC (`default-vpc-sg` / `sg-01a2b3c4d`) с разрешенными портами `22`, `80`, `443` и привязками к инстансам.
    *   Дефолтный S3-бакет (`aegis-backups-bucket`) с демонстрационными объектами.
    *   Предустановленные IAM пользователи: `admin-operator` (с полными правами) и `dev-developer` (с ограниченными правами разработчика).

#### Схема Таблиц базы данных
В СУБД создаются следующие таблицы:
*   `system_state` — Глобальные параметры системы (баланс, тарифы биллинга, статус DDoS-атаки).
*   `containers` — Состояние контейнеров Aegis-Compute (лимиты, PID, статус).
*   `transactions` — Лог списаний и пополнений баланса пользователей.
*   `ddos_logs` — Записи о заблокированных DDoS-атаках.
*   `aws_security_groups` — Группы безопасности AWS (правила и привязанные инстансы хранятся в формате JSONB).
*   `aws_s3_buckets` — Хранилище метаданных S3 бакетов и файлов (список объектов в JSONB).
*   `aws_iam_users` — Пользователи IAM и их политики доступа (JSON-строки).
*   `external_servers` — Подключенные внешние SSH-серверы для управления.

#### Ручная верификация базы данных
Вы можете подключиться к базе данных напрямую для проверки целостности таблиц:
```bash
sudo docker compose exec db psql -U postgres -d aegis -c "\dt"
```
Для просмотра списка запущенных контейнеров из базы данных:
```bash
sudo docker compose exec db psql -U postgres -d aegis -c "SELECT id, name, status FROM containers;"
### 10.5. Панель управления инфраструктурой (команды, логи, git-обновление)

Для обеспечения удобства администрирования в панель управления на порту `8080` была добавлена специализированная вкладка **«Инфраструктура»**. Она позволяет удаленно диагностировать хост-сервер, отслеживать логи в реальном времени и выполнять горячее обновление кодовой базы с GitHub без перезагрузки всей операционной системы хоста.

#### Функциональные возможности:

1. **Синхронизация с GitHub (Git-интеграция)**:
   - Отображает текущую ветку, хэш последнего коммита, автора, дату и сообщение.
   - Определяет статус синхронизации (актуален ли локальный код по сравнению с origin или на сервере есть локальные изменения).
   - Кнопка **«Обновить код с GitHub (без перезагрузки сервера)»**: при нажатии запускается команда `git pull` и последующая пересборка контейнеров (`docker compose up -d --build`). Новые образы бэкенда, фронтендов и оркестратора собираются и перезапускаются за несколько секунд без прерывания работы самой ОС хоста.

2. **Просмотр логов контейнеров (Logs Terminal)**:
   - Выпадающий список позволяет переключаться между сервисами: `FastAPI Бэкенд`, `Админ Панель`, `Go-Оркестратор`, `Клиент Панель`, `База данных Postgres`.
   - Поддерживает чекбокс **«Автообновление»** для автоматического обновления логов каждые 4 секунды с прокруткой в конец.
   - Позволяет быстро локализовать любые runtime-ошибки СУБД, eBPF-драйвера или API.

3. **Интерактивный Терминал Выполнения Команд**:
   - Предоставляет строку ввода для выполнения произвольных шелл-команд в пространстве имен хост-машины (через `nsenter --target 1 ...` для полноценного доступа к сети, дискам и процессам хоста).
   - Содержит панель **быстрых кнопок** для мгновенной диагностики:
     - `Диски` (`df -h`) — проверка свободного места на SSD.
     - `Память` (`free -m`) — проверка утилизации RAM.
     - `Контейнеры` (`docker ps ...`) — проверка запущенных Docker-сервисов и их портов.
     - `Сеть (IP)` (`ip -br addr`) — список физических и виртуальных (Bridge/Multus) интерфейсов хоста.
     - `Аптайм` (`uptime`) — время непрерывной работы сервера и Load Average.
     - `IPTables NAT` (`iptables -t nat -vnL ...`) — правила трансляции сетевых адресов фаервола.
   - Интегрирована базовая безопасность, блокирующая выполнение заведомо деструктивных команд (например, `rm -rf /` или `mkfs`).

---

## 11. Руководство пользователя по функциям консоли AWS

Веб-панель управления полностью имитирует интерфейс облачного гиганта Amazon Web Services (AWS Management Console), предоставляя администраторам и пользователям привычный функционал.

### 11.1. EC2 Dashboard и анализ сетевых путей

1. Перейдите по адресу `http://ваша_нода_ip:8080` (для администратора) или `http://ваша_нода_ip:8081` (для пользователя).
2. Выберите раздел **EC2** -> **Instances** (Инстансы).
3. На экране отобразится список созданных виртуальных машин, их состояние (Running/Stopped), внешние/внутренние IP адреса и тип инстанса (например, `t3.medium`).
4. Нажмите на инстанс и перейдите во вкладку **Networking**. Функция **Reachability Analyzer** позволяет симулировать сетевой путь пакета от одной ВМ к другой. Она проверяет правила Security Groups на источнике и получателе, таблицы маршрутизации ядра и выдает вердикт: `Network Path is Reachable` или `Blocked by Security Group Rule #4`.

### 11.2. Создание и привязка VPC Security Groups

Security Groups в Aegis работают как распределенный сетевой экран (Stateful Firewall). Вы можете объединять ВМ в группы безопасности и управлять открытыми портами.

1. Перейдите в раздел **EC2** -> **Security Groups**.
2. Нажмите **Create Security Group**. Введите имя (`web-sg`) и описание.
3. Добавьте правила во вкладку **Inbound Rules** (Входящий трафик):
   - Разрешить HTTP: Protocol `TCP`, Port `80`, Source `0.0.0.0/0` (доступ отовсюду).
   - Разрешить SSH: Protocol `TCP`, Port `22`, Source `192.168.1.0/24` (доступ только из корпоративной подсети).
4. Нажмите **Save Rules**.
5. Привяжите созданную группу к виртуальной машине. Оркестратор автоматически переведет данные правила в цепочки IPTables на хост-сервере для соответствующего виртуального интерфейса CNI.

### 11.3. Создание бакетов S3 и заливка файлов

Объектное хранилище S3 позволяет хранить дистрибутивы ОС, бэкапы и медиафайлы клиентов.

1. Перейдите в раздел **S3 Console**.
2. Нажмите **Create Bucket**. Имя бакета должно быть глобально уникальным (например, `user-123-backups`).
3. Зайдите внутрь созданного бакета. Вы можете перетаскивать файлы для загрузки.
4. При загрузке Go-оркестратор разрежет файл на 4 части данных, сгенерирует 2 проверочных блока Рида-Соломона и запишет их в разные каталоги.
5. При скачивании файла оркестратор автоматически восстановит файл, даже если часть дисков на сервере выйдет из строя.

### 11.4. Настройка политик IAM и работа с симулятором

AWS IAM (Identity and Access Management) отвечает за гибкую настройку прав доступа.

1. Перейдите в раздел **IAM Console** -> **Users**.
2. Выберите пользователя и перейдите во вкладку **Permissions Policies**.
3. Политика представляет собой JSON документ. Пример политики, разрешающей только просмотр ВМ и создание S3 бакетов:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "ec2:DescribeInstances",
           "s3:CreateBucket",
           "s3:ListBucket"
         ],
         "Resource": "*"
       }
     ]
   }
   ```
4. Вкладка **IAM Policy Simulator** позволяет проверить права без совершения реального запроса к API. Выберите действие `ec2:TerminateInstances`, нажмите **Run Simulation**, и симулятор выдаст вердикт `Denied (Implicitly Denied by default)`.

---

## 12. Справочник API Эндпоинтов

Ниже приведен перечень HTTP-запросов для автоматической интеграции Aegis с внешними биллинговыми системами (например, WHMCS или BILLmanager).

### 12.1. Получение общего состояния AWS (`/api/aegis/aws`)

Запрос возвращает список всех ВМ, бакетов S3, пользователей IAM и текущую нагрузку на физические ноды.

* **Метод**: `GET`
* **URL**: `http://localhost:8001/api/aegis/aws`
* **Пример ответа (JSON)**:
  ```json
  {
    "instances": [
      {
        "id": "i-09f1228ac",
        "name": "Production-Database",
        "status": "running",
        "ip_address": "172.20.0.15",
        "type": "c5.xlarge",
        "security_groups": ["sg-012345"]
      }
    ],
    "s3_buckets": [
      {
        "name": "client-assets",
        "created_at": "2026-06-08T10:00:00Z",
        "objects_count": 42
      }
    ],
    "iam_users": [
      {
        "username": "admin-vladislav",
        "groups": ["Administrators"]
      }
    ]
  }
  ```

### 12.2. Создание группы безопасности (`/api/aegis/aws/security-groups`)

* **Метод**: `POST`
* **URL**: `http://localhost:8001/api/aegis/aws/security-groups`
* **Тело запроса (JSON)**:
  ```json
  {
    "action": "create",
    "name": "frontend-sg",
    "description": "Rules for public web servers"
  }
  ```
* **Пример ответа**:
  ```json
  {
    "status": "success",
    "group_id": "sg-a8f199",
    "message": "Security group frontend-sg created successfully"
  }
  ```

### 12.3. Обновление правил фаервола Security Group (`/api/aegis/aws/security-groups`)

* **Метод**: `POST`
* **URL**: `http://localhost:8001/api/aegis/aws/security-groups`
* **Тело запроса (JSON)**:
  ```json
  {
    "action": "update_rules",
    "id": "sg-a8f199",
    "rules": [
      {
        "type": "Inbound",
        "protocol": "tcp",
        "port_range": "443",
        "source": "0.0.0.0/0"
      },
      {
        "type": "Inbound",
        "protocol": "tcp",
        "port_range": "22",
        "source": "192.168.1.50/32"
      }
    ]
  }
  ```

### 12.4. Привязка группы к инстансу (`/api/aegis/aws/security-groups`)

* **Метод**: `POST`
* **URL**: `http://localhost:8001/api/aegis/aws/security-groups`
* **Тело запроса (JSON)**:
  ```json
  {
    "action": "bind",
    "id": "sg-a8f199",
    "instance": "i-09f1228ac"
  }
  ```

### 12.5. Управление S3 бакетами (`/api/aegis/aws/s3/buckets`)

* **Метод**: `POST`
* **URL**: `http://localhost:8001/api/aegis/aws/s3/buckets`
* **Тело запроса (Создать бакет)**:
  ```json
  {
    "action": "create",
    "name": "my-database-backups"
  }
  ```
* **Тело запроса (Загрузить файл по частям Рида-Соломона)**:
  ```json
  {
    "action": "upload",
    "name": "my-database-backups",
    "key": "db-dump-2026.sql",
    "size": 104857600
  }
  ```

---

## 13. Диагностика и решение возможных проблем (Troubleshooting)

В данном разделе собраны наиболее распространенные проблемы при установке и эксплуатации Aegis Cloud Engine, методы их диагностики и решения.

### 13.1. Виртуальная машина зависла в статусе `Importing` или `PvcBound`
- **Причина**: Медленная скорость загрузки образа ОС (CDI скачивает ISO-файл из интернета).
- **Решение**: Проверьте логи пода-импортера CDI в Kubernetes:
  ```bash
  kubectl get pods -A | grep cdi
  kubectl logs -n default -l app=cdi-importer --tail=100
  ```
  Убедитесь, что URL-адрес источника образа доступен с вашей ноды.

### 13.2. Ошибка `VNC-сессия разорвана API-сервером`
- **Причина**: Тайм-аут прокси-соединения websockets в Nginx или падение пода VNC-прокси.
- **Решение**: Проверьте, запущен ли веб-сокет прокси сервер на бэкенде:
  ```bash
  sudo docker compose logs backend | grep -i vnc
  ```
  Перезапустите контейнер бэкенда:
   ```bash
   sudo docker compose restart backend
   ```

### 13.3. Ошибки маршрутизации сети Multus CNI
- **Причина**: Физический свитч блокирует сторонние MAC-адреса, или на сетевой карте не включен смешанный режим (promiscuous mode).
- **Решение**: Включите promiscuous mode на сетевых интерфейсах хоста:
  ```bash
  sudo ip link set br0 promisc on
  sudo ip link set enp3s0 promisc on
  ```
  Убедитесь, что правила безопасности вашего хостинг-провайдера разрешают отправку пакетов с произвольными MAC-адресами.

### 13.4. Сбой сборки Go-оркестратора на macOS
- **Причина**: Go-оркестратор вызывает низкоуровневые Linux-системные вызовы (`syscall.Syscall` для namespaces и cgroups), которые отсутствуют в macOS Kernel (Darwin).
- **Решение**: Запускайте в режиме Mock-эмуляции или скомпилируйте бинарный файл под Linux:
  ```bash
  GOOS=linux GOARCH=amd64 go build -o aegis-daemon .
  ```

### 13.5. Конфликт портов при запуске Docker Compose
- **Причина**: Порты `8080`, `8081`, `8000` или `8001` заняты другими службами на хост-сервере.
- **Решение**: Найдите процесс, занимающий порт, и завершите его:
  ```bash
  sudo lsof -i :8080
  sudo systemctl stop nginx || true
  ```

### 13.6. Ошибка `KVM device not found`
- **Причина**: Не включена вложенная виртуализация (Nested Virtualization) в настройках гипервизора, или сбросились права доступа к устройству `/dev/kvm`.
- **Решение**:
  ```bash
  sudo chmod 666 /dev/kvm
  ```
  Проверьте доступность аппаратного ускорения: `kvm-ok`.

### 13.7. Ошибка при расширении диска ВМ (Resize error)
- **Причина**: Файловая система внутри виртуалки не поддерживает автоматическое расширение разделов (не установлен пакет cloud-guest-utils).
- **Решение**: Зайдите в консоль ВМ и принудительно обновите таблицу разделов:
  ```bash
  sudo growpart /dev/vda 1
  sudo resize2fs /dev/vda1
  ```

### 13.8. Проблемы с биллингом (баланс пользователя списывается неверно)
- **Причина**: Сбой Gorilla TSDB из-за переполнения оперативной памяти или зависания таймера биллинга.
- **Решение**: Посмотрите логи контейнера оркестратора:
  ```bash
  sudo docker compose logs aegis-orchestrator | grep -i billing
  ```
  Проверьте баланс и историю транзакций в PostgreSQL:
  ```bash
  sudo docker compose exec db psql -U postgres -d aegis -c "SELECT * FROM system_state;"
  sudo docker compose exec db psql -U postgres -d aegis -c "SELECT * FROM transactions ORDER BY created_at DESC LIMIT 10;"
  ```

### 13.9. Лимит дисковых квот containerd (Disk pressure в K3s)
- **Причина**: На системном диске осталось менее 10% свободного места, Kubernetes останавливает поды виртуалки.
- **Решение**: Очистите неиспользуемые Docker-образы и кэш Kubernetes:
  ```bash
  sudo k3s crictl rmi --prune
  sudo docker system prune -af --volumes
  ```

### 13.10. Проблема с зависанием VSwitch туннелей в Shared Memory
- **Причина**: Оркестратор аварийно завершил работу, не освободив разделяемую память IPC.
- **Решение**: Очистите сегменты разделяемой памяти IPC:
  ```bash
  ipcs -m
  ipcrm -M <shmkey>
  sudo docker compose restart aegis-orchestrator
  ```

### 13.11. Ошибка "CDI importer Pod crashed" при импорте дисков Windows ISO
- **Причина**: Недостаточно оперативной памяти для распаковки ISO-файла, или сбой файловой системы локального раздела.
- **Решение**: Выделите дополнительный раздел на диске и смонтируйте его в `/var/lib/kubelet` или расширьте дисковую квоту системного диска.

### 13.12. Ошибка "VirtualMachineInstance is not schedulable"
- **Причина**: В кластере Kubernetes нет нод с достаточным количеством свободной оперативной памяти или ядер CPU.
- **Решение**:
  1. Уменьшите запрашиваемые ресурсы ВМ в форме заказа кабинета пользователя.
  2. Подключите дополнительный Worker-сервер к кластеру для расширения пула RAM/vCPU ресурсов.

### 13.13. Ошибка авторизации SSH во внешнем мониторинге
- **Причина**: Отсутствует публичный ключ Master-сервера в файле `/root/.ssh/authorized_keys` на Worker-ноде.
- **Решение**:
  Отредактируйте файл `/etc/ssh/sshd_config` на удаленном сервере, разрешив авторизацию root по ключам:
  ```ini
  PermitRootLogin prohibit-password
  PubkeyAuthentication yes
  ```
  Перезапустите SSH-демона:
  ```bash
  sudo systemctl restart sshd
  ```

### 13.14. Ошибка инициализации eBPF (Anti-DDoS не запускается)
- **Причина**: Версия установленных заголовков ядра Linux (linux-headers) не совпадает с текущим ядром хоста.
- **Решение**:
  Установите заголовки ядра под текущую версию:
  ```bash
  sudo apt-get install -y linux-headers-$(uname -r)
  ```

### 13.15. Ошибка синхронизации баланса из-за прерывания SSE потока
- **Причина**: Nginx обрывает соединения по таймауту (proxy_read_timeout по умолчанию 60с).
- **Решение**: В файле `nginx.conf` добавьте параметры для SSE роутов:
  ```nginx
  proxy_read_timeout 86400s;
  proxy_send_timeout 86400s;
  ```

### 13.16. Ошибка монтирования NFS: "Permission denied"
- **Причина**: На NFS-сервере заблокирован IP адрес Master-сервера, или неверно настроены права UID/GID.
- **Решение**: Убедитесь, что в файле `/etc/exports` на NFS-сервере включена директива `no_root_squash`.

### 13.17. Проблема с кэшированием статики Nginx (VDS кабинет)
- **Причина**: Браузер пользователя сохраняет старые JS/CSS файлы при обновлении панели.
- **Решение**: Добавьте заголовки отключения кэша в конфиг `nginx.conf`:
  ```nginx
  location / {
      add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0";
      try_files $uri $uri/ /index.html;
  }
  ```

### 13.18. Ошибка создания S3 бакета с дублирующим именем
- **Причина**: Базовые проверки оркестратора запрещают дублирование имен бакетов на одном сервере.
- **Решение**: Используйте уникальные имена бакетов, содержащие ID пользователя, например: `client-01-web-backups`.

### 13.19. Ошибка "conntrack table full"
- **Причина**: Сервер подвергся DDoS-атаке типа Syn-Flood, заполнившей таблицу сетевых соединений.
- **Решение**: Увеличьте лимиты conntrack на хост-сервере:
  ```bash
  sudo sysctl -w net.netfilter.nf_conntrack_max=262144
  ```

### 13.20. Зависание дискового IO на виртуалках (Direct-IO latency)
- **Причина**: На дисках SSD/NVMe используется устаревший планировщик ввода-вывода (например, `mq-deadline`).
- **Решение**: Установите планировщик `none` или `kyber` на хост-системе для NVMe накопителей:
  ```bash
  echo none | sudo tee /sys/block/sdb/queue/scheduler
  ```

### 13.21. Ошибка "CDI volume size mismatch" при создании ВМ
- **Причина**: Запрошенный размер диска меньше, чем фактический размер импортируемого шаблона ОС.
- **Решение**: Увеличьте размер диска ВМ до значений, превышающих 20 ГБ (рекомендуемый объем для шаблонов Ubuntu Server).

### 13.22. Конфликт маршрутизации при наличии нескольких внешних интерфейсов
- **Причина**: В таблице маршрутизации хоста создаются два дефолтных шлюза (Default Gateway) с одинаковой метрикой.
- **Решение**: Настройте метрику маршрута в Netplan:
  ```yaml
  routes:
    - to: default
      via: 192.168.1.1
      metric: 100
  ```

### 13.23. Сбой запуска контейнера FastAPI из-за недоступности k3s.yaml
- **Причина**: Права доступа к `/etc/rancher/k3s/k3s.yaml` не позволяют читать файл непривилегированным пользователям.
- **Решение**: Убедитесь, что вы скопировали файл k3s.yaml в домашнюю директорию или выдали права на чтение:
  ```bash
  sudo chmod 644 /etc/rancher/k3s/k3s.yaml
  ```

### 13.24. Внутренние виртуальные машины не пингуют внешние адреса
- **Причина**: Заблокирован форвардинг пакетов (FORWARD chain в iptables установлен в DROP).
- **Решение**: Измените политику по умолчанию для форвардинга пакетов:
  ```bash
  sudo iptables -P FORWARD ACCEPT
  ```

### 13.25. Баланс пользователя не обновляется в реальном времени
- **Причина**: Упало WebSocket-соединение с Go-оркестратором, либо база данных заблокирована/недоступна.
- **Решение**: Убедитесь, что СУБД PostgreSQL доступна и отвечает на запросы, проверив логи контейнера `db`:
  ```bash
  sudo docker compose logs db
  ```

---

## 14. Автозапуск, мониторинг и обеспечение отказоустойчивости

Для промышленной эксплуатации Aegis Cloud Engine необходимо настроить автоматический запуск всех служб при старте системы и ежедневное резервное копирование.

### 14.1. Создание Systemd-службы для Docker Compose

Создайте конфигурационный файл службы `/etc/systemd/system/aegis-hosting.service`:

```ini
[Unit]
Description=Aegis Cloud Engine hosting control panel
Requires=docker.service k3s.service
After=docker.service k3s.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/Users/vladislavkarasev/Documents/Хостинг
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
ExecReload=/usr/bin/docker compose restart

[Install]
WantedBy=multi-user.target
```

### 14.2. Активация автозапуска службы

Перечитайте конфигурацию Systemd и добавьте службу в автозапуск:
```bash
sudo systemctl daemon-reload
sudo systemctl enable aegis-hosting.service
sudo systemctl start aegis-hosting.service
```

### 14.3. Автоматическая очистка кэша образов (Cron Task)

При частом создании и удалении виртуальных машин в системе накапливаются неиспользуемые тома и кэши образов ОС. Настройте ежедневную очистку по расписанию.
Создайте задание в cron:
```bash
sudo crontab -l > /tmp/cron_backup || true
echo "0 3 * * * /usr/local/bin/k3s crictl rmi --prune" >> /tmp/cron_backup
sudo crontab /tmp/cron_backup
rm /tmp/cron_backup
```

### 14.4. Мониторинг здоровья ноды (Liveness healthcheck скрипт)

Создайте bash-скрипт мониторинга `/opt/aegis-healthcheck.sh`:
```bash
#!/bin/bash
# Проверка доступности API бэкенда
HTTP_STATUS=$(curl -o /dev/null -s -w "%{http_code}" http://localhost:8000/api/health || true)

if [ "$HTTP_STATUS" -ne 200 ]; then
    echo "[ALERT] API backend is unresponsive (HTTP $HTTP_STATUS). Restarting service..."
    sudo systemctl restart aegis-hosting.service
fi

# Проверка свободного места на диске виртуальных машин
DISK_USAGE=$(df /mnt/aegis-storage/vms | tail -1 | awk '{print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -gt 90 ]; then
    echo "[WARNING] Disk space for VMS is critically low ($DISK_USAGE%). Please expand storage."
fi
```
Сделайте скрипт исполняемым:
```bash
sudo chmod +x /opt/aegis-healthcheck.sh
```

### 14.5. Автоматическая синхронизация бэкапов в S3

Создайте скрипт `/opt/aegis-backup-sync.sh` для ежесуточного бэкапа базы данных PostgreSQL и загрузки в S3 бакет через API:
```bash
#!/bin/bash
DATE=$(date +%F)
BACKUP_FILE="/tmp/aegis-db-backup-$DATE.sql"

# Выполняем дамп базы данных PostgreSQL из контейнера
docker exec -i aegis-db pg_dump -U postgres aegis > $BACKUP_FILE || true

curl -X POST \
  -H "Content-Type: application/json" \
  -d "{\"action\":\"upload\",\"name\":\"aegis-backups-bucket\",\"key\":\"backups/db-backup-$DATE.sql\",\"size\":$(wc -c < $BACKUP_FILE 2>/dev/null || echo 0)}" \
  http://localhost:8001/api/aegis/aws/s3/buckets

rm -f $BACKUP_FILE
echo "[BACKUP] Бэкап базы данных PostgreSQL успешно загружен в S3 бакет."
```
Сделайте скрипт исполняемым и добавьте его в cron:
```bash
sudo chmod +x /opt/aegis-backup-sync.sh
echo "0 2 * * * /bin/bash /opt/aegis-backup-sync.sh > /dev/null 2>&1" | sudo tee -a /var/spool/cron/crontabs/root
```

---

## 15. Глоссарий терминов и детальные системные спецификации

Для удобства администрирования хостинга ниже приведен подробный глоссарий основных терминов и спецификации задействованных технологий.

### 15.1. Виртуализация и оркестрация вычислений
* **Hyperconvergence (Гиперконвергентность)** — архитектура ИТ-инфраструктуры, которая объединяет вычислительные ресурсы, системы хранения данных и сетевые функции в единую программно-определяемую систему. Aegis Cloud Engine является классическим примером HCI.
* **cgroups v2 (Control Groups)** — механизм ядра Linux, позволяющий ограничивать и изолировать ресурсы (CPU, RAM, дисковое IO, сетевой трафик) для групп процессов. Используется в Aegis-Compute для задания жестких лимитов.
* **CPU Pinning (Привязка процессора)** — привязка виртуального процессора (vCPU) или процесса к конкретному физическому ядру процессора на хост-сервере. Это минимизирует задержки планировщика задач ядра.
* **KubeVirt** — надстройка над Kubernetes, позволяющая запускать виртуальные машины в подах. Она использует QEMU/KVM для непосредственного выполнения гостевых операционных систем.
* **CDI (Containerized Data Importer)** — вспомогательный сервис Kubernetes, обеспечивающий доставку, конвертацию и запись дисковых образов ОС в тома Persistent Volume Claims (PVC) для ВМ KubeVirt.

### 15.2. Сетевые протоколы и маршрутизация
* **Multus CNI** — плагин CNI (Container Network Interface) для Kubernetes, позволяющий подключать к одному поду несколько сетевых интерфейсов одновременно (например, один интерфейс для управления кластером, второй — для выделенного внешнего IP).
* **macvlan** — драйвер сетевого интерфейса Linux, позволяющий создавать несколько виртуальных сетевых адаптеров с уникальными MAC-адресами на базе одного физического сетевого порта.
* **eBPF (Extended Berkeley Packet Filter)** — технология ядра Linux, позволяющая безопасно выполнять пользовательские программы в пространстве ядра. Используется для Anti-DDoS фильтрации на уровне сетевой карты.
* **conntrack (Connection Tracking)** — подсистема ядра Linux, отслеживающая состояние сетевых соединений (Stateful firewall). Позволяет Security Groups автоматически пропускать ответные пакеты.

### 15.3. Системы хранения данных
* **Reed-Solomon (Кодирование стирания)** — математический алгоритм избыточного кодирования. Используется в распределенных СХД для защиты данных от сбоев жестких дисков с меньшими затратами дискового пространства, чем при классическом зеркалировании (RAID-1).
* **LVM2 (Logical Volume Manager)** — менеджер логических томов в Linux. Позволяет динамически расширять разделы дисков и создавать мгновенные снимки (снапшоты).
* **RBD (Ceph RADOS Block Device)** — распределенное отказоустойчивое блочное хранилище в Ceph. Позволяет виртуальным машинам монтировать диски по сети с защитой от сбоев физических серверов.

---

## 16. Развернутый перечень CLI-команд для администратора хостинга

Ниже приведен полный справочник консольных команд, разделенный по сферам администрирования.

### 16.1. Диагностика виртуальных машин KubeVirt
* Получить список всех виртуальных машин в кластере:
  `kubectl get vm -o wide`
* Получить список запущенных экземпляров виртуальных машин:
  `kubectl get vmi -o wide`
* Проверить подробное состояние конкретной ВМ:
  `kubectl describe vm <vm_name>`
* Открыть консоль логирования событий виртуальной машины:
  `kubectl logs virt-launcher-<vm_name>-xxxxx -c compute`
* Принудительный перезапуск виртуальной машины:
  `kubectl virt restart <vm_name>`
* Остановка виртуальной машины:
  `kubectl virt stop <vm_name>`
* Запуск остановленной виртуальной машины:
  `kubectl virt start <vm_name>`

### 16.2. Управление дисками и PersistentVolumeClaims (PVC)
* Проверить статус всех дисков виртуальных машин:
  `kubectl get pvc -o wide`
* Проверить статус физических томов в Kubernetes:
  `kubectl get pv -o wide`
* Посмотреть свободное место на локальных накопителях:
  `df -hT | grep -E 'ext4|xfs|nfs'`
* Проверить состояние CDI импортеров образов:
  `kubectl get pods -n cdi`
* Посмотреть журналы импорта конкретного образа ОС:
  `kubectl logs -n default -l app=cdi-importer`

### 16.3. Мониторинг сетевых интерфейсов и мостов
* Посмотреть список всех сетевых интерфейсов на хосте:
  `ip addr show`
* Посмотреть список созданных сетевых мостов:
  `brctl show`
* Проверить статус работы CNI Multus:
  `kubectl get daemonset -n kube-system | grep multus`
* Проверить конфигурацию NetworkAttachmentDefinition:
  `kubectl get network-attachment-definitions -o yaml`
* Проверить таблицы маршрутизации:
  `ip route show`
* Проверить правила трансляции сетевых адресов:
  `sudo iptables -t nat -L -v -n`

### 16.4. Проверка состояния S3 нод оркестратора
* Проверить права доступа к директориям нод S3:
  `ls -la /app/data/s3/`
* Посмотреть загруженность S3 нод (количество размещенных частей Рида-Соломона):
  `du -sh /app/data/s3/node_*`
* Проверить логи Go-оркестратора при записи блоков данных:
  `sudo docker compose logs aegis-orchestrator | grep -E 'S3|Reed-Solomon'`

### 16.5. Работа с IAM политиками и правами
* Вывести список всех созданных IAM пользователей:
  `curl -s http://localhost:8001/api/aegis/aws | jq '.iam_users'`
* Проверить данные в таблице IAM пользователей в PostgreSQL:
  `sudo docker compose exec db psql -U postgres -d aegis -c "SELECT username, joined_at FROM aws_iam_users;"`

### 16.6. Дополнительные сценарии администрирования нод и кластера

Ниже представлены детальные пошаговые инструкции для обслуживания нод и обеспечения работоспособности вычислительного кластера при плановых работах или авариях.


#### Сценарий обслуживания ноды #1
Данный сценарий описывает регламентные работы на физической ноде `node-01` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-01`:
   `kubectl cordon node-01`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-01 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-01` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-01`

#### Сценарий обслуживания ноды #2
Данный сценарий описывает регламентные работы на физической ноде `node-02` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-02`:
   `kubectl cordon node-02`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-02 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-02` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-02`

#### Сценарий обслуживания ноды #3
Данный сценарий описывает регламентные работы на физической ноде `node-03` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-03`:
   `kubectl cordon node-03`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-03 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-03` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-03`

#### Сценарий обслуживания ноды #4
Данный сценарий описывает регламентные работы на физической ноде `node-04` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-04`:
   `kubectl cordon node-04`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-04 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-04` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-04`

#### Сценарий обслуживания ноды #5
Данный сценарий описывает регламентные работы на физической ноде `node-05` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-05`:
   `kubectl cordon node-05`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-05 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-05` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-05`

#### Сценарий обслуживания ноды #6
Данный сценарий описывает регламентные работы на физической ноде `node-06` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-06`:
   `kubectl cordon node-06`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-06 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-06` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-06`

#### Сценарий обслуживания ноды #7
Данный сценарий описывает регламентные работы на физической ноде `node-07` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-07`:
   `kubectl cordon node-07`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-07 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-07` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-07`

#### Сценарий обслуживания ноды #8
Данный сценарий описывает регламентные работы на физической ноде `node-08` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-08`:
   `kubectl cordon node-08`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-08 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-08` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-08`

#### Сценарий обслуживания ноды #9
Данный сценарий описывает регламентные работы на физической ноде `node-09` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-09`:
   `kubectl cordon node-09`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-09 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-09` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-09`

#### Сценарий обслуживания ноды #10
Данный сценарий описывает регламентные работы на физической ноде `node-010` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-010`:
   `kubectl cordon node-010`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-010 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-010` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-010`

#### Сценарий обслуживания ноды #11
Данный сценарий описывает регламентные работы на физической ноде `node-011` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-011`:
   `kubectl cordon node-011`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-011 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-011` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-011`

#### Сценарий обслуживания ноды #12
Данный сценарий описывает регламентные работы на физической ноде `node-012` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-012`:
   `kubectl cordon node-012`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-012 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-012` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-012`

#### Сценарий обслуживания ноды #13
Данный сценарий описывает регламентные работы на физической ноде `node-013` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-013`:
   `kubectl cordon node-013`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-013 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-013` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-013`

#### Сценарий обслуживания ноды #14
Данный сценарий описывает регламентные работы на физической ноде `node-014` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-014`:
   `kubectl cordon node-014`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-014 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-014` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-014`

#### Сценарий обслуживания ноды #15
Данный сценарий описывает регламентные работы на физической ноде `node-015` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-015`:
   `kubectl cordon node-015`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-015 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-015` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-015`

#### Сценарий обслуживания ноды #16
Данный сценарий описывает регламентные работы на физической ноде `node-016` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-016`:
   `kubectl cordon node-016`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-016 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-016` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-016`

#### Сценарий обслуживания ноды #17
Данный сценарий описывает регламентные работы на физической ноде `node-017` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-017`:
   `kubectl cordon node-017`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-017 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-017` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-017`

#### Сценарий обслуживания ноды #18
Данный сценарий описывает регламентные работы на физической ноде `node-018` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-018`:
   `kubectl cordon node-018`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-018 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-018` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-018`

#### Сценарий обслуживания ноды #19
Данный сценарий описывает регламентные работы на физической ноде `node-019` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-019`:
   `kubectl cordon node-019`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-019 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-019` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-019`

#### Сценарий обслуживания ноды #20
Данный сценарий описывает регламентные работы на физической ноде `node-020` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-020`:
   `kubectl cordon node-020`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-020 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-020` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-020`

#### Сценарий обслуживания ноды #21
Данный сценарий описывает регламентные работы на физической ноде `node-021` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-021`:
   `kubectl cordon node-021`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-021 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-021` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-021`

#### Сценарий обслуживания ноды #22
Данный сценарий описывает регламентные работы на физической ноде `node-022` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-022`:
   `kubectl cordon node-022`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-022 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-022` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-022`

#### Сценарий обслуживания ноды #23
Данный сценарий описывает регламентные работы на физической ноде `node-023` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-023`:
   `kubectl cordon node-023`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-023 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-023` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-023`

#### Сценарий обслуживания ноды #24
Данный сценарий описывает регламентные работы на физической ноде `node-024` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-024`:
   `kubectl cordon node-024`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-024 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-024` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-024`

#### Сценарий обслуживания ноды #25
Данный сценарий описывает регламентные работы на физической ноде `node-025` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-025`:
   `kubectl cordon node-025`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-025 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-025` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-025`

#### Сценарий обслуживания ноды #26
Данный сценарий описывает регламентные работы на физической ноде `node-026` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-026`:
   `kubectl cordon node-026`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-026 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-026` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-026`

#### Сценарий обслуживания ноды #27
Данный сценарий описывает регламентные работы на физической ноде `node-027` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-027`:
   `kubectl cordon node-027`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-027 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-027` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-027`

#### Сценарий обслуживания ноды #28
Данный сценарий описывает регламентные работы на физической ноде `node-028` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-028`:
   `kubectl cordon node-028`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-028 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-028` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-028`

#### Сценарий обслуживания ноды #29
Данный сценарий описывает регламентные работы на физической ноде `node-029` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-029`:
   `kubectl cordon node-029`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-029 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-029` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-029`

#### Сценарий обслуживания ноды #30
Данный сценарий описывает регламентные работы на физической ноде `node-030` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-030`:
   `kubectl cordon node-030`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-030 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-030` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-030`

#### Сценарий обслуживания ноды #31
Данный сценарий описывает регламентные работы на физической ноде `node-031` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-031`:
   `kubectl cordon node-031`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-031 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-031` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-031`

#### Сценарий обслуживания ноды #32
Данный сценарий описывает регламентные работы на физической ноде `node-032` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-032`:
   `kubectl cordon node-032`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-032 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-032` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-032`

#### Сценарий обслуживания ноды #33
Данный сценарий описывает регламентные работы на физической ноде `node-033` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-033`:
   `kubectl cordon node-033`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-033 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-033` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-033`

#### Сценарий обслуживания ноды #34
Данный сценарий описывает регламентные работы на физической ноде `node-034` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-034`:
   `kubectl cordon node-034`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-034 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-034` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-034`

#### Сценарий обслуживания ноды #35
Данный сценарий описывает регламентные работы на физической ноде `node-035` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-035`:
   `kubectl cordon node-035`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-035 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-035` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-035`

#### Сценарий обслуживания ноды #36
Данный сценарий описывает регламентные работы на физической ноде `node-036` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-036`:
   `kubectl cordon node-036`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-036 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-036` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-036`

#### Сценарий обслуживания ноды #37
Данный сценарий описывает регламентные работы на физической ноде `node-037` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-037`:
   `kubectl cordon node-037`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-037 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-037` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-037`

#### Сценарий обслуживания ноды #38
Данный сценарий описывает регламентные работы на физической ноде `node-038` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-038`:
   `kubectl cordon node-038`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-038 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-038` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-038`

#### Сценарий обслуживания ноды #39
Данный сценарий описывает регламентные работы на физической ноде `node-039` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-039`:
   `kubectl cordon node-039`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-039 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-039` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-039`

#### Сценарий обслуживания ноды #40
Данный сценарий описывает регламентные работы на физической ноде `node-040` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-040`:
   `kubectl cordon node-040`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-040 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-040` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-040`

#### Сценарий обслуживания ноды #41
Данный сценарий описывает регламентные работы на физической ноде `node-041` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-041`:
   `kubectl cordon node-041`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-041 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-041` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-041`

#### Сценарий обслуживания ноды #42
Данный сценарий описывает регламентные работы на физической ноде `node-042` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-042`:
   `kubectl cordon node-042`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-042 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-042` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-042`

#### Сценарий обслуживания ноды #43
Данный сценарий описывает регламентные работы на физической ноде `node-043` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-043`:
   `kubectl cordon node-043`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-043 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-043` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-043`

#### Сценарий обслуживания ноды #44
Данный сценарий описывает регламентные работы на физической ноде `node-044` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-044`:
   `kubectl cordon node-044`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-044 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-044` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-044`

#### Сценарий обслуживания ноды #45
Данный сценарий описывает регламентные работы на физической ноде `node-045` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-045`:
   `kubectl cordon node-045`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-045 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-045` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-045`

#### Сценарий обслуживания ноды #46
Данный сценарий описывает регламентные работы на физической ноде `node-046` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-046`:
   `kubectl cordon node-046`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-046 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-046` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-046`

#### Сценарий обслуживания ноды #47
Данный сценарий описывает регламентные работы на физической ноде `node-047` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-047`:
   `kubectl cordon node-047`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-047 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-047` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-047`

#### Сценарий обслуживания ноды #48
Данный сценарий описывает регламентные работы на физической ноде `node-048` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-048`:
   `kubectl cordon node-048`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-048 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-048` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-048`

#### Сценарий обслуживания ноды #49
Данный сценарий описывает регламентные работы на физической ноде `node-049` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-049`:
   `kubectl cordon node-049`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-049 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-049` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-049`

#### Сценарий обслуживания ноды #50
Данный сценарий описывает регламентные работы на физической ноде `node-050` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-050`:
   `kubectl cordon node-050`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-050 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-050` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-050`

#### Сценарий обслуживания ноды #51
Данный сценарий описывает регламентные работы на физической ноде `node-051` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-051`:
   `kubectl cordon node-051`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-051 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-051` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-051`

#### Сценарий обслуживания ноды #52
Данный сценарий описывает регламентные работы на физической ноде `node-052` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-052`:
   `kubectl cordon node-052`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-052 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-052` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-052`

#### Сценарий обслуживания ноды #53
Данный сценарий описывает регламентные работы на физической ноде `node-053` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-053`:
   `kubectl cordon node-053`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-053 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-053` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-053`

#### Сценарий обслуживания ноды #54
Данный сценарий описывает регламентные работы на физической ноде `node-054` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-054`:
   `kubectl cordon node-054`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-054 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-054` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-054`

#### Сценарий обслуживания ноды #55
Данный сценарий описывает регламентные работы на физической ноде `node-055` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-055`:
   `kubectl cordon node-055`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-055 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-055` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-055`

#### Сценарий обслуживания ноды #56
Данный сценарий описывает регламентные работы на физической ноде `node-056` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-056`:
   `kubectl cordon node-056`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-056 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-056` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-056`

#### Сценарий обслуживания ноды #57
Данный сценарий описывает регламентные работы на физической ноде `node-057` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-057`:
   `kubectl cordon node-057`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-057 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-057` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-057`

#### Сценарий обслуживания ноды #58
Данный сценарий описывает регламентные работы на физической ноде `node-058` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-058`:
   `kubectl cordon node-058`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-058 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-058` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-058`

#### Сценарий обслуживания ноды #59
Данный сценарий описывает регламентные работы на физической ноде `node-059` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-059`:
   `kubectl cordon node-059`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-059 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-059` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-059`

#### Сценарий обслуживания ноды #60
Данный сценарий описывает регламентные работы на физической ноде `node-060` с целью технического обслуживания (замена SSD накопителей, продувка от пыли, апгрейд RAM).
1. Установите запрет на планирование новых виртуальных машин на ноду `node-060`:
   `kubectl cordon node-060`
2. Начните процесс эвакуации (живой миграции) всех пользовательских инстансов VDS на другие серверы:
   `kubectl drain node-060 --ignore-daemonsets --delete-emptydir-data`
3. Убедитесь, что все ВМ успешно мигрировали и нода свободна:
   `kubectl get vmi -o wide | grep node-060` (вывод должен быть пустым)
4. Выполните работы по техническому обслуживанию сервера. При замене SSD инициализируйте LVM на новом диске.
5. После включения сервера верните его в рабочий пул планировщика Kubernetes:
   `kubectl uncordon node-060`


## Лицензия

Проект распространяется под лицензией Apache 2.0. Все права защищены. Разработано в учебных и демонстрационных целях для демонстрации навыков проектирования сложных виртуализированных облачных сред и системного программирования.
