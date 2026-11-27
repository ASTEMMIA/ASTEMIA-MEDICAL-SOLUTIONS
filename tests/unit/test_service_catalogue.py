"""The hospital service catalogue: Annex A15 coverage plus ASTEMIA extensions."""

import pathlib
import re

import pytest

from astemia.catalogue import load_catalogue, load_crosswalk, template_rows
from astemia.domain import catalogue as cat
from astemia.domain.common import InvalidTransition, InvariantViolation

CATALOGUE = load_catalogue()
GROUPS = CATALOGUE["groups"]


def test_every_directory_a_position_maps_to_exactly_one_group() -> None:
    """Annex A16 release evidence: every source position maps to one primary group."""
    positions = [p for g in GROUPS for p in g["directory_a_positions"]]
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


@pytest.mark.parametrize(
    ("directory", "positions", "listings"), [("directory_a", 281, 281), ("directory_b", 172, 170)]
)
def test_every_directory_listing_maps_to_exactly_one_service(
    directory: str, positions: int, listings: int
) -> None:
    """Positions keep the publisher's order; removed listings leave a recorded gap."""
    cw = load_crosswalk(directory)
    entries = cw["entries"]
    removed = set(cw.get("removed_positions", []))
    assert [e["position"] for e in entries] == [
        p for p in range(1, positions + 1) if p not in removed
    ]
    assert len(entries) == listings
    unknown = [e for e in entries if e["service_code"] not in SERVICE_GROUP]
    assert unknown == []


def test_directory_a_listings_sit_in_the_annex_a15_group() -> None:
    """Service-level directory A mapping agrees with the group-level mapping in Annex A15."""
    group_of_position = {p: g["code"] for g in GROUPS for p in g["directory_a_positions"]}
    for e in load_crosswalk("directory_a")["entries"]:
        assert SERVICE_GROUP[e["service_code"]] == group_of_position[e["position"]], e


@pytest.mark.parametrize(
    ("directory", "listing", "service"),
    [
        ("directory_a", "The Havens", "Sexual assault referral centre"),
        ("directory_a", "Breast cancer", "Breast care and screening"),
        ("directory_a", "Mastectomy", "Breast surgery (lumpectomy and mastectomy)"),
        (
            "directory_a",
            "Frank Cooksey Rehabilitation Unit",
            "Chronic pain rehabilitation programme",
        ),
        ("directory_b", "WestMARC", "Prosthetics"),
        ("directory_b", "Cash withdrawal (ATM)", "Visitor amenities"),
        ("directory_b", "Milk Bank Scotland", "Donor milk bank"),
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


@pytest.mark.parametrize("directory", ["directory_a", "directory_b"])
def test_no_gp_or_nhs_in_directory_listing_names(directory: str) -> None:
    """ASTEMIA naming applies to the directory crosswalks too, without exceptions."""
    banned = re.compile(r"(?<![A-Za-z])(GP|NHS|GGC)(?![a-z])")  # NHSGGC included
    listings = [e["listing"] for e in load_crosswalk(directory)["entries"]]
    assert [x for x in listings if banned.search(x)] == []


def test_directories_carry_no_organisation_names() -> None:
    """Both directories are named after the Astemia Medical Solutions for
    Integrated Care Records Service. Web addresses are the publishers' own and
    stay as they are."""
    root = pathlib.Path(__file__).parents[2]
    files = [*root.glob("src/astemia/catalogue/data/*.json"), root / "docs/service-catalogue.md"]
    banned = re.compile(r"King.s College|Greater Glasgow|Clyde|\bKCH\b|NHSGGC|\bkch\b|nhsggc", re.I)
    url = re.compile(r"https?://\S+")
    hits = [
        f"{f.name}: {line.strip()}"
        for f in files
        for line in f.read_text().splitlines()
        if banned.search(url.sub("", line))
    ]
    assert hits == []
    for directory in ("directory_a", "directory_b"):
        assert (
            "Astemia Medical Solutions for Integrated Care Records Service"
            in (load_crosswalk(directory)["title"])
        )


def test_removed_directory_b_listings_stay_removed() -> None:
    listings = {e["listing"] for e in load_crosswalk("directory_b")["entries"]}
    assert not listings & {"Esteem Glasgow", "Glasgow City Youth Health Service"}
    assert load_crosswalk("directory_b")["removed_positions"] == [41, 52]
