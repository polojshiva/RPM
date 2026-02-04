"""
Authentication Dependencies
FastAPI dependencies for Azure AD SSO authentication

Frontend Integration:
- Frontend sends Azure AD access tokens directly in Authorization header
- Backend validates Azure AD tokens on each API request  
- Extract user info from Azure AD token claims (no database lookup)
- Stateless authentication via token validation only
"""
import logging
from typing import List
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.auth.azure_jwt import verify_token
from app.auth.role_mapper import map_azure_groups_to_roles
from app.models.user import User, UserRole


# Set up logging
logger = logging.getLogger(__name__)

security = HTTPBearer()


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> User:
    """
    Extract and validate user from Azure AD JWT token
    
    Frontend Integration:
    - Validates Azure AD access token from Authorization header
    - Extracts user info from Azure AD token claims (not database)
    - Maps Azure AD groups/roles to application roles
    - Returns User object with data from token claims
    
    Args:
        request: FastAPI request object
        credentials: HTTP Bearer token credentials (Azure AD access token)
        
    Returns:
        User object with claims extracted from Azure AD token
        
    Raises:
        HTTPException: If token is invalid or user cannot be extracted
    """
    try:
        logger.debug("Processing Azure AD SSO authentication request...")
        
        if not credentials:
            logger.warning("No credentials provided by HTTPBearer dependency")
            raise HTTPException(
                status_code=401,
                detail="No Authorization header provided"
            )
        
        # Extract Azure AD access token from Authorization header
        token = credentials.credentials
        logger.debug(f"Azure AD token length: {len(token)} characters")
        
        # Verify Azure AD token and get claims
        logger.debug("Validating Azure AD token with Microsoft")
        claims = await verify_token(token)
        logger.info(f"Azure AD token verified successfully. Claims keys: {list(claims.keys())}")  # Keep as INFO - milestone
        
        # Extract user information from Azure AD token claims
        user_id = claims.get("oid") or claims.get("sub")
        if not user_id:
            logger.error("Azure AD token missing user identifier (oid/sub)")
            raise HTTPException(
                status_code=401,
                detail="Azure AD token missing user identifier (oid/sub)"
            )
        
        username = claims.get("preferred_username", "") or claims.get("unique_name", "") or claims.get("upn", "")
        email = claims.get("email", "") or claims.get("unique_name", "") or claims.get("upn", "") or username
        name = claims.get("name", username)
        
        logger.debug(f"User extracted from Azure AD token - ID: {user_id}, Username: {username}, Name: {name}")  # Changed to DEBUG
        
        # Extract and map roles from Azure AD token claims
        groups = claims.get("groups", [])
        roles_claim = claims.get("roles", [])
        logger.debug(f"Groups from Azure AD token: {groups}")
        logger.debug(f"Roles from Azure AD token: {roles_claim}")
        
        # Combine groups and roles claims
        all_groups = list(set(groups + roles_claim))
        logger.debug(f"Combined Azure AD groups/roles: {all_groups}")
        
        # Map Azure AD groups/roles to application roles
        roles = map_azure_groups_to_roles(all_groups)
        logger.debug(f"Mapped application roles: {[role.value for role in roles]}")  # Changed to DEBUG
        
        # Create User object from Azure AD token claims (stateless)
        user = User(
            id=user_id,
            username=username,
            email=email,
            name=name,
            roles=roles
        )
        
        logger.info(f"Azure AD SSO authentication successful for user: {user.username}")  # Keep as INFO - important milestone
        return user
        
    except HTTPException as http_ex:
        logger.error(f"HTTP Authentication error: {http_ex.detail}")
        raise http_ex
    except Exception as e:
        logger.error(f"Unexpected Azure AD authentication error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=401,
            detail=f"Azure AD authentication failed: {str(e)}"
        )


def require_roles(required_roles: List[UserRole]):
    """
    Dependency factory to require specific roles
    
    Args:
        required_roles: List of roles that are allowed access
        
    Returns:
        Dependency function that validates user roles
    """
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        """
        Check if user has any of the required roles
        
        Args:
            current_user: Current authenticated user
            
        Returns:
            User object if authorized
            
        Raises:
            HTTPException: If user lacks required roles
        """
        # Check if user has any of the required roles
        user_has_required_role = any(role in current_user.roles for role in required_roles)
        
        if not user_has_required_role:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required roles: {[role.value for role in required_roles]}"
            )
        
        return current_user
    
    return role_checker