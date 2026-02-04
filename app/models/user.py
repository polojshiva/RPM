"""
User Models
Pydantic models for user authentication and authorization with Azure AD
"""
from enum import Enum
from typing import List
from pydantic import BaseModel


class UserRole(str, Enum):
    """User roles for RBAC"""
    INTAKE_COORDINATOR = "IntakeCoordinator"
    COORDINATOR = "IntakeCoordinator"  # Alias for compatibility
    ADMIN = "Admin"
    SUPER_ADMIN = "SuperAdmin"
    MD = "MD"
    REVIEWER = "MD"  # Reviewers are typically MDs
    USER = "User"


class User(BaseModel):
    """User model for Azure AD authenticated users"""
    id: str
    username: str
    email: str
    name: str
    roles: List[UserRole]

    class Config:
        from_attributes = True
