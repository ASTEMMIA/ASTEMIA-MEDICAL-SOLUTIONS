"""The clinic list (UG01) and a clinician's own drafts (UG02): the two lists the
scheduling and notes screens work from."""

import uuid
from datetime import timedelta
from urllib.parse import quote

from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, register
from tests.e2e.test_clinical_notes import write
from tests.e2e.test_scheduling import TOMORROW, booked, make_slots


def q(dt: object) -> str:
    return quote(str(dt))


def test_the_clinic_list(api: Api) -> None:
    pid = register(api)
    first, _unbooked, third = make_slots(api, count=3)
    a = booked(api, first["id"], pid)
    b = booked(api, third["id"], pid)
    window = f"from={q(TOMORROW.isoformat())}&to={q((TOMORROW + timedelta(hours=2)).isoformat())}"

    r = api.get("scheduler", f"/v1/appointments?{window}")
    assert r.status_code == 200, r.text
    listed = r.json()
    assert [x["appointment"]["id"] for x in listed] == [a["id"], b["id"]]  # in time order
    assert listed[0]["patient"]["family_name"] == "Adeyemi"
    nin = next(i for i in listed[0]["patient"]["identifiers"] if i["issuer"] == "NG-NIN")
    assert nin["value"] != "12345678901"  # masked for a scheduler

    cancelled = api.post(
        "scheduler",
        f"/v1/appointments/{b['id']}/cancel",
        {"reason": "Patient asked to cancel"},
        **{"If-Match": '"1"'},
    )
    assert cancelled.status_code == 200, cancelled.text
    booked_only = api.get("scheduler", f"/v1/appointments?{window}&status=booked").json()
    assert [x["appointment"]["id"] for x in booked_only] == [a["id"]]
    doctor = api.tenant.practitioners["clinician"]
    by = f"{window}&practitioner_id={doctor}&facility_id={api.tenant.facility_id}"
    assert len(api.get("clinician", f"/v1/appointments?{by}&patient_id={pid}").json()) == 2
    assert api.get("scheduler", f"/v1/appointments?{window}&patient_id={uuid.uuid4()}").json() == []
    assert api.get("scheduler", "/v1/appointments").json() == []  # today: nothing booked
    assert api.get("scientist", "/v1/appointments").status_code == 403


def test_a_clinician_sees_only_their_own_drafts(api: Api) -> None:
    pid = register(api)
    enc = admit(api, pid)
    mine = write(api, enc["id"]).json()
    signed = write(api, enc["id"], title="Ward round").json()
    api.post("clinician", f"/v1/entries/{signed['id']}/sign", {}, **{"If-Match": '"1"'})
    r = api.get("clinician", f"/v1/patients/{pid}/drafts")
    assert r.status_code == 200, r.text
    assert [d["id"] for d in r.json()] == [mine["id"]]
    assert r.json()[0]["revisions"][0]["body"].startswith("Chest pain")
    assert api.get("clinician2", f"/v1/patients/{pid}/drafts").status_code == 404

    # A correction to a signed note is a draft too, until it is signed.
    amend = api.post(
        "clinician",
        f"/v1/entries/{signed['id']}/amendments",
        {"body": "Ward round: troponin negative", "reason": "Result came back"},
        **{"If-Match": '"2"'},
    )
    assert amend.status_code == 200, amend.text
    ids = [d["id"] for d in api.get("clinician", f"/v1/patients/{pid}/drafts").json()]
    assert sorted(ids) == sorted([mine["id"], signed["id"]])
