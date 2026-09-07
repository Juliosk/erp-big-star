"""Application use cases for the M1 bounded context."""

from erp.modules.admin.application.auth_dto import (
    AuthenticationResult,
    LoginCommand,
    RefreshTokenClaims,
    TokenPair,
)
from erp.modules.admin.application.auth_ports import (
    IdentityRepository,
    PasswordVerifier,
    SessionRepository,
    TokenService,
)
from erp.modules.admin.application.auth_service import AuthenticationService
from erp.modules.admin.application.corporate_command_dto import (
    BranchCreationResult,
    BranchUpdateResult,
    BranchView,
    CompanyCreationResult,
    CompanyUpdateResult,
    CreateBranchCommand,
    CreateCompanyCommand,
    RequestMetadata,
    UpdateBranchCommand,
    UpdateCompanyCommand,
)
from erp.modules.admin.application.corporate_command_ports import CorporateCommandStore
from erp.modules.admin.application.corporate_command_service import CorporateCreationService
from erp.modules.admin.application.corporate_dto import CompanyView
from erp.modules.admin.application.corporate_permissions import (
    ADMIN_BRANCH_CREATE,
    ADMIN_BRANCH_READ,
    ADMIN_BRANCH_UPDATE,
    ADMIN_COMPANY_CREATE,
    ADMIN_COMPANY_READ,
    ADMIN_COMPANY_UPDATE,
    ADMIN_ECONOMIC_GROUP_READ,
    corporate_permission_registry,
)
from erp.modules.admin.application.corporate_ports import CorporateDirectory
from erp.modules.admin.application.corporate_query_service import ListCompaniesService
from erp.modules.admin.application.security import SecurityContext, SecurityContextResolver

__all__ = [
    "ADMIN_BRANCH_CREATE",
    "ADMIN_BRANCH_READ",
    "ADMIN_BRANCH_UPDATE",
    "ADMIN_COMPANY_CREATE",
    "ADMIN_COMPANY_READ",
    "ADMIN_COMPANY_UPDATE",
    "ADMIN_ECONOMIC_GROUP_READ",
    "AuthenticationResult",
    "AuthenticationService",
    "BranchCreationResult",
    "BranchUpdateResult",
    "BranchView",
    "CompanyCreationResult",
    "CompanyUpdateResult",
    "CompanyView",
    "CorporateCommandStore",
    "CorporateCreationService",
    "CorporateDirectory",
    "CreateBranchCommand",
    "CreateCompanyCommand",
    "IdentityRepository",
    "ListCompaniesService",
    "LoginCommand",
    "PasswordVerifier",
    "RefreshTokenClaims",
    "RequestMetadata",
    "SecurityContext",
    "SecurityContextResolver",
    "SessionRepository",
    "TokenPair",
    "TokenService",
    "UpdateBranchCommand",
    "UpdateCompanyCommand",
    "corporate_permission_registry",
]
