import io
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import select

from duecare import ai, timetable_api, timetable_draft, timetable_extract, timetable_scheduler
from duecare.db import transaction
from duecare.models import Profile, Slot

from . import scheduler_png
from .conftest import account
from .timetable_pdf import DAYS, TIMES, build, sample

PROFILE = {
    "branchCode": "COMPS",
    "classYear": "SY",
    "currentSemester": 3,
    "division": "B",
    "generalBatch": "2",
    "rollNumber": "001A",
}


@pytest.fixture(autouse=True)
def no_ai(monkeypatch):
    calls = []

    def down(*args, **kwargs):
        calls.append(args)
        raise ai.AIUnavailable("AI providers are temporarily unavailable")

    monkeypatch.setattr(ai, "structured", down)
    return calls


def setup(client, headers, subjects=()):
    client.get("/api/v1/me", headers=headers)
    client.patch("/api/v1/me", headers=headers, json={"revision": 1, **PROFILE})
    out = {}
    for name, kind, *code in subjects:
        body = {"name": name, "kind": kind, **({"code": code[0]} if code else {})}
        out[(name, kind)] = client.post("/api/v1/subjects", headers=headers.fresh(), json=body).json()
    return out


def upload(client, headers, files):
    return client.post(
        "/api/v1/timetable-imports/extract",
        headers=headers.fresh(),
        files=[("files", (name, data, kind)) for name, data, kind in files],
    )


def interpret(client, headers, reading):
    pages = [{"id": p["id"], "layout": p["layout"], "header": p["header"]} for p in reading["pages"]]
    keys = (
        "id",
        "page",
        "weekday",
        "start",
        "end",
        "lines",
        "bbox",
        "spansDays",
        "narrow",
        "clippedTop",
        "clippedBottom",
    )
    cells = [{k: c[k] for k in keys if k in c} for p in reading["pages"] for c in p["cells"]]
    return client.post(
        "/api/v1/timetable-imports/interpret", headers=headers.fresh(), json={"pages": pages, "cells": cells}
    )


def test_pdf_grid_reads_merged_labs_batches_and_afternoon_rows(client, headers):
    setup(client, headers)
    r = upload(client, headers, [("tt.pdf", sample(), "application/pdf")])
    assert r.status_code == 200, r.text
    reading = r.json()
    assert reading["method"] == "pdf_text"
    page = reading["pages"][0]
    assert page["header"]["classLabel"] == "SY B. Tech COMP B"
    assert page["preview"].startswith("data:image/jpeg;base64,")
    cells = {" ".join(c["lines"]): c for c in page["cells"]}
    lab = cells["B2 DBMS B116A JMR"]
    assert (lab["weekday"], lab["start"], lab["end"], lab["narrow"]) == (1, "14:00", "16:00", True)
    assert (cells["COA B205 KMK"]["start"], cells["COA B205 KMK"]["end"]) == ("12:00", "13:00")
    assert not cells["DS B204 JMR"]["narrow"]
    assert all(0 <= v <= 1 for v in lab["bbox"])


def test_time_rows_follow_the_grid_order():
    rows, issues = timetable_extract.time_rows(["11:00-12:00", "12:00-1:00", "1:00-2:00", "5:00-6:00"])
    assert rows == [(660, 720), (720, 780), (780, 840), (1020, 1080)]
    assert issues == []
    rows, issues = timetable_extract.time_rows(["2:00-3:00"])
    assert rows == [(840, 900)] and issues


def test_cell_text_parsing():
    p = timetable_draft.parse_cell("B2 DBMS B116A JMR")
    assert (p["batches"], p["label"], p["location"], p["instructor"], p["component"]) == (
        ["B2"], "DBMS", "B116A", "JMR", None,
    )  # fmt: skip
    p = timetable_draft.parse_cell("E- Dev_10 B107A CO2")
    assert (p["label"], p["baseLabel"], p["group"], p["instructor"]) == ("E-Dev_10", "E-Dev", 10, "CO2")
    p = timetable_draft.parse_cell("ASCT B102 SAM / JRS")
    assert (p["component"], p["instructor"]) == ("theory", "SAM, JRS")


@pytest.mark.parametrize("name", ["Maths", "Mathematics", "Engineering Mathematics", "AM-II", "EM3", "ITVC"])
def test_maths_batch_defaults_to_tutorial(name):
    assert timetable_draft.parse_cell(f"B2 {name} B102 SAM")["component"] == "tutorial"
    assert timetable_draft.parse_cell(f"{name} B102 SAM")["component"] == "theory"


def test_bulk_subjects_reuse_existing_and_keep_components_separate(client, headers):
    setup(client, headers, [("Maths", "theory")])
    body = {
        "subjects": [
            {"name": "maths", "kind": "theory"},
            {"name": "Maths", "kind": "tutorial"},
            {"name": "MATHS", "kind": "tutorial"},
            {"name": "DS", "kind": "lab"},
        ]
    }
    response = client.post("/api/v1/subjects/bulk", headers=headers.fresh(), json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["created"] == 2
    assert result["items"][1]["id"] == result["items"][2]["id"]
    assert result["items"][0]["id"] != result["items"][1]["id"]
    retry = client.post("/api/v1/subjects/bulk", headers=headers.fresh(), json=body).json()
    assert retry["created"] == 0
    assert [s["id"] for s in retry["items"]] == [s["id"] for s in result["items"]]
    # Another student's equally named subject must never be returned.
    other = account("bulk-other@somaiya.edu")
    separate = client.post("/api/v1/subjects/bulk", headers=other.headers, json=body).json()
    assert separate["created"] == 3
    assert not {s["id"] for s in separate["items"]} & {s["id"] for s in result["items"]}


def test_bulk_subject_validation_leaves_no_partial_creates(client, headers):
    response = client.post(
        "/api/v1/subjects/bulk",
        headers=headers.fresh(),
        json={
            "subjects": [
                {"name": "DS", "kind": "theory"},
                {"name": " ", "kind": "lab"},
            ]
        },
    )
    assert response.status_code == 422
    assert client.get("/api/v1/subjects", headers=headers).json()["items"] == []
    assert timetable_draft.parse_cell("H-CSFTUT_1 B217A CO2")["component"] == "tutorial"
    assert timetable_draft.parse_cell("DLD-LAB B414 NDM")["component"] == "lab"
    assert timetable_draft.parse_cell("MDM -- --")["label"] == "MDM"
    assert timetable_draft.parse_cell("B1 ITVC CCF_A.1 YMT")["location"] == "CCF_A.1"
    assert timetable_draft.batch_key("2", "B") == "B2"
    assert timetable_draft.batch_key("Batch b-3") == "B3"


def test_interpret_applies_batch_links_subjects_and_needs_group_choice(client, headers, no_ai):
    subjects = setup(
        client,
        headers,
        [
            ("Data Structures", "theory", "DS"),
            ("Data Structures Lab", "lab"),
            ("DBMS", "theory"),
            ("DBMS", "lab"),
            ("COA", "theory"),
        ],
    )
    reading = upload(client, headers, [("tt.pdf", sample(), "application/pdf")]).json()
    r = interpret(client, headers, reading)
    assert r.status_code == 200, r.text
    draft = r.json()
    assert draft["batch"] == "B2" and draft["profileRevision"] == 2
    assert draft["ai"] == {"used": False, "unavailable": True} and no_ai
    rows = {r["sourceText"]: r for r in draft["rows"]}
    assert {i["text"] for i in draft["ignored"]} == {"LUNCH BREAK"}
    mine = rows["B2 / DBMS / B116A JMR"]
    assert (
        mine["include"] and mine["subjectId"] == subjects[("DBMS", "lab")]["id"] and mine["link"] == "exact"
    )
    assert (mine["startTime"], mine["endTime"], mine["location"]) == ("14:00", "16:00", "B116A")
    other = rows["B1 / WDL / B115B SIP"]
    assert not other["include"] and other["exclusionReason"] == "Batch B1"
    assert rows["DBMS B202 ASH"]["subjectId"] == subjects[("DBMS", "theory")]["id"]
    assert rows["DS B204 JMR"]["subjectId"] == subjects[("Data Structures", "theory")]["id"]
    # The other division batch's DS lab would only be a suggestion; never an exact link.
    assert rows["B3 / DS B109 / PVK"]["suggestedSubjectId"] == subjects[("Data Structures Lab", "lab")]["id"]
    assert rows["B3 / DS B109 / PVK"]["subjectId"] is None
    groups = [r for r in draft["rows"] if r["choiceKey"] == "group:da"]
    assert [g["choiceLabel"] for g in groups] == ["Group 1", "Group 2"]
    assert rows["COA B205 KMK"]["subjectId"] == subjects[("COA", "theory")]["id"]


def test_ai_suggestions_are_limited_to_supplied_compatible_subjects(client, headers, monkeypatch):
    subjects = setup(client, headers, [("Computer Architecture", "theory"), ("Graphics", "lab")])
    target = subjects[("Computer Architecture", "theory")]["id"]

    def fake(system, user, schema, deadline=None, **kwargs):
        assert "COA" in user and deadline is not None
        import json

        labels = json.loads(user)["labels"]
        out = []
        for item in labels:
            pick = {"COA": target, "DS": str(uuid4()), "DBMS": subjects[("Graphics", "lab")]["id"]}
            out.append({"key": item["key"], "subjectId": pick.get(item["label"])})
        return schema.model_validate({"labels": out}), {"provider": "fake", "model": "fake-1"}

    monkeypatch.setattr(ai, "structured", fake)
    reading = upload(client, headers, [("tt.pdf", sample(), "application/pdf")]).json()
    draft = interpret(client, headers, reading).json()
    rows = {r["sourceText"]: r for r in draft["rows"]}
    assert rows["COA B205 KMK"]["suggestedSubjectId"] == target
    assert rows["COA B205 KMK"]["subjectId"] is None  # A suggestion still needs the student.
    assert rows["DS B204 JMR"]["suggestedSubjectId"] is None  # Invented ID discarded.
    assert rows["DBMS B202 ASH"]["suggestedSubjectId"] is None  # Lab subject cannot take theory.
    assert draft["ai"]["used"] is True


def png_bytes(image):
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def test_upload_validation(client, headers):
    setup(client, headers)
    png = png_bytes(Image.new("RGB", (40, 30), "white"))
    assert upload(client, headers, [("a.txt", b"hello", "text/plain")]).status_code == 415
    mixed = [("a.pdf", sample(), "application/pdf"), ("b.png", png, "image/png")]
    assert upload(client, headers, mixed).json()["code"] == "MIXED_UPLOAD"
    five = [(f"{n}.png", png, "image/png") for n in range(5)]
    assert upload(client, headers, five).json()["code"] == "TOO_MANY_FILES"
    assert upload(client, headers, [("bad.pdf", b"%PDF-1.4 broken", "application/pdf")]).status_code == 422
    blank = build("Class: SY", ["Notes"], ["x"], [])
    assert upload(client, headers, [("blank.pdf", blank, "application/pdf")]).status_code == 422


def test_scanned_pdf_is_rejected_with_guidance(client, headers):
    setup(client, headers)
    scan = io.BytesIO()
    Image.new("RGB", (800, 560), "white").save(scan, "PDF")
    r = upload(client, headers, [("scan.pdf", scan.getvalue(), "application/pdf")])
    assert r.status_code == 422 and r.json()["code"] == "SCANNED_PDF"
    assert "scheduler" in r.json()["message"]


needs_ocr = pytest.mark.skipif(not timetable_scheduler.ocr_ready(), reason="Tesseract OCR is not installed")
PINK, GREEN, PURPLE, BLUE = (232, 84, 115), (94, 132, 9), (129, 0, 129), (4, 2, 254)
WEEK = [
    (2, 540, 600, PINK, ["16U2508", "Introduction to", "Virtual Reality and"]),
    (1, 660, 720, GREEN, ["16U2602 Data", "Structures"]),
    (2, 660, 780, PURPLE, ["16U2603 Data", "Structures", "Laboratory"]),
    (4, 720, 780, BLUE, ["16U2291 Database", "Management", "Systems."]),
]


@needs_ocr
def test_scheduler_screenshots_are_read_without_ai(client, headers, monkeypatch):
    setup(client, headers)

    def no_ai(*args, **kwargs):
        raise AssertionError("Reading screenshots must not call an AI provider")

    monkeypatch.setattr(ai, "structured", no_ai)
    # Two scrolled views overlap; the lab is cut off at the bottom of the first.
    first = png_bytes(scheduler_png.screenshot(420, 715, WEEK))
    second = png_bytes(scheduler_png.screenshot(690, 985, WEEK))
    r = upload(client, headers, [("b.png", second, "image/png"), ("a.png", first, "image/png")])
    assert r.status_code == 200, r.text
    reading = r.json()
    assert reading["method"] == "scheduler_ocr"
    assert [p["visible"] for p in reading["pages"]] == ["11:30–16:25", "07:00–11:55"]
    assert all(p["issues"] == [] and p["layout"] == "scheduler" for p in reading["pages"])
    cells = sorted(
        (
            (c["weekday"], c["start"], c["end"], " ".join(c["lines"]))
            for p in reading["pages"]
            for c in p["cells"]
        )
    )
    assert cells == [
        (1, "11:00", "12:00", "16U2602 Data Structures"),
        (2, "09:00", "10:00", "16U2508 Introduction to Virtual Reality and"),
        (2, "11:00", "13:00", "16U2603 Data Structures Laboratory"),
        (4, "12:00", "13:00", "16U2291 Database Management Systems."),
    ]


@needs_ocr
def test_scheduler_gaps_and_cut_off_classes_are_flagged(client, headers):
    setup(client, headers)
    morning = png_bytes(scheduler_png.screenshot(420, 600, WEEK))
    afternoon = png_bytes(scheduler_png.screenshot(690, 900, WEEK))
    reading = upload(
        client, headers, [("m.png", morning, "image/png"), ("a.png", afternoon, "image/png")]
    ).json()
    assert "No screenshot shows 10:00–11:30" in " ".join(reading["pages"][0]["issues"])
    lab = [c for p in reading["pages"] for c in p["cells"] if "Laboratory" in " ".join(c["lines"])]
    assert len(lab) == 1 and lab[0]["clippedTop"] and not lab[0]["clippedBottom"]
    not_scheduler = png_bytes(Image.new("RGB", (900, 600), "white"))
    r = upload(client, headers, [("photo.png", not_scheduler, "image/png")])
    assert r.json()["code"] == "NOT_A_TIMETABLE_PICTURE"


@needs_ocr
def test_scheduler_draft_links_by_name_and_code(client, headers):
    subjects = setup(
        client,
        headers,
        [
            ("Data Structures", "theory"),
            ("Data Structures Lab", "lab"),
            ("Introduction to Virtual Reality and Unity Game Engine", "theory"),
            ("DBMS", "theory", "16U2291"),
        ],
    )
    shot = png_bytes(scheduler_png.screenshot(420, 1020, WEEK))
    reading = upload(client, headers, [("s.png", shot, "image/png")]).json()
    draft = interpret(client, headers, reading).json()
    rows = {r["label"]: r for r in draft["rows"]}
    assert set(rows) == {
        "Data Structures",
        "Data Structures Laboratory",
        "Introduction to Virtual Reality and",
        "Database Management Systems",
    }, draft["rows"]
    assert all(r["include"] and not r["batches"] and r["choiceKey"] is None for r in draft["rows"])
    assert rows["Data Structures"]["subjectId"] == subjects[("Data Structures", "theory")]["id"]
    lab = rows["Data Structures Laboratory"]
    assert lab["component"] == "lab" and lab["code"] == "16U2603"
    assert lab["suggestedSubjectId"] == subjects[("Data Structures Lab", "lab")]["id"]
    vr = rows["Introduction to Virtual Reality and"]
    assert (
        vr["suggestedSubjectId"]
        == subjects[("Introduction to Virtual Reality and Unity Game Engine", "theory")]["id"]
    )
    assert rows["Database Management Systems"]["subjectId"] == subjects[("DBMS", "theory")]["id"]  # by code


def confirm(client, headers, body, fresh=True):
    return client.post(
        "/api/v1/timetable-imports/confirm", headers=headers.fresh() if fresh else headers, json=body
    )


def slot(subject, weekday=1, start="09:00", end="10:00", **extra):
    return {"subjectId": subject["id"], "weekday": weekday, "startTime": start, "endTime": end, **extra}


def test_confirm_dry_run_add_duplicates_and_replay(client, headers):
    s = setup(client, headers, [("DS", "theory"), ("DBMS", "lab")])
    ds, lab = s[("DS", "theory")], s[("DBMS", "lab")]
    body = {
        "profileRevision": 2,
        "subjects": [{"id": ds["id"], "revision": 1}, {"id": lab["id"], "revision": 1}],
        "slots": [
            slot(ds, location="B204", instructor="JMR"),
            slot(ds, location="B204", instructor="JMR"),
            slot(lab, 1, "14:00", "16:00", location="B116A"),
        ],
    }
    dry = confirm(client, headers, {**body, "dryRun": True}).json()
    assert len(dry["summary"]["added"]) == 2 and dry["summary"]["repeated"] == 1
    with transaction(account_uid(headers)) as db:
        assert db.scalars(select(Slot)).all() == []
    key = headers.fresh()
    r = client.post("/api/v1/timetable-imports/confirm", headers=key, json=body)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert [x["revision"] for x in saved["subjects"]] == [2, 2]
    again = client.post("/api/v1/timetable-imports/confirm", headers=key, json=body)
    assert again.json() == saved  # Uncertain retry with the same key never duplicates slots.
    tt = client.get("/api/v1/subjects/" + lab["id"] + "/timetable", headers=headers).json()
    assert len(tt["slots"]) == 1 and tt["slots"][0]["origin"]["type"] == "timetable_import"
    assert tt["slots"][0]["semesterContext"] == 3 and tt["slots"][0]["location"] == "B116A"
    stale = confirm(client, headers, body)
    assert stale.status_code == 409 and stale.json()["code"] == "REVISION_CONFLICT"
    body["subjects"] = [{"id": ds["id"], "revision": 2}, {"id": lab["id"], "revision": 2}]
    dup = confirm(client, headers, body).json()
    assert dup["summary"]["added"] == [] and len(dup["summary"]["duplicates"]) == 2
    assert all(d["sameDetails"] for d in dup["summary"]["duplicates"])


def test_confirm_replace_conflicts_rollback_and_ownership(client, headers):
    s = setup(client, headers, [("DS", "theory"), ("COA", "theory")])
    ds, coa = s[("DS", "theory")], s[("COA", "theory")]
    path = "/api/v1/subjects/" + ds["id"] + "/timetable"
    manual = {"weekday": 2, "startTime": "10:00", "endTime": "11:00", "validFrom": "2026-07-01"}
    kept = {"weekday": 1, "startTime": "09:00", "endTime": "10:00", "location": "B201"}
    old = client.put(path, headers=headers.fresh(), json={"revision": 1, "slots": [manual, kept]}).json()
    kept_id = [x["id"] for x in old["slots"] if x["weekday"] == 1][0]
    # A stale revision on one subject saves nothing for either subject.
    body = {
        "mode": "replace",
        "profileRevision": 2,
        "subjects": [{"id": ds["id"], "revision": 2}, {"id": coa["id"], "revision": 9}],
        "slots": [slot(ds, location="B204"), slot(coa, 3, "12:00", "13:00")],
    }
    assert confirm(client, headers, body).status_code == 409
    assert len(client.get(path, headers=headers).json()["slots"]) == 2
    body["subjects"][1]["revision"] = 1
    dry = confirm(client, headers, {**body, "dryRun": True}).json()["summary"]
    assert [(r["weekday"], r["startTime"]) for r in dry["removed"]] == [(2, "10:00")]
    assert len(dry["updated"]) == 1 and len(dry["added"]) == 1
    r = confirm(client, headers, body)
    assert r.status_code == 200, r.text
    slots = client.get(path, headers=headers).json()["slots"]
    assert [(x["id"], x["location"]) for x in slots] == [(kept_id, "B204")]  # Slot ID preserved.
    # Profile changes invalidate the reviewed batch decisions.
    client.patch("/api/v1/me", headers=headers.fresh(), json={"revision": 2, "generalBatch": "3"})
    body = {"profileRevision": 2, "subjects": [{"id": coa["id"], "revision": 2}], "slots": [slot(coa, 5)]}
    assert confirm(client, headers, body).json()["code"] == "PROFILE_CHANGED"
    other = account("other@somaiya.edu")
    client.get("/api/v1/me", headers=other.headers)
    foreign = {"profileRevision": 1, "subjects": [{"id": coa["id"], "revision": 2}], "slots": [slot(coa, 5)]}
    r = client.post("/api/v1/timetable-imports/confirm", headers=other.headers, json=foreign)
    assert r.status_code == 404
    mismatch = {"profileRevision": 3, "subjects": [{"id": ds["id"], "revision": 3}], "slots": [slot(coa, 5)]}
    assert confirm(client, headers, mismatch).status_code == 422


def test_import_ignores_unrelated_profile_version_changes(client, headers, student):
    subjects = setup(client, headers, [("DS", "theory")])
    ds = subjects[("DS", "theory")]
    body = {
        "profileRevision": 2,
        "profileContext": timetable_api.profile_context(PROFILE),
        "subjects": [{"id": ds["id"], "revision": 1}],
        "slots": [slot(ds)],
    }
    # Both explicit appearance changes and background faculty/policy updates increment revision.
    client.patch("/api/v1/me", headers=headers.fresh(), json={"revision": 2, "theme": "dark"})
    with transaction(str(student.uid)) as db:
        p = db.get(Profile, student.uid)
        p.data = {**p.data, "approvedFaculty": {"teacher@somaiya.edu": {"approved": True}}}
        p.revision += 1
    dry = confirm(client, headers, {**body, "dryRun": True})
    assert dry.status_code == 200, dry.text
    saved = confirm(client, headers, body, fresh=False)
    assert saved.status_code == 200, saved.text
    # Replaying the same save after further profile changes returns the original result.
    client.patch("/api/v1/me", headers=headers.fresh(), json={"revision": 4, "generalBatch": "3"})
    again = confirm(client, headers, body, fresh=False)
    assert again.json() == saved.json()


@pytest.mark.parametrize(
    "changes",
    [
        {"generalBatch": "3"},
        {"division": "A"},
        {"currentSemester": 4},
        {"classYear": "TY"},
        {"branchCode": "IT"},
    ],
)
def test_import_still_rejects_changed_academic_context(client, headers, changes):
    subjects = setup(client, headers, [("DS", "theory")])
    ds = subjects[("DS", "theory")]
    body = {
        "profileRevision": 2,
        "profileContext": timetable_api.profile_context(PROFILE),
        "subjects": [{"id": ds["id"], "revision": 1}],
        "slots": [slot(ds)],
    }
    client.patch("/api/v1/me", headers=headers.fresh(), json={"revision": 2, **changes})
    response = confirm(client, headers, body)
    assert response.status_code == 409
    assert response.json()["code"] == "PROFILE_CHANGED"
    assert client.get(f"/api/v1/subjects/{ds['id']}/timetable", headers=headers).json()["slots"] == []


def test_overlaps_require_acknowledgement(client, headers):
    s = setup(client, headers, [("DS", "theory"), ("COA", "theory")])
    ds, coa = s[("DS", "theory")], s[("COA", "theory")]
    client.put(
        "/api/v1/subjects/" + ds["id"] + "/timetable",
        headers=headers.fresh(),
        json={"revision": 1, "slots": [{"weekday": 1, "startTime": "09:00", "endTime": "11:00"}]},
    )
    body = {
        "profileRevision": 2,
        "subjects": [{"id": coa["id"], "revision": 1}],
        "slots": [slot(coa, 1, "10:00", "11:00")],
    }
    dry = confirm(client, headers, {**body, "dryRun": True}).json()["summary"]
    assert len(dry["overlaps"]) == 1
    assert {dry["overlaps"][0]["first"]["subjectName"], dry["overlaps"][0]["second"]["subjectName"]} == {
        "DS",
        "COA",
    }
    assert confirm(client, headers, body).json()["code"] == "OVERLAPS_NEED_REVIEW"
    assert confirm(client, headers, {**body, "acknowledgeOverlaps": True}).status_code == 200


def test_interpret_rejects_malformed_extraction(client, headers):
    setup(client, headers)
    cell = {"id": "c1", "page": "p1", "weekday": 1, "start": "10:00", "end": "09:00", "lines": ["DS"]}
    r = client.post(
        "/api/v1/timetable-imports/interpret",
        headers=headers.fresh(),
        json={"pages": [{"id": "p1"}], "cells": [cell]},
    )
    assert r.status_code == 422
    cell = {**cell, "end": "11:00", "page": "p9"}
    r = client.post(
        "/api/v1/timetable-imports/interpret",
        headers=headers.fresh(),
        json={"pages": [{"id": "p1"}], "cells": [cell]},
    )
    assert r.status_code == 422


def test_other_division_timetable_is_excluded_visibly(client, headers):
    setup(client, headers)
    pdf = build(
        "Class: SY B. Tech COMP A    Year: 2026-2027", DAYS, TIMES, [(0, 0, 0, 0, 1, ["DS B204 JMR"])]
    )
    reading = upload(client, headers, [("a.pdf", pdf, "application/pdf")]).json()
    draft = interpret(client, headers, reading).json()
    assert draft["documents"][0]["mismatch"] == "This timetable is for division A"
    assert [r["include"] for r in draft["rows"]] == [False]


def account_uid(headers):
    from duecare import auth

    with transaction() as db:
        from duecare.models import WebSession

        return str(db.get(WebSession, auth.digest(headers["x-session"])).user_id)


def test_subjects_are_not_repeated(client, headers):
    s = setup(client, headers, [("Data Structures", "theory"), ("Data Structures", "lab")])
    again = client.post(
        "/api/v1/subjects", headers=headers.fresh(), json={"name": " data  structures ", "kind": "theory"}
    )
    assert again.status_code == 409 and again.json()["code"] == "DUPLICATE_SUBJECT"
    lab = s[("Data Structures", "lab")]
    rename = client.patch(
        "/api/v1/subjects/" + lab["id"],
        headers=headers.fresh(),
        json={"name": "Data Structures", "kind": "theory", "revision": lab["revision"]},
    )
    assert rename.status_code == 409
    created = client.post(
        "/api/v1/subjects",
        headers=headers.fresh(),
        json={"name": "Database Management Systems", "kind": "lab", "code": "16U2296", "aliases": ["DBMS"]},
    )
    assert created.status_code == 201 and created.json()["aliases"] == ["DBMS"]


def whatsapp(image):
    """Forwarding through WhatsApp shrinks screenshots and recompresses them as JPEG."""
    small = image.resize((round(image.width * 0.64), round(image.height * 0.64)), Image.LANCZOS)
    out = io.BytesIO()
    small.save(out, "JPEG", quality=70)
    return out.getvalue()


@needs_ocr
def test_shrunk_jpeg_screenshots_read_the_same(client, headers):
    setup(client, headers)
    first = whatsapp(scheduler_png.screenshot(420, 715, WEEK))
    second = whatsapp(scheduler_png.screenshot(690, 985, WEEK))
    r = upload(client, headers, [("a.jpeg", first, "image/jpeg"), ("b.jpeg", second, "image/jpeg")])
    assert r.status_code == 200, r.text
    cells = sorted(
        (c["weekday"], c["start"], c["end"], c["lines"][0]) for p in r.json()["pages"] for c in p["cells"]
    )
    assert cells == [
        (1, "11:00", "12:00", "16U2602"),
        (2, "09:00", "10:00", "16U2508"),
        (2, "11:00", "13:00", "16U2603"),
        (4, "12:00", "13:00", "16U2291"),
    ]


def test_code_repair():
    assert timetable_scheduler.fix_code("32$B002 Glimpses") == "32SB002 Glimpses"
    assert timetable_scheduler.fix_code("16U2S38 Integral") == "16U2538 Integral"
    assert timetable_scheduler.fix_code("Data Structures") == "Data Structures"


def rendered(pdf_bytes, dpi=110):
    """A department timetable as a picture (a phone screenshot or scan of the PDF)."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return pdf.pages[0].to_image(resolution=dpi).original.convert("RGB")


@needs_ocr
def test_department_timetable_pictures_and_scans_read_like_the_pdf(client, headers):
    setup(client, headers)
    pdf = upload(client, headers, [("tt.pdf", sample(), "application/pdf")]).json()
    expected = sorted((c["weekday"], c["start"], c["end"], c["narrow"]) for c in pdf["pages"][0]["cells"])
    picture = png_bytes(rendered(sample()))
    r = upload(client, headers, [("tt.png", picture, "image/png")])
    assert r.status_code == 200, r.text
    page = r.json()["pages"][0]
    assert page["method"] == "image_ocr" and page["layout"] == "grid"
    assert page["header"]["classLabel"].startswith("SY B")
    got = sorted((c["weekday"], c["start"], c["end"], c["narrow"]) for c in page["cells"])
    assert got == expected
    lab = next(c for c in page["cells"] if c["lines"][0] == "B2")
    assert (lab["start"], lab["end"], "DBMS" in " ".join(lab["lines"])) == ("14:00", "16:00", True)
    # A scanned PDF (only a picture inside) is read the same way.
    scan = io.BytesIO()
    rendered(sample(), dpi=150).save(scan, "PDF", resolution=150)
    r = upload(client, headers, [("scan.pdf", scan.getvalue(), "application/pdf")])
    assert r.status_code == 200, r.text
    assert r.json()["pages"][0]["method"] == "image_ocr"
    assert sorted((c["weekday"], c["start"], c["end"]) for c in r.json()["pages"][0]["cells"]) == [
        e[:3] for e in expected
    ]


def test_electives_honours_minor_and_teacher_choices():
    cells = [
        {
            "id": f"c{n}",
            "page": "p1",
            "weekday": d,
            "start": s,
            "end": e,
            "lines": [t],
            "bbox": None,
            "narrow": narrow,
        }  # fmt: skip
        for n, (d, s, e, t, narrow) in enumerate(
            [
                (1, "09:00", "10:00", "Minor -- --", False),
                (1, "10:00", "11:00", "EL -- --", False),
                (2, "12:00", "13:00", "E-ACC B201 ZSS", True),
                (2, "12:00", "13:00", "E-ACC B202 SIP", True),
                (3, "12:00", "13:00", "E-ACC B201 ZSS", True),
                (3, "12:00", "13:00", "E-ACC B202 SIP", True),
                (2, "14:00", "16:00", "E-ACC_1 B210A SIP", True),
                (2, "14:00", "16:00", "E-ACC_2 B210B ZSS", True),
                (4, "09:00", "11:00", "H-CSFTUT_1 B217A CO2", True),
                (4, "09:00", "11:00", "H-DA_1 B115A AAG", True),
                (5, "09:00", "10:00", "H_CSF B203 ZSS", False),
            ]
        )
    ]
    subjects = [{"id": "s1", "name": "Advanced Cloud Computing", "kind": "theory", "aliases": ["ACC"]}]
    d = timetable_draft.build(
        cells, [{"id": "p1"}], {"classYear": "LY", "division": "A"}, subjects, use_ai=False
    )
    rows = {r["sourceText"]: r for r in d["rows"]}
    assert rows["Minor -- --"]["placeholder"] and rows["Minor -- --"]["track"] == "minor"
    assert "placeholder" in rows["EL -- --"]["issues"] and rows["EL -- --"]["include"]
    fams = {f["key"]: f for f in d["families"]}
    assert set(fams) == {"elective:acc", "honours:csf", "honours:da"}
    assert (
        fams["elective:acc"]["selected"] and not fams["honours:da"]["selected"]
    )  # Linked ACC starts ticked.
    assert fams["honours:csf"]["slots"] == 2  # CSF tutorial and CSF theory are one course family.
    # Each teacher keeps the same E-ACC group all week: one choice, not one per day.
    teachers = {
        (r["choiceKey"], r["choiceLabel"])
        for r in d["rows"]
        if r["baseLabel"] == "E-ACC" and r["group"] is None
    }
    assert teachers == {("teacher:eacc", "ZSS"), ("teacher:eacc", "SIP")}
    assert rows["E-ACC_1 / B210A SIP".replace(" / ", " ")]["choiceKey"] == "group:eacc"
