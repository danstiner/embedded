#!/usr/bin/env python3
"""Error budget for the 2-sided coplanar probe (config C) vs excitation frequency.

Part 1: log-sensitivities S_eps = dlnC/dln(er'), S_sig = dlnC/dln(sigma) -> how much of the
        reading is dielectric (moisture) vs conductive (salinity/temperature), and the VWC error
        produced by a 1 % model error or a 10 % error in a measured bulk-EC correction.
Part 2: apparent-theta error at true theta = 0.25 against a nominal low-EC calibration for
        realistic perturbations, plus Rp seen by an FDC2212 for 50/100 mm insertion.
"""
import numpy as np
import soil_probe_sim as s

S5 = [('S', -5.5, -0.5), ('G', 0.5, 5.5)]
TH = np.round(np.arange(0.02, 0.47, 0.04), 2)

def run(mat, f, **kw):
    return s.solve(s.pcb_scene(S5, S5, mat, W=12, **kw), f)

def C_of(er, sig, f, **kw):
    return run((er, sig, 0.0), f, **kw)['C']

def dln_eps_dtheta(th, d=1e-3):
    return (np.log(s.crim_er(th + d)) - np.log(s.crim_er(th - d))) / (2 * d)

print('Part 1: sensitivities.  VWC errors are for theta est. with sigma known (EC-corrected).')
print(f"{'f':>6s} {'theta':>5s} {'S_eps':>6s} {'S_sig':>6s} {'VWC/1%C err':>12s} {'VWC/10% sig err':>16s}")
for f in (1e6, 2e6, 5e6, 8e6, 10e6, 30e6, 70e6):
    for th in (0.10, 0.25, 0.40):
        er, sig, _ = s.soil_material(th)
        Se = (np.log(C_of(er * 1.05, sig, f)) - np.log(C_of(er / 1.05, sig, f))) / (2 * np.log(1.05))
        Ss = (np.log(C_of(er, sig * 1.05, f)) - np.log(C_of(er, sig / 1.05, f))) / (2 * np.log(1.05))
        k = dln_eps_dtheta(th)
        print(f"{f/1e6:5.0f}M {th:5.2f} {Se:6.3f} {Ss:6.3f} {100*0.01/(Se*k):+11.2f}% {100*Ss*0.10/(Se*k):+15.2f}%")

print('\nPart 2: apparent-theta error [%VWC] at true theta=0.25 vs nominal low-EC calibration.')
print(f"{'f':>5s} {'EC x2':>6s} {'EC x6':>6s} {'T+10C':>6s} {'gap.1':>6s} {'mask-33%':>8s} {'mask+33%':>8s} {'Rp100mm':>8s} {'Rp50mm':>7s} {'Rp100 coat.3':>12s}")
for f in (2e6, 5e6, 8e6, 10e6, 70e6):
    C = np.array([run(s.soil_material(th), f)['C'] for th in TH]); o = np.argsort(C)
    app = lambda r: 100 * (np.interp(r['C'], C[o], TH[o]) - 0.25)
    er, sig, _ = s.soil_material(0.25)
    ec2 = app(run(s.soil_material(0.25, 0.10), f))
    ec6 = app(run(s.soil_material(0.25, 0.30), f))
    T10 = app(run((s.crim_er(0.25, er_water=80 * 0.96), sig * 1.2, 0.0), f))   # water er -0.4%/C, sigma +2%/C
    gap = app(run(s.soil_material(0.25), f, gap_top=0.1))
    mlo = app(run(s.soil_material(0.25), f, stack=dict(s.STACK, t_mask=0.0102)))  # OSH Park 0.6 +/- 0.2 mil
    mhi = app(run(s.soil_material(0.25), f, stack=dict(s.STACK, t_mask=0.0203)))
    r = run(s.soil_material(0.25), f); rc = run(s.soil_material(0.25), f, coat=(0.3, s.COAT))
    print(f"{f/1e6:4.0f}M {ec2:+6.1f} {ec6:+6.1f} {T10:+6.1f} {gap:+6.1f} {mlo:+8.1f} {mhi:+8.1f} "
          f"{1/(r['G']*0.1):7.0f}Ω {1/(r['G']*0.05):6.0f}Ω {1/(rc['G']*0.1):11.0f}Ω")
