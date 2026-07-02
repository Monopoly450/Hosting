from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey
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
    password = Column(String, nullable=False)

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
    
    # Queue / State
    status = Column(String, default="Pending") # Pending, Provisioning, Running, Error
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    cluster = relationship("Cluster", back_populates="vms")
    owner = relationship("User", back_populates="vms")
