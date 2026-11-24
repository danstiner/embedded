"""Model checks: field solver against closed forms, builder regression, line-model limits,
and the end-to-end round trip.  Run: pytest scripts/  (table-dependent tests skip until
probe.py and spice/characterize.py have been run)."""
import os
import numpy as np
import pytest
from scipy.special import ellipk
import soil_probe_sim as s
import probe as p

HAVE_PROBE = os.path.exists(f'{p.RESULTS}/probe_table_nominal.npz')
HAVE_OSC = os.path.exists(f'{p.RESULTS}/osc_table_nominal.npz')


def test_two_wire_line():
    er, sig = 10.0, 0.05
    r = s.solve(s.nail_scene((er, sig, 0), r=1.75, spacing=20.0, L=120.0, dmin=0.02, dmax=2.0), 1e6)
    k = np.pi / np.arccosh(20.0 / 3.5)
    assert r['C'] == pytest.approx(s.EPS0 * er * k, rel=0.01)
    assert r['G'] == pytest.approx(sig * k, rel=0.01)


def test_coplanar_strips_conformal_map():
    """Thin coplanar strips in a uniform medium: C' = eps K(k') / K(k), k = g / (g + 2 w)."""
    w, g, er = 5.5, 7.0, 4.0
    uni = dict(dielectrics=[(0.2, (er, 0, 0)), (1.0, (er, 0, 0))], cu=[0.005, 0.005, 0.005], t_mask=0.0)
    st = [('S', -g / 2 - w, -g / 2), ('G', g / 2, g / 2 + w)]
    C = s.solve(s.stack_scene(uni, {1: st}, (er, 0, 0), W=20.0, Lx=150, Ly=150, dmax=4.0), 1e6)['C']
    k = g / (g + 2 * w)
    assert C == pytest.approx(s.EPS0 * er * ellipk(1 - k**2) / ellipk(k**2), rel=0.03)


def test_mask_insulates_outer_copper_edges():
    # in a conductor at low frequency, masked strips are a capacitor (the mask), not a resistor
    st = [('S', -3.0, -1.0), ('G', 1.0, 3.0)]
    y = s.solve(s.stack_scene(s.OSHPARK_2L, {1: st}, (80.0, 1.0, 0.0), W=9), 1e3)['Y']
    assert y.real < 0.05 * y.imag
    c_mask = s.EPS0 * s.MASK[0] * 2.0 / 0.0152 / 2          # two 2 mm plates in series, F/m
    assert y.imag / (2 * 3.141592653589793 * 1e3) == pytest.approx(c_mask, rel=0.15)


def test_mesh_convergence_and_energy_partition():
    soil = s.soil_material(0.25)
    a = s.solve(p.scene(soil), 100e6)
    b = s.solve(p.scene(soil, dmin=0.0025, dmax=1.0, growth=1.2), 100e6)
    assert b['C'] == pytest.approx(a['C'], rel=0.005)
    assert sum(a['frac'].values()) == pytest.approx(1.0, abs=1e-6)


def test_capacitance_rises_with_water_and_falls_with_air_gap():
    C = [s.solve(p.scene(s.soil_material(t)), 100e6)['C'] for t in (0.05, 0.25, 0.45)]
    assert C[0] < C[1] < C[2]
    assert s.solve(p.scene(s.soil_material(0.25), gap_top=0.1), 100e6)['C'] < C[1]


@pytest.mark.skipif(not HAVE_PROBE, reason='run scripts/probe.py first')
def test_table_and_line_limits():
    t = p.table()
    for eps in (complex(3, -0.2), complex(20, -8), complex(60, -40)):
        assert complex(np.ravel(t.cstar(eps.real, -eps.imag))[0]) == pytest.approx(p.cstar_direct(eps), rel=0.003)
    # electrically short line -> C' * length; open quarter wave -> short circuit
    f, cs = 1e6, complex(np.ravel(t.cstar(10.0, 0.0))[0])
    Y = p.line_Y([cs], [80.0], f)
    assert Y.imag / (2 * np.pi * f) == pytest.approx(cs.real * 0.08, rel=1e-3)
    fq = 1 / (4 * 0.08 * np.sqrt(p.Lpul() * cs.real))
    assert abs(p.line_Y([cs], [80.0], fq)) > 100 * abs(p.line_Y([cs], [80.0], fq / 4))


@pytest.mark.skipif(not (HAVE_PROBE and HAVE_OSC), reason='run probe.py and spice/characterize.py first')
def test_round_trip_and_salinity_rejection():
    import system_sim as S
    S.OSC = S.Oscillator()
    fw = S.Firmware()
    fs = [S.measure(S.soil(t))[0] for t in (0.05, 0.2, 0.4, 0.55)]
    assert all(a > b for a, b in zip(fs, fs[1:]))                      # monotonic transfer curve
    for th in (0.10, 0.30, 0.50):
        f, det = S.measure(S.soil(th, 0.30))
        est, ec = fw.theta(f, det, 25.0)
        assert est == pytest.approx(th, abs=0.005)
        assert ec == pytest.approx(S.soil(th, 0.30)[1], rel=0.05, abs=5e-4)
    # a unit with different L and strays reads the same after its own two-point calibration
    unit = dict(dL=0.02, dC0=2e-12)
    f, det = S.measure(S.soil(0.30), unit)
    assert S.Firmware(unit).theta(f, det, 25.0, use_det=False)[0] == pytest.approx(fw.theta(*S.measure(S.soil(0.30)), 25.0, use_det=False)[0], abs=0.003)
