"""CubeVision web app: receives frames from the phone relay, runs vision + cube
logic + coaching, and sends instructions back to the glasses.

Run:  uvicorn cubevision.server:app --host 0.0.0.0 --port 8000

Device WebSocket protocol  (/ws/device?session=default)
  phone -> server, binary:  1 byte kind + payload
        0x01 + JPEG bytes          one camera frame from the glasses
        0x02 + PCM16 mono 16 kHz   microphone audio chunk (for speech-to-speech)
  phone -> server, text JSON:
        {"type": "hello", "device": "...", "app_version": "..."}
        {"type": "reset"}
        {"type": "config", "level": "full"|"2look", "cross_color": "W"}
        {"type": "observations", "faces": [...]}       # bypass vision (testing)
        {"type": "load_state", "state": "<54 colour chars>"}
  server -> phone, text JSON events, e.g.
        {"type": "step", "say": "...", "step": {...}, "audio_b64": "...", "audio_format": "mp3"}
        The phone plays audio_b64 if present, otherwise speaks "say" with on-device TTS.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .assemble import FaceObservation, observation_of
from .cube import FACES, FACE_TURNS, SOLVED, apply, centers
from .pieces import validate
from .plugins import load_speech, load_vision
from .solver.cfop import DEFAULT_SCHEME, solve
from .tracker import Session

log = logging.getLogger("cubevision")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="CubeVision")
vision = load_vision()
speech = load_speech()

FRAME, AUDIO = 0x01, 0x02


class Hub:
    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self.devices: dict[str, set[WebSocket]] = {}
        self.viewers: dict[str, set[WebSocket]] = {}
        self.busy: dict[str, bool] = {}

    def session(self, sid: str) -> Session:
        if sid not in self.sessions:
            self.sessions[sid] = Session(scheme=dict(DEFAULT_SCHEME))
        return self.sessions[sid]

    async def emit(self, sid: str, events: list[dict]):
        if not events:
            return
        sess = self.session(sid)
        speech.context(sid, sess.snapshot())
        for ev in events:
            if ev.get("say"):
                try:
                    audio = await speech.speak(sid, ev["say"])
                except Exception:  # never let TTS break coaching
                    log.exception("speech.speak failed")
                    audio = None
                if audio:
                    ev["audio_b64"] = base64.b64encode(audio).decode()
                    ev.setdefault("audio_format", "mp3")
        for ws in list(self.devices.get(sid, ())):
            try:
                for ev in events:
                    await ws.send_json(ev)
            except Exception:
                self.devices[sid].discard(ws)
        await self.update_viewers(sid, events)

    async def update_viewers(self, sid: str, events: list[dict]):
        snap = self.session(sid).snapshot()
        msg = {"events": [{k: v for k, v in e.items() if k != "audio_b64"} for e in events], "snapshot": snap}
        for ws in list(self.viewers.get(sid, ())):
            try:
                await ws.send_json(msg)
            except Exception:
                self.viewers[sid].discard(ws)


hub = Hub()


def _parse_faces(faces: list[dict]) -> list[FaceObservation]:
    out = []
    for f in faces:
        try:
            out.append(FaceObservation.from_dict(f))
        except (ValueError, KeyError, TypeError) as e:
            log.warning("bad face observation %s: %s", f, e)
    return out


async def handle_frame(sid: str, jpeg: bytes):
    """Latest-frame-wins: drop frames that arrive while vision is still busy."""
    if hub.busy.get(sid):
        return
    hub.busy[sid] = True
    try:
        faces = await asyncio.to_thread(vision.detect, jpeg)
        events = hub.session(sid).on_frame(_parse_faces(faces or []))
        await hub.emit(sid, events)
    except Exception:
        log.exception("frame processing failed")
    finally:
        hub.busy[sid] = False


async def handle_command(sid: str, msg: dict) -> list[dict]:
    sess = hub.session(sid)
    t = msg.get("type")
    if t == "hello":
        return [{"type": "welcome", "say": "Connected. Show me your cube, one side at a time.",
                 "snapshot": sess.snapshot()}]
    if t == "reset":
        return sess.reset()
    if t == "config":
        if msg.get("level") in ("full", "2look"):
            sess.level = msg["level"]
        if msg.get("cross_color"):
            sess.cross_color = msg["cross_color"].upper()
        return [{"type": "config", "level": sess.level, "cross_color": sess.cross_color}]
    if t == "observations":
        return sess.on_frame(_parse_faces(msg.get("faces", [])))
    if t == "load_state":
        return sess.load_state(msg["state"].upper())
    return [{"type": "warning", "message": f"unknown message type {t!r}"}]


@app.websocket("/ws/device")
async def ws_device(ws: WebSocket, session: str = "default"):
    await ws.accept()
    hub.devices.setdefault(session, set()).add(ws)
    log.info("device connected to session %s", session)
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes"):
                data: bytes = msg["bytes"]
                kind, payload = data[0], data[1:]
                if kind == FRAME:
                    asyncio.create_task(handle_frame(session, payload))
                elif kind == AUDIO:
                    await hub.emit(session, await speech.on_audio(session, payload) or [])
            elif msg.get("text"):
                await hub.emit(session, await handle_command(session, json.loads(msg["text"])))
    except WebSocketDisconnect:
        pass
    finally:
        hub.devices.get(session, set()).discard(ws)
        log.info("device left session %s", session)


@app.websocket("/ws/viewer")
async def ws_viewer(ws: WebSocket, session: str = "default"):
    await ws.accept()
    hub.viewers.setdefault(session, set()).add(ws)
    await ws.send_json({"events": [], "snapshot": hub.session(session).snapshot()})
    try:
        while True:
            msg = await ws.receive_json()
            await hub.emit(session, await handle_command(session, msg))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.viewers.get(session, set()).discard(ws)


# ------------------------------------------------------------------ REST (testing)
class Faces(BaseModel):
    faces: list[dict]


class StateIn(BaseModel):
    state: str
    level: str = "full"
    cross_color: str = "W"


@app.post("/api/{session}/observations")
async def post_observations(session: str, body: Faces):
    events = await handle_command(session, {"type": "observations", "faces": body.faces})
    await hub.emit(session, events)
    return {"events": events, "snapshot": hub.session(session).snapshot()}


@app.post("/api/{session}/frame")
async def post_frame(session: str, request: Request):
    """POST a raw JPEG (Content-Type: image/jpeg) to run it through vision."""
    await handle_frame(session, await request.body())
    return hub.session(session).snapshot()


@app.post("/api/{session}/reset")
async def post_reset(session: str):
    await hub.emit(session, hub.session(session).reset())
    return hub.session(session).snapshot()


@app.post("/api/{session}/load_state")
async def post_state(session: str, body: StateIn):
    events = await handle_command(session, {"type": "load_state", "state": body.state})
    await hub.emit(session, events)
    return {"events": events}


@app.get("/api/{session}")
async def get_session(session: str):
    return hub.session(session).snapshot()


@app.post("/api/validate")
async def api_validate(body: StateIn):
    return validate(body.state.upper()).to_dict()


@app.post("/api/solve")
async def api_solve(body: StateIn):
    return solve(body.state.upper(), cross_color=body.cross_color, level=body.level).to_dict()


# ------------------------------------------------------------------ simulator
# A fake "real cube" per session so the full loop can be exercised from the
# dashboard without glasses or a vision model.
SIM: dict[str, str] = {}


class SimIn(BaseModel):
    action: str                 # scramble | next_move | wrong_move | show_all
    moves: str | None = None


def _sim_turn(sid: str, move: str):
    """Apply a move given in the coach's solving frame to the simulated cube."""
    sess = hub.session(sid)
    frame = sess.solution.start_state if sess.solution else SIM[sid]
    colour = centers(frame)[move[0]]
    face = next(f for f, c in centers(SIM[sid]).items() if c == colour)
    SIM[sid] = apply(SIM[sid], face + move[1:])


def _sim_views(sid: str, faces=None) -> list[dict]:
    st = SIM[sid]
    return [observation_of(st, f, random.randrange(4)) for f in (faces or FACES)]


@app.post("/api/{session}/simulate")
async def simulate(session: str, body: SimIn):
    sess = hub.session(session)
    events: list[dict] = []
    if body.action == "scramble":
        scr = body.moves or " ".join(random.choice(FACE_TURNS) for _ in range(20))
        SIM[session] = "".join(DEFAULT_SCHEME[c] for c in apply(SOLVED, scr))
        events += sess.reset()
        for f in FACES:  # show the faces one at a time, like a person would
            events += sess.on_frame(_parse_faces(_sim_views(session, [f])))
        events.insert(0, {"type": "sim", "scramble": scr})
    elif body.action in ("next_move", "wrong_move") and session in SIM and sess.solution:
        flat = [m for st in sess.solution.steps for m in st.moves]
        if body.action == "next_move" and sess.pos < len(flat):
            mv = flat[sess.pos]
        else:
            mv = random.choice(FACE_TURNS)
        _sim_turn(session, mv)
        events.append({"type": "sim", "did": mv})
        # the camera sees a couple of faces after each turn
        for _ in range(8):
            ev = sess.on_frame(_parse_faces(_sim_views(session, random.sample("URFDLB", 2))))
            events += ev
            if ev:
                break
    elif body.action == "show_all" and session in SIM:
        for f in FACES:
            events += sess.on_frame(_parse_faces(_sim_views(session, [f])))
    await hub.emit(session, events)
    return {"events": events, "snapshot": sess.snapshot()}


@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")
