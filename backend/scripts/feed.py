"""Pipe face observations into a running CubeVision server (no glasses / vision needed).

  python scripts/feed.py scramble "R U R' F2 D L'"     # scan a virtual cube with that scramble
  python scripts/feed.py file observations.json        # send a JSON list of face observations
  python scripts/feed.py solve                          # keep doing the coach's next move until solved
"""
import json
import random
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cubevision.assemble import observation_of  # noqa: E402
from cubevision.cube import FACES, SOLVED, apply  # noqa: E402
from cubevision.solver.cfop import DEFAULT_SCHEME  # noqa: E402

BASE = "http://localhost:8000/api/default"


def show(r):
    for ev in r.get("events", []):
        print(f"[{ev['type']}]", ev.get("say") or ev.get("errors") or "")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scramble"
    if cmd == "scramble":
        scr = sys.argv[2] if len(sys.argv) > 2 else "R U R' U' F2 D L' B U2"
        state = "".join(DEFAULT_SCHEME[c] for c in apply(SOLVED, scr))
        httpx.post(f"{BASE}/reset")
        for f in FACES:  # one face per "frame", random image rotation
            show(httpx.post(f"{BASE}/observations", json={"faces": [observation_of(state, f, random.randrange(4))]}).json())
    elif cmd == "file":
        faces = json.loads(Path(sys.argv[2]).read_text())
        show(httpx.post(f"{BASE}/observations", json={"faces": faces}).json())
    elif cmd == "solve":
        httpx.post(f"{BASE}/simulate", json={"action": "scramble"})
        while True:
            r = httpx.post(f"{BASE}/simulate", json={"action": "next_move"}).json()
            show(r)
            if r["snapshot"]["phase"] != "solving":
                break


if __name__ == "__main__":
    main()
