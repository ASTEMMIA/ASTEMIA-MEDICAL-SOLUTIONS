"""Migration staging and national-extract tables generated from the ERDs.

* Entities with up to WIDE_LIMIT fields become verbatim staging tables
  (stg_<entity>) holding raw source values as TEXT, plus the MIG-01 lineage
  columns. The same entity drawn in several ERDs is one table with the union
  of its fields.
* Wide CDS transactions and national extracts (A&E, Admitted Patient Care,
  Outpatients, MHMDS, Ward Attenders, Elective Admissions) exceed InnoDB's
  8126-byte row limit even as TEXT, so their fields are kept in a dictionary
  (national_extract_field) and their rows as JSON keyed by field key.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import SchemaItem

from astemia.adapters.db.legacy_names import column_name, entity_key, localise, unique_names
from astemia.adapters.db.types import BinaryUUID, UTCDateTime

ERD_FILES = (
    "ams_master_schema_wip_erp.json",
    "zetter_ams_erd.json",
    "ae_ams_erd.json",
    "ahis_master_erd.json",
    "pdi_ams_schema_erp.json",
)
WIDE_LIMIT = 60
LINEAGE_COLUMNS = {
    "tenant_id",
    "id",
    "batch_id",
    "source_system",
    "source_entity",
    "source_row_key",
    "row_digest",
    "mapping_version",
    "reconciliation_status",
    "exception_owner",
    "loaded_at",
}
TABLE_OPTS: dict[str, Any] = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


@dataclass(frozen=True)
class ErdEntity:
    key: str
    names: tuple[str, ...]
    sources: tuple[str, ...]
    fields: tuple[str, ...]

    @property
    def wide(self) -> bool:
        return len(self.fields) > WIDE_LIMIT


def load_erds() -> list[ErdEntity]:
    merged: dict[str, dict[str, Any]] = {}
    pkg = resources.files("astemia.adapters.db") / "erd"
    for filename in ERD_FILES:
        data = json.loads((pkg / filename).read_text())
        for e in data["entities"]:
            key = entity_key(e["name"])
            slot = merged.setdefault(key, {"names": [], "sources": [], "fields": [], "wide": False})
            if e["name"] not in slot["names"]:
                slot["names"].append(e["name"])
            if filename not in slot["sources"]:
                slot["sources"].append(filename)
            if len(e["fields"]) > WIDE_LIMIT:
                # Wide extracts keep their exact field order and repeats.
                if len(e["fields"]) > len(slot["fields"]):
                    slot["fields"] = list(e["fields"])
                slot["wide"] = True
            elif not slot["wide"]:
                # Union by column key: 'NHS Number', 'nhs_number' and
                # 'medicare_number' variants of one field become one column.
                keys = {column_name(f) for f in slot["fields"]}
                for f in e["fields"]:
                    if column_name(f) not in keys:
                        slot["fields"].append(f)
                        keys.add(column_name(f))
    return [
        ErdEntity(k, tuple(v["names"]), tuple(v["sources"]), tuple(v["fields"]))
        for k, v in merged.items()
    ]


def staging_table_name(entity: ErdEntity) -> str:
    name = entity.key
    if not name.startswith("stg_"):
        name = f"stg_{name}"
    return name[:60]


def build_staging_tables(metadata: MetaData) -> dict[str, Table]:
    tables: dict[str, Table] = {}
    for entity in load_erds():
        if entity.wide:
            continue
        name = staging_table_name(entity)
        cols: list[Column[Any]] = [
            Column("tenant_id", BinaryUUID, primary_key=True),
            Column("id", BinaryUUID, primary_key=True),
            Column("batch_id", BinaryUUID, nullable=False),
            Column("source_system", String(32), nullable=False),
            Column("source_entity", String(64), nullable=False),
            Column("source_row_key", String(128), nullable=False),
            Column("row_digest", String(64), nullable=False),
            Column("mapping_version", String(32), nullable=False),
            Column("reconciliation_status", String(16), nullable=False, server_default="staged"),
            Column("exception_owner", String(64)),
            Column("loaded_at", UTCDateTime, nullable=False),
        ]
        for _label, key, _n in unique_names(list(entity.fields)):
            if key in LINEAGE_COLUMNS:
                key = f"src_{key}"
            cols.append(Column(key, Text))
        items: list[SchemaItem] = [
            *cols,
            ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            # Re-running a batch adds zero duplicates (MIG-02).
            UniqueConstraint(
                "tenant_id", "source_system", "source_entity", "source_row_key", "row_digest"
            ),
            Index(None, "tenant_id", "batch_id"),
        ]
        tables[name] = Table(
            name,
            metadata,
            *items,
            comment=(
                f"Verbatim staging for ERD entity {', '.join(entity.names)} "
                f"({', '.join(entity.sources)})"
            ),
            **TABLE_OPTS,
        )
    return tables


def extract_dictionary_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Seed rows for national_extract and national_extract_field."""
    extracts, fields = [], []
    for entity in load_erds():
        if not entity.wide:
            continue
        code = entity.key[:48]
        extracts.append(
            {
                "code": code,
                "name": localise(entity.names[0]),
                "source_entities": " | ".join(entity.names),
                "source_erd": " | ".join(entity.sources),
                "field_count": len(entity.fields),
            }
        )
        for pos, (label, key, n) in enumerate(unique_names(list(entity.fields)), start=1):
            fields.append(
                {
                    "extract_code": code,
                    "position": pos,
                    "field_key": key,
                    "label": localise(label),
                    "source_label": label,
                    "occurrence": n,
                }
            )
    return extracts, fields


# --- Dictionary-backed tables (declared on the shared Base in models.py) -------


def declare_extract_models(base: Any) -> dict[str, Any]:
    class NationalExtract(base):  # type: ignore[misc]
        """A national dataset or CDS transaction type from the ERDs."""

        __tablename__ = "national_extract"
        __table_args__ = (TABLE_OPTS,)

        code: Mapped[str] = mapped_column(String(48), primary_key=True)
        name: Mapped[str] = mapped_column(String(200), nullable=False)
        source_entities: Mapped[str] = mapped_column(String(500), nullable=False)
        source_erd: Mapped[str] = mapped_column(String(200), nullable=False)
        field_count: Mapped[int] = mapped_column(Integer, nullable=False)

    class NationalExtractField(base):  # type: ignore[misc]
        __tablename__ = "national_extract_field"
        __table_args__ = (
            ForeignKeyConstraint(["extract_code"], ["national_extract.code"]),
            UniqueConstraint("extract_code", "field_key"),
            TABLE_OPTS,
        )

        extract_code: Mapped[str] = mapped_column(String(48), primary_key=True)
        position: Mapped[int] = mapped_column(Integer, primary_key=True)
        field_key: Mapped[str] = mapped_column(String(60), nullable=False)
        label: Mapped[str] = mapped_column(String(255), nullable=False)
        source_label: Mapped[str] = mapped_column(String(255), nullable=False)
        occurrence: Mapped[int] = mapped_column(Integer, nullable=False)
        canonical_mapping: Mapped[str | None] = mapped_column(String(255))

    class StgExtractRecord(base):  # type: ignore[misc]
        """Inbound wide legacy rows (MIG-01), payload keyed by field_key."""

        __tablename__ = "stg_extract_record"
        __table_args__ = (
            ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            ForeignKeyConstraint(["extract_code"], ["national_extract.code"]),
            UniqueConstraint(
                "tenant_id", "extract_code", "source_system", "source_row_key", "row_digest"
            ),
            Index(None, "tenant_id", "batch_id"),
            TABLE_OPTS,
        )

        tenant_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
        id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
        extract_code: Mapped[str] = mapped_column(String(48), nullable=False)
        batch_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, nullable=False)
        source_system: Mapped[str] = mapped_column(String(32), nullable=False)
        source_row_key: Mapped[str] = mapped_column(String(128), nullable=False)
        row_digest: Mapped[str] = mapped_column(String(64), nullable=False)
        mapping_version: Mapped[str] = mapped_column(String(32), nullable=False)
        reconciliation_status: Mapped[str] = mapped_column(
            String(16), nullable=False, default="staged"
        )
        exception_owner: Mapped[str | None] = mapped_column(String(64))
        loaded_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
        payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    class NationalExtractRecord(base):  # type: ignore[misc]
        """Outbound national return rows generated from canonical records."""

        __tablename__ = "national_extract_record"
        __table_args__ = (
            ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            ForeignKeyConstraint(["extract_code"], ["national_extract.code"]),
            ForeignKeyConstraint(
                ["tenant_id", "encounter_id"], ["encounter.tenant_id", "encounter.id"]
            ),
            Index(None, "tenant_id", "extract_code", "period_start"),
            TABLE_OPTS,
        )

        tenant_id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
        id: Mapped[uuid.UUID] = mapped_column(BinaryUUID, primary_key=True)
        extract_code: Mapped[str] = mapped_column(String(48), nullable=False)
        encounter_id: Mapped[uuid.UUID | None] = mapped_column(BinaryUUID)
        period_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
        period_end: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
        status: Mapped[str] = mapped_column(String(16), nullable=False)
        generator_version: Mapped[str] = mapped_column(String(32), nullable=False)
        generated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
        payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    return {
        "NationalExtract": NationalExtract,
        "NationalExtractField": NationalExtractField,
        "StgExtractRecord": StgExtractRecord,
        "NationalExtractRecord": NationalExtractRecord,
    }
