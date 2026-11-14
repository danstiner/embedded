#!/usr/bin/env python3
"""Analyse data/measurements.csv from TEST_PLAN.md.
  python analyze_calibration.py [--correct]     (--correct applies the bulk-EC correction)
Reports per soil: cubic fit theta(C), RMS residual, re-insertion scatter, salinity and temperature slopes."""
import sys, numpy as np, pandas as pd

L_H, C1, CPAR = 470e-9, 22e-12, 6e-12      # Clapp tank; edit if changed
S_SIGMA = lambda th: 0.4 * th              # dlnC/dln(sigma) at 8-10 MHz, bare geometry (DESIGN.md §1); refit from data

def f_to_C(f, fscale=0.9):
    """Invert the Clapp: f = fscale/(2 pi sqrt(L Ceff)), 1/Ceff = 1/Cp + 2/C1.  fscale from Phase 1 air point."""
    Ceff = (fscale / (2 * np.pi * f))**2 / L_H
    return 1 / (1 / Ceff - 2 / C1)

df = pd.read_csv(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else 'data/measurements.csv')
df = df[df.phase == 3].copy()
if df.empty: sys.exit('no phase-3 rows yet')
if df.C_pF.isna().all(): df['C_pF'] = f_to_C(df.f_Hz) * 1e12
correct = '--correct' in sys.argv
for soil, g in df.groupby('soil'):
    pts = g.groupby(['batch', 'theta_v', 'ec_w_Sm']).agg(C=('C_pF', 'mean'), Csd=('C_pF', 'std'),
                                                       ec=('ec_bulk_Sm', 'mean'), T=('temp_C', 'mean')).reset_index()
    ref = pts.ec_w_Sm.min()
    lo = pts[pts.ec_w_Sm == ref]
    if correct:
        ecref = np.interp(pts.theta_v, lo.theta_v, lo.ec)
        pts['C'] = pts.C * (pts.ec / ecref) ** (-S_SIGMA(pts.theta_v))
    p = np.polyfit(lo.C, lo.theta_v, 3)
    th_fit = np.polyval(p, pts.C)
    res = th_fit - pts.theta_v
    print(f'\n== {soil} ==  cubic theta(C) fitted on EC_w={ref} S/m ({len(lo)} points){"  [EC-corrected]" if correct else ""}')
    print(f'   RMS residual, low-EC points : {100*np.sqrt(np.mean(res[pts.ec_w_Sm==ref]**2)):.2f} % VWC')
    hi = pts.ec_w_Sm != ref
    if hi.any(): print(f'   mean error at other EC       : {100*res[hi].mean():+.2f} % VWC  (salinity term)')
    scat = 100 * (pts.Csd / pts.C) / np.abs(np.polyval(np.polyder(p), pts.C) * pts.C / pts.theta_v.clip(0.02)) * pts.theta_v.clip(0.02)
    print(f'   re-insertion scatter (1 sd)  : {scat.mean():.2f} % VWC average over beakers')
    if pts.T.std() > 3:
        sl = np.polyfit(pts.T, res, 1)[0]; print(f'   temperature slope            : {100*sl*10:+.2f} % VWC per 10 C')
    print('   fit coefficients (theta = p3 C^3 + p2 C^2 + p1 C + p0, C in pF):', np.round(p, 6))
