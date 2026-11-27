"""The hospital service catalogue: Annex A15 coverage plus ASTEMIA extensions."""

import re

import pytest

from astemia.catalogue import load_catalogue, load_crosswalk, template_rows
from astemia.domain import catalogue as cat
from astemia.domain.common import InvalidTransition, InvariantViolation

CATALOGUE = load_catalogue()
GROUPS = CATALOGUE["groups"]


def test_every_kch_listing_position_maps_to_exactly_one_group() -> None:
    """Annex A16 release evidence: every source position maps to one primary group."""
    positions = [p for g in GROUPS for p in g["kch_positions"]]
    assert sorted(positions) == list(range(1, 282))


def test_spec_groups_and_extensions() -> None:
    spec = [g["code"] for g in GROUPS if g["source"] == "ams-002-annex-a15"]
    ext = [g["code"] for g in GROUPS if g["source"] == "astemia-extension"]
    assert spec == [f"D{n:02d}" for n in range(1, 37)]
    assert ext == [f"D{n:02d}" for n in range(37, 51)]


@pytest.mark.parametrize("group", GROUPS, ids=lambda g: g["code"])
def test_each_group_is_specified_like_the_annex(group: dict) -> None:  # type: ignore[type-arg]
    assert group["services"], "a group needs at least one service"
    assert all(re.fullmatch(r"(WF|HS|UG|SA)\d\d", r) for r in group["requirement_refs"])
    assert group["requirement_refs"] and group["canonical_records"]
    for field in ("workflow", "security_checks", "acceptance", "division"):
        assert len(group[field]) > 10
    for s in group["services"]:
        assert re.fullmatch(rf"{group['code']}-\d\d", s["code"])
        assert s["age_policy"] in {"adult", "paediatric", "all"}
        assert s["care_settings"] and set(s["care_settings"]) <= {c.value for c in cat.CareSetting}


def test_service_codes_and_names_are_unique() -> None:
    _, services = template_rows()
    assert len({s["code"] for s in services}) == len(services)
    names = [s["name"].lower() for s in services]
    assert len(set(names)) == len(names)


@pytest.mark.parametrize(
    "service",
    [
        "Ear nose and throat surgery",
        "Burns unit",
        "Adult inpatient psychiatry",
        "Malaria diagnosis and treatment",
        "Tuberculosis DOTS clinic",
        "Lassa fever and viral haemorrhagic fever isolation",
        "Outpatient therapeutic feeding (CMAM)",
        "Clinical genetics clinic",
        "External beam radiotherapy",
        "Emergency call and dispatch",
        "Mortuary",
        "Needlestick and exposure management",
        "Blood collection",
        "Prosthetics",
        "Virtual ward",
    ],
)
def test_extension_services_are_present(service: str) -> None:
    _, services = template_rows()
    assert service in {s["name"] for s in services}


def test_activation_rules() -> None:
    cat.check_activation(True, True, "CAB-2026-114")
    with pytest.raises(InvariantViolation, match="owner, approval"):
        cat.check_activation(False, True, None)
    with pytest.raises(InvalidTransition):
        cat.move(cat.ServiceStatus.RETIRED, cat.ServiceStatus.ACTIVE)


SERVICE_GROUP = {s["code"]: g["code"] for g in GROUPS for s in g["services"]}


@pytest.mark.parametrize(("directory", "listings"), [("kch", 281), ("nhsggc", 172)])
def test_every_directory_listing_maps_to_exactly_one_service(directory: str, listings: int) -> None:
    entries = load_crosswalk(directory)["entries"]
    assert [e["position"] for e in entries] == list(range(1, listings + 1))
    unknown = [e for e in entries if e["service_code"] not in SERVICE_GROUP]
    assert unknown == []


def test_kch_listings_sit_in_the_annex_a15_group() -> None:
    """Service-level KCH mapping agrees with the group-level mapping in Annex A15."""
    group_of_position = {p: g["code"] for g in GROUPS for p in g["kch_positions"]}
    for e in load_crosswalk("kch")["entries"]:
        assert SERVICE_GROUP[e["service_code"]] == group_of_position[e["position"]], e


@pytest.mark.parametrize(
    ("directory", "listing", "service"),
    [
        ("kch", "The Havens", "Sexual assault referral centre"),
        ("kch", "Breast cancer", "Breast care and screening"),
        ("kch", "Mastectomy", "Breast surgery (lumpectomy and mastectomy)"),
        ("kch", "Frank Cooksey Rehabilitation Unit", "Chronic pain rehabilitation programme"),
        ("nhsggc", "WestMARC", "Prosthetics"),
        ("nhsggc", "Esteem Glasgow", "Early intervention in psychosis"),
        ("nhsggc", "Cash withdrawal (ATM)", "Visitor amenities"),
        ("nhsggc", "Milk Bank Scotland", "Donor milk bank"),
    ],
)
def test_crosswalk_examples(directory: str, listing: str, service: str) -> None:
    names = {s["code"]: s["name"] for g in GROUPS for s in g["services"]}
    hits = [
        names[e["service_code"]]
        for e in load_crosswalk(directory)["entries"]
        if e["listing"] == listing
    ]
    assert hits and set(hits) == {service}


def test_no_gp_in_catalogue_service_names() -> None:
    _, services = template_rows()
    assert not [s["name"] for s in services if "GP" in s["name"].split()]
    assert "Medical doctor out of hours" in {s["name"] for s in services}


@pytest.mark.parametrize("directory", ["kch", "nhsggc"])
def test_no_gp_or_nhs_in_directory_listing_names(directory: str) -> None:
    """ASTEMIA naming applies to the directory crosswalks too, without exceptions."""
    import re

    banned = re.compile(r"(?<![A-Za-z])(GP|NHS)(?![a-z])")  # NHSGGC included
    listings = [e["listing"] for e in load_crosswalk(directory)["entries"]]
    assert [x for x in listings if banned.search(x)] == []
