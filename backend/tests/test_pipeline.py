import random

from fastapi.testclient import TestClient

from cubevision.assemble import FaceObservation, ScanBuffer, observation_of
from cubevision.cube import FACES, FACE_TURNS, SOLVED, apply, centers
from cubevision.server import app
from cubevision.solver.cfop import DEFAULT_SCHEME
from cubevision.tracker import Session


def coloured(scr):
    return "".join(DEFAULT_SCHEME[c] for c in apply(SOLVED, scr))


def views(state, faces, rng, with_up=False):
    return [FaceObservation.from_dict(observation_of(state, f, rng.randrange(4), with_up)) for f in faces]


def test_assembly_with_up_hints_is_always_unique():
    rng = random.Random(0)
    for _ in range(50):
        st = coloured([rng.choice(FACE_TURNS) for _ in range(25)])
        sb = ScanBuffer(DEFAULT_SCHEME)
        for o in views(st, FACES, rng, with_up=True):
            sb.add(o)
        r = sb.assemble()
        assert r.ok and r.state == st


def test_assembly_votes_out_noise():
    rng = random.Random(1)
    st = coloured([rng.choice(FACE_TURNS) for _ in range(25)])
    sb = ScanBuffer(DEFAULT_SCHEME)
    for rep in range(5):
        for f in FACES:
            d = observation_of(st, f, rng.randrange(4))
            if rep == 0:  # first look at every face has one misread sticker
                d["grid"][0][0] = "Y" if d["grid"][0][0] != "Y" else "W"
            sb.add(FaceObservation.from_dict(d))
    r = sb.assemble()
    assert r.ok and r.state == st


def test_sticker_list_format():
    st = coloured("R U F")
    o = observation_of(st, "F", 2)
    stickers = [{"row": r, "col": c, "color": o["grid"][r][c], "conf": 0.9} for r in range(3) for c in range(3)]
    fo = FaceObservation.from_dict({"stickers": stickers})
    assert fo.grid == o["grid"]


def _turn(real, sess, move):
    """Apply a coach-frame move to the real cube (find the face by centre colour)."""
    colour = centers(sess.solution.start_state)[move[0]]
    face = next(f for f, c in centers(real).items() if c == colour)
    return apply(real, face + move[1:])


def test_full_session_follows_user():
    rng = random.Random(7)
    real = coloured([rng.choice(FACE_TURNS) for _ in range(20)])
    sess = Session()
    events = []
    for f in FACES:
        events += sess.on_frame(views(real, [f], rng))
    assert sess.phase == "solving", events
    assert any(e["type"] == "solution" for e in events)
    flat = [m for st in sess.solution.steps for m in st.moves]
    for i, m in enumerate(flat):
        real = _turn(real, sess, m)
        for _ in range(30):
            sess.on_frame(views(real, rng.sample(FACES, 2), rng))
            if sess.pos == i + 1 or sess.phase == "solved":
                break
        assert sess.pos == i + 1, (i, m)
    assert sess.phase == "solved"


def test_recovers_from_wrong_move():
    rng = random.Random(3)
    real = coloured([rng.choice(FACE_TURNS) for _ in range(20)])
    sess = Session()
    sess.load_state(real)
    nxt = sess.solution.steps[0].moves[0]
    wrong = next(m for m in FACE_TURNS if m[0] != nxt[0])
    real = _turn(real, sess, wrong)
    events = []
    for _ in range(12):
        events += sess.on_frame(views(real, FACES[:], rng))
    types = [e["type"] for e in events]
    assert "off_track" in types or "lost" in types
    if "off_track" in types:
        assert sess.phase == "solving"


def test_server_rest_and_ws():
    c = TestClient(app)
    st = coloured("R U R' U' F2 D L")
    r = c.post("/api/validate", json={"state": st})
    assert r.json()["ok"]
    sol = c.post("/api/solve", json={"state": st}).json()
    assert sol["ok"] and sol["steps"]
    rng = random.Random(0)
    with c.websocket_connect("/ws/device?session=t1") as ws:
        ws.send_json({"type": "hello"})
        assert ws.receive_json()["type"] == "welcome"
        ws.send_json({"type": "observations", "faces": [observation_of(st, f, rng.randrange(4)) for f in FACES]})
        got = [ws.receive_json() for _ in range(2)]
        assert got[0]["type"] == "solution" and got[1]["type"] == "step"
        ws.send_bytes(b"\x01" + b"notajpeg")  # null vision -> no events, must not crash
    r = c.post("/api/sim1/simulate", json={"action": "scramble"}).json()
    assert r["snapshot"]["phase"] == "solving"
    for _ in range(150):
        r = c.post("/api/sim1/simulate", json={"action": "next_move"}).json()
        if r["snapshot"]["phase"] == "solved":
            break
    assert r["snapshot"]["phase"] == "solved"


def test_partial_scan_state_and_live_progress():
    """Stickers arriving a few at a time are progress (not errors) and show up in display_state."""
    rng = random.Random(11)
    st = coloured([rng.choice(FACE_TURNS) for _ in range(20)])
    sess = Session()
    assert sess.snapshot()["display_state"] == "?" * 54
    types = []
    for face in FACES:
        k = rng.randrange(4)
        view = observation_of(st, face, k, with_up=True)
        cells = [(r, c) for r in range(3) for c in range(3) if (r, c) != (1, 1)]
        rng.shuffle(cells)
        seen = {(1, 1)}
        for i in range(0, 8, 2):
            seen.update(cells[i:i + 2])
            grid = [[view["grid"][r][c] if (r, c) in seen else None for c in range(3)] for r in range(3)]
            types += [e["type"] for e in sess.on_frame([FaceObservation.from_dict({"grid": grid, "up": view["up"]})])]
            if sess.phase == "scanning":
                disp = sess.snapshot()["display_state"]
                # every known sticker shown so far must be correct
                assert all(a == "?" or a == b for a, b in zip(disp, st))
    assert "scan_error" not in types
    assert sess.phase == "solving"
    # after solving starts, the 3D view shows the scanned cube in the same orientation
    assert sess.snapshot()["display_state"] == st


def test_live_scan_endpoint():
    import time
    c = TestClient(app)
    r = c.post("/api/live1/simulate", json={"action": "live_scan"}).json()
    assert r["events"][0]["live"]
