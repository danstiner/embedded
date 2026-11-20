#!/usr/bin/env python3
"""Map the oscillator over the probe's load plane (parallel C, G at the feed) with ngspice and
store the table the system simulation interpolates: frequency, amplitude, detector voltage.
Also reports the loss pulling of both topologies.  Writes ../results/osc_table.npz."""
import os, sys
from multiprocessing.pool import ThreadPool
import numpy as np
import osc

OUT = os.path.join(osc.HERE, '..', 'results')
C_GRID = np.array([0, 1, 2, 3.5, 5, 7.5, 10, 14, 18, 23, 28, 35, 45, 60, 80]) * 1e-12
G_GRID = np.array([0, 0.25, 0.5, 1, 1.5, 2, 3, 4, 5, 6.5, 8, 10, 13, 16, 20]) * 1e-3


def table(tag='nominal', **over):
    jobs = [(c, g) for c in C_GRID for g in G_GRID]
    with ThreadPool(os.cpu_count()) as p:
        res = p.map(lambda a: osc.run(a[0] + 1e-15, a[1], **over), jobs)
    shp = (len(C_GRID), len(G_GRID))
    arr = {k: np.array([r[k] for r in res], float).reshape(shp) for k in ('f', 'amp', 'det', 'icc')}
    arr['settled'] = np.array([r['settled'] for r in res]).reshape(shp)
    np.savez(f'{OUT}/osc_table_{tag}.npz', C=C_GRID, G=G_GRID, **arr)
    return arr


def pulling():
    G = np.array([1e-5, 1e-3, 2e-3, 4e-3, 6e-3, 8e-3])
    print('\nLoss pulling at fixed probe capacitance (equivalent dCp = df / (df/dCp)):')
    for topo in ('xcp', 'clapp'):
        for Cp in (11e-12, 22e-12):
            jobs = [(Cp, g) for g in G] + [(Cp * 1.05, G[0])]
            with ThreadPool(os.cpu_count()) as p:
                r = p.map(lambda a: osc.run(a[0], a[1], topology=topo), jobs)
            f0 = r[0]['f']; S = np.log(r[-1]['f'] / f0) / np.log(1.05)
            row = ' '.join(f"{100*np.log(x['f']/f0)/S:+6.1f}" if np.isfinite(x['f']) else '  stop' for x in r[1:-1])
            print(f'  {topo:5s} Cp={Cp*1e12:2.0f} pF  f0={f0/1e6:6.1f} MHz  dCp/Cp [%] at G=1,2,4,6,8 mS: {row}')


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    a = table()
    np.set_printoptions(linewidth=220, precision=1, suppress=True)
    print('f [MHz], rows C =', C_GRID * 1e12, 'pF; cols G =', G_GRID * 1e3, 'mS')
    print(a['f'] / 1e6)
    print('amplitude [mV pk differential]'); print(a['amp'] * 1e3)
    print('detector [mV]'); print(a['det'] * 1e3)
    print('unsettled points:', int((~a['settled'] & np.isfinite(a['f'])).sum()))
    if '--pulling' in sys.argv: pulling()
