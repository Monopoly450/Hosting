from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
import datetime
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base

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
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    vms = relationship("VMTask", back_populates="cluster")

class VMTask(Base):
    __tablename__ = "vm_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    cluster_id = Column(Integer, ForeignKey("clusters.id"), nullable=True)
    
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
    
    # Queue / State
    status = Column(String, default="Pending") # Pending, Provisioning, Running, Error
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    cluster = relationship("Cluster", back_populates="vms")
