"""NFR-02: a chart read is fast, and its cost does not grow with the number of
results (hardening P0). The query count is exact; the time is a generous guard
for CI machines, measured against the 2-second target."""

import time
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, order, register, release


@contextmanager
def counted(factory: sessionmaker[Session]) -> Iterator[list[int]]:
    engine = factory.kw["bind"]
    seen = [0]

    def on_execute(*_: object) -> None:
        seen[0] += 1

    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)


def chart_queries(api: Api, factory: sessionmaker[Session], pid: str) -> int:
    with counted(factory) as seen:
        assert api.get("clinician", f"/v1/patients/{pid}/chart").status_code == 200
    return seen[0]


def test_chart_queries_do_not_grow_with_results(api: Api, factory: sessionmaker[Session]) -> None:
    pid = register(api)
    enc = admit(api, pid)
    for _ in range(2):
        release(api, order(api, pid, enc["id"])["id"])
    few = chart_queries(api, factory, pid)
    for _ in range(10):
        release(api, order(api, pid, enc["id"])["id"])
    many = chart_queries(api, factory, pid)
    assert many == few, f"{few} queries with 2 results, {many} with 12"


def test_a_busy_chart_reads_within_the_target(api: Api) -> None:
    pid = register(api)
    enc = admit(api, pid)
    for _ in range(40):
        release(api, order(api, pid, enc["id"])["id"])
    times = []
    for _ in range(20):
        start = time.perf_counter()
        r = api.get("clinician", f"/v1/patients/{pid}/chart")
        times.append(time.perf_counter() - start)
        assert r.status_code == 200 and len(r.json()["reports"]) == 40
    times.sort()
    p95 = times[18]
    assert p95 < 2.0, f"chart p95 {p95:.3f} s"
