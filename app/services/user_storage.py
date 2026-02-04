"""
User storage and management for Azure AD authenticated users
"""
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from app.models.user import User, UserRole


# In-memory user storage (replace with database in production)
_user_storage: Dict[str, Dict] = {}


def store_user(user: User) -> User:
    """
    Store user information in memory
    
    Args:
        user: User object to store
        
    Returns:
        Stored user object
    """
    user_data = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "name": user.name,
        "roles": [role.value for role in user.roles],
        "created_at": datetime.utcnow().isoformat(),
        "last_login": datetime.utcnow().isoformat()
    }
    
    _user_storage[user.id] = user_data
    return user


def get_stored_user(user_id: str) -> Optional[User]:
    """
    Retrieve stored user by ID
    
    Args:
        user_id: User identifier
        
    Returns:
        User object if found, None otherwise
    """
    user_data = _user_storage.get(user_id)
    if not user_data:
        return None
    
    return User(
        id=user_data["id"],
        username=user_data["username"], 
        email=user_data["email"],
        name=user_data["name"],
        roles=[UserRole(role) for role in user_data["roles"]]
    )


def update_user_login(user_id: str) -> None:
    """
    Update user's last login timestamp
    
    Args:
        user_id: User identifier
    """
    if user_id in _user_storage:
        _user_storage[user_id]["last_login"] = datetime.utcnow().isoformat()


def list_all_users() -> List[Dict]:
    """
    Get all stored users
    
    Returns:
        List of user data dictionaries
    """
    return list(_user_storage.values())


def user_exists(user_id: str) -> bool:
    """
    Check if user exists in storage
    
    Args:
        user_id: User identifier
        
    Returns:
        True if user exists, False otherwise
    """
    return user_id in _user_storage