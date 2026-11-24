#!/usr/bin/env python3
"""Small-signal mode analysis of the tank with the strip line attached.

The strips are a quarter wave long at 160-600 MHz depending on the medium, so the tank has a
second parallel resonance above the wanted one.  The cross-coupled pair has gain to GHz and
runs on whichever mode is less damped: with a plain capacitor and parallel resistor across
the tank it hops to ~230 MHz in water and in saturated low-salinity soil (seen in ngspice
with the distributed line).  Putting the damping resistor in series with the tank capacitor
(R3 + C4) makes its loss rise as f^2: a few mS in the working band, 25-100 mS at the
spurious modes, which are then at least twice as lossy as the wanted mode in every medium.

Prints every parallel resonance (f, G) per medium; --search scans snubber values."""
import itertools, sys
import numpy as np
import soil_probe_sim as s, probe as p, system_sim as S

L_TANK, C_STRAY, QL = 44.24e-9, 2.64e-12, 35.0      # fitted to the ngspice table: L, and C0 less the tank capacitor
G_PAIR = 30.0                                       # mS, small-signal negative conductance of the pair (gm/2)
F = np.linspace(40e6, 1000e6, 4801)
MEDIA = [('air', s.AIR), ('mix th 0.05', S.soil(0.05)), ('mix th 0.15', S.soil(0.15, 0.02)),
         ('mix th 0.30 lo-EC', S.soil(0.30, 0.02)), ('mix th 0.45 lo-EC', S.soil(0.45, 0.02)),
         ('mix th 0.60 lo-EC', S.soil(0.60, 0.02)), ('mix th 0.45 hi-EC', S.soil(0.45, 0.30)),
         ('mix th 0.60 hi-EC', S.soil(0.60, 0.30)), ('water, deionised', S.WATER_CAL),
         ('water, tap', (78.3, 0.05, 0)), ('sand saturated lo-EC', S.soil(0.42, 0.01, medium='mineral soil'))]
_yp = {}


def probe_Y(length):
    if length not in _yp:
        _yp[length] = {n: np.array([p.feed_Y(m, x, length_mm=length) for x in F]) for n, m in MEDIA}
    return _yp[length]


def tank_Y(Cpar, Rpar=None, snub=None):
    """Tank without the probe: inductors, parallel C (and R), series snubber (R, C)."""
    w = 2 * np.pi * F
    Rs = 2 * np.pi * 110e6 * L_TANK / QL * np.sqrt(F / 110e6)
    Y = 1 / (1j * w * L_TANK + Rs) + 1j * w * (C_STRAY + Cpar)
    if Rpar: Y = Y + 1 / Rpar
    if snub: Y = Y + 1 / (snub[0] + 1 / (1j * w * snub[1]))
    return Y


def modes(Cpar, Rpar=None, snub=None, length=80.0):
    """{medium: [(f MHz, G mS), ...]} for every parallel resonance, wanted mode first."""
    out = {}
    Yt = tank_Y(Cpar, Rpar, snub)
    for n, Yp in probe_Y(length).items():
        Y = Yt + Yp; B = Y.imag
        idx = np.where((B[:-1] < 0) & (B[1:] >= 0))[0]
        out[n] = [(F[i] / 1e6, Y.real[i] * 1e3) for i in idx]
    return out


def show(tag, m):
    print(tag)
    for n, lst in m.items():
        print(f'   {n:22s}', '  '.join(f'{a:4.0f} MHz {g:5.1f} mS' for a, g in lst))
    spur = min((g for lst in m.values() for _, g in lst[1:]), default=np.inf)
    ratio = min((min(g for _, g in lst[1:]) / lst[0][1] for lst in m.values() if len(lst) > 1), default=np.inf)
    print(f'   least-damped spurious mode {spur:.1f} mS (pair offers {G_PAIR:.0f} mS); worst spurious/wanted loss ratio {ratio:.2f}')


AS_BUILT = dict(Cpar=0.0, snub=(15.0, 33e-12))       # R3 + C4

if __name__ == '__main__':
    show('first iteration: 27 pF || 330 R across the tank', modes(27e-12, 330.0))
    show('as built: 33 pF in series with 15 R', modes(**AS_BUILT))
    for ell in (76.0, 84.0):
        m = modes(length=ell, **AS_BUILT)
        r = min(min(g for _, g in l[1:]) / l[0][1] for l in m.values() if len(l) > 1)
        print(f'   strips {ell:.0f} mm: worst spurious/wanted loss ratio {r:.2f}')
    if '--search' in sys.argv:
        rows = []
        for Rt, Ct, Cpar in itertools.product([6.8, 10, 12, 15, 22], [22e-12, 27e-12, 33e-12, 39e-12, 47e-12], [0, 4.7e-12, 10e-12]):
            m = modes(Cpar, None, (Rt, Ct))
            f1 = [l[0][0] for l in m.values()]; g1 = [l[0][1] for l in m.values()]
            ratio = min(min(g for _, g in l[1:]) / l[0][1] for l in m.values() if len(l) > 1)
            spur = min(g for l in m.values() for _, g in l[1:])
            rows.append((spur, ratio, Rt, Ct, Cpar, min(f1), max(f1), max(g1)))
        print('least spurious G mS | worst ratio | R  C pF  Cpar pF | wanted mode f | max wanted G')
        for b in sorted(rows, key=lambda b: -b[0])[:12]:
            print(f'  {b[0]:6.1f} | {b[1]:5.2f} | {b[2]:4.1f} {b[3]*1e12:3.0f} {b[4]*1e12:4.1f} | {b[5]:.0f}-{b[6]:.0f} MHz | {b[7]:.1f} mS')
