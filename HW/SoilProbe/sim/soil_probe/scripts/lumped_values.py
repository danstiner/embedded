#!/usr/bin/env python3
"""Lumped probe values (C, G, D = G/wC, Rp) for real probe lengths, from the 2-D field solver.
Feeds spice/run_clapp.py (tank design) and DESIGN.md (FDC2212 tank).  Geometry: config C
(two 5 mm strips, 1 mm apart, mirrored on both faces of a 12 mm board), optional 0.3 mm coat."""
import numpy as np, soil_probe_sim as s

S5 = [('S', -5.5, -0.5), ('G', 0.5, 5.5)]
CASES = [(0.05, 0.05, 'dry'), (0.25, 0.05, 'moist lo-EC'), (0.25, 0.30, 'moist hi-EC'),
         (0.45, 0.05, 'sat lo-EC'), (0.45, 0.30, 'sat hi-EC')]

def table(f, L_mm, coat, C_par_pF=6.0):
    print(f'\n--- f = {f/1e6:.0f} MHz, probe {L_mm:.0f} mm, coat = {coat} mm, +{C_par_pF} pF parasitic ---')
    print(f"{'case':14s} {'C_pF':>6s} {'G_mS':>6s} {'D=G/wC':>7s} {'Rp_ohm':>7s}")
    out = {}
    for th, sw, name in CASES:
        kw = dict(coat=(coat, s.COAT)) if coat else {}
        r = s.solve(s.pcb_scene(S5, S5, s.soil_material(th, sw), W=12, **kw), f)
        C = r['C'] * L_mm * 1e-3 + C_par_pF * 1e-12
        G = r['G'] * L_mm * 1e-3
        D = G / (2 * np.pi * f * C)
        print(f'{name:14s} {C*1e12:6.1f} {G*1e3:6.2f} {D:7.2f} {1/G:7.0f}')
        out[name] = (C, G)
    return out

if __name__ == '__main__':
    for f, L, coat in [(10e6, 50, 0.3), (10e6, 50, 0.0), (60e6, 50, 0.0), (60e6, 80, 0.0), (60e6, 80, 0.3)]:
        table(f, L, coat)
