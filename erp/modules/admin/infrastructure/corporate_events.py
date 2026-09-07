"""M1 corporate event names and routing contracts."""

from erp.platform.messaging import build_routing_key

COMPANY_CREATED = "CompanyCreated"
BRANCH_CREATED = "BranchCreated"
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

__all__ = [
    "BRANCH_CREATED",
    "BRANCH_CREATED_ROUTING_KEY",
    "COMPANY_CREATED",
    "COMPANY_CREATED_ROUTING_KEY",
]
