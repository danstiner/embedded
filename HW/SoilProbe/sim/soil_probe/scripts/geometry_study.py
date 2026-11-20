#!/usr/bin/env python3
"""Electrode cross-section study at 70 MHz: outer-layer strips (mask only, or with a dipped coat)
vs strips buried on the inner layers of a 4-layer board, single blade vs slotted fork, board
width and strip spacing.  Ranks by contact error (air gap, water film), salinity error,
loss, sampling depth and fab-tolerance spread.  Writes ../results/geometry_study.{txt,csv}."""
import csv, itertools, os, sys
from multiprocessing import Pool
import numpy as np
import soil_probe_sim as s

F = 70e6
TH = np.round(np.arange(0.0, 0.61, 0.05), 2)
TH0 = 0.25
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'results')


def design(kind, W, g, fork=False):
    """kind: '2L' mask only, '2L+coat' 0.2 mm dip, '4L' buried on L2/L3."""
    edge = 1.0 if kind == '4L' else 0.5              # copper pull-back from the board edge
    w = (W - g) / 2 - edge
    st = [('S', -g / 2 - w, -g / 2), ('G', g / 2, g / 2 + w)]
    stack, ifc = (s.OSHPARK_4L, (1, 2)) if kind == '4L' else (s.OSHPARK_2L, (0, 1))
    kw = dict(stack=stack, strips={ifc[0]: st, ifc[1]: st}, W=W)
    if kind == '2L+coat': kw['coat'] = (0.2, s.COAT)
    if fork: kw['slots'] = [(-g / 2 + edge, g / 2 - edge)]
    return kw, w


def solve(kw, soil, **extra):
    k = dict(kw); k.update(extra)
    return s.solve(s.stack_scene(k.pop('stack'), k.pop('strips'), soil, **k), F)


def evaluate(args):
    kind, W, g, fork = args
    kw, w = design(kind, W, g, fork)
    if w < 1.5 or (fork and g < 4): return None
    C = np.array([solve(kw, s.soil_material(t))['C'] for t in TH])
    app = lambda r: 100 * (np.interp(r['C'], C, TH) - TH0)
    soil = s.soil_material(TH0)
    r0 = solve(kw, soil)
    hi = solve(kw, s.soil_material(0.45, 0.30))
    # depth from the faces holding 90 % of the air -> soil response
    Ca = solve(kw, soil, medium=s.AIR)['C']
    ds = np.array([0.5, 1, 2, 3, 5, 8, 12, 20])
    resp = np.array([(solve(kw, soil, half_space=(d, s.AIR))['C'] - Ca) / (r0['C'] - Ca) for d in ds])
    # fab tolerance: 2L mask 0.6 +/- 0.2 mil; 4L prepreg +/-10 %; dipped coat +/-50 %
    if kind == '4L':
        lo = dict(s.OSHPARK_4L, dielectrics=[(t * (0.9 if i != 1 else 1), m) for i, (t, m) in enumerate(s.OSHPARK_4L['dielectrics'])])
        tol = app(solve(dict(kw, stack=lo), soil))
    elif kind == '2L':
        tol = app(solve(dict(kw, stack=dict(s.OSHPARK_2L, t_mask=0.0102)), soil))
    else:
        tol = app(solve(dict(kw, coat=(0.1, s.COAT)), soil))
    return dict(kind=kind + (' fork' if fork else ''), W=W, gap=g, strip=round(w, 2),
                C_air=Ca * 1e12, C_dry=C[1] * 1e12, C_wet=np.interp(0.45, TH, C) * 1e12,
                ratio=np.interp(0.45, TH, C) / C[1], soil_pct=100 * r0['frac']['soil'],
                dth_per_pctC=1 / (100 * np.gradient(np.log(C), TH)[5]) * 100,
                gap01=app(solve(kw, soil, gap_top=0.1)), gap03=app(solve(kw, soil, gap_top=0.3)),
                film01=app(solve(kw, soil, gap_top=0.1, gap_mat=s.WATER)),
                ec6=app(solve(kw, s.soil_material(TH0, 0.30))),
                D_wet_hiEC=hi['G'] / (2 * np.pi * F * hi['C']),
                d90_mm=float(np.interp(0.9, resp, ds)), tol=tol)


if __name__ == '__main__':
    cases = [(k, W, g, False) for k in ('2L', '2L+coat', '4L') for W in (12, 16, 20, 25)
             for g in (1, 2, 3, 5, 7, 9, 12) if g < W - 5]
    cases += [('4L', W, g, True) for W in (16, 20, 25) for g in (5, 7, 9, 12) if g < W - 5]
    with Pool() as p:
        rows = [r for r in p.map(evaluate, cases) if r]
    os.makedirs(OUT, exist_ok=True)
    with open(f'{OUT}/geometry_study.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    hdr = (f"{'stack':13s} {'W':>3s} {'gap':>4s} {'strip':>5s} {'C_air':>6s} {'C_dry':>6s} {'C_wet':>6s} {'ratio':>5s} "
           f"{'soil%':>5s} {'gap.1':>6s} {'gap.3':>6s} {'film':>6s} {'ECx6':>6s} {'D':>5s} {'d90':>5s} {'fab':>6s}")
    lines = ['70 MHz, potting-mix CRIM model.  C in pF per m.  Errors in % VWC at true 25 %.', hdr]
    for r in rows:
        lines.append(f"{r['kind']:13s} {r['W']:3d} {r['gap']:4.0f} {r['strip']:5.1f} {r['C_air']:6.1f} {r['C_dry']:6.1f} "
                     f"{r['C_wet']:6.1f} {r['ratio']:5.2f} {r['soil_pct']:4.0f}% {r['gap01']:+6.1f} {r['gap03']:+6.1f} "
                     f"{r['film01']:+6.1f} {r['ec6']:+6.1f} {r['D_wet_hiEC']:5.2f} {r['d90_mm']:5.1f} {r['tol']:+6.1f}")
    open(f'{OUT}/geometry_study.txt', 'w').write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
