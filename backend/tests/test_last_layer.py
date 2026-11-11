import itertools

import pytest

from cubevision.cube import SOLVED, apply
from cubevision.pieces import from_cubies, validate
from cubevision.solver import last_layer as ll

F2L_STICKERS = [i for i in range(54) if not (i < 9 or (i % 9) < 3 and i // 9 in (1, 2, 4, 5))]


def f2l_intact(fs):
    return all(fs[i] == SOLVED[i] for i in F2L_STICKERS)


def _oriented_ll_states():
    for co in itertools.product(range(3), repeat=3):
        c4 = (-sum(co)) % 3
        for eo in itertools.product(range(2), repeat=3):
            e4 = sum(eo) % 2
            yield from_cubies(list(range(8)), list(co) + [c4, 0, 0, 0, 0],
                              list(range(12)), list(eo) + [e4] + [0] * 8)


def _parity(p):
    return sum(1 for i in range(len(p)) for j in range(i) if p[j] > p[i]) % 2


def _pll_states():
    for cp in itertools.permutations(range(4)):
        for ep in itertools.permutations(range(4)):
            if _parity(cp) != _parity(ep):
                continue
            yield from_cubies(list(cp) + [4, 5, 6, 7], [0] * 8, list(ep) + list(range(4, 12)), [0] * 12)


@pytest.mark.parametrize("alg", ll.OLL + ll.PLL + ll.EO_2LOOK + ll.CP_2LOOK, ids=lambda a: a.name)
def test_alg_preserves_f2l_and_has_no_net_rotation(alg):
    s = apply(SOLVED, list(ll.face_turns(alg.alg)))
    assert f2l_intact(s), alg.name


@pytest.mark.parametrize("alg", ll.PLL + ll.EP_2LOOK, ids=lambda a: a.name)
def test_pll_keeps_orientation(alg):
    assert ll.oll_done(apply(SOLVED, list(ll.face_turns(alg.alg))))


def test_every_oll_case_covered():
    n = 0
    for s in _oriented_ll_states():
        assert validate(s).ok
        step = ll.find(s, ll.OLL, ll.oll_done)
        if step:
            assert ll.oll_done(apply(apply(s, step.pre_auf), list(ll.face_turns(step.alg.alg))))
        n += 1
    assert n == 216


def test_each_oll_alg_is_used():
    used = set()
    for s in _oriented_ll_states():
        step = ll.find(s, ll.OLL, ll.oll_done)
        if step:
            used.add(step.alg.name)
    assert len(used) == 57, sorted({a.name for a in ll.OLL} - used)


def test_every_pll_case_covered():
    used = set()
    for s in _pll_states():
        step = ll.find(s, ll.PLL, lambda x: ll.solved_up_to_auf(x) is not None)
        if step:
            used.add(step.alg.name)
    assert len(used) == 21, sorted({a.name for a in ll.PLL} - used)


def test_two_look_covers_everything():
    for s in _oriented_ll_states():
        st = ll.find(s, ll.EO_2LOOK, ll.edges_oriented)
        if st:
            s = apply(apply(s, st.pre_auf), list(ll.face_turns(st.alg.alg)))
        st = ll.find(s, ll.CO_2LOOK, ll.oll_done)
        if st:
            s = apply(apply(s, st.pre_auf), list(ll.face_turns(st.alg.alg)))
        assert ll.oll_done(s)
    for s in _pll_states():
        st = ll.find(s, ll.CP_2LOOK, ll.corners_permuted)
        if st:
            s = apply(apply(s, st.pre_auf), list(ll.face_turns(st.alg.alg)))
        st = ll.find(s, ll.EP_2LOOK, lambda x: ll.solved_up_to_auf(x) is not None)
        if st:
            s = apply(apply(s, st.pre_auf), list(ll.face_turns(st.alg.alg)))
        assert ll.solved_up_to_auf(s) is not None
