"""OLL / PLL algorithm tables and case recognition.

Algorithms are written in normal human notation (wide moves, slices and
rotations allowed).  They are converted to fixed-centre face turns for state
tracking, and every table entry is verified by the test-suite against every
possible last-layer case.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from ..cube import apply, to_face_turns

AUFS = ["", "U", "U2", "U'"]


@dataclass(frozen=True)
class Alg:
    name: str
    alg: str            # what we show / say to the human
    nickname: str = ""

    @property
    def label(self) -> str:
        return f"{self.name} ({self.nickname})" if self.nickname else self.name


OLL = [
    Alg("OLL 1", "R U2 R2 F R F' U2 R' F R F'", "dot"),
    Alg("OLL 2", "F R U R' U' F' f R U R' U' f'", "dot"),
    Alg("OLL 3", "f R U R' U' f' U' F R U R' U' F'", "dot"),
    Alg("OLL 4", "f R U R' U' f' U F R U R' U' F'", "dot"),
    Alg("OLL 5", "r' U2 R U R' U r", "small square"),
    Alg("OLL 6", "r U2 R' U' R U' r'", "small square"),
    Alg("OLL 7", "r U R' U R U2 r'", "small lightning"),
    Alg("OLL 8", "l' U' L U' L' U2 l", "small lightning"),
    Alg("OLL 9", "R U R' U' R' F R2 U R' U' F'", "fish"),
    Alg("OLL 10", "R U R' U R' F R F' R U2 R'", "fish"),
    Alg("OLL 11", "r U R' U R' F R F' R U2 r'", "small lightning"),
    Alg("OLL 12", "M' R' U' R U' R' U2 R U' R r'", "small lightning"),
    Alg("OLL 13", "F U R U' R2 F' R U R U' R'", "knight"),
    Alg("OLL 14", "R' F R U R' F' R F U' F'", "knight"),
    Alg("OLL 15", "r' U' r R' U' R U r' U r", "knight"),
    Alg("OLL 16", "r U r' R U R' U' r U' r'", "knight"),
    Alg("OLL 17", "R U R' U R' F R F' U2 R' F R F'", "dot"),
    Alg("OLL 18", "r U R' U R U2 r2 U' R U' R' U2 r", "dot"),
    Alg("OLL 19", "M U R U R' U' M' R' F R F'", "dot"),
    Alg("OLL 20", "r U R' U' M2 U R U' R' U' M'", "dot"),
    Alg("OLL 21", "R U2 R' U' R U R' U' R U' R'", "H / double headlights"),
    Alg("OLL 22", "R U2 R2 U' R2 U' R2 U2 R", "Pi / bruno"),
    Alg("OLL 23", "R2 D' R U2 R' D R U2 R", "headlights"),
    Alg("OLL 24", "r U R' U' r' F R F'", "chameleon"),
    Alg("OLL 25", "F' r U R' U' r' F R", "bowtie"),
    Alg("OLL 26", "R U2 R' U' R U' R'", "anti-Sune"),
    Alg("OLL 27", "R U R' U R U2 R'", "Sune"),
    Alg("OLL 28", "r U R' U' M U R U' R'", "arrow"),
    Alg("OLL 29", "R U R' U' R U' R' F' U' F R U R'", "awkward"),
    Alg("OLL 30", "F R' F R2 U' R' U' R U R' F2", "awkward"),
    Alg("OLL 31", "R' U' F U R U' R' F' R", "P shape"),
    Alg("OLL 32", "L U F' U' L' U L F L'", "P shape"),
    Alg("OLL 33", "R U R' U' R' F R F'", "T shape"),
    Alg("OLL 34", "R U R2 U' R' F R U R U' F'", "C shape"),
    Alg("OLL 35", "R U2 R2 F R F' R U2 R'", "fish"),
    Alg("OLL 36", "L' U' L U' L' U L U L F' L' F", "W shape"),
    Alg("OLL 37", "F R' F' R U R U' R'", "fish"),
    Alg("OLL 38", "R U R' U R U' R' U' R' F R F'", "W shape"),
    Alg("OLL 39", "L F' L' U' L U F U' L'", "big lightning"),
    Alg("OLL 40", "R' F R U R' U' F' U R", "big lightning"),
    Alg("OLL 41", "R U R' U R U2 R' F R U R' U' F'", "awkward"),
    Alg("OLL 42", "R' U' R U' R' U2 R F R U R' U' F'", "awkward"),
    Alg("OLL 43", "F' U' L' U L F", "P shape"),
    Alg("OLL 44", "F U R U' R' F'", "P shape"),
    Alg("OLL 45", "F R U R' U' F'", "T shape"),
    Alg("OLL 46", "R' U' R' F R F' U R", "C shape"),
    Alg("OLL 47", "R' U' R' F R F' R' F R F' U R", "small L"),
    Alg("OLL 48", "F R U R' U' R U R' U' F'", "small L"),
    Alg("OLL 49", "r U' r2 U r2 U r2 U' r", "small L"),
    Alg("OLL 50", "r' U r2 U' r2 U' r2 U r'", "small L"),
    Alg("OLL 51", "F U R U' R' U R U' R' F'", "line"),
    Alg("OLL 52", "R U R' U R U' B U' B' R'", "line"),
    Alg("OLL 53", "l' U2 L U L' U' L U L' U l", "small L"),
    Alg("OLL 54", "r U2 R' U' R U R' U' R U' r'", "small L"),
    Alg("OLL 55", "R' F R U R U' R2 F' R2 U' R' U R U R'", "line"),
    Alg("OLL 56", "r' U' r U' R' U R U' R' U R r' U r", "line"),
    Alg("OLL 57", "R U R' U' M' U R U' r'", "H / mummy"),
]

PLL = [
    Alg("Ua perm", "R U' R U R U R U' R' U' R2"),
    Alg("Ub perm", "R2 U R U R' U' R' U' R' U R'"),
    Alg("H perm", "M2 U M2 U2 M2 U M2"),
    Alg("Z perm", "M' U M2 U M2 U M' U2 M2"),
    Alg("Aa perm", "x R' U R' D2 R U' R' D2 R2 x'"),
    Alg("Ab perm", "x R2 D2 R U R' D2 R U' R x'"),
    Alg("E perm", "x' R U' R' D R U R' D' R U R' D R U' R' D' x"),
    Alg("T perm", "R U R' U' R' F R2 U' R' U' R U R' F'"),
    Alg("F perm", "R' U' F' R U R' U' R' F R2 U' R' U' R U R' U R"),
    Alg("Ja perm", "R' U L' U2 R U' R' U2 R L"),
    Alg("Jb perm", "R U R' F' R U R' U' R' F R2 U' R'"),
    Alg("Ra perm", "R U' R' U' R U R D R' U' R D' R' U2 R'"),
    Alg("Rb perm", "R2 F R U R U' R' F' R U2 R' U2 R"),
    Alg("V perm", "R' U R' U' y R' F' R2 U' R' U R' F R F y'"),
    Alg("Y perm", "F R U' R' U' R U R' F' R U R' U' R' F R F'"),
    Alg("Na perm", "R U R' U R U R' F' R U R' U' R' F R2 U' R' U2 R U' R'"),
    Alg("Nb perm", "R' U R U' R' F' U' F R U R' F R' F' R U' R"),
    Alg("Ga perm", "R2 U R' U R' U' R U' R2 U' D R' U R D'"),
    Alg("Gb perm", "R' U' R U D' R2 U R' U R U' R U' R2 D"),
    Alg("Gc perm", "R2 U' R U' R U R' U R2 U D' R U' R' D"),
    Alg("Gd perm", "R U R' U' D R2 U' R U' R' U R' U R2 D'"),
]

# Beginner-friendly "2-look" subsets
EO_2LOOK = [
    Alg("Edge OLL: line", "F R U R' U' F'"),
    Alg("Edge OLL: L shape", "f R U R' U' f'"),
    Alg("Edge OLL: dot", "F R U R' U' F' f R U R' U' f'"),
]
CO_2LOOK = [a for a in OLL if a.name in {"OLL 21", "OLL 22", "OLL 23", "OLL 24", "OLL 25", "OLL 26", "OLL 27"}]
CP_2LOOK = [Alg("Corner PLL: headlights (T perm)", PLL[7].alg), Alg("Corner PLL: diagonal (Y perm)", PLL[14].alg)]
EP_2LOOK = [a for a in PLL if a.name in {"Ua perm", "Ub perm", "H perm", "Z perm"}]


@lru_cache(maxsize=None)
def face_turns(alg: str) -> tuple[str, ...]:
    moves, rot = to_face_turns(alg)
    if rot:
        raise ValueError(f"Algorithm {alg!r} leaves the cube rotated by {rot}")
    return tuple(moves)


# ---------------------------------------------------------------- predicates
def _top_ring(fs: str) -> str:
    # top rows of F, R, B, L
    return fs[18:21] + fs[9:12] + fs[45:48] + fs[36:39]


def oll_done(fs: str) -> bool:
    return fs[0:9] == "U" * 9


def edges_oriented(fs: str) -> bool:
    return all(fs[i] == "U" for i in (1, 3, 5, 7))


def solved(fs: str) -> bool:
    return all(fs[i * 9:(i + 1) * 9] == fs[i * 9 + 4] * 9 for i in range(6))


def solved_up_to_auf(fs: str) -> str | None:
    for a in AUFS:
        if solved(apply(fs, a) if a else fs):
            return a
    return None


def corners_permuted(fs: str) -> bool:
    """Every side's top-layer corners match each other (up to AUF)."""
    ring = _top_ring(fs)
    return all(ring[k * 3] == ring[k * 3 + 2] for k in range(4))


@dataclass
class LLStep:
    alg: Alg
    pre_auf: str


def find(fs: str, algs: list[Alg], goal) -> LLStep | None:
    """Try every alg with every pre-AUF; return the shortest one reaching `goal`."""
    if goal(fs):
        return None
    best = None
    for a in AUFS:
        s0 = apply(fs, a) if a else fs
        for alg in algs:
            mv = face_turns(alg.alg)
            if goal(apply(s0, list(mv))):
                cost = len(mv) + (1 if a else 0)
                if best is None or cost < best[0]:
                    best = (cost, LLStep(alg, a))
    if best is None:
        raise LookupError("no algorithm matches this last-layer case")
    return best[1]
