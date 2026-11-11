"""Cross and F2L search.

Pieces are tracked by the facelet index of one reference sticker, which encodes
both position and orientation (24 possibilities per edge/corner).  All tables
are derived from the geometric move permutations in cube.py.

The cube is assumed oriented with the cross on D (solving frame, face letters).
"""
from __future__ import annotations

import os
import pickle
from functools import lru_cache
from pathlib import Path

from ..cube import FACE_TURNS, OPPOSITE, move_perm
from ..pieces import CORNER_STICKER_SET, CORNER_STICKERS, CORNER_NAMES, EDGE_STICKER_SET, EDGE_STICKERS, EDGE_NAMES

E_IDX = {s: i for i, s in enumerate(EDGE_STICKER_SET)}
C_IDX = {s: i for i, s in enumerate(CORNER_STICKER_SET)}
E_STK = EDGE_STICKER_SET
C_STK = CORNER_STICKER_SET

ALL_MOVES = FACE_TURNS  # 18
F2L_MOVES = [m for m in FACE_TURNS if m[0] != "D"]  # humans don't turn D during F2L

EMOVE = {m: [E_IDX[move_perm(m)[s]] for s in E_STK] for m in FACE_TURNS}
CMOVE = {m: [C_IDX[move_perm(m)[s]] for s in C_STK] for m in FACE_TURNS}

CROSS_EDGES = ["DF", "DR", "DB", "DL"]
# F2L slot -> (corner name, edge name)
SLOTS = {"FR": ("DFR", "FR"), "FL": ("DLF", "FL"), "BL": ("DBL", "BL"), "BR": ("DRB", "BR")}
SLOT_FACES = {"FR": "FR", "FL": "FL", "BL": "BL", "BR": "BR"}


def _edge_home(name: str) -> int:
    return E_IDX[EDGE_STICKERS[EDGE_NAMES.index(name)][0]]


def _corner_home(name: str) -> int:
    return C_IDX[CORNER_STICKERS[CORNER_NAMES.index(name)][0]]


def locate_edge(fs: str, name: str) -> int:
    """Where (encoded) the reference sticker of edge `name` currently is."""
    ref, other = name[0], name[1]
    for st in EDGE_STICKERS:
        a, b = fs[st[0]], fs[st[1]]
        if {a, b} == {ref, other}:
            return E_IDX[st[0] if a == ref else st[1]]
    raise ValueError(f"edge {name} not found")


def locate_corner(fs: str, name: str) -> int:
    ref = name[0]
    want = set(name)
    for st in CORNER_STICKERS:
        cols = [fs[i] for i in st]
        if set(cols) == want:
            return C_IDX[st[cols.index(ref)]]
    raise ValueError(f"corner {name} not found")


# --------------------------------------------------------------------------
# Pruning tables (cached on disk; the cross table takes a few seconds to build)
# --------------------------------------------------------------------------
_CACHE = Path(os.environ.get("CUBEVISION_CACHE", Path.home() / ".cache" / "cubevision"))


def _bfs(start_states, encode, decode, size, moves, step):
    table = bytearray([255]) * size
    frontier = []
    for s in start_states:
        table[encode(s)] = 0
        frontier.append(s)
    d = 0
    while frontier:
        d += 1
        nxt = []
        for s in frontier:
            for m in moves:
                t = step(s, m)
                k = encode(t)
                if table[k] == 255:
                    table[k] = d
                    nxt.append(t)
        frontier = nxt
    return table


def _cross_encode(s):
    return ((s[0] * 24 + s[1]) * 24 + s[2]) * 24 + s[3]


@lru_cache(maxsize=None)
def cross_table() -> bytes:
    path = _CACHE / "cross_v1.bin"
    if path.exists():
        return path.read_bytes()
    home = tuple(_edge_home(n) for n in CROSS_EDGES)
    t = _bfs([home], _cross_encode, None, 24 ** 4, ALL_MOVES,
             lambda s, m: (EMOVE[m][s[0]], EMOVE[m][s[1]], EMOVE[m][s[2]], EMOVE[m][s[3]]))
    _CACHE.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(t))
    return bytes(t)


@lru_cache(maxsize=None)
def pair_table(slot: str) -> bytes:
    cn, en = SLOTS[slot]
    home = (_corner_home(cn), _edge_home(en))
    return bytes(_bfs([home], lambda s: s[0] * 24 + s[1], None, 576, F2L_MOVES,
                      lambda s, m: (CMOVE[m][s[0]], EMOVE[m][s[1]])))


@lru_cache(maxsize=None)
def edge_pair_table(e1: str, e2: str) -> bytes:
    """Distance to solve two edges simultaneously (used to strengthen the F2L heuristic)."""
    home = (_edge_home(e1), _edge_home(e2))
    return bytes(_bfs([home], lambda s: s[0] * 24 + s[1], None, 576, F2L_MOVES,
                      lambda s, m: (EMOVE[m][s[0]], EMOVE[m][s[1]])))


# --------------------------------------------------------------------------
# Search helpers
# --------------------------------------------------------------------------
_FACE_ORDER = {f: i for i, f in enumerate("URFDLB")}


def _allowed(face: str, last: str | None) -> bool:
    if last is None:
        return True
    if face == last:
        return False
    # for commuting opposite faces only allow one order
    if OPPOSITE[face] == last and _FACE_ORDER[face] < _FACE_ORDER[last]:
        return False
    return True


def solve_cross(fs: str) -> list[str]:
    """Optimal cross on D (greedy descent on the exact distance table)."""
    table = cross_table()
    s = tuple(locate_edge(fs, n) for n in CROSS_EDGES)
    path: list[str] = []
    d = table[_cross_encode(s)]
    last = None
    while d:
        for m in ALL_MOVES:
            if not _allowed(m[0], last):
                continue
            t = tuple(EMOVE[m][x] for x in s)
            if table[_cross_encode(t)] == d - 1:
                s, d, last = t, d - 1, m[0]
                path.append(m)
                break
        else:  # pragma: no cover
            raise RuntimeError("cross table inconsistent")
    return path


def solve_f2l_pair(fs: str, solved_slots: list[str], candidate_slots: list[str],
                   max_depth: int = 14) -> tuple[str, list[str]]:
    """Find the shortest sequence that solves ONE of `candidate_slots`, keeping the
    cross and `solved_slots` intact.  Returns (slot, moves).

    At each depth it first tries "human" move sets (U plus the slot's two faces),
    then falls back to any non-D face turn.
    """
    ctab = cross_table()
    cross = tuple(locate_edge(fs, n) for n in CROSS_EDGES)
    kept = [(pair_table(sl), locate_corner(fs, SLOTS[sl][0]), locate_edge(fs, SLOTS[sl][1])) for sl in solved_slots]

    # cross edge pairs adjacent to each slot -> extra heuristic
    def slot_cross_edges(slot):
        return ["D" + slot[0], "D" + slot[1]]

    for depth in range(0, max_depth + 1):
        for restricted in (True, False):
            for slot in candidate_slots:
                cn, en = SLOTS[slot]
                target = (pair_table(slot), locate_corner(fs, cn), locate_edge(fs, en))
                pairs = kept + [target]
                ce = slot_cross_edges(slot)
                ept = edge_pair_table(ce[0], ce[1])
                ce_idx = (CROSS_EDGES.index(ce[0]), CROSS_EDGES.index(ce[1]))
                moves = [m for m in F2L_MOVES if (m[0] in "U" + slot)] if restricted else F2L_MOVES
                res = _ida(cross, pairs, ctab, ept, ce_idx, moves, depth)
                if res is not None:
                    return slot, res
    raise RuntimeError("F2L search failed")


def _ida(cross, pairs, ctab, ept, ce_idx, moves, depth):
    tabs = [p[0] for p in pairs]
    cs = [p[1] for p in pairs]
    es = [p[2] for p in pairs]
    path: list[str] = []
    a, b = ce_idx

    def h(cr, cs, es):
        v = ctab[_cross_encode(cr)]
        w = ept[cr[a] * 24 + cr[b]]
        if w > v:
            v = w
        for t, c, e in zip(tabs, cs, es):
            w = t[c * 24 + e]
            if w > v:
                v = w
        return v

    def dfs(cr, cs, es, g, last):
        hv = h(cr, cs, es)
        if hv == 0:
            return True
        if g + hv > depth:
            return False
        for m in moves:
            f = m[0]
            if not _allowed(f, last):
                continue
            em, cm = EMOVE[m], CMOVE[m]
            path.append(m)
            if dfs((em[cr[0]], em[cr[1]], em[cr[2]], em[cr[3]]),
                   [cm[c] for c in cs], [em[e] for e in es], g + 1, f):
                return True
            path.pop()
        return False

    if h(tuple(cross), cs, es) > depth:
        return None
    # require exact depth so we iterate shortest-first
    found = dfs(tuple(cross), cs, es, 0, None)
    return list(path) if found else None


def slot_solved(fs: str, slot: str) -> bool:
    cn, en = SLOTS[slot]
    return locate_corner(fs, cn) == _corner_home(cn) and locate_edge(fs, en) == _edge_home(en)


def cross_solved(fs: str) -> bool:
    return all(locate_edge(fs, n) == _edge_home(n) for n in CROSS_EDGES)
