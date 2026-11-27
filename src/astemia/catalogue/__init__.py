"""ASTEMIA hospital service catalogue (AMS-002 Annex A15-A16).

D01-D36 reproduce Annex A15, which maps all 281 listing positions of the King's
College Hospital services A-Z directory to one primary group each. D37 onward
are ASTEMIA extensions: services from the Astemia Medical Solutions Greater Glasgow and Clyde A-Z,
and services a comprehensive general hospital and the Nigeria country profile
need. Both directories are crosswalked listing by listing to a service
(data/crosswalk_kch.json, data/crosswalk_nhsggc.json). Every service is a
template: tenants instantiate it as a draft and activate it only after
CAT-01/CAT-05 approval.
"""

import json
from functools import lru_cache
from importlib import resources
from typing import Any


@lru_cache
def load_catalogue() -> dict[str, Any]:
    data = (resources.files("astemia.catalogue") / "data" / "service_catalogue.json").read_text()
    return dict(json.loads(data))


def template_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cat = load_catalogue()
    groups, services = [], []
    for g in cat["groups"]:
        groups.append(
            {
                k: g[k]
                for k in (
                    "code",
                    "division",
                    "name",
                    "workflow",
                    "requirement_refs",
                    "canonical_records",
                    "security_checks",
                    "acceptance",
                    "kch_positions",
                    "source",
                )
            }
            | {"catalogue_version": cat["version"]}
        )
        for s in g["services"]:
            services.append({"group_code": g["code"], **s})
    return groups, services


DIRECTORIES = {"kch": "crosswalk_kch.json", "nhsggc": "crosswalk_nhsggc.json"}


@lru_cache
def load_crosswalk(directory: str) -> dict[str, Any]:
    raw = (resources.files("astemia.catalogue") / "data" / DIRECTORIES[directory]).read_text()
    return dict(json.loads(raw))


def directory_rows() -> list[dict[str, Any]]:
    rows = []
    for directory in DIRECTORIES:
        cw = load_crosswalk(directory)
        for e in cw["entries"]:
            rows.append(
                {
                    "directory": directory,
                    "position": e["position"],
                    "listing": e["listing"],
                    "url": e["url"],
                    "service_code": e["service_code"],
                    "snapshot": cw["snapshot"],
                }
            )
    return rows
