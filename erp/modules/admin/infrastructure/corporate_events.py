"""M1 corporate event names and routing contracts."""

from erp.platform.messaging import build_routing_key

COMPANY_CREATED = "CompanyCreated"
BRANCH_CREATED = "BranchCreated"
COMPANY_UPDATED = "CompanyUpdated"
BRANCH_UPDATED = "BranchUpdated"
COMPANY_CREATED_ROUTING_KEY = build_routing_key(
    domain="admin",
    aggregate="company",
    action="created",
    version=1,
)
BRANCH_CREATED_ROUTING_KEY = build_routing_key(
    domain="admin",
    aggregate="branch",
    action="created",
    version=1,
)
COMPANY_UPDATED_ROUTING_KEY = build_routing_key(
    domain="admin",
    aggregate="company",
    action="updated",
    version=1,
)
BRANCH_UPDATED_ROUTING_KEY = build_routing_key(
    domain="admin",
    aggregate="branch",
    action="updated",
    version=1,
)

__all__ = [
    "BRANCH_CREATED",
    "BRANCH_CREATED_ROUTING_KEY",
    "BRANCH_UPDATED",
    "BRANCH_UPDATED_ROUTING_KEY",
    "COMPANY_CREATED",
    "COMPANY_CREATED_ROUTING_KEY",
    "COMPANY_UPDATED",
    "COMPANY_UPDATED_ROUTING_KEY",
]
