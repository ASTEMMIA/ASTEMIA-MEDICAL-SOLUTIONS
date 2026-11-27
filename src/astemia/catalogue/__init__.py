"""ASTEMIA hospital service catalogue (AMS-002 Annex A15-A16).

D01-D36 reproduce Annex A15, which maps all 281 listing positions of directory A
of the Astemia Medical Solutions for Integrated Care Records Service services
A-Z to one primary group each. D37 onward are ASTEMIA extensions: services from
directory B, and services a comprehensive general hospital and the Nigeria
country profile need. Both directories are crosswalked listing by listing to a
service (data/crosswalk_directory_a.json, data/crosswalk_directory_b.json).
Every service is a
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


# Migration 0004 seeds the catalogue tables by calling template_rows() and
# directory_rows() with no arguments, using the column name and directory keys
# it created. Migration 0009 renamed them. A pushed migration is never
# rewritten, so with no arguments these functions keep producing the 0004 form.
Schema = dict[str, str]
SCHEMA_0004: Schema = {"positions": "kch_positions", "a": "kch", "b": "nhsggc"}
SCHEMA_CURRENT: Schema = {
    "positions": "directory_a_positions",
    "a": "directory_a",
    "b": "directory_b",
}


def template_rows(
    schema: Schema = SCHEMA_0004,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
                    "source",
                )
            }
            | {schema["positions"]: g["directory_a_positions"], "catalogue_version": cat["version"]}
        )
        for s in g["services"]:
            services.append({"group_code": g["code"], **s})
    return groups, services


DIRECTORIES = {
    "directory_a": "crosswalk_directory_a.json",
    "directory_b": "crosswalk_directory_b.json",
}


@lru_cache
def load_crosswalk(directory: str) -> dict[str, Any]:
    raw = (resources.files("astemia.catalogue") / "data" / DIRECTORIES[directory]).read_text()
    return dict(json.loads(raw))


def directory_rows(schema: Schema = SCHEMA_0004) -> list[dict[str, Any]]:
    rows = []
    for directory, key in (("directory_a", schema["a"]), ("directory_b", schema["b"])):
        cw = load_crosswalk(directory)
        for e in cw["entries"]:
            rows.append(
                {
                    "directory": key,
                    "position": e["position"],
                    "listing": e["listing"],
                    "url": e["url"],
                    "service_code": e["service_code"],
                    "snapshot": cw["snapshot"],
                }
            )
    return rows
