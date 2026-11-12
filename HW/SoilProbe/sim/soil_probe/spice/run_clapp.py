#!/usr/bin/env python3
"""Sweep the Clapp oscillator over probe (Cp, Gp) cases with ngspice; report oscillation
frequency, amplitude, start-up time, and pulling relative to the ideal LC formula."""
import subprocess, re, sys, os, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))

def run(Cp, Gp, **over):
    p = dict(Cp=Cp, Gp=max(Gp, 1e-6)); p.update(over)
    cir = open(f'{HERE}/clapp_osc.cir').read()
    # override .param line
    cir = re.sub(r'^\.param.*$', '.param ' + ' '.join(f'{k}={v}' for k, v in
                 dict(Cp=p['Cp'], Gp=p['Gp'], L=over.get('L', 470e-9), RL=over.get('RL', 4), C1=over.get('C1', 22e-12),
                      C2=over.get('C2', 22e-12), Vcc=over.get('Vcc', 3.0), Re=over.get('Re', 390),
                      Rb1=22e3, Rb2=22e3).items()), cir, flags=re.M)
    open(f'{HERE}/_tmp.cir', 'w').write(cir)
    subprocess.run(['ngspice', '-b', f'{HERE}/_tmp.cir'], cwd=HERE, capture_output=True)
    d = np.loadtxt(f'{HERE}/clapp_out.txt')
    t, ve = d[:, 0], d[:, 1]
    # steady state: last 1 us
    m = t > 2e-6
    ts, vs = t[m], ve[m] - ve[m].mean()
    zc = np.where((vs[:-1] < 0) & (vs[1:] >= 0))[0]
    if len(zc) < 5: return None
    # linear-interpolated crossing times for sub-step resolution
    tz = ts[zc] - vs[zc] * (ts[zc + 1] - ts[zc]) / (vs[zc + 1] - vs[zc])
    f = (len(tz) - 1) / (tz[-1] - tz[0])
    vpp = vs.max() - vs.min()
    # start-up: time at which envelope first reaches 90% of steady amplitude
    env = np.abs(ve - ve[m].mean())
    idx = np.where(env > 0.45 * vpp)[0]
    tstart = t[idx[0]] if len(idx) else np.nan
    return f, vpp, tstart

def ideal(Cp, L=470e-9, C1=22e-12, C2=22e-12):
    Ceff = 1 / (1 / Cp + 1 / C1 + 1 / C2)
    return 1 / (2 * np.pi * np.sqrt(L * Ceff))

CASES = [('dry',          14.2e-12, 0.19e-3), ('moist lo-EC', 21.7e-12, 0.71e-3), ('moist hi-EC', 22.5e-12, 1.90e-3),
         ('sat lo-EC',    28.6e-12, 0.93e-3), ('sat hi-EC',   31.1e-12, 2.71e-3)]

if __name__ == '__main__':
    print('80 mm probe, 0.3 mm coat, 70 MHz-class Clapp (L=470 nH, C1=C2=22 pF, Re=390 -> Ie~2.5 mA, Vcc 3.0 V)')
    print(f"{'case':14s} {'Cp pF':>6s} {'Gp mS':>6s} {'f_osc MHz':>10s} {'f_ideal':>8s} {'pull %':>7s} {'Vpp(e)':>7s} {'t_start us':>10s}")
    for name, Cp, Gp in CASES:
        r = run(Cp, Gp)
        if r is None: print(f'{name:14s} {Cp*1e12:6.1f} {Gp*1e3:6.2f}   NO OSCILLATION'); continue
        f, vpp, ts = r; fi = ideal(Cp)
        print(f'{name:14s} {Cp*1e12:6.1f} {Gp*1e3:6.2f} {f/1e6:10.3f} {fi/1e6:8.3f} {100*(f/fi-1):+7.2f} {vpp:7.2f} {ts*1e6:10.2f}')
    print('\nPulling by loss alone (Cp fixed 22 pF):')
    f0 = None
    for Gp in (0.01e-3, 1e-3, 2e-3, 4e-3, 8e-3, 12e-3):
        r = run(22e-12, Gp)
        if r is None: print(f'  Gp={Gp*1e3:5.2f} mS  NO OSCILLATION'); continue
        f0 = f0 or r[0]
        D = Gp / (2 * np.pi * r[0] * 22e-12)
        print(f'  Gp={Gp*1e3:5.2f} mS  D={D:4.2f}  f={r[0]/1e6:8.3f} MHz  df/f0={100*(r[0]/f0-1):+6.2f}%  -> equiv dC/C={-200*(r[0]/f0-1):+6.2f}%  Vpp={r[1]:.2f}')
    print('\nSalinity residual: calibrate theta(f) on the lo-EC cases, then read the hi-EC moist case')
    th = np.array([0.05, 0.25, 0.45]); fl = np.array([run(c, g)[0] for _, c, g in (CASES[0], CASES[1], CASES[3])])
    fh = run(CASES[2][1], CASES[2][2])[0]
    th_app = np.interp(-fh, -fl, th)          # f decreases with theta
    print(f'  hi-EC moist reads theta = {th_app:.3f}  (true 0.250)  -> error {100*(th_app-0.25):+.1f} % VWC, uncorrected')
    fa = run(22e-12, 0.71e-3)[0]; fb = run(22e-12, 1.90e-3)[0]; fs = run(28.6e-12, 0.93e-3)[0]
    fc1 = run(21.7e-12, 0.71e-3)[0]; fc2 = run(22.5e-12, 0.71e-3)[0]; slope = (fc1 - fs) / 0.20
    print(f'  of which oscillator pulling (0.71->1.90 mS at 22 pF): {(fa-fb)/slope*100:+.1f} % VWC, probe coat Maxwell-Wagner (FEM, +3.7 % C): {(fc1-fc2)/slope*100:+.1f} % VWC')
    print('\nTemperature (transistor model only; add inductor tempco separately):')
    for T in (0, 27, 50):
        cir = open(f'{HERE}/clapp_osc.cir').read(); open(f'{HERE}/clapp_osc.cir', 'w').write(cir.replace('.options', f'.temp {T}\n.options'))
        try: r = run(21.7e-12, 0.71e-3)
        finally: open(f'{HERE}/clapp_osc.cir', 'w').write(cir)
        print(f'  T={T:2d}C f={r[0]/1e6:.3f} MHz  Vpp={r[1]:.2f}')
    print('\nSupply / bias sensitivity (moist lo-EC):')
    for Vcc in (2.7, 3.0, 3.3):
        r = run(21.7e-12, 0.71e-3, Vcc=Vcc); print(f'  Vcc={Vcc}: f={r[0]/1e6:.3f} MHz Vpp={r[1]:.2f}')
