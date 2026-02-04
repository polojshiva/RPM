"""
SQLAlchemy models for integration schema
Maps to integration.send_serviceops and related tables
"""
from sqlalchemy import Column, String, Integer, DateTime, BigInteger, Boolean, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import MetaData
from datetime import datetime

# Import Base from packet_db to ensure same registry
from app.models.packet_db import Base


class SendServiceOpsDB(Base):
    """
    Maps to integration.send_serviceops table
    Stores messages from clinical_ops that need to be processed into service_ops.packet
    """
    __tablename__ = "send_serviceops"
    __table_args__ = {'schema': 'integration'}
    
    message_id = Column(BigInteger, primary_key=True)
    decision_tracking_id = Column(String)  # UUID - links to clinical_ops workflow
    workflow_instance_id = Column(BigInteger, nullable=True)
    payload = Column(JSONB, nullable=False)  # Contains all data: ingest_data, file_download_data, documents
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    audit_user = Column(String(100))
    audit_timestamp = Column(DateTime(timezone=True), default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)
    channel_type_id = Column(BigInteger, nullable=True)  # 1=Portal, 2=Fax, 3=ESMD
    message_type_id = Column(BigInteger, nullable=True)  # 1=Process, 2=Skip (different workflow)

