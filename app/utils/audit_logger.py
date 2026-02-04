"""
Audit Logger
Append-only file-based audit trail for compliance and forensics
"""
import json
import os
import logging
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel
from app.config import settings

logger = logging.getLogger(__name__)


class AuditEntry(BaseModel):
    """Audit log entry structure"""
    timestamp: str
    user_id: Optional[str] = None
    username: Optional[str] = None
    ip: Optional[str] = None
    action: str  # 'login', 'logout', 'packet:create', 'packet:update', etc.
    outcome: str  # 'success' or 'failure'
    details: Optional[str] = None


def write_audit_log(entry: AuditEntry) -> None:
    """
    Write an audit log entry to the audit log file.
    Appends JSON lines to the file with restricted permissions.
    """
    log_path = settings.audit_log_path

    # Ensure timestamp is set
    if not entry.timestamp:
        entry.timestamp = datetime.now(timezone.utc).isoformat()

    # Convert to JSON line
    log_line = entry.model_dump_json() + "\n"

    try:
        # Append to log file
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_line)

        # Set restrictive permissions (Unix only)
        try:
            os.chmod(log_path, 0o600)
        except (OSError, AttributeError):
            pass  # Windows doesn't support chmod the same way

    except IOError as e:
        # Log error but don't fail the request
        logger.error(f"Failed to write audit log: {e}")


def log_auth_event(
    action: str,
    outcome: str,
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    ip: Optional[str] = None,
    details: Optional[str] = None,
) -> None:
    """Helper function to log authentication events"""
    entry = AuditEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        user_id=user_id,
        username=username,
        ip=ip,
        action=action,
        outcome=outcome,
        details=details,
    )
    write_audit_log(entry)


def log_packet_event(
    action: str,
    outcome: str,
    user_id: str,
    username: str,
    ip: Optional[str] = None,
    packet_id: Optional[str] = None,
    details: Optional[str] = None,
) -> None:
    """Helper function to log packet-related events"""
    entry = AuditEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        user_id=user_id,
        username=username,
        ip=ip,
        action=f"packet:{action}",
        outcome=outcome,
        details=f"Packet ID: {packet_id}. {details}" if packet_id else details,
    )
    write_audit_log(entry)
