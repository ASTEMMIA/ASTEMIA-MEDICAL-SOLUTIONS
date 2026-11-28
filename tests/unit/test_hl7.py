"""The HL7 v2 parser (CEDA section 6): pure, no database."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from astemia.domain import hl7

RAW = "\r".join(
    [
        "MSH|^~\\&|LAB|SITE|ASTEMIA|PILOT|20261128090000||ORU^R01|C1|P|2.5",
        "PID|1||111^^^NG-NIN~222^^^LOCAL||Doe^Jane",
        "OBX|1|ST|X^Note^LN||a\\S\\b\\F\\c\\T\\d\\R\\e\\E\\f",
    ]
)


def test_fields_components_repetitions_and_escapes() -> None:
    msg = hl7.parse(RAW)
    assert (msg.message_type, msg.control_id, msg.sender) == ("ORU^R01", "C1", "LAB^SITE")
    assert msg.msh.field(1) == "|" and msg.msh.field(2) == "^~\\&"
    pid = msg.first("PID")
    assert pid.component(3, 1, 1) == "222" and pid.component(3, 4, 1) == "LOCAL"
    assert pid.component(3, 1, 5) == ""  # no such repetition
    assert pid.component(5, 9) == ""  # no such component
    assert pid.field(40) == ""  # no such field
    assert msg.first("OBX").component(5) == "a^b|c&d~e\\f"
    assert len(msg.all("OBX")) == 1 and msg.all("NTE") == []
    with pytest.raises(hl7.Hl7Error, match="no PV1"):
        msg.first("PV1")


@pytest.mark.parametrize(
    "raw, why",
    [
        ("", "starts with an MSH"),
        ("PID|1", "starts with an MSH"),
        ("MSH|^~\\&|A|B|C|D|20261128||ADT^A01||P|2.5", "MSH-10"),
        ("MSH|^~\\&|A|B|C|D|20261128||ADT^A01|1|P|2.5\rpid|1", "not a segment name"),
    ],
)
def test_unreadable_messages_are_refused(raw: str, why: str) -> None:
    with pytest.raises(hl7.Hl7Error, match=why):
        hl7.parse(raw)


def test_timestamps() -> None:
    assert hl7.timestamp("20261128") == datetime(2026, 11, 28, tzinfo=UTC)
    assert hl7.timestamp("202611280930") == datetime(2026, 11, 28, 9, 30, tzinfo=UTC)
    lagos = hl7.timestamp("20261128093015.123+0100")
    assert lagos == datetime(2026, 11, 28, 9, 30, 15, tzinfo=timezone(timedelta(hours=1)))
    assert hl7.timestamp("20261128093015-0230").utcoffset() == -timedelta(hours=2, minutes=30)
    with pytest.raises(hl7.Hl7Error, match="not an HL7 date"):
        hl7.timestamp("28/11/2026")


def test_an_ack_answers_the_message() -> None:
    msg = hl7.parse(RAW)
    text = hl7.ack(msg, "AE", "no|such^patient", "A1", datetime(2026, 11, 28, 10, tzinfo=UTC))
    msh, msa = text.split("\r")
    assert msh.startswith("MSH|^~\\&|ASTEMIA|PILOT|LAB|SITE|20261128100000||ACK^R01^ACK|A1|P|2.5")
    assert msa == "MSA|AE|C1|no such patient"
