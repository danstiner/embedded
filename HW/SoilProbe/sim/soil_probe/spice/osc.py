#!/usr/bin/env python3
"""ngspice harness for the probe oscillator.

'xcp'   : cross-coupled BFR181 pair across a parallel tank (2 x Lh, series Cfix + Rd, probe).  The pair is a two-terminal negative conductance, so the circuit runs at the
          tank's parallel resonance.  Probe loss moves the frequency only through the delay of
          the pair (tau ~ 0.1 ns, mostly base stopper x Miller capacitance): dC_apparent = tau * G.
'clapp' : single-transistor series-resonant Clapp of the first design iteration, for comparison.

run() does one transient and returns frequency, differential amplitude, the detector voltage
(reference emitter minus common emitter) and supply current."""
import os, subprocess, tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

# Schematic values.  Cstray is the per-node pad + comparator-input capacitance to ground.
XCP = dict(Vcc=3.0, Lh=22e-9, QL=35.0, Cfix=33e-12, Rd=15.0, Rt=560.0, Rcm=100.0,
           Cstray=2.5e-12, Rbs=22.0, temp=27.0, Q='BFR181')

XCP_CIR = """* cross-coupled pair probe oscillator
.include {here}/rf_bjt.lib
.param Rbs={Rbs} Cp={Cp} Gp={Gp} Lh={Lh} QL={QL} Cfix={Cfix} Rd={Rd} Rt={Rt} Rcm={Rcm} Vcc={Vcc} Cs={Cstray}
.temp {temp}
Vcc  vcc 0 dc {{Vcc}}
Rcm  vcc vcm {{Rcm}}
Ccm  vcm 0 100n
* tank inductors: series loss for Q = QL at 110 MHz, 0.13 pF self-capacitance
L1   vcm a1 {{Lh}}
R1   a1  a  {{2*3.14159265*110e6*Lh/QL}}
C1   vcm a  0.13p
L2   vcm b1 {{Lh}}
R2   b1  b  {{2*3.14159265*110e6*Lh/QL}}
C2   vcm b  0.13p
* series RC across the tank: loss rises as f^2, so the strip line's second resonance
* (230-800 MHz, see scripts/tank_modes.py) is always more damped than the wanted mode
Cfix a m {{Cfix}}
Rd   m b {{Rd}}
Csa  a 0 {{Cs}}
Csb  b 0 {{Cs}}
* base stoppers damp the GHz emitter-follower mode through the package inductance
Rb1  b bq1 {{Rbs}}
Rb2  a bq2 {{Rbs}}
XQ1  a bq1 e {Q}
XQ2  b bq2 e {Q}
Rt   e 0 {{Rt}}
Ce   e 0 0.5p
* amplitude detector reference: same transistor type at half the tail current, no RF
Rb3  vcm bq3 {{Rbs}}
XQ3  vcm bq3 r {Q}
Rr   r 0 {{2*Rt}}
{probe}
Ikick a b pulse(0 0.2m 1n 0.2n 0.2n 1n 1)
.options reltol=1e-5 abstol=1e-13 vntol=1e-7 method=gear maxord=2
.tran {tstep} {tstop} 0 {tstep}
.control
run
wrdata {out} v(a,b) v(r,e) i(Vcc)
.endc
.end
"""

CLAPP_CIR = """* series-resonant Clapp, probe in series with the inductor
.include {here}/rf_bjt.lib
.param Cp={Cp} Gp={Gp}
.temp {temp}
Vcc  vcc 0 dc 3.0
Rb1  vcc bb 22k
Rb2  bb 0 22k
Rbs  bb bq 22
XQ1  vcc bq e {Q}
Re   e 0 390
C1   bb e 22p
C2   e 0 22p
Cblk bb n0 10n
L1   n0 n1 150n
RL   n1 a 2
Vb   b 0 0
{probe}
Ikick b a pulse(0 2m 1n 0.2n 0.2n 1n 1)
.options reltol=1e-5 abstol=1e-13 vntol=1e-7 method=gear maxord=2
.tran {tstep} {tstop} 0 {tstep}
.control
run
wrdata {out} v(e) v(e) i(Vcc)
.endc
.end
"""


def lumped_probe():
    return "Cpr a b {Cp}\nRpr a b {1/Gp}"


def ladder_probe(Cpul, Gpul, Lpul, length, n=10):
    """n-section ladder for the open-ended strip pair (per-unit-length SI values, length in m)."""
    d = length / n
    lines, prev = [], 'a'
    for k in range(n):
        node = f'pl{k}'
        lines += [f'Lpl{k} {prev} {node} {Lpul*d:.6e}', f'Cpl{k} {node} b {Cpul*d:.6e}',
                  f'Rpl{k} {node} b {1/max(Gpul*d, 1e-9):.6e}']
        prev = node
    return '\n'.join(lines)


def run(Cp=10e-12, Gp=1e-4, topology='xcp', probe=None, tstop=400e-9, tstep=10e-12, keep=False, **over):
    p = dict(XCP); p.update(over)
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, 'o.txt')
        tmpl = XCP_CIR if topology == 'xcp' else CLAPP_CIR
        cir = tmpl.format(here=HERE, out=out, Cp=Cp, Gp=max(Gp, 1e-7), tstep=tstep, tstop=tstop,
                          probe=probe or lumped_probe(), **p)
        path = os.path.join(td, 'c.cir')
        with open(path, 'w') as fh: fh.write(cir)
        r = subprocess.run(['ngspice', '-b', path], capture_output=True, text=True, cwd=td)
        if not os.path.exists(out):
            raise RuntimeError(r.stdout[-2000:] + r.stderr[-2000:])
        d = np.loadtxt(out)
    t, v, det, icc = d[:, 0], d[:, 1], d[:, 3], -d[:, 5]
    m = t > 0.5 * tstop
    ts, vs = t[m], v[m] - v[m].mean()
    amp = 0.5 * np.ptp(vs)
    res = dict(f=np.nan, amp=amp, det=det[m].mean(), icc=icc[m].mean(), settled=False)
    if keep: res.update(t=t, v=v)
    zc = np.where((vs[:-1] < 0) & (vs[1:] >= 0))[0]
    if len(zc) < 8 or amp < 5e-3:
        res['amp'] = 0.0
        return res
    tz = ts[zc] - vs[zc] * (ts[zc + 1] - ts[zc]) / (vs[zc + 1] - vs[zc])
    res['f'] = (len(tz) - 1) / (tz[-1] - tz[0])
    q = len(vs) // 2
    res['settled'] = bool(abs(np.ptp(vs[q:]) / np.ptp(vs[:q]) - 1) < 0.01)
    return res


if __name__ == '__main__':
    print('probe load        f MHz   Vdiff pk   det mV   Icc mA')
    for name, Cp, Gp in [('air', 1.6e-12, 1e-6), ('dry soil', 3.5e-12, 0.13e-3), ('moist', 10.8e-12, 0.8e-3),
                         ('wet, 3 dS/m', 21.5e-12, 5.4e-3), ('water', 48e-12, 2.2e-3)]:
        r = run(Cp, Gp)
        print(f"{name:14s} {r['f']/1e6:8.3f} {r['amp']:9.3f} {r['det']*1e3:8.1f} {r['icc']*1e3:8.2f}")
