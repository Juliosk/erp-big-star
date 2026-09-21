"""Supplier aggregate lifecycle and establishment invariants."""

from dataclasses import replace
from typing import Any, cast
from uuid import uuid4

import pytest

from erp.modules.procurement.domain import (
    DuplicateSupplierSiteError,
    InvalidSupplierDataError,
    InvalidSupplierIdentityError,
    InvalidSupplierTransitionError,
    Supplier,
    SupplierAddress,
    SupplierIdentityKind,
    SupplierKind,
    SupplierSite,
    SupplierStatus,
)


def supplier(*, kind: SupplierKind = SupplierKind.COMPANY) -> Supplier:
    if kind is SupplierKind.INDIVIDUAL:
        identity_kind = SupplierIdentityKind.CPF
        identity_value = "52998224725"
        country = "BR"
    elif kind is SupplierKind.FOREIGN:
        identity_kind = SupplierIdentityKind.FOREIGN_REGISTRATION
        identity_value = "US-998877"
        country = "US"
    else:
        identity_kind = SupplierIdentityKind.CNPJ
        identity_value = "11222333000181"
        country = "BR"
    return Supplier.create(
        company_id=uuid4(),
        kind=kind,
        identity_kind=identity_kind,
        identity_value=identity_value,
        identity_country_code=country,
        legal_name=" Supplier Legal Name ",
        trade_name=" Supplier Trade Name ",
    )


def site(owner: Supplier, *, code: str, primary: bool = False) -> SupplierSite:
    return SupplierSite.create(
        company_id=owner.company_id,
        supplier_id=owner.id,
        code=code,
        name=f"Site {code}",
        address=SupplierAddress.create(
            line1="Rua Um",
            city="Sao Paulo",
            state="SP",
            postal_code="01234567",
            country_code="BR",
        ),
        is_primary=primary,
    )


@pytest.mark.parametrize("kind", list(SupplierKind))
def test_supplier_creation_supports_domestic_and_foreign_kinds(kind: SupplierKind) -> None:
    created = supplier(kind=kind)

    assert created.status is SupplierStatus.ACTIVE
    assert created.legal_name == "Supplier Legal Name"
    assert created.trade_name == "Supplier Trade Name"
    assert created.sites == ()
    assert created.version == 1


def test_supplier_kind_must_match_fiscal_identity() -> None:
    with pytest.raises(InvalidSupplierIdentityError, match="incompatible"):
        Supplier.create(
            company_id=uuid4(),
            kind=SupplierKind.COMPANY,
            identity_kind=SupplierIdentityKind.CPF,
            identity_value="52998224725",
            identity_country_code="BR",
            legal_name="Wrong identity supplier",
        )


def test_supplier_lifecycle_is_explicit_versioned_and_restricts_blocked_state() -> None:
    created = supplier()
    inactive = created.transition_status(SupplierStatus.INACTIVE)
    blocked = inactive.transition_status(SupplierStatus.BLOCKED)

    assert inactive.version == 2
    assert blocked.version == 3
    assert blocked.transition_status(SupplierStatus.BLOCKED) is blocked
    with pytest.raises(InvalidSupplierTransitionError, match="not allowed"):
        blocked.transition_status(SupplierStatus.INACTIVE)
    active = blocked.transition_status(SupplierStatus.ACTIVE)
    assert active.status is SupplierStatus.ACTIVE
    assert active.version == 4


def test_update_master_preserves_identity_and_avoids_noop_version() -> None:
    created = supplier()

    unchanged = created.update_master(
        legal_name=created.legal_name, trade_name=created.trade_name
    )
    changed = created.update_master(legal_name=" New Legal ", trade_name=None)

    assert unchanged is created
    assert changed.version == 2
    assert changed.legal_name == "New Legal"
    assert changed.trade_name is None
    assert changed.tax_identity == created.tax_identity


def test_supplier_supports_multiple_unique_sites_and_one_primary() -> None:
    created = supplier()
    with_primary = created.add_site(site(created, code="MATRIZ", primary=True))
    complete = with_primary.add_site(site(created, code="FILIAL_01"))

    assert [item.code for item in complete.sites] == ["MATRIZ", "FILIAL_01"]
    assert complete.version == 3
    with pytest.raises(DuplicateSupplierSiteError, match="only one primary"):
        complete.add_site(site(created, code="FILIAL_02", primary=True))
    with pytest.raises(DuplicateSupplierSiteError, match="already exists"):
        complete.add_site(site(created, code="FILIAL_01"))


def test_supplier_rejects_site_from_another_company_or_aggregate() -> None:
    created = supplier()
    foreign_site = SupplierSite.create(
        company_id=uuid4(),
        supplier_id=uuid4(),
        code="OTHER",
        name="Other site",
        address=SupplierAddress.create(
            line1="Rua Dois",
            city="Sao Paulo",
            state="SP",
            postal_code="01234567",
            country_code="BR",
        ),
    )
    with pytest.raises(InvalidSupplierDataError, match="belong"):
        created.add_site(foreign_site)


def test_supplier_rejects_non_site_and_corrupted_site_snapshots() -> None:
    created = supplier()
    with pytest.raises(InvalidSupplierDataError, match="validated SupplierSite"):
        created.add_site("bad")  # type: ignore[arg-type]

    valid_site = site(created, code="MATRIZ", primary=True)
    other = site(created, code="FILIAL", primary=True)
    with pytest.raises(InvalidSupplierDataError, match="belong"):
        replace(created, sites=(replace(valid_site, supplier_id=uuid4()),))
    with pytest.raises(DuplicateSupplierSiteError, match="unique"):
        replace(created, sites=(valid_site, replace(valid_site, is_primary=False)))
    with pytest.raises(DuplicateSupplierSiteError, match="only one primary"):
        replace(created, sites=(valid_site, other))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"id": "bad"}, "UUID"),
        ({"kind": "COMPANY"}, "kind"),
        ({"tax_identity": "bad"}, "tax_identity"),
        ({"status": "ACTIVE"}, "status"),
        ({"legal_name": " "}, "legal_name"),
        ({"trade_name": " "}, "trade_name"),
        ({"version": 0}, "version"),
        ({"sites": []}, "tuple"),
    ],
)
def test_supplier_snapshot_rejects_invalid_fields(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises((InvalidSupplierDataError, InvalidSupplierIdentityError), match=message):
        cast(Any, replace)(supplier(), **changes)


def test_transition_rejects_non_enum_target() -> None:
    with pytest.raises(InvalidSupplierTransitionError, match="target"):
        supplier().transition_status("ACTIVE")  # type: ignore[arg-type]
