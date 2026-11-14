#!/usr/bin/env python3
"""Predicted probe values in reference liquids (Phase 1 of TEST_PLAN.md): validates geometry,
coat and parasitics before any soil is involved.  Liquids fill any gap, so this isolates the
field solver from contact effects.  er values at ~25 C."""
import numpy as np, soil_probe_sim as s

LIQUIDS = [('air', 1.0, 0.0), ('mineral oil', 2.2, 0.0), ('isopropanol 99%', 18.3, 1e-5),
           ('glycerol', 42.5, 1e-5), ('DI water', 78.5, 1e-4), ('tap water ~300 uS/cm', 78.5, 0.03),
           ('NaCl 1 g/L', 78.5, 0.20)]
S5 = [('S', -5.5, -0.5), ('G', 0.5, 5.5)]

def pred(f, L_mm, coat, C_par=6e-12, tank='clapp'):
    print(f'\n--- {f/1e6:.0f} MHz, {L_mm:.0f} mm immersed, coat {coat} mm, +{C_par*1e12:.0f} pF parasitic ---')
    col = 'Clapp f MHz (470n/22p/22p, x0.9 for Q1 caps)' if tank == 'clapp' else 'FDC tank f MHz (12 uH + 10 pF)'
    print(f"{'liquid':22s} {'er':>5s} {'C_pF':>6s} {'G_mS':>6s} {'D':>5s} {'Rp_ohm':>7s}  {col}")
    for name, er, sig in LIQUIDS:
        kw = dict(coat=(coat, s.COAT)) if coat else {}
        r = s.solve(s.pcb_scene(S5, S5, (er, sig, 0.0), W=12, **kw), f)
        C = r['C'] * L_mm * 1e-3 + C_par; G = r['G'] * L_mm * 1e-3
        if tank == 'clapp':
            Ceff = 1 / (1 / C + 2 / 22e-12); fi = 0.9 / (2 * np.pi * np.sqrt(470e-9 * Ceff))
        else:
            fi = 1 / (2 * np.pi * np.sqrt(12e-6 * (C + 10e-12)))
        print(f'{name:22s} {er:5.1f} {C*1e12:6.1f} {G*1e3:6.2f} {G/(2*np.pi*f*C):5.2f} {1/max(G,1e-9):7.0f}  {fi/1e6:6.1f}')

if __name__ == '__main__':
    pred(76e6, 80, 0.3)
    pred(10e6, 50, 0.3, tank='fdc')
    print('\nInsertion-depth check (glycerol, 76 MHz, coated): C should be linear in depth;')
    r = s.solve(s.pcb_scene(S5, S5, (42.5, 1e-5, 0.0), W=12, coat=(0.3, s.COAT)), 76e6)
    for L in (20, 40, 60, 80): print(f'  {L} mm: {(r["C"]*L*1e-3 + 6e-12)*1e12:5.1f} pF')
