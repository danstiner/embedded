#!/usr/bin/env python3
"""Cross-check of the system model: the oscillator table driven by the transmission-line
admittance (system_sim.measure) against one ngspice transient of the oscillator loaded by a
distributed ladder of the same strip line.  Agreement says the lumped-load table is a fair
stand-in for the distributed probe, harmonics included."""
import os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
import soil_probe_sim as s, probe as p, system_sim as S, osc

S.OSC = S.Oscillator()
import tank_modes
CASES = tank_modes.MEDIA + [('mix th 0.25', S.soil(0.25))]


def ladder(mat, f, n_per_cm=2):
    w = 2 * np.pi * f
    lines, prev, k = [], 'a', 0
    secs = [(p.POTTING, p.GEOM['stub']), (mat, p.GEOM['length'])]          # from the feed outward
    for m, ell in secs:
        cs = complex(np.ravel(p.table().cstar(*p.eps_star(m, f)))[0])
        n = max(2, int(round(ell / 10 * n_per_cm)))
        d = ell * 1e-3 / n
        for _ in range(n):
            node = f'pl{k}'
            lines += [f'Lpl{k} {prev} {node} {p.Lpul()*d:.6e}', f'Cpl{k} {node} b {cs.real*d:.6e}',
                      f'Rpl{k} {node} b {1/max(-cs.imag*w*d, 1e-9):.6e}']
            prev, k = node, k + 1
    return '\n'.join(lines)


if __name__ == '__main__':
    print(f"{'medium':22s} {'model f MHz':>11s} {'ladder f MHz':>12s} {'df ppm':>8s} {'model det mV':>12s} {'ladder det mV':>13s}")
    from multiprocessing.pool import ThreadPool
    def job(c):
        f, det = S.measure(c[1])
        return c[0], f, det, osc.run(probe=ladder(c[1], f))
    with ThreadPool(os.cpu_count()) as pool:
        for name, f, det, r in pool.map(job, CASES):
            print(f"{name:22s} {f/1e6:11.3f} {r['f']/1e6:12.3f} {1e6*(r['f']/f-1):+8.0f} {det*1e3:12.1f} {r['det']*1e3:13.1f}")
