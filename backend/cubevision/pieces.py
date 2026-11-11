"""Corner/edge definitions and full cube-state validation."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .cube import FACES, NORMALS, OPPOSITE, centers, sticker_index

CORNER_NAMES = ["URF", "UFL", "ULB", "UBR", "DFR", "DLF", "DBL", "DRB"]
EDGE_NAMES = ["UR", "UF", "UL", "UB", "DR", "DF", "DL", "DB", "FR", "FL", "BL", "BR"]


def _det(a, b, c):
    return (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0]))


def _pos(faces: str):
    return tuple(sum(NORMALS[f][k] for f in faces) for k in range(3))


def _corner_faces(name: str) -> tuple[str, str, str]:
    """Faces of a corner, starting with U/D, in clockwise order (seen from outside)."""
    a = name[0]
    b, c = name[1], name[2]
    if _det(NORMALS[a], NORMALS[b], NORMALS[c]) != -1:
        b, c = c, b
    return a, b, c


CORNER_FACES = [_corner_faces(n) for n in CORNER_NAMES]
CORNER_STICKERS = [tuple(sticker_index(f, _pos(n)) for f in fs) for n, fs in zip(CORNER_NAMES, CORNER_FACES)]
EDGE_FACES = [(n[0], n[1]) for n in EDGE_NAMES]
EDGE_STICKERS = [tuple(sticker_index(f, _pos(n)) for f in n) for n in EDGE_NAMES]

CORNER_STICKER_SET = sorted(i for t in CORNER_STICKERS for i in t)
EDGE_STICKER_SET = sorted(i for t in EDGE_STICKERS for i in t)

_CORNER_BY_SET = {frozenset(fs): k for k, fs in enumerate(CORNER_FACES)}
_EDGE_BY_SET = {frozenset(fs): k for k, fs in enumerate(EDGE_FACES)}


def position_name(index: int) -> str:
    """Human name of the piece slot a sticker belongs to, e.g. 'UFR corner, U sticker'."""
    for n, st in zip(CORNER_NAMES, CORNER_STICKERS):
        if index in st:
            return f"{n} corner ({FACES[index // 9]} side)"
    for n, st in zip(EDGE_NAMES, EDGE_STICKERS):
        if index in st:
            return f"{n} edge ({FACES[index // 9]} side)"
    return f"{FACES[index // 9]} centre"


@dataclass
class Cubies:
    cp: list[int]
    co: list[int]
    ep: list[int]
    eo: list[int]


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    # sticker indices implicated in errors (to highlight / re-scan)
    suspect_stickers: list[int] = field(default_factory=list)
    face_state: str | None = None  # URFDLB letters, only when colours map cleanly
    cubies: Cubies | None = None

    def to_dict(self):
        return {"ok": self.ok, "errors": self.errors, "suspect_stickers": sorted(set(self.suspect_stickers))}


def _parity(perm: list[int]) -> int:
    seen = [False] * len(perm)
    p = 0
    for i in range(len(perm)):
        if not seen[i]:
            j, n = i, 0
            while not seen[j]:
                seen[j] = True
                j = perm[j]
                n += 1
            p ^= (n - 1) & 1
    return p


def validate(state: str) -> ValidationResult:
    """Check a 54-char colour facelet string (any 6 colour symbols) for legality."""
    r = ValidationResult(ok=False)
    if len(state) != 54:
        r.errors.append(f"Expected 54 stickers, got {len(state)}.")
        return r
    unknown = [i for i, ch in enumerate(state) if ch in "?.-_ "]
    if unknown:
        r.errors.append(f"{len(unknown)} sticker(s) not yet seen.")
        r.suspect_stickers += unknown
        return r

    cen = centers(state)
    if len(set(cen.values())) != 6:
        r.errors.append(f"Centres must be 6 different colours, got {''.join(cen[f] for f in FACES)}.")
        return r
    counts = Counter(state)
    for col, n in sorted(counts.items()):
        if col not in cen.values():
            r.errors.append(f"Colour {col!r} appears {n}x but is not a centre colour.")
            r.suspect_stickers += [i for i, ch in enumerate(state) if ch == col]
        elif n != 9:
            r.errors.append(f"Colour {col} appears {n} times (should be 9).")
    if r.errors:
        return r

    col2face = {c: f for f, c in cen.items()}
    fs = "".join(col2face[ch] for ch in state)
    r.face_state = fs

    cp, co = [-1] * 8, [0] * 8
    for pos, st in enumerate(CORNER_STICKERS):
        faces = [fs[i] for i in st]
        key = frozenset(faces)
        if len(key) != 3 or key not in _CORNER_BY_SET:
            cols = "".join(state[i] for i in st)
            r.errors.append(f"Corner at {CORNER_NAMES[pos]} has colours {cols}, which no corner piece has.")
            r.suspect_stickers += list(st)
            continue
        piece = _CORNER_BY_SET[key]
        ori = next(k for k, f in enumerate(faces) if f in "UD")
        # rotate so the U/D sticker is first and compare cyclic order with the real piece
        rotated = faces[ori:] + faces[:ori]
        if tuple(rotated) != CORNER_FACES[piece]:
            r.errors.append(f"Corner at {CORNER_NAMES[pos]} is a mirror image of a real corner "
                            f"(two of its stickers were probably misread).")
            r.suspect_stickers += list(st)
            continue
        cp[pos], co[pos] = piece, ori

    ep, eo = [-1] * 12, [0] * 12
    for pos, st in enumerate(EDGE_STICKERS):
        faces = [fs[i] for i in st]
        key = frozenset(faces)
        if len(key) != 2 or key not in _EDGE_BY_SET:
            cols = "".join(state[i] for i in st)
            r.errors.append(f"Edge at {EDGE_NAMES[pos]} has colours {cols}, which no edge piece has.")
            r.suspect_stickers += list(st)
            continue
        piece = _EDGE_BY_SET[key]
        ep[pos] = piece
        eo[pos] = 0 if faces[0] == EDGE_FACES[piece][0] else 1

    if r.errors:
        return r

    for name, perm, names in (("corner", cp, CORNER_NAMES), ("edge", ep, EDGE_NAMES)):
        c = Counter(perm)
        for piece, n in c.items():
            if n > 1:
                r.errors.append(f"The {names[piece]} {name} piece appears {n} times.")
                stickers = CORNER_STICKERS if name == "corner" else EDGE_STICKERS
                r.suspect_stickers += [i for pos, p in enumerate(perm) if p == piece for i in stickers[pos]]
        missing = [names[k] for k in range(len(perm)) if k not in c]
        if missing:
            r.errors.append(f"Missing {name} piece(s): {', '.join(missing)}.")
    if r.errors:
        return r

    if sum(co) % 3:
        r.errors.append("One corner is twisted in place (corner twist sum is not 0 mod 3). "
                        "Either a corner sticker was misread or the cube was physically tampered with.")
    if sum(eo) % 2:
        r.errors.append("One edge is flipped in place (edge flip parity is odd). "
                        "Either an edge sticker was misread or the cube was reassembled wrongly.")
    if _parity(cp) != _parity(ep):
        r.errors.append("Permutation parity mismatch: two pieces appear swapped. "
                        "Usually two stickers were misread (or the cube was reassembled).")
    if r.errors:
        return r

    r.ok = True
    r.cubies = Cubies(cp, co, ep, eo)
    return r


def check_color_scheme(state: str, scheme: dict[str, str]) -> list[str]:
    """Warn if centres disagree with the expected colour scheme's opposite pairs."""
    cen = centers(state)
    inv = {c: f for f, c in scheme.items()}
    errs = []
    for f in FACES:
        a, b = cen[f], cen[OPPOSITE[f]]
        if a in inv and b in inv and OPPOSITE[inv[a]] != inv[b]:
            errs.append(f"{a} and {b} are on opposite faces, but in your colour scheme they're adjacent.")
    return errs


def from_cubies(cp: list[int], co: list[int], ep: list[int], eo: list[int]) -> str:
    """Build a URFDLB facelet string from cubie permutation/orientation arrays."""
    fs = ["?"] * 54
    for i, f in enumerate(FACES):
        fs[i * 9 + 4] = f
    for pos in range(8):
        piece, ori = cp[pos], co[pos]
        for k in range(3):
            fs[CORNER_STICKERS[pos][(k + ori) % 3]] = CORNER_FACES[piece][k]
    for pos in range(12):
        piece, ori = ep[pos], eo[pos]
        for k in range(2):
            fs[EDGE_STICKERS[pos][(k + ori) % 2]] = EDGE_FACES[piece][k]
    return "".join(fs)
