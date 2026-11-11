"""Facelet-level Rubik's cube model, derived from 3D geometry.

Every sticker is identified by (cubie position, outward normal) in a coordinate
system where +x = R, +y = U, +z = F.  Move permutations are computed by actually
rotating those vectors, so nothing here depends on memorised move tables.

Facelet string layout (Kociemba order): 54 chars, faces U R F D L B, each face
read row by row as seen in the standard net:

              U0 U1 U2
              U3 U4 U5
              U6 U7 U8
    L0 L1 L2  F0 F1 F2  R0 R1 R2  B0 B1 B2
    L3 L4 L5  F3 F4 F5  R3 R4 R5  B3 B4 B5
    L6 L7 L8  F6 F7 F8  R6 R7 R8  B6 B7 B8
              D0 D1 D2
              D3 D4 D5
              D6 D7 D8

(U is drawn with B at the top, D with F at the top, side faces with U at the top.)
"""
from __future__ import annotations

import re
from functools import lru_cache

FACES = "URFDLB"
NORMALS: dict[str, tuple[int, int, int]] = {
    "U": (0, 1, 0),
    "R": (1, 0, 0),
    "F": (0, 0, 1),
    "D": (0, -1, 0),
    "L": (-1, 0, 0),
    "B": (0, 0, -1),
}
FACE_OF_NORMAL = {v: k for k, v in NORMALS.items()}
OPPOSITE = {"U": "D", "D": "U", "R": "L", "L": "R", "F": "B", "B": "F"}
SOLVED = "".join(f * 9 for f in FACES)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def rotate_cw(v, n):
    """Quarter turn of vector v, clockwise when looking at the face with normal n."""
    c = _cross(n, v)
    d = _dot(n, v)
    return (-c[0] + n[0] * d, -c[1] + n[1] * d, -c[2] + n[2] * d)


def _row_col(face: str, p) -> tuple[int, int]:
    x, y, z = p
    if face == "U":
        return z + 1, x + 1
    if face == "D":
        return 1 - z, x + 1
    if face == "F":
        return 1 - y, x + 1
    if face == "B":
        return 1 - y, 1 - x
    if face == "R":
        return 1 - y, 1 - z
    if face == "L":
        return 1 - y, z + 1
    raise ValueError(face)


def sticker_index(face: str, p) -> int:
    r, c = _row_col(face, p)
    return FACES.index(face) * 9 + r * 3 + c


# index -> (position, normal)
STICKERS: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = [None] * 54  # type: ignore
for _f, _n in NORMALS.items():
    for _a in (-1, 0, 1):
        for _b in (-1, 0, 1):
            # build every position on this face
            if _n[0]:
                _p = (_n[0], _a, _b)
            elif _n[1]:
                _p = (_a, _n[1], _b)
            else:
                _p = (_a, _b, _n[2])
            STICKERS[sticker_index(_f, _p)] = (_p, _n)
INDEX_OF = {s: i for i, s in enumerate(STICKERS)}


def face_of(index: int) -> str:
    return FACES[index // 9]


# --------------------------------------------------------------------------
# Move definitions
# --------------------------------------------------------------------------
# name -> (axis normal, layer predicate on p·n)
_LAYER_MOVES = {}
for _f in FACES:
    _LAYER_MOVES[_f] = (NORMALS[_f], lambda d: d == 1)
    _LAYER_MOVES[_f.lower()] = (NORMALS[_f], lambda d: d >= 0)  # wide move
    _LAYER_MOVES[_f + "w"] = _LAYER_MOVES[_f.lower()]
_LAYER_MOVES["M"] = (NORMALS["L"], lambda d: d == 0)
_LAYER_MOVES["E"] = (NORMALS["D"], lambda d: d == 0)
_LAYER_MOVES["S"] = (NORMALS["F"], lambda d: d == 0)
_LAYER_MOVES["x"] = (NORMALS["R"], lambda d: True)
_LAYER_MOVES["y"] = (NORMALS["U"], lambda d: True)
_LAYER_MOVES["z"] = (NORMALS["F"], lambda d: True)

ROTATIONS = {"x", "y", "z"}


def _quarter_perm(base: str) -> list[int]:
    """perm[i] = where sticker i goes after one clockwise quarter of `base`."""
    n, in_layer = _LAYER_MOVES[base]
    perm = list(range(54))
    for i, (p, nn) in enumerate(STICKERS):
        if in_layer(_dot(p, n)):
            perm[i] = INDEX_OF[(rotate_cw(p, n), rotate_cw(nn, n))]
    return perm


def _compose(*perms: list[int]) -> list[int]:
    """Perm that applies perms in order."""
    out = list(range(54))
    for perm in perms:
        out = [perm[j] for j in out]
    return out


_TOKEN_RE = re.compile(r"^([URFDLB]w?|[urfdlbMESxyz])(2|')?'?$")


@lru_cache(maxsize=None)
def move_perm(token: str) -> tuple[int, ...]:
    m = _TOKEN_RE.match(token)
    if not m:
        raise ValueError(f"Bad move token: {token!r}")
    base, suf = m.group(1), m.group(2)
    q = _quarter_perm(base)
    times = {None: 1, "2": 2, "'": 3}[suf]
    if token.endswith("2'"):
        times = 2
    return tuple(_compose(*([q] * times)))


@lru_cache(maxsize=None)
def move_src(token: str) -> tuple[int, ...]:
    """src[j] = which index's sticker ends up at j (for fast string application)."""
    perm = move_perm(token)
    src = [0] * 54
    for i, j in enumerate(perm):
        src[j] = i
    return tuple(src)


def parse(alg: str | list[str]) -> list[str]:
    """Split an algorithm string into tokens.  Accepts brackets/commas."""
    if isinstance(alg, list):
        return alg
    cleaned = re.sub(r"[()\[\],]", " ", alg).replace("’", "'")
    toks = cleaned.split()
    for t in toks:
        move_perm(t)  # validate
    return toks


def apply(state: str, alg: str | list[str]) -> str:
    for t in parse(alg):
        src = move_src(t)
        state = "".join([state[i] for i in src])
    return state


def invert_token(t: str) -> str:
    if t.endswith("2") or t.endswith("2'"):
        return t.rstrip("'")
    if t.endswith("'"):
        return t[:-1]
    return t + "'"


def invert(alg: str | list[str]) -> list[str]:
    return [invert_token(t) for t in reversed(parse(alg))]


# --------------------------------------------------------------------------
# Converting human algorithms (wide / slice / rotation moves) into pure face
# turns on a cube whose centres never move.
# --------------------------------------------------------------------------
_DECOMP = {
    "r": ["L", "x"], "l": ["R", "x'"], "u": ["D", "y"], "d": ["U", "y'"],
    "f": ["B", "z"], "b": ["F", "z'"],
    "M": ["R", "L'", "x'"], "E": ["U", "D'", "y'"], "S": ["F'", "B", "z"],
}


def _split(token: str) -> tuple[str, int]:
    m = _TOKEN_RE.match(token)
    base, suf = m.group(1), m.group(2)
    if base.endswith("w"):
        base = base[0].lower()
    times = {None: 1, "2": 2, "'": 3}[suf]
    return base, times


def _rotate_orientation(orient: dict[str, str], rot: str) -> dict[str, str]:
    """orient maps physical face position -> original face label sitting there."""
    n = NORMALS[{"x": "R", "y": "U", "z": "F"}[rot]]
    new = {}
    for pos, label in orient.items():
        dest = FACE_OF_NORMAL[rotate_cw(NORMALS[pos], n)]
        new[dest] = label
    return new


def to_face_turns(alg: str | list[str]) -> tuple[list[str], str]:
    """Return (equivalent face-turn sequence with fixed centres, net rotation).

    The net rotation is a whole-cube rotation string ('' if none) that the
    person holding the cube ends up with after doing the original algorithm.
    """
    orient = {f: f for f in FACES}
    out: list[str] = []
    for tok in parse(alg):
        base, times = _split(tok)
        for _ in range(times):
            parts = _DECOMP.get(base, [base])
            for p in parts:
                pb, pt = _split(p)
                for _ in range(pt):
                    if pb in ROTATIONS:
                        orient = _rotate_orientation(orient, pb)
                    else:
                        out.append(orient[pb])
    return simplify(out), _describe_rotation(orient)


def _describe_rotation(orient: dict[str, str]) -> str:
    if all(orient[f] == f for f in FACES):
        return ""
    # brute-force the shortest rotation sequence reproducing this orientation
    rots = ["x", "x2", "x'", "y", "y2", "y'", "z", "z2", "z'"]
    target = orient
    for a in rots:
        if _orient_after([a]) == target:
            return a
    for a in rots:
        for b in rots:
            if _orient_after([a, b]) == target:
                return f"{a} {b}"
    raise AssertionError("unreachable")


def _orient_after(rots: list[str]) -> dict[str, str]:
    orient = {f: f for f in FACES}
    for r in rots:
        base, times = _split(r)
        for _ in range(times):
            orient = _rotate_orientation(orient, base)
    return orient


def simplify(moves: list[str]) -> list[str]:
    """Merge consecutive turns of the same face (R R -> R2, R R' -> nothing)."""
    stack: list[tuple[str, int]] = []
    for m in moves:
        face, times = _split(m)
        # opposite faces commute, so R L R -> R2 L
        k = None
        if stack and stack[-1][0] == face:
            k = len(stack) - 1
        elif len(stack) >= 2 and stack[-1][0] == OPPOSITE[face] and stack[-2][0] == face:
            k = len(stack) - 2
        if k is None:
            stack.append((face, times))
            continue
        t = (stack[k][1] + times) % 4
        if t:
            stack[k] = (face, t)
        else:
            stack.pop(k)
    return [f + {1: "", 2: "2", 3: "'"}[t] for f, t in stack]


def rotation_to(state: str, up: str, front: str) -> str:
    """Whole-cube rotation (string) that brings centre colour `up` to U and `front` to F."""
    rots = ["", "x", "x2", "x'", "y", "y2", "y'", "z", "z2", "z'"]
    for a in rots:
        for b in ["", "y", "y2", "y'"]:
            seq = " ".join(t for t in (a, b) if t)
            s = apply(state, seq) if seq else state
            if s[4] == up and s[22] == front:
                return seq
    raise ValueError(f"Cannot put {up} on top with {front} in front (are they opposite?)")


def centers(state: str) -> dict[str, str]:
    """face -> centre colour"""
    return {f: state[i * 9 + 4] for i, f in enumerate(FACES)}


def to_face_letters(state: str) -> str:
    """Translate a colour facelet string into U/R/F/D/L/B letters via its centres."""
    c = {col: f for f, col in centers(state).items()}
    return "".join(c[ch] for ch in state)


def face_grid(state: str, face: str) -> list[list[str]]:
    o = FACES.index(face) * 9
    return [list(state[o + r * 3: o + r * 3 + 3]) for r in range(3)]


def net(state: str) -> str:
    """ASCII net for debugging."""
    g = {f: face_grid(state, f) for f in FACES}
    lines = []
    for r in range(3):
        lines.append("      " + " ".join(g["U"][r]))
    for r in range(3):
        lines.append(" ".join(g["L"][r]) + " " + " ".join(g["F"][r]) + " " + " ".join(g["R"][r]) + " " + " ".join(g["B"][r]))
    for r in range(3):
        lines.append("      " + " ".join(g["D"][r]))
    return "\n".join(lines)


FACE_TURNS = [f + s for f in FACES for s in ("", "2", "'")]
