# Как устроен ByteBurners Hosting — карта взаимодействий

Этот документ объясняет **как компоненты общаются между собой**: кто кому шлёт запросы,
где хранятся данные, как проходит запрос от кнопки в браузере до реальной виртуалки.
Дополняет [README.md](README.md) (установка) и [DESIGN.md](DESIGN.md) (внешний вид).

---

## 1. Компоненты и кто с кем разговаривает

```mermaid
graph TD
    Browser([Браузер пользователя])

    subgraph Docker [Docker Compose на хосте]
        FE[hosting-frontend<br/>React + Nginx]
        BE[hosting-backend<br/>FastAPI :8000]
        WK[hosting-worker<br/>потребитель очереди]
        MQ{{hosting-rabbitmq<br/>очередь задач}}
        DB[(aegis-db<br/>PostgreSQL — метаданные)]
        MDB[(aegis-mariadb)]
        MINIO[(aegis-minio<br/>S3)]
        MAIL[aegis-mailserver + webmail]
        ORCH[aegis-orchestrator<br/>Go :8001]
    end

    subgraph Host [Ядро хоста Ubuntu]
        K3S[K3s + KubeVirt]
        NGINX[Host Nginx<br/>балансировщик]
        IPT[iptables / NAT]
        DNS[dnsmasq + мост br-vms]
        VM1[VMI: виртуалка QEMU/KVM]
        DBPOD[Приватные БД-поды<br/>+ NetworkPolicy]
    end

    EXT[Внешние Linux-серверы<br/>напрямую или через бастион]

    Browser -->|HTTPS, REST + JWT| FE
    FE -->|проксирует /api| BE
    Browser -.->|WebSocket VNC| BE

    BE -->|быстрые операции| K3S
    BE -->|тяжёлые задачи| MQ
    MQ --> WK
    WK -->|создание/удаление ВМ| K3S
    BE & WK -->|состояние| DB
    BE -->|nsenter| NGINX
    BE -->|nsenter| IPT
    BE -->|SSH / paramiko| EXT

    K3S --> VM1
    K3S --> DBPOD
    VM1 --- DNS
    IPT -->|проброс портов| VM1
    NGINX -->|upstream| VM1
    BE -->|S3 API + mc| MINIO
    ORCH --> DB
```

Кратко о ролях:

| Компонент | Что делает | С кем общается |
|---|---|---|
| **frontend** | React-панель, отдаётся через Nginx | Браузер → `/api` проксирует в backend |
| **backend (FastAPI)** | Вся логика, авторизация, API | K3s, RabbitMQ, PostgreSQL, MinIO, host nginx/iptables, внешние серверы |
| **worker** | Выполняет долгие задачи из очереди + фоновые демоны: расписания бэкапов, проверка правил алертов, лимиты дисков, переустановка проброса портов | RabbitMQ → K3s → PostgreSQL, Telegram/webhook |
| **RabbitMQ** | Очередь `vm_tasks` — развязывает API и тяжёлые операции | backend (пишет), worker (читает) |
| **PostgreSQL `aegis-db`** | Метаданные: пользователи, ВМ, БД, бакеты, диски, серверы | backend, worker, orchestrator |
| **MinIO** | S3-хранилище пользователей | backend (создаёт бакеты/ключи через `mc`) |
| **K3s + KubeVirt** | Запускает ВМ как поды, приватные БД-поды | backend, worker |
| **Host Nginx / iptables / dnsmasq** | Балансировка, проброс портов, DHCP для ВМ | backend через `nsenter` в неймспейс хоста |
| **`aegis-caddy`** | Реверс-прокси своих доменов, сам выпускает и продлевает TLS Let's Encrypt | backend создаёт контейнер и кладёт в него Caddyfile; наружу — 80/443 |
| **`aegis-registry`** | Приватный реестр Docker-образов с htpasswd-аутентификацией | backend (Registry API v2), клиенты `docker push/pull` |

Последние два контейнера панель создаёт **сама** через Docker-сокет, по кнопке в
интерфейсе — их нет в `docker-compose.yml`.

---

## 2. Ключевой приём: backend управляет ХОСТОМ через `nsenter`

Контейнер backend запущен как `privileged`, `network_mode: host`, `pid: host`.
Благодаря этому он через `nsenter --target 1` выполняет команды **в неймспейсе хоста** —
правит `iptables`, конфиги `/etc/nginx/conf.d`, перезагружает nginx. То есть «панель в контейнере»
реально настраивает сеть физического сервера.

> ⚠️ Обратная сторона: компрометация backend = root на хосте. Поэтому все места, куда
> подставляются пользовательские значения (IP файрвола, имена пулов), строго валидируются —
> см. [раздел 6](#6-модель-безопасности).

---

## 3. Потоки запросов (жизненные циклы)

### 3.1 Вход в панель
```
Браузер → POST /api/auth/login (логин+пароль)
  backend: verify_password (PBKDF2) → create_access_token (HMAC-подпись, ~JWT)
  ← access_token сохраняется в localStorage
Далее каждый запрос: main.jsx подставляет заголовок Authorization: Bearer <token>
  backend: get_current_user декодирует токен → находит пользователя
```
Защита от брутфорса: 5 неудач с одного IP за 5 минут → 429.

### 3.2 Создание виртуальной машины (асинхронно)
```
Браузер → POST /api/vms  (get_current_user + проверка квот)
  backend: пишет строку VMTask (status=Pending) в PostgreSQL
  backend: publish_task("vm_tasks", {...}) → RabbitMQ        ← API сразу отвечает
  ─────────────────────────────────────────────
  worker: читает задачу → generate_linux/windows_manifest
  worker: k8s.create_vm_from_manifest → KubeVirt поднимает VMI
  worker: status=Running в PostgreSQL
Фронтенд каждые 5 сек опрашивает GET /api/vms и видит смену статуса.
```

### 3.3 Как ВМ становится доступной снаружи (порты)
```
ВМ получает IP (KubeVirt masquerade / мост br-vms через dnsmasq)
backend вычисляет СТАБИЛЬНЫЙ внешний порт = 22000 + ID_ВМ  (не от IP!)
backend через nsenter добавляет DNAT:
   iptables PREROUTING --dport <ext_port> → <IP_ВМ>:22
Белый список firewall_rules превращается в правила FORWARD ACCEPT/DROP.
```
Порт берётся от ID из БД, поэтому **не меняется при перезагрузке** (см. `k8s_client.get_vm`).

### 3.4 Подключение к своей БД («хаб подключения»)
```
Браузер → POST /api/databases (get_current_user + квота)
  backend: генерирует db_user/db_password (случайные)
  backend: k8s.create_private_db → под PostgreSQL/MySQL в K8s
  backend: NetworkPolicy запрещает весь вход, кроме привязанной ВМ
  db_password ШИФРУЕТСЯ (Fernet) и хранится в PostgreSQL
Кнопка «Подключиться» на фронте показывает host/port/user/pass и готовые
строки (psql / URI / Python / Node) — пароль расшифровывается на лету при отдаче.
```

### 3.5 Внешний сервер через бастион (jump host)
```
Браузер → POST /api/external-servers (только админ)
  Если включён бастион: SSHInspector.open()
     paramiko: коннект к бастиону → канал direct-tcpip до целевого хоста
     → коннект к целевому серверу ЧЕРЕЗ этот канал (sock)
  Пароли сервера и бастиона ШИФРУЮТСЯ (Fernet) в PostgreSQL
Мониторинг, метрики и терминал сервера идут тем же путём (через бастион, если задан).
```

### 3.6 Балансировщик
```
Браузер → POST /api/vms/balancer/pools (только админ, имя валидируется)
  backend: находит IP выбранных ВМ (валидирует как IPv4)
  backend: пишет /proc/1/root/etc/nginx/conf.d/aegis_balancer_<имя>.conf
  backend: nsenter → nginx -t && nginx -s reload
Трафик на публичный порт хоста распределяется nginx между ВМ.
```

### 3.7 Свой домен с автоматическим TLS
```
Браузер → POST /api/domains  (цель: деплой или ВМ + внутренний порт)
  backend: генерирует токен и показывает ДВЕ записи, которые нужно создать:
     TXT  _aegis-challenge.<домен> = <токен>   ← доказательство владения
     A    <домен>                  = IP хоста  ← маршрутизация

Браузер → POST /api/domains/{id}/verify
  backend: сверяет TXT (dnspython) И A-запись (резолв в detect_host_ip)
  ТОЛЬКО если обе прошли:
     services/domains.build_entries → Caddyfile (upstream = IP_ВМ:порт)
     backend: put_archive кладёт конфиг в контейнер aegis-caddy
     backend: caddy reload  (без простоя)
  Caddy сам получает сертификат Let's Encrypt по HTTP-01 на порту 80.
```
TXT-проверка обязательна: без неё любой пользователь мог бы добавить домен,
который и так указывает на этот сервер, и увести его трафик на свою ВМ.

### 3.8 Установка приложения из маркетплейса
```
Браузер → POST /api/marketplace/deploy (app_id + размер ВМ)
  backend: resolve_env — секреты генерируются, переносы строк запрещены
  ФАЗА 1: создаётся запись ВМ → появляется её id
          внешний порт = 28000 + ID_ВМ  (известен только теперь)
  ФАЗА 2: PUBLIC_URL = http://<IP хоста>:<внешний порт>
          build_marketplace_cloud_init → docker-compose.yml + .env внутрь ВМ
  publish_task → worker создаёт ВМ
Внутри ВМ cloud-init ставит docker и выполняет `docker compose up -d`.
```
Две фазы нужны потому, что Ghost, WordPress, Nextcloud и n8n строят абсолютные
ссылки из своего URL, а он зависит от порта, который известен только после
появления ID виртуалки.

### 3.9 Алерт и уведомление
```
worker (демон, раз в минуту) → services/alerts.evaluate_alerts
  для каждого включённого правила: читает метрику
     ВМ:   статус / CPU% / RAM%  (KubeVirt + metrics API)
     хост: CPU% / RAM%           (node metrics)
  is_breach(...) → новое состояние
  уведомление отправляется ТОЛЬКО при смене состояния (ok ↔ firing)
     webhook  → POST JSON (адрес заново проверяется на SSRF)
     telegram → api.telegram.org/bot<token>/sendMessage
```
Если метрика недоступна, состояние правила не меняется — чтобы временный сбой
сбора метрик не выглядел как авария.

---

## 4. Где что хранится

| Данные | Где |
|---|---|
| Пользователи, квоты, метаданные ВМ/БД/бакетов/дисков/серверов | PostgreSQL `aegis-db` |
| **Секреты** (пароли внешних серверов, пароли БД, ключи S3, пароль бастиона) | PostgreSQL, **зашифрованы Fernet** (`app.core.crypto`) |
| Пароли пользователей панели | PostgreSQL, хэш PBKDF2-HMAC-SHA256 |
| Диски ВМ | K3s storage (local-path / OpenEBS LVM / NFS) |
| Файлы пользователей | MinIO (S3) |
| Конфиги балансировщика | `/etc/nginx/conf.d/` на хосте |
| Правила проброса | `iptables` хоста |
| Проекты, участники и роли | PostgreSQL: `projects`, `project_members`; `project_id` у ВМ/БД/деплоев |
| Свои домены и токены подтверждения | PostgreSQL `domains` |
| **TLS-сертификаты** | том `aegis-caddy-data` (Caddy хранит и продлевает их сам) |
| Образы приватного реестра | том `aegis-registry-data` |
| Пароль реестра | файл в `./data`, **зашифрован Fernet** |
| Расписания бэкапов и правила алертов | PostgreSQL: `backup_schedules`, `alert_rules` |
| Каналы уведомлений (bot_token, URL) | PostgreSQL `notification_channels`, **зашифрованы Fernet** |
| API-токены | PostgreSQL `api_tokens` — только SHA-256, сам токен не хранится |
| Секрет 2FA и резервные коды | PostgreSQL `users`: секрет зашифрован, коды — SHA-256 |
| Бэкапы ВМ / баз данных | CDI DataVolume в K3s / бакет `database-backups` в MinIO |

Ключ шифрования секретов — `AEGIS_SECRET_KEY` (если не задан, выводится из `ADMIN_TOKEN`).
**Менять его после первого запуска нельзя** — старые секреты не расшифруются.

---

## 5. Карта кода (куда смотреть)

```
backend/app/
├── main.py                 # старт FastAPI, миграции, подключение роутеров, CORS
├── api/
│   ├── auth.py             # логин, пользователи, квоты, смена пароля, 2FA (TOTP)
│   ├── vms.py              # ВМ: создание, порты/файрвол, балансировщик, миграция
│   ├── databases.py        # управляемые БД + «хаб подключения»
│   ├── s3.py               # бакеты MinIO + файловый браузер
│   ├── external_servers.py # внешние серверы + БАСТИОН
│   ├── projects.py         # проекты, участники, привязка ресурсов (RBAC)
│   ├── domains.py          # свои домены, проверка владения, TLS через Caddy
│   ├── registry.py         # приватный реестр образов (admin)
│   ├── marketplace.py      # каталог и установка приложений в один клик
│   ├── alerts.py           # каналы уведомлений и правила оповещения
│   ├── backups.py          # расписания резервного копирования
│   ├── tokens.py           # персональные API-токены (aeg_...)
│   └── host.py, infra.py, clusters.py, volumes.py, mail.py, vnc.py, images.py
├── core/
│   ├── auth.py             # хэш паролей, токены, get_current_user / check_admin
│   ├── rbac.py             # РЕШЕНИЕ О ДОСТУПЕ (чистая has_permission + роли проекта)
│   ├── crypto.py           # ШИФРОВАНИЕ секретов (Fernet)
│   ├── ssrf.py             # проверка исходящих URL (webhook) по РЕЗУЛЬТАТУ резолва
│   ├── totp.py             # TOTP (RFC 6238), резервные коды, QR как SVG
│   ├── netutils.py         # detect_host_ip + ВАЛИДАТОРЫ (анти-инъекция)
│   ├── migrations.py       # идемпотентные ALTER TABLE
│   └── k8s_client.py       # всё общение с KubeVirt / K8s
├── services/
│   ├── ssh_inspector.py    # SSH к внешним серверам + бастион
│   ├── domains.py          # генерация Caddyfile, TXT-челлендж, жизненный цикл Caddy
│   ├── registry.py         # клиент Registry API v2 + провижининг с htpasswd
│   ├── marketplace.py      # каталог compose-стеков и сборка cloud-init
│   ├── alerts.py           # чтение метрик, стейт-машина правил, доставка
│   └── scheduled_backups.py # расчёт next_run, запуск бэкапа, ротация
└── worker.py               # потребитель очереди + демоны (бэкапы, алерты, файрвол)

frontend/src/
├── App.jsx                 # каркас, вход (в т.ч. код 2FA), сайдбар, создание ВМ
└── components/             # VMCard, DatabasesPanel, S3Panel, ProjectsPanel,
                            # DomainsPanel, RegistryPanel, MarketplacePanel,
                            # AlertsPanel, BackupsPanel, TokensPanel, ...

terraform-provider-aegis/   # Terraform-провайдер (Go): aegis_vm, aegis_database
cli/aegis                   # CLI без зависимостей (vm, db, schedule, token, audit)
VERIFICATION.md             # чеклист живой проверки на реальном сервере
```

---

## 6. Модель безопасности

- **Авторизация**: токен в заголовке `Authorization` (не в куках). Все API требуют
  `get_current_user`; управление хостом (nginx, iptables, docker, реестр, внешние
  серверы, миграция) — только админ (`check_admin` / `verify_admin_token`).
  Принимаются три вида учётных данных: сессионный токен (HMAC-SHA256 + `exp`),
  `X-Admin-Token` и персональный API-токен `aeg_...` (в БД только SHA-256).
  Секреты сравниваются за постоянное время (`core.auth.secure_eq`).
- **Второй фактор**: TOTP по RFC 6238 с одноразовыми резервными кодами. При
  включённой 2FA логин с верным паролем, но без кода отвечает `TOTP_REQUIRED`
  и не засчитывается как неудачная попытка.
- **Владение ресурсами и роли**: базово — только свои ресурсы (`check_vm_ownership`,
  фильтр по `owner_id`). Поверх этого — проекты (`core/rbac.py`): участник получает
  доступ по роли, где `viewer` может читать, но не изменять. Единый шлюз доступа к ВМ
  по умолчанию требует роль `editor`, то есть забытая проверка делает эндпоинт
  строже, а не дырявее. Выдача SSH-паролей намеренно оставлена на уровне `editor`.
- **Секреты**: в БД только в зашифрованном виде (Fernet) или хэшированные (пароли
  входа — PBKDF2, API-токены — SHA-256). Обязательные пароли инфраструктуры
  (`POSTGRES_PASSWORD`, `RABBITMQ_*`, `MINIO_ROOT_PASSWORD`, …) объявлены в
  `docker-compose.yml` как `${VAR:?}`: без них compose не стартует, вместо того
  чтобы молча подставить значение по умолчанию.
- **Изоляция БД**: каждая пользовательская БД — отдельный под с `NetworkPolicy`,
  доступ только привязанной ВМ.
- **Анти-инъекция**: значения, уходящие в shell (`iptables`, имена nginx-пулов, IP),
  проходят строгую проверку (`netutils.is_valid_ipv4 / is_valid_ip_or_cidr / is_safe_name`).
  Имена репозиториев и тегов реестра проверяются по грамматике Docker (иначе `..`
  в пути уводил запрос за пределы репозитория), а значения переменных маркетплейса
  не могут содержать перенос строки (иначе в `.env` дописывались чужие переменные).
- **Исходящие запросы**: адрес webhook-канала проверяется по **результату резолва**,
  а не по строке, и повторно перед каждой отправкой (`core/ssrf.py`). Иначе панель,
  работающая в сети хоста, становилась прокси во внутреннюю сеть — к метаданным
  облака (`169.254.169.254`) и к собственному API на `localhost`.
- **Владение доменом**: прежде чем домен начнёт проксироваться, проверяется TXT-запись
  `_aegis-challenge.<домен>`. Без этого любой пользователь мог бы забрать себе домен,
  который и так указывает на сервер, и увести его трафик на свою ВМ.
- **Реестр образов**: обязательная аутентификация htpasswd/bcrypt; пароль генерируется
  автоматически и хранится зашифрованным.
- **Ошибки наружу**: ответы `5xx` отдают только код обращения, полный текст уходит в
  лог — чтобы не раскрывать трейсбеки, пути и внутренние адреса. Сообщения `4xx`
  (квоты, валидация) остаются информативными.
- **Сетевой периметр**: служебные порты (PostgreSQL, RabbitMQ, MariaDB, консоль MinIO)
  слушают только `127.0.0.1`; наружу торчат веб-панель, S3 API, почта, реестр (`5000`)
  и прокси доменов (`80`/`443`).

> **Граница доверия.** Backend и worker работают с `network_mode: host`, `pid: host`,
> расширенными capabilities и доступом к `docker.sock` — они по замыслу управляют самим
> хостом через `nsenter`. Контейнерной изоляции у control-plane нет: компрометация
> бэкенда равносильна компрометации хоста. Поэтому доступ в панель и есть главный
> периметр защиты.

---

## 7. Мини-глоссарий

- **VMI** — VirtualMachineInstance, запущенный экземпляр ВМ в KubeVirt.
- **nsenter** — вход в неймспейсы хоста из контейнера (так backend правит сеть хоста).
- **Бастион / jump host** — промежуточный SSH-сервер, через который панель ходит к
  недоступным напрямую (локальным) серверам.
- **Fernet** — симметричное шифрование (AES) для секретов в БД.
- **Multus / br-vms** — сетевой слой: мост хоста, к которому подключаются ВМ.
- **TOTP** — одноразовый код по времени (RFC 6238), второй фактор входа.
- **ACME / HTTP-01** — протокол выпуска сертификатов Let's Encrypt: сервер должен
  ответить на проверку по порту 80, поэтому он обязан быть открыт снаружи.
- **TXT-челлендж** — запись `_aegis-challenge.<домен>` с токеном: доказывает, что
  домен принадлежит тому, кто его добавляет.
- **SSRF** — атака, когда сервер заставляют сходить по внутреннему адресу
  (метаданные облака, собственное API); отсюда проверка webhook-адресов.
- **RBAC** — доступ по ролям: `viewer` (чтение), `editor` (управление ресурсами),
  `owner` (плюс участники проекта).
- **CDI DataVolume** — механизм KubeVirt для копирования дисков; на нём сделаны
  бэкапы ВМ.
