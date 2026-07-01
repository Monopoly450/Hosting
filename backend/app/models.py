from sqlalchemy import Column, Integer, String, JSON, ForeignKey, DateTime
from sqlalchemy.orm import relationship
import datetime
from .db import Base

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
    
    # Queue / State
    status = Column(String, default="Pending") # Pending, Provisioning, Running, Error
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    cluster = relationship("Cluster", back_populates="vms")
