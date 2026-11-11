"""CFOP solver that produces step-by-step human teaching instructions."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..cube import OPPOSITE, apply, centers, parse, rotation_to, to_face_letters
from ..pieces import validate
from . import last_layer as ll
from .search import CROSS_EDGES, SLOTS, cross_solved, locate_corner, locate_edge, slot_solved, solve_cross, solve_f2l_pair
from .search import C_STK, E_STK, _corner_home, _edge_home

COLOR_NAMES = {"W": "white", "Y": "yellow", "R": "red", "O": "orange", "G": "green", "B": "blue"}
DEFAULT_SCHEME = {"U": "W", "F": "G", "R": "R", "D": "Y", "L": "O", "B": "B"}
SLOT_NAMES = {"FR": "front-right", "FL": "front-left", "BL": "back-left", "BR": "back-right"}
FACE_WORDS = {"U": "top", "D": "bottom", "F": "front", "B": "back", "R": "right", "L": "left"}

# Short spoken cue for each move (what the stickers on the front do)
MOVE_SPEECH = {
    "R": "right up", "R'": "right down", "L": "left down", "L'": "left up",
    "U": "top left", "U'": "top right", "D": "bottom right", "D'": "bottom left",
    "F": "front clockwise", "F'": "front counter-clockwise",
    "B": "back clockwise", "B'": "back counter-clockwise",
    "r": "right two layers up", "r'": "right two layers down",
    "l": "left two layers down", "l'": "left two layers up",
    "f": "front two layers clockwise", "f'": "front two layers counter-clockwise",
    "u": "top two layers left", "u'": "top two layers right",
    "d": "bottom two layers right", "d'": "bottom two layers left",
    "M": "middle down", "M'": "middle up", "E": "equator right", "E'": "equator left",
    "S": "standing slice clockwise", "S'": "standing slice counter-clockwise",
    "x": "tilt whole cube so the front goes to the top", "x'": "tilt whole cube so the top comes to the front",
    "y": "turn whole cube so the right side faces you", "y'": "turn whole cube so the left side faces you",
    "z": "roll whole cube to the right", "z'": "roll whole cube to the left",
}


_DOUBLE_ROT = {"x2": "flip whole cube upside down, front to back", "y2": "turn whole cube around so the back faces you",
               "z2": "flip whole cube upside down, side to side"}


def speak_move(tok: str) -> str:
    if tok in _DOUBLE_ROT:
        return _DOUBLE_ROT[tok]
    if tok.endswith("2"):
        base = tok[:-1]
        return MOVE_SPEECH.get(base, base).replace(" up", "").replace(" down", "").replace(" left", "").replace(
            " right", "").replace(" clockwise", "").replace(" counter-clockwise", "") + " twice"
    return MOVE_SPEECH.get(tok, tok)


@dataclass
class Step:
    phase: str                 # cross | f2l | oll | pll | auf
    title: str
    alg: str                   # human notation to show/say
    moves: list[str]           # equivalent fixed-centre face turns (for tracking)
    explanation: str
    say: str = ""              # short text for speech output
    case: str = ""
    learn_more: str = ""


@dataclass
class Solution:
    ok: bool
    errors: list[str] = field(default_factory=list)
    orientation: dict = field(default_factory=dict)
    start_state: str = ""      # colour facelets in the solving orientation
    steps: list[Step] = field(default_factory=list)

    @property
    def total_moves(self) -> int:
        return sum(len(s.moves) for s in self.steps)

    def to_dict(self):
        d = asdict(self)
        d["total_moves"] = self.total_moves
        return d


def _cn(c: str) -> str:
    return COLOR_NAMES.get(c, c)


def _piece_colours(colmap: dict[str, str], faces: str) -> str:
    return "-".join(_cn(colmap[f]) for f in faces)


def _where_corner(fs: str, name: str) -> str:
    idx = C_STK[locate_corner(fs, name)]
    return _where(idx, corner=True, home=C_STK[_corner_home(name)])


def _where_edge(fs: str, name: str) -> str:
    idx = E_STK[locate_edge(fs, name)]
    return _where(idx, corner=False, home=E_STK[_edge_home(name)])


def _where(idx: int, corner: bool, home: int) -> str:
    from ..pieces import CORNER_STICKERS, CORNER_NAMES, EDGE_STICKERS, EDGE_NAMES
    names, stickers = (CORNER_NAMES, CORNER_STICKERS) if corner else (EDGE_NAMES, EDGE_STICKERS)
    pos = next(n for n, st in zip(names, stickers) if idx in st)
    home_pos = next(n for n, st in zip(names, stickers) if home in st)
    if pos == home_pos:
        return ("already in its slot but " + ("twisted" if corner else "flipped")) if idx != home else "already solved"
    if "U" in pos:
        words = "-".join(FACE_WORDS[c] for c in pos if c != "U")
        return f"in the top layer at the {words}"
    side = "".join(c for c in pos if c != "D")
    slot = SLOT_NAMES.get(side) or SLOT_NAMES.get(side[::-1])
    if slot is None:  # a bottom edge
        return f"in the bottom layer at the {FACE_WORDS[side]}"
    return f"stuck in the {slot} slot"


def _speech(alg: str) -> str:
    return ", ".join(speak_move(t) for t in parse(alg))


def _auf_text(a: str) -> str:
    return {"": "", "U": "Turn the top layer once to the left (U). ",
            "U'": "Turn the top layer once to the right (U'). ",
            "U2": "Turn the top layer twice (U2). "}[a]


def solve(state: str, cross_color: str = "W", front_color: str | None = None,
          level: str = "full") -> Solution:
    """Solve a colour facelet string (any orientation, as scanned).

    level: "full" (full OLL/PLL) or "2look" (beginner 2-look OLL + 2-look PLL).
    """
    v = validate(state)
    if not v.ok:
        return Solution(ok=False, errors=v.errors)
    cen = centers(state)
    inv = {c: f for f, c in cen.items()}
    if cross_color not in inv:
        return Solution(ok=False, errors=[f"No centre has colour {cross_color}"])
    top_color = cen[OPPOSITE[inv[cross_color]]]
    if front_color is None or front_color in (cross_color, top_color):
        front_color = next(c for c in ("G", "R", "B", "O") + tuple(cen.values()) if c in inv and c not in (cross_color, top_color))
    rot = rotation_to(state, top_color, front_color)
    s = apply(state, rot) if rot else state
    colmap = centers(s)  # face letter -> colour in solving frame
    fs = to_face_letters(s)

    sol = Solution(ok=True, start_state=s)
    sol.orientation = {
        "top": top_color, "front": front_color, "bottom": cross_color,
        "right": colmap["R"], "rotation_from_scan": rot,
        "say": f"Hold the cube with {_cn(top_color)} on top and {_cn(front_color)} facing you.",
    }

    # ---------------- cross
    cross = solve_cross(fs)
    edges = ", ".join(_piece_colours(colmap, e) for e in CROSS_EDGES)
    alg = " ".join(cross)
    sol.steps.append(Step(
        phase="cross", title=f"{_cn(cross_color).capitalize()} cross", alg=alg, moves=list(cross),
        explanation=(f"Build a {_cn(cross_color)} cross on the bottom. Each {_cn(cross_color)} edge ({edges}) must "
                     f"line up with its side centre. Plan the whole cross before turning — this one takes "
                     f"{len(cross)} moves." if cross else "The cross is already solved!"),
        say=("Cross: " + _speech(alg)) if cross else "Cross is already done.",
        learn_more="Try to plan the cross during inspection; good solvers do it in 8 moves or fewer.",
    ))
    fs = apply(fs, cross)

    # ---------------- F2L
    solved_slots = [sl for sl in SLOTS if slot_solved(fs, sl)]
    remaining = [sl for sl in SLOTS if sl not in solved_slots]
    n = len(solved_slots)
    while remaining:
        slot, mv = solve_f2l_pair(fs, solved_slots, remaining)
        cn, en = SLOTS[slot]
        corner_desc = _where_corner(fs, cn)
        edge_desc = _where_edge(fs, en)
        n += 1
        pc, pe = _piece_colours(colmap, cn), _piece_colours(colmap, en)
        alg = " ".join(mv)
        tips = []
        if "stuck" in corner_desc or "stuck" in edge_desc:
            tips.append("First take the stuck piece out of its slot into the top layer.")
        if all(m[0] in "U" + slot for m in mv):
            tips.append(f"Only the top and the {SLOT_NAMES[slot]} slot's faces are needed.")
        sol.steps.append(Step(
            phase="f2l", title=f"F2L pair {n}: {SLOT_NAMES[slot]} slot",
            case=f"corner {corner_desc}; edge {edge_desc}",
            alg=alg, moves=list(mv),
            explanation=(f"Pair the {pc} corner (currently {corner_desc}) with the {pe} edge (currently "
                         f"{edge_desc}) and insert them together into the {SLOT_NAMES[slot]} slot. " + " ".join(tips)),
            say=f"Pair {n}, {SLOT_NAMES[slot]}: " + _speech(alg),
            learn_more="Intuitive F2L: join the corner and edge in the top layer, hide the pair, then insert.",
        ))
        fs = apply(fs, mv)
        solved_slots.append(slot)
        remaining.remove(slot)
    assert cross_solved(fs) and all(slot_solved(fs, sl) for sl in SLOTS)

    # ---------------- last layer
    top = _cn(colmap["U"])
    if level == "2look":
        stages = [
            ("oll", "Orient edges", ll.EO_2LOOK, ll.edges_oriented,
             f"Make a {top} cross on top (ignore corners)."),
            ("oll", "Orient corners", ll.CO_2LOOK, ll.oll_done, f"Make the whole top face {top}."),
            ("pll", "Permute corners", ll.CP_2LOOK, ll.corners_permuted,
             "Put the top corners in their places (look for 'headlights': two matching corners on one side, "
             "and hold them at the back)."),
            ("pll", "Permute edges", ll.EP_2LOOK, lambda x: ll.solved_up_to_auf(x) is not None,
             "Cycle the top edges into place."),
        ]
    else:
        stages = [
            ("oll", "OLL", ll.OLL, ll.oll_done, f"Orient the last layer so the whole top is {top}."),
            ("pll", "PLL", ll.PLL, lambda x: ll.solved_up_to_auf(x) is not None,
             "Permute the last layer — every piece into its final place."),
        ]
    for phase, title, algs, goal, why in stages:
        st = ll.find(fs, algs, goal)
        if st is None:
            sol.steps.append(Step(phase=phase, title=f"{title}: skip!", alg="", moves=[],
                                  explanation=f"{why} It's already done — a skip!", say=f"{title} skip!"))
            continue
        disp = (st.pre_auf + " " if st.pre_auf else "") + st.alg.alg
        mv = ([st.pre_auf] if st.pre_auf else []) + list(ll.face_turns(st.alg.alg))
        sol.steps.append(Step(
            phase=phase, title=f"{title}: {st.alg.label}", case=st.alg.label, alg=disp, moves=mv,
            explanation=f"{why} {_auf_text(st.pre_auf)}This is {st.alg.label}: {st.alg.alg}",
            say=f"{st.alg.label}. " + _speech(disp),
        ))
        fs = apply(fs, mv)

    auf = ll.solved_up_to_auf(fs)
    if auf:
        sol.steps.append(Step(phase="auf", title="Final turn", alg=auf, moves=[auf],
                              explanation=_auf_text(auf) + "Solved!", say=speak_move(auf) + ". Solved!"))
        fs = apply(fs, auf)
    assert ll.solved(fs)
    return sol
