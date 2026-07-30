from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import relationship
import datetime
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="student")  # "admin" or "student"
    balance = Column(Float, default=100.0)
    
    # Quotas
    max_vcpus = Column(Integer, default=4)
    max_ram_mb = Column(Integer, default=4096)
    max_vms = Column(Integer, default=2)
    max_storage_gb = Column(Integer, default=40)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Двухфакторная аутентификация (TOTP)
    totp_secret = Column(String, nullable=True)        # base32-секрет, зашифрован (Fernet)
    totp_enabled = Column(Boolean, default=False)      # включена ли 2FA
    totp_backup_codes = Column(Text, nullable=True)    # JSON-список SHA-256 неиспользованных кодов

    # Relationships
    vms = relationship("VMTask", back_populates="owner")
    clusters = relationship("Cluster", back_populates="owner")
    databases = relationship("UserDatabase", back_populates="owner")
    buckets = relationship("UserBucket", back_populates="owner")
    volumes = relationship("UserVolume", back_populates="owner")
    mailboxes = relationship("UserMailbox", back_populates="owner")

class UserDatabase(Base):
    __tablename__ = "user_databases"

    id = Column(Integer, primary_key=True, index=True)
    db_name = Column(String, unique=True, index=True, nullable=False)
    db_type = Column(String, default="postgres")  # "postgres" or "mysql"
    db_user = Column(String, nullable=False)
    db_password = Column(String, nullable=False)
    associated_vm_id = Column(Integer, ForeignKey("vm_tasks.id"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    status = Column(String, default="Active")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    owner = relationship("User", back_populates="databases")

class UserBucket(Base):
    __tablename__ = "user_buckets"

    id = Column(Integer, primary_key=True, index=True)
    bucket_name = Column(String, unique=True, index=True, nullable=False)
    access_key = Column(String, nullable=False)
    secret_key = Column(String, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    owner = relationship("User", back_populates="buckets")

class UserVolume(Base):
    __tablename__ = "user_volumes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    size_gb = Column(Integer, nullable=False)
    attached_vm_id = Column(Integer, ForeignKey("vm_tasks.id"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String, default="Available")  # "Available" or "Attached"
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    owner = relationship("User", back_populates="volumes")

class UserMailbox(Base):
    __tablename__ = "user_mailboxes"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    quota_mb = Column(Integer, default=500)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    owner = relationship("User", back_populates="mailboxes")

class ExternalServer(Base):
    __tablename__ = "external_servers"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    host = Column(String, nullable=False)
    port = Column(Integer, default=22)
    username = Column(String, default="root")
    password = Column(String, nullable=False)  # encrypted (app.core.crypto)

    # Optional SSH bastion / jump host — панель ходит на target через этот сервер
    bastion_host = Column(String, nullable=True)
    bastion_port = Column(Integer, default=22)
    bastion_username = Column(String, nullable=True)
    bastion_password = Column(String, nullable=True)  # encrypted (app.core.crypto)

class SystemState(Base):
    __tablename__ = "system_state"

    id = Column(Integer, primary_key=True, default=1)
    balance = Column(Float, default=50.0)
    billing_rate = Column(Float, default=0.0)
    ddos_active = Column(Boolean, default=False)

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    time = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(String, nullable=False)

class AWSSecurityGroup(Base):
    __tablename__ = "aws_security_groups"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    rules = Column(JSONB, default=list)
    bound_instances = Column(JSONB, default=list)

class AWSS3Bucket(Base):
    __tablename__ = "aws_s3_buckets"

    name = Column(String, primary_key=True, index=True)
    region = Column(String, default="us-east-1")
    access_policy = Column(String, default="Private")
    objects = Column(JSONB, default=list)

class AWSIAMUser(Base):
    __tablename__ = "aws_iam_users"

    username = Column(String, primary_key=True, index=True)
    policy = Column(String, nullable=False)
    joined_at = Column(String, nullable=False)

class Cluster(Base):
    __tablename__ = "clusters"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    network_name = Column(String)  # Multus NetworkAttachmentDefinition name
    status = Column(String, default="Creating") # Creating, Active, Error
    
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    vms = relationship("VMTask", back_populates="cluster")
    owner = relationship("User", back_populates="clusters")

class VMTask(Base):
    __tablename__ = "vm_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    cluster_id = Column(Integer, ForeignKey("clusters.id"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    
    # VM Spec
    os_type = Column(String)
    cpu_cores = Column(Integer)
    memory_gb = Column(Integer)
    disk_gb = Column(Integer)
    custom_image = Column(String, nullable=True)
    packages = Column(String, nullable=True)
    network_drives = Column(String, nullable=True)
    
    # New limits and security fields
    disk_read_mbs = Column(Integer, default=0)
    disk_write_mbs = Column(Integer, default=0)
    disk_read_iops = Column(Integer, default=0)
    disk_write_iops = Column(Integer, default=0)
    ports_config = Column(String, nullable=True) # JSON array of ports and forwarding rules
    firewall_rules = Column(String, nullable=True) # JSON array of firewall whitelist rules
    cloud_init_template = Column(String, nullable=True)
    custom_user_data = Column(Text, nullable=True)
    iso_url = Column(String, nullable=True)
    ssh_key = Column(String, nullable=True)
    static_ip = Column(String, nullable=True)  # стабильный IP на мосту br-vms (172.20.0.x)
    # Пароль, реально прописанный в cloud-init (шифруется Fernet).
    # Нужен, когда cloud-init задан извне — деплои и маркетплейс генерируют
    # пароль сами, и воркер обязан положить в Secret именно его, иначе панель
    # не сможет зайти в ВМ по SSH (логи сборки, терминал, подсказка подключения).
    vm_password = Column(String, nullable=True)
    
    # Queue / State
    status = Column(String, default="Pending") # Pending, Provisioning, Running, Error
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    cluster = relationship("Cluster", back_populates="vms")
    owner = relationship("User", back_populates="vms")


class AppDeployment(Base):
    __tablename__ = "app_deployments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    repo_url = Column(String, nullable=False)
    branch = Column(String, default="main")
    stack = Column(String, default="compose")  # compose | dockerfile | node | python | static | custom
    app_port = Column(Integer, default=3000)   # порт, который слушает приложение внутри ВМ
    run_command = Column(Text, nullable=True)   # своя команда запуска (для custom и переопределений)

    # Привязанная выделенная ВМ
    vm_id = Column(Integer, ForeignKey("vm_tasks.id"), nullable=True)
    vm_name = Column(String, nullable=True)

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    status = Column(String, default="Deploying")  # Deploying | Running | Error
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    username = Column(String, index=True)   # кто выполнил действие
    ip = Column(String)                     # с какого IP
    method = Column(String)                 # HTTP-метод
    path = Column(String)                   # путь запроса
    action = Column(String)                 # человекочитаемое действие
    status_code = Column(Integer)           # код ответа
    success = Column(Boolean, default=True)


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)          # понятное имя (напр. "ci-runner")
    token_prefix = Column(String, nullable=False)  # первые символы для отображения (aeg_1a2b…)
    token_hash = Column(String, unique=True, index=True, nullable=False)  # SHA-256 самого токена
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_used = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)


class BackupSchedule(Base):
    """Расписание автоматических бэкапов ВМ или базы данных.
    Планировщик в воркере раз в минуту проверяет next_run и запускает бэкап,
    когда время наступило, затем ротирует старые копии по retention."""
    __tablename__ = "backup_schedules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)                # понятное имя расписания
    target_type = Column(String, nullable=False)         # "vm" | "database"
    target_id = Column(Integer, nullable=False)          # VMTask.id или UserDatabase.id
    target_name = Column(String, nullable=False)         # имя ВМ / БД (для отображения и запуска)
    frequency = Column(String, nullable=False, default="daily")  # "hourly" | "daily" | "weekly"
    hour = Column(Integer, default=3)                    # час (UTC) для daily/weekly
    minute = Column(Integer, default=0)                  # минута
    weekday = Column(Integer, nullable=True)             # день недели 0=Пн..6=Вс для weekly
    retention = Column(Integer, default=7)               # сколько последних копий хранить
    enabled = Column(Boolean, default=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_run = Column(DateTime, nullable=True)
    last_status = Column(String, nullable=True)          # "success" | "error: ..."
    next_run = Column(DateTime, nullable=True)


class Project(Base):
    """Проект — рабочее пространство, объединяющее ресурсы и участников."""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class ProjectMember(Base):
    """Участник проекта и его роль.
    viewer — только чтение, editor — управление ресурсами, owner — плюс участники."""
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String, nullable=False, default="viewer")  # viewer | editor | owner
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Domain(Base):
    """Свой домен пользователя, проксируемый Caddy на ВМ с автоматическим TLS
    (Let's Encrypt). Caddy держит сертификаты сам, панель лишь генерирует конфиг."""
    __tablename__ = "domains"

    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String, unique=True, index=True, nullable=False)
    target_type = Column(String, nullable=False, default="deployment")  # "deployment" | "vm"
    target_id = Column(Integer, nullable=False)
    target_port = Column(Integer, nullable=False)     # внутренний порт приложения в ВМ
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String, default="pending")        # pending | active | error
    # Подтверждение владения доменом: TXT-запись _aegis-challenge.<домен>
    verification_token = Column(String, nullable=True)
    ownership_ok = Column(Boolean, default=False)
    dns_ok = Column(Boolean, default=False)           # A-запись указывает на наш хост
    last_checked = Column(DateTime, nullable=True)
    last_error = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class NotificationChannel(Base):
    """Канал доставки уведомлений об алертах (webhook или Telegram).
    config шифруется (может содержать секреты: bot_token, URL с токеном)."""
    __tablename__ = "notification_channels"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)                # "webhook" | "telegram"
    config = Column(Text, nullable=False)                # JSON, зашифрован (app.core.crypto)
    enabled = Column(Boolean, default=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class AlertRule(Base):
    """Правило оповещения по метрике. Демон в воркере периодически считывает
    метрику, сравнивает с порогом и при СМЕНЕ состояния (ok<->firing) шлёт
    уведомление в привязанный канал."""
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    target_type = Column(String, nullable=False)         # "vm" | "host"
    target_id = Column(Integer, nullable=True)           # VMTask.id (для host — NULL)
    target_name = Column(String, nullable=False)         # имя ВМ или "host"
    metric = Column(String, nullable=False)              # status | cpu_percent | memory_percent
    comparator = Column(String, default=">")             # ">" | "<" (для числовых метрик)
    threshold = Column(Float, nullable=True)             # порог (для status не используется)
    channel_id = Column(Integer, ForeignKey("notification_channels.id"), nullable=True)
    enabled = Column(Boolean, default=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    # Состояние
    state = Column(String, default="ok")                 # "ok" | "firing" | "unknown"
    last_value = Column(Float, nullable=True)
    last_checked = Column(DateTime, nullable=True)
    last_state_change = Column(DateTime, nullable=True)
    last_notified = Column(DateTime, nullable=True)
    last_error = Column(String, nullable=True)
