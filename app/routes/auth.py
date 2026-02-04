"""
Authentication Routes
Azure AD SSO authentication endpoints for user info and roles

Frontend Integration:
- Frontend sends Azure AD access tokens directly
- Backend validates Azure AD tokens on each request
- Extract user info from Azure AD token claims (not database)
- No login/refresh/logout endpoints needed (MSAL handles this)
"""
import uuid
from typing import Dict, Any
from fastapi import APIRouter, Request, Depends
from app.models.user import User
from app.auth.dependencies import get_current_user


router = APIRouter(prefix="/api/auth", tags=["Authentication"])





def create_success_response(data: Any, correlation_id: str = None) -> Dict[str, Any]:
    """Create standardized success response as expected by frontend"""
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
    
    return {
        "success": True,
        "data": data,
        "correlation_id": correlation_id
    }


@router.get("/user-info")
async def get_user_info(
    request: Request,
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get current user information extracted from Azure AD token claims
    
    Purpose: Return user data as required by frontend from Azure AD token
    Backend extracts user info from validated Azure AD token claims (not database)
    
    Returns:
        User information including id, username, email, name, and roles
    """
    
    correlation_id = getattr(request.state, 'correlation_id', str(uuid.uuid4()))
    
    user_data = {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "name": current_user.name,
        "roles": [role.value for role in current_user.roles]
    }
    
    return create_success_response(user_data, correlation_id)


@router.get("/user-roles")
async def get_user_roles(
    request: Request,
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get current user's assigned roles from Azure AD app registration
    
    Purpose: Return user roles as extracted from Azure AD token claims
    Backend extracts roles from Azure AD token (not database lookup)
    
    Returns:
        List of user roles from Azure AD app registration
    """
    correlation_id = getattr(request.state, 'correlation_id', str(uuid.uuid4()))
    
    roles_data = {
        "user_id": current_user.id,
        "roles": [role.value for role in current_user.roles]
    }
    
    return create_success_response(roles_data, correlation_id)

