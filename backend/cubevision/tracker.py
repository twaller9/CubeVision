"""Live coaching session: scanning -> solving (move tracking) -> solved.

Feed it the face observations from each frame; it returns events to send to the
phone/glasses.  Every event has a "type" and most have a "say" string meant for
speech output.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .assemble import FaceObservation, ScanBuffer, rotate
from .cube import FACES, FACE_TURNS, apply, invert
from .solver.cfop import COLOR_NAMES, DEFAULT_SCHEME, Solution, solve, speak_move

MATCH_TOLERANCE = 1      # stickers allowed to disagree (vision noise)
OFF_TRACK_FRAMES = 6     # consecutive unexplained frames before we re-localise


def _face_grid(state: str, centre: str):
    for i, f in enumerate(FACES):
        if state[i * 9 + 4] == centre:
            return [[state[i * 9 + r * 3 + c] for c in range(3)] for r in range(3)]
    return None


def face_matches(state: str, obs: FaceObservation, tol: int = MATCH_TOLERANCE) -> bool:
    g = _face_grid(state, obs.center)
    if g is None:
        return False
    for k in range(4):
        rg = rotate(obs.grid, k)
        bad = sum(1 for r in range(3) for c in range(3) if rg[r][c] != "?" and rg[r][c] != g[r][c])
        if bad <= tol:
            return True
    return False


@dataclass
class Session:
    scheme: dict = field(default_factory=lambda: dict(DEFAULT_SCHEME))
    cross_color: str = "W"
    level: str = "full"              # "full" | "2look"
    phase: str = "scanning"          # scanning | solving | solved
    scan: ScanBuffer = None          # type: ignore
    solution: Solution | None = None
    states: list[str] = field(default_factory=list)       # state after k face turns
    step_ends: list[int] = field(default_factory=list)    # cumulative move index at end of each step
    pos: int = 0                     # how many face turns the user has done
    misses: int = 0
    recent: list[FaceObservation] = field(default_factory=list)
    _last_scan_say: str = ""

    def __post_init__(self):
        self.scan = ScanBuffer(self.scheme)

    # ------------------------------------------------------------ public API
    def reset(self) -> list[dict]:
        self.__init__(scheme=self.scheme, cross_color=self.cross_color, level=self.level)
        return [{"type": "reset", "say": "Okay, let's start over. Show me each side of the cube."}]

    def load_state(self, state: str) -> list[dict]:
        """Skip scanning: start coaching from a known colour state."""
        return self._start_solution(state)

    def on_frame(self, observations: list[FaceObservation]) -> list[dict]:
        if not observations:
            return []
        if self.phase == "scanning":
            return self._on_scan(observations)
        if self.phase == "solving":
            return self._on_track(observations)
        return []

    def snapshot(self) -> dict:
        d = {"phase": self.phase, "faces_seen": self.scan.seen(), "missing": self.scan.missing()}
        if self.solution:
            d.update(solution=self.solution.to_dict(), move_index=self.pos,
                     step_index=self._step_index(), state=self.states[self.pos])
            # Same orientation the cube was scanned in, so the 3D view doesn't jump when the
            # coach switches to the solving orientation (cross on the bottom).
            rot = self.solution.orientation.get("rotation_from_scan", "")
            d["display_state"] = apply(self.states[self.pos], invert(rot)) if rot else self.states[self.pos]
        else:
            d["display_state"] = self.scan.partial_state()
        return d

    # ------------------------------------------------------------ scanning
    def _on_scan(self, observations) -> list[dict]:
        events = []
        for o in observations:
            try:
                self.scan.add(o)
            except ValueError as e:
                events.append({"type": "warning", "message": str(e)})
        res = self.scan.assemble()
        if res.ok:
            return events + self._start_solution(res.state)
        if res.missing_faces or res.incomplete:
            if res.missing_faces:
                nxt = res.missing_faces[0]
                say = f"Got it. Now show me the {COLOR_NAMES.get(nxt, nxt)} side."
            else:
                say = "Almost there, hold it steady."
            ev = {"type": "scan_progress", "faces_seen": self.scan.seen(), "missing": res.missing_faces}
            if say != self._last_scan_say:
                ev["say"] = say
                self._last_scan_say = say
            return events + [ev]
        say = res.errors[0]
        ev = {"type": "scan_error", "errors": res.errors, "ambiguous": res.ambiguous}
        if say != self._last_scan_say:
            ev["say"] = ("Something doesn't add up, let me look again. Slowly show me every side."
                         if not res.ambiguous else "Hold the cube so I can see two sides at once.")
            self._last_scan_say = say
        if not res.ambiguous and min(fv.n for fv in self.scan.faces.values()) >= 8:
            self.scan.reset()   # stale/bad votes: start the scan over
        return events + [ev]

    def _start_solution(self, state: str) -> list[dict]:
        sol = solve(state, cross_color=self.cross_color, level=self.level)
        if not sol.ok:
            self.scan.reset()
            return [{"type": "scan_error", "errors": sol.errors,
                     "say": "That cube state isn't possible. Let's scan again."}]
        self.solution = sol
        self.states = [sol.start_state]
        self.step_ends = []
        for st in sol.steps:
            for m in st.moves:
                self.states.append(apply(self.states[-1], m))
            self.step_ends.append(len(self.states) - 1)
        self.pos = 0
        self.phase = "solving" if sol.steps else "solved"
        ev = [{"type": "solution", "solution": sol.to_dict(),
               "say": sol.orientation["say"] + f" I found a {sol.total_moves} move solution."}]
        return ev + self._step_event()

    # ------------------------------------------------------------ tracking
    def _step_index(self) -> int:
        for i, end in enumerate(self.step_ends):
            if self.pos < end:
                return i
        return len(self.step_ends)

    def _step_event(self) -> list[dict]:
        i = self._step_index()
        if i >= len(self.solution.steps):
            self.phase = "solved"
            return [{"type": "solved", "say": "Solved! Nice work."}]
        st = self.solution.steps[i]
        start = self.step_ends[i - 1] if i else 0
        return [{"type": "step", "index": i, "of": len(self.solution.steps), "step": st.__dict__,
                 "move_in_step": self.pos - start, "say": st.say}]

    def _on_track(self, observations) -> list[dict]:
        self.recent = (self.recent + observations)[-12:]
        lookahead = min(len(self.states) - 1, self.pos + 12)
        cands = [j for j in range(self.pos, lookahead + 1)
                 if all(face_matches(self.states[j], o) for o in observations)]
        if self.pos in cands:
            self.misses = 0
            return []                           # nothing visibly changed (or ambiguous)
        if cands:
            self.misses = 0
            old_step = self._step_index()
            self.pos = cands[0]
            if self._step_index() != old_step:
                return [{"type": "step_done", "index": old_step}] + self._step_event()
            nxt = self.solution and self._next_move()
            return [{"type": "progress", "move_index": self.pos, "next_move": nxt,
                     "say": speak_move(nxt) if nxt else ""}]
        self.misses += 1
        if self.misses < OFF_TRACK_FRAMES:
            return []
        return self._relocalise()

    def _next_move(self) -> str | None:
        flat = [m for st in self.solution.steps for m in st.moves]
        return flat[self.pos] if self.pos < len(flat) else None

    def _relocalise(self) -> list[dict]:
        """User did something unexpected: find the actual state from recent views."""
        self.misses = 0
        here = self.states[self.pos]
        obs = self.recent
        candidates = []
        for m1 in FACE_TURNS:
            s1 = apply(here, m1)
            if all(face_matches(s1, o) for o in obs[-4:]):
                candidates.append((s1, [m1]))
            for m2 in FACE_TURNS:
                if m2[0] == m1[0]:
                    continue
                s2 = apply(s1, m2)
                if all(face_matches(s2, o) for o in obs[-4:]):
                    candidates.append((s2, [m1, m2]))
        distinct = {c[0] for c in candidates}
        if len(distinct) == 1:
            state, done = candidates[0]
            ev = [{"type": "off_track", "detected_moves": done,
                   "say": f"Oops, looks like you did {' '.join(done)}. Let me re-plan."}]
            self.phase = "solving"
            return ev + self._start_solution(state)
        self.phase = "scanning"
        self.scan.reset()
        return [{"type": "lost", "say": "I lost track of the cube. Please show me every side again."}]

