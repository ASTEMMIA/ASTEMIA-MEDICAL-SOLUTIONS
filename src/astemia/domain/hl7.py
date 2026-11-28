"""HL7 v2 messages (CEDA section 6; ICRS X5). Pure parsing, no vendor library.

A message is segments of fields; fields hold repetitions of components and
subcomponents, with the separators the MSH segment declares. Fields are
numbered as in the standard: MSH-1 is the field separator itself, so MSH-3 is
the sending application. Escaped separators are restored in values.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from astemia.domain.common import InvariantViolation

_TS = re.compile(r"^(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?(?:\.\d+)?([+-]\d{4})?$")


class Hl7Error(InvariantViolation):
    """A message that cannot be read or does not say what it must."""

    code = "hl7_invalid"


@dataclass(frozen=True, slots=True)
class Separators:
    field: str = "|"
    component: str = "^"
    repetition: str = "~"
    escape: str = "\\"
    subcomponent: str = "&"


@dataclass(frozen=True, slots=True)
class Segment:
    name: str
    fields: tuple[str, ...]  # fields[n] is field n, as numbered in the standard
    seps: Separators

    def field(self, n: int) -> str:
        return self.fields[n] if n < len(self.fields) else ""

    def component(self, n: int, c: int = 1, rep: int = 0) -> str:
        """Field n, repetition rep, component c (1-based), unescaped."""
        reps = self.field(n).split(self.seps.repetition)
        if rep >= len(reps):
            return ""
        comps = reps[rep].split(self.seps.component)
        return unescape(comps[c - 1], self.seps) if c <= len(comps) else ""


@dataclass(frozen=True, slots=True)
class Message:
    segments: tuple[Segment, ...]

    @property
    def msh(self) -> Segment:
        return self.segments[0]

    def first(self, name: str) -> Segment:
        for s in self.segments:
            if s.name == name:
                return s
        raise Hl7Error(f"the message has no {name} segment")

    def all(self, name: str) -> list[Segment]:
        return [s for s in self.segments if s.name == name]

    @property
    def message_type(self) -> str:
        """For example ORU^R01."""
        return f"{self.msh.component(9, 1)}^{self.msh.component(9, 2)}"

    @property
    def control_id(self) -> str:
        return self.msh.field(10)

    @property
    def sender(self) -> str:
        """Sending application and facility (MSH-3, MSH-4)."""
        return f"{self.msh.component(3)}^{self.msh.component(4)}"


def unescape(value: str, seps: Separators) -> str:
    e = seps.escape
    for code, char in (
        ("F", seps.field),
        ("S", seps.component),
        ("T", seps.subcomponent),
        ("R", seps.repetition),
        ("E", seps.escape),
    ):
        value = value.replace(f"{e}{code}{e}", char)
    return value


def parse(raw: str) -> Message:
    lines = [ln for ln in re.split(r"\r\n|\r|\n", raw.strip()) if ln.strip()]
    if not lines or not lines[0].startswith("MSH") or len(lines[0]) < 8:
        raise Hl7Error("an HL7 message starts with an MSH segment")
    head = lines[0]
    field_sep, enc = head[3], head[4:8]
    seps = Separators(field_sep, enc[0], enc[1], enc[2], enc[3])
    segments = []
    for line in lines:
        parts = line.split(field_sep)
        name = parts[0]
        if not re.fullmatch(r"[A-Z][A-Z0-9]{2}", name):
            raise Hl7Error(f"{name!r} is not a segment name")
        # MSH-1 is the separator itself and MSH-2 the encoding characters.
        fields = (name, field_sep, *parts[1:]) if name == "MSH" else (name, *parts[1:])
        segments.append(Segment(name, tuple(fields), seps))
    msg = Message(tuple(segments))
    if not msg.control_id:
        raise Hl7Error("MSH-10, the message control id, is required")
    return msg


def timestamp(value: str) -> datetime:
    """HL7 TS/DTM: YYYYMMDD[HHMM[SS]][+/-ZZZZ]; without an offset, UTC."""
    m = _TS.match(value)
    if not m:
        raise Hl7Error(f"{value!r} is not an HL7 date and time")
    y, mo, d, h, mi, sec, off = m.groups()
    tz = UTC
    if off:
        sign = 1 if off[0] == "+" else -1
        tz = timezone(sign * timedelta(hours=int(off[1:3]), minutes=int(off[3:5])))
    return datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(sec or 0), tzinfo=tz)


def ack(msg: Message, code: str, text: str, control_id: str, now: datetime) -> str:
    """An ACK for the message: AA accepted, AE application error, AR rejected."""
    s = msg.msh.seps
    f = s.field
    stamp = now.astimezone(UTC).strftime("%Y%m%d%H%M%S")
    receiving = f"{msg.msh.field(5)}{f}{msg.msh.field(6)}"
    sending = f"{msg.msh.field(3)}{f}{msg.msh.field(4)}"
    trigger = msg.msh.component(9, 2)
    clean = text.replace(f, " ").replace(s.component, " ")[:80]
    return "\r".join(
        [
            f"MSH{f}{s.component}{s.repetition}{s.escape}{s.subcomponent}{f}{receiving}{f}{sending}"
            f"{f}{stamp}{f}{f}ACK{s.component}{trigger}{s.component}ACK{f}{control_id}{f}P{f}2.5",
            f"MSA{f}{code}{f}{msg.control_id}{f}{clean}",
        ]
    )
