import random

import pytest

from cubevision.cube import FACE_TURNS, SOLVED, apply
from cubevision.pieces import validate
from cubevision.solver.cfop import DEFAULT_SCHEME, solve
from cubevision.solver.last_layer import solved

def colour(fs):
    return "".join(DEFAULT_SCHEME[c] for c in fs)


def scramble(seed, n=25):
    rng = random.Random(seed)
    return [rng.choice(FACE_TURNS) for _ in range(n)]


@pytest.mark.parametrize("level", ["full", "2look"])
@pytest.mark.parametrize("seed", range(15))
def test_random_scrambles_solve(seed, level):
    state = colour(apply(SOLVED, scramble(seed)))
    sol = solve(state, level=level)
    assert sol.ok, sol.errors
    s = sol.start_state
    for step in sol.steps:
        s = apply(s, step.moves)
    assert solved(s)
    phases = [st.phase for st in sol.steps]
    assert phases[0] == "cross" and phases.count("f2l") <= 4
    assert sol.total_moves < 90


def test_cross_colour_choice():
    state = colour(apply(SOLVED, scramble(99)))
    sol = solve(state, cross_color="Y")
    assert sol.ok
    assert sol.orientation["top"] == "W" and sol.orientation["bottom"] == "Y"


def test_solved_cube():
    sol = solve(colour(SOLVED))
    assert sol.ok and sol.total_moves == 0


def test_invalid_rejected():
    s = list(colour(apply(SOLVED, scramble(3))))
    # twist a corner: rotate the URF stickers (U9, R1, F3 = 8, 9, 20)
    s[8], s[9], s[20] = s[20], s[8], s[9]
    sol = solve("".join(s))
    assert not sol.ok and any("twisted" in e for e in sol.errors)


def test_validation_messages():
    s = list(colour(SOLVED))
    s[0], s[9 * 2 + 0] = s[9 * 2 + 0], s[0]  # swap two stickers between different pieces
    r = validate("".join(s))
    assert not r.ok and r.suspect_stickers
    r = validate(colour(SOLVED)[:-1] + "W")
    assert not r.ok and "appears 10 times" in " ".join(r.errors)
    # single edge flip
    s = list(colour(SOLVED)); s[7], s[19] = s[19], s[7]
    r = validate("".join(s)); assert not r.ok and "flipped" in r.errors[0]
    # swap two whole edges (UR <-> UF) -> parity
    s = list(colour(SOLVED)); s[5], s[7], s[10], s[19] = s[7], s[5], s[19], s[10]
    r = validate("".join(s)); assert not r.ok and "parity" in r.errors[0]
