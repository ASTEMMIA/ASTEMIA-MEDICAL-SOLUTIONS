"""Every ICRS requirement and component is assigned exactly once, and every
requirement claimed as delivered names a test that exists."""

import json
import pathlib
import re

from astemia import icrs

ROOT = pathlib.Path(__file__).parents[2]
PLAN = icrs.plan()


def test_catalogue_matches_the_source_document() -> None:
    extracted = icrs.extract(ROOT / PLAN["source"])
    assert extracted == icrs.requirements()
    assert len(extracted) == 971
    assert len({r["id"] for r in extracted}) == 971


def test_every_requirement_has_exactly_one_owner() -> None:
    assignments = icrs.assign(icrs.requirements(), PLAN)
    assert [a.requirement_id for a in assignments if a.matches != 1] == []
    owners = {g["code"] for g in (*PLAN["modules"], *PLAN["areas"])}
    assert {a.owner for a in assignments} <= owners


def test_assignment_flags_gaps_and_overlaps() -> None:
    plan = {
        "modules": [{"code": "101", "ranges": [["1.1.1", "1.1.5"], ["1.1.4", "1.1.9"]]}],
        "areas": [],
        "overrides": {"1.1.7": "101"},
    }
    reqs = [{"id": i} for i in ("1.1.1", "1.1.4", "1.1.7", "2.1.1")]
    got = {a.requirement_id: (a.owner, a.matches) for a in icrs.assign(reqs, plan)}
    assert got == {
        "1.1.1": ("101", 1),
        "1.1.4": ("101", 2),
        "1.1.7": ("101", 1),
        "2.1.1": ("", 0),
    }


def test_modules_101_to_120_and_components() -> None:
    codes = [m["code"] for m in PLAN["modules"]]
    assert codes == [str(c) for c in range(101, 121)]
    assert {c["module"] for c in PLAN["components"]} <= set(codes)
    assert len({c["name"] for c in PLAN["components"]}) == len(PLAN["components"]) == 41


def test_delivered_requirements_name_an_existing_test() -> None:
    ids = {r["id"] for r in icrs.requirements()}
    for rid, evidence in PLAN["delivered"].items():
        assert rid in ids, rid
        path, _, name = evidence.partition("::")
        assert re.search(rf"^def {name}\(", (ROOT / path).read_text(), re.M), evidence


def test_summary_counts_add_up() -> None:
    rows = icrs.module_summary()
    assert sum(r["requirements"] for r in rows) == 971
    assert sum(r["delivered"] for r in rows) == len(PLAN["delivered"])
    patient_index = next(r for r in rows if r["code"] == "102")
    assert patient_index["delivered"] == len(PLAN["delivered"])


def test_generated_page_is_current() -> None:
    assert (ROOT / "docs" / "icrs-traceability.md").read_text() == icrs.render_markdown()


def test_page_says_when_nothing_is_delivered() -> None:
    page = icrs.render_markdown({**PLAN, "delivered": {}})
    assert page.endswith("## Delivered requirements\n\nNone yet.\n")


def test_naming_in_requirement_text() -> None:
    assert icrs.localise("not registered with a GP; GPs and GP\u2019s") == (
        "Not registered with a medical doctor; medical doctors and medical doctor\u2019s"
    )
    text = json.dumps(icrs.requirements())
    assert not re.search(r"(?<![A-Za-z])GPs?(?![A-Za-z])", text)
