"""
Azure AD Groups and Roles to Application Role Mapping

Frontend Integration:
- Maps Azure AD groups and app registration roles to application roles
- Supports both group memberships and application role assignments
- Handles roles claim from Azure AD token
"""
from typing import List
from app.models.user import UserRole


def map_azure_groups_to_roles(groups_and_roles: List[str]) -> List[UserRole]:
    """
    Map Azure AD groups and application roles to application roles
    
    Frontend Integration:
    - Processes both 'groups' and 'roles' claims from Azure AD token
    - Maps Azure AD app registration roles (IntakeCoordinator, Admin, etc.)
    - Maps Azure AD security groups to application roles
    - Supports role hierarchy and combinations
    
    Args:
        groups_and_roles: List of Azure AD group names/IDs and application role names
        
    Returns:
        List of UserRole enums mapped from Azure AD claims
    """
    # Azure AD Application Roles (from app registration)
    app_role_mapping = {
        "IntakeCoordinator": UserRole.INTAKE_COORDINATOR,
        "Admin": UserRole.ADMIN,
        "SuperAdmin": UserRole.SUPER_ADMIN,
        "MD": UserRole.MD,
        "User": UserRole.USER
    }
    
    # Azure AD Group Names to Role mapping (security groups)
    group_role_mapping = {
        "WISeR-Admins": UserRole.ADMIN,
        "WISeR-SuperAdmins": UserRole.SUPER_ADMIN,
        "WISeR-MDs": UserRole.MD,
        "WISeR-Coordinators": UserRole.INTAKE_COORDINATOR,
        "WISeR-Users": UserRole.USER
    }
    
    roles = []
    
    # Check each group/role and add corresponding application roles
    for item in groups_and_roles:
        # Check application roles first (from Azure AD app registration)
        if item in app_role_mapping:
            role = app_role_mapping[item]
            if role not in roles:  # Avoid duplicates
                roles.append(role)
        # Then check group memberships (Azure AD security groups)
        elif item in group_role_mapping:
            role = group_role_mapping[item]
            if role not in roles:  # Avoid duplicates
                roles.append(role)
    
    # If no roles found, default to User role
    if not roles:
        roles.append(UserRole.USER)
    
    return roles