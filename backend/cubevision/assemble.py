"""Build a full cube state from per-face observations coming out of the vision model.

The vision model only has to report, for each cube face it can see in a frame,
the 3x3 sticker colours *as they appear in the image* (row 0 = top of image).
It does NOT need to know which way the face is rotated: we figure that out by
(a) an optional hint — which neighbouring face is visible above it in the image —
and (b) trying all rotations and keeping only combinations where every corner
and edge is a real piece.

Observation JSON accepted by `FaceObservation.from_dict`:

    {"grid": [["W","W","R"],["G","W","W"],["B","O","W"]],   # required (or "stickers")
     "up": "G",                       # optional: centre colour of the face above it in the image
     "confidence": [[0.9, ...], ...]}  # optional, same shape as grid

or the sticker-list form:

    {"center": "W",
     "stickers": [{"row": 0, "col": 0, "color": "W", "conf": 0.93}, ...],
     "up": "G"}
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .cube import FACES, NORMALS, FACE_OF_NORMAL, STICKERS
from .pieces import CORNER_FACES, CORNER_STICKERS, EDGE_FACES, EDGE_STICKERS, validate

Grid = list[list[str]]
UNKNOWN = "?"


def rot_cw(g: Grid) -> Grid:
    return [[g[2 - c][r] for c in range(3)] for r in range(3)]


def rotate(g: Grid, k: int) -> Grid:
    for _ in range(k % 4):
        g = rot_cw(g)
    return g


@dataclass
class FaceObservation:
    grid: Grid
    up: str | None = None
    confidence: list[list[float]] | None = None

    @property
    def center(self) -> str:
        return self.grid[1][1]

    @classmethod
    def from_dict(cls, d: dict) -> "FaceObservation":
        if "grid" in d:
            grid = [[(c or UNKNOWN).upper() for c in row] for row in d["grid"]]
            conf = d.get("confidence")
        else:
            grid = [[UNKNOWN] * 3 for _ in range(3)]
            conf = [[1.0] * 3 for _ in range(3)]
            for s in d["stickers"]:
                grid[s["row"]][s["col"]] = (s.get("color") or UNKNOWN).upper()
                conf[s["row"]][s["col"]] = float(s.get("conf", 1.0))
            if d.get("center"):
                grid[1][1] = d["center"].upper()
        if len(grid) != 3 or any(len(r) != 3 for r in grid):
            raise ValueError("grid must be 3x3")
        if grid[1][1] == UNKNOWN:
            raise ValueError("centre sticker colour is required to identify the face")
        return cls(grid=grid, up=(d.get("up") or None) and d["up"].upper(), confidence=conf)


# direction (0=top,1=right,2=bottom,3=left of the canonical net grid) -> neighbour face
def _neighbours(face: str) -> list[str]:
    out = []
    n = NORMALS[face]
    for r, c in ((0, 1), (1, 2), (2, 1), (1, 0)):
        p, _ = STICKERS[FACES.index(face) * 9 + r * 3 + c]
        d = tuple(p[k] - n[k] for k in range(3))
        out.append(FACE_OF_NORMAL[d])
    return out


NEIGHBOURS = {f: _neighbours(f) for f in FACES}


@dataclass
class FaceVotes:
    votes: list[list[Counter]] = field(default_factory=lambda: [[Counter() for _ in range(3)] for _ in range(3)])
    n: int = 0
    abs_rot_votes: Counter = field(default_factory=Counter)  # rotation of this consensus frame into the net

    def consensus(self) -> Grid:
        g = [[UNKNOWN] * 3 for _ in range(3)]
        for r in range(3):
            for c in range(3):
                if self.votes[r][c]:
                    g[r][c] = self.votes[r][c].most_common(1)[0][0]
        return g

    def agreement(self) -> float:
        tot = best = 0.0
        for r in range(3):
            for c in range(3):
                v = self.votes[r][c]
                if v:
                    tot += sum(v.values())
                    best += v.most_common(1)[0][1]
        return best / tot if tot else 0.0


@dataclass
class AssemblyResult:
    ok: bool
    state: str | None = None          # colour facelets in the scheme's reference orientation
    errors: list[str] = field(default_factory=list)
    missing_faces: list[str] = field(default_factory=list)  # centre colours not yet seen
    ambiguous: bool = False


class ScanBuffer:
    """Accumulates face observations across frames (the cube must not be turned while scanning)."""

    def __init__(self, scheme: dict[str, str]):
        self.scheme = dict(scheme)            # face letter -> centre colour (reference orientation)
        self.face_of_colour = {c: f for f, c in scheme.items()}
        self.faces: dict[str, FaceVotes] = defaultdict(FaceVotes)

    def reset(self):
        self.faces.clear()

    def seen(self) -> list[str]:
        return [c for c in self.faces if self.faces[c].n]

    def missing(self) -> list[str]:
        return [self.scheme[f] for f in FACES if self.scheme[f] not in self.seen()]

    def add(self, obs: FaceObservation) -> None:
        col = obs.center
        if col not in self.face_of_colour:
            raise ValueError(f"Unknown centre colour {col!r}; colour scheme is {self.scheme}")
        fv = self.faces[col]
        k_align = 0
        if fv.n:
            cons = fv.consensus()
            k_align = max(range(4), key=lambda k: _agree(rotate(obs.grid, k), cons))
        g = rotate(obs.grid, k_align)
        conf = rotate(obs.confidence, k_align) if obs.confidence else None
        for r in range(3):
            for c in range(3):
                if g[r][c] != UNKNOWN:
                    fv.votes[r][c][g[r][c]] += conf[r][c] if conf else 1.0
        fv.n += 1
        if obs.up and obs.up in self.face_of_colour:
            face = self.face_of_colour[col]
            up_face = self.face_of_colour[obs.up]
            if up_face in NEIGHBOURS[face]:
                k_abs = NEIGHBOURS[face].index(up_face)        # rotation of the raw obs into the net
                fv.abs_rot_votes[(k_abs - k_align) % 4] += 1

    def assemble(self) -> AssemblyResult:
        missing = self.missing()
        if missing:
            return AssemblyResult(ok=False, missing_faces=missing,
                                  errors=[f"Haven't seen the {', '.join(missing)} face(s) yet."])
        grids, options = {}, {}
        for f in FACES:
            fv = self.faces[self.scheme[f]]
            grids[f] = fv.consensus()
            if fv.abs_rot_votes:
                options[f] = [fv.abs_rot_votes.most_common(1)[0][0]]
            else:
                options[f] = [0, 1, 2, 3]
            unknown = sum(ch == UNKNOWN for row in grids[f] for ch in row)
            if unknown:
                return AssemblyResult(ok=False, errors=[f"{unknown} sticker(s) on the {self.scheme[f]} face unreadable."])

        solutions = _search_rotations(grids, options, self.face_of_colour)
        if not solutions:
            # Report what is wrong with the most plausible arrangement
            st = _build({f: rotate(grids[f], options[f][0]) for f in FACES})
            v = validate(st)
            errs = v.errors or ["Stickers don't form a valid cube in any face rotation."]
            return AssemblyResult(ok=False, state=st, errors=["Scan is inconsistent: " + e for e in errs])
        if len(solutions) > 1:
            return AssemblyResult(ok=False, ambiguous=True, state=solutions[0],
                                  errors=["Several face rotations fit; show two faces at once so I can tell how they connect."])
        return AssemblyResult(ok=True, state=solutions[0])


def _agree(a: Grid, b: Grid) -> int:
    return sum(a[r][c] == b[r][c] for r in range(3) for c in range(3) if b[r][c] != UNKNOWN)


def _build(placed: dict[str, Grid]) -> str:
    s = []
    for f in FACES:
        g = placed.get(f)
        for r in range(3):
            for c in range(3):
                s.append(g[r][c] if g else UNKNOWN)
    return "".join(s)


def _search_rotations(grids, options, face_of_colour) -> list[str]:
    """Backtracking over face rotations with piece-legality pruning."""
    corner_sets = {frozenset(fs): fs for fs in CORNER_FACES}
    edge_sets = {frozenset(fs) for fs in EDGE_FACES}
    order = sorted(FACES, key=lambda f: len(options[f]))
    results: list[str] = []
    placed: dict[str, Grid] = {}

    def pieces_ok() -> bool:
        st = _build(placed)
        fs = [face_of_colour.get(ch, UNKNOWN) for ch in st]
        seen_c, seen_e = set(), set()
        for sts in CORNER_STICKERS:
            faces = [fs[i] for i in sts]
            if UNKNOWN in faces:
                continue
            key = frozenset(faces)
            if key not in corner_sets or key in seen_c:
                return False
            k = next(i for i, f in enumerate(faces) if f in "UD")
            if tuple(faces[k:] + faces[:k]) != corner_sets[key]:
                return False
            seen_c.add(key)
        for sts in EDGE_STICKERS:
            faces = [fs[i] for i in sts]
            if UNKNOWN in faces:
                continue
            key = frozenset(faces)
            if key not in edge_sets or key in seen_e:
                return False
            seen_e.add(key)
        return True

    def rec(i):
        if len(results) > 4:
            return
        if i == len(order):
            st = _build(placed)
            if validate(st).ok:
                results.append(st)
            return
        f = order[i]
        tried = set()
        for k in options[f]:
            g = rotate(grids[f], k)
            key = str(g)
            if key in tried:      # symmetric face: rotations look identical
                continue
            tried.add(key)
            placed[f] = g
            if pieces_ok():
                rec(i + 1)
            del placed[f]

    rec(0)
    return results


# ---------------------------------------------------------------- simulation
def observation_of(state: str, face: str, k_image: int = 0, with_up: bool = False) -> dict:
    """Synthesize what a vision model would report for one face of `state`
    seen rotated k_image quarter-turns (useful for tests and the simulator)."""
    o = FACES.index(face) * 9
    g = [[state[o + r * 3 + c] for c in range(3)] for r in range(3)]
    # inverse rotate: image = canonical rotated counter-clockwise k times
    img = rotate(g, (4 - k_image) % 4)
    d = {"grid": img}
    if with_up:
        up_face = NEIGHBOURS[face][k_image % 4]
        d["up"] = state[FACES.index(up_face) * 9 + 4]
    return d

