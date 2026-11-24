#!/usr/bin/env python3
"""The probe boards already drawn under HW/, run through the framework of design_comparison.py.

Boards (copper read from the .kicad_pcb files): two strips on the front face only, under solder
mask, on the OSH Park 2-layer stack (1.6 mm FR-4, 1 oz, 15 um mask):
  Probe_Parallel9mm        9 mm board, 2 x 50 mm strips, 2 mm gap
  Probe_Parallel12mm      12 mm board, 3 x 50 mm strips, 3 mm gap
  Probe_ParallelOneInch   25 mm board, 6 x 60 mm strips, 6 mm gap   (Soily has the same strips)
  SoilProbe_FDC1004_Parallel9mm   12 mm board, 2 x 50 mm strips, 2 mm gap, FDC1004 on board
Readouts:
  FDC1004   25 kHz charge transfer, +/-15 pF on top of at most 100 pF offset (data sheet)
  FDC2x12   LC tank across the strips; the chip reports the resonant frequency, which moves with
            the medium (10 uH + 33 pF on the breakouts, 18 uH + 33 pF on Soily).  Data sheet:
            10 kHz-10 MHz, drive at most 1.56 mA for at least 1.2 V peak.

Writes ../results/existing_boards.txt."""
import os, sys
import numpy as np
import soil_probe_sim as s
import design_comparison as D

MASK_TOL = dict(stack=dict(s.OSHPARK_2L, t_mask=0.0152 * 1.33))      # +/-0.2 mil on 0.6 mil = 3 sd
def _g(label, W, w, gap, length):
    return dict(label=label, stack=s.OSHPARK_2L, ifc=(1,), W=W, strips=D._strips(w, gap), length=length,
                tol=MASK_TOL, tol_sd=1 / 3)
D.GEOMS.update({
    'p9':   _g('2 mm strips, 2 mm gap, 9 mm board', 9.05, 2.0, 2.0, 0.050),
    'p12':  _g('3 mm strips, 3 mm gap, 12 mm board', 12.05, 3.0, 3.0, 0.050),
    'p25':  _g('6 mm strips, 6 mm gap, 25 mm board', 25.05, 6.0, 6.0, 0.060),
    'fdc9': _g('2 mm strips, 2 mm gap, 12 mm board', 11.94, 2.0, 2.0, 0.050),
})
C_STRAY = 5e-12              # F, pins, traces and header on the tank (estimate)
FDC1004_MAX = 115e-12        # F, single-ended with CAPDAC
RP_MIN = 1.2 / 1.563e-3      # ohm: amplitude ~ drive current x parallel resistance (order of magnitude)


class LC(D.Design):
    """Tank L, C0 with the strips across it.  m = 1/f^2 at the self-consistent resonant frequency."""
    def __init__(self, key, geom, L, C0, label):
        self.L, self.C0 = L, C0 + C_STRAY
        super().__init__(key, geom, 'cp', 1 / (2 * np.pi * np.sqrt(L * self.C0)), label)
        self.usable = self.mono

    def state(self, eps, gap=0.0, unit=0.0):
        """eps(f) -> (e', e'').  Returns resonant frequency and probe conductance."""
        f = self.f
        for _ in range(40):
            Y = D.feed_Y(self.geom, *eps(f), f, gap, unit)
            f = 1 / (2 * np.pi * np.sqrt(self.L * np.maximum(self.C0 + Y.imag / (2 * np.pi * f), 1e-13)))
        return f, D.feed_Y(self.geom, *eps(f), f, gap, unit).real

    def x(self, theta, sigma_w, T, gap=0.0, unit=0.0):
        one = np.ones_like(np.asarray(theta, float) + np.asarray(unit, float))
        m = lambda eps, g: self.state(eps, g, unit)[0] ** -2.0
        ma = m(lambda f: (one, 0 * one), 0.0)
        mw = m(lambda f: (s.water_er(D.T_REF) * one, 0.005 / (2 * np.pi * f * s.EPS0) * one), 0.0)
        return (m(lambda f: D.soil_eps(theta * one, sigma_w, T, f), gap) - ma) / (mw - ma), None


def designs():
    out = [D.Design(k, g, 'charge', 25e3, lab) for k, g, lab in (
        ('P9/1004', 'p9', 'Probe_Parallel9mm + FDC1004 breakout'),
        ('P12/1004', 'p12', 'Probe_Parallel12mm + FDC1004 breakout'),
        ('P25/1004', 'p25', 'Probe_ParallelOneInch + FDC1004 breakout'),
        ('FDC9', 'fdc9', 'SoilProbe_FDC1004_Parallel9mm'))]
    out += [LC(k, g, L, 33e-12, lab) for k, g, L, lab in (
        ('P9/2x12', 'p9', 10e-6, 'Probe_Parallel9mm + FDC2112/2212 breakout'),
        ('P12/2x12', 'p12', 10e-6, 'Probe_Parallel12mm + FDC2112/2212 breakout'),
        ('P25/2x12', 'p25', 10e-6, 'Probe_ParallelOneInch + FDC2112/2212 breakout'),
        ('Soily', 'p25', 18e-6, 'Soily (FDC2212, 18 uH)'))]
    return out + [D.Design('ref', 'buried20', 'par', 100e6, 'SoilProbe 2026v1 (4-layer, buried, 100 MHz)')]


def operating(d, n=4000, seed=11):
    """Electrical operating point over the nominal draws, and in air and water."""
    th, sw, T, Tm, gap, unit = D.draw(np.random.default_rng(seed), n, ('EC', 'T', 'contact', 'unit'))
    u = unit * D.GEOMS[d.geom]['tol_sd']
    one = np.ones(1)
    air = lambda f: (one, 0 * one)
    wat = lambda f: (s.water_er(D.T_REF) * one, 0.005 / (2 * np.pi * f * s.EPS0) * one)
    if isinstance(d, LC):
        f, G = d.state(lambda f: D.soil_eps(th, sw, T, f), gap, u)
        fa, fw = d.state(air)[0][0], d.state(wat)[0][0]
        cap = lambda fn, f0: D.feed_Y(d.geom, *fn(f0), f0)[0].imag / (2 * np.pi * f0)
        return dict(c_air=cap(air, fa), c_water=cap(wat, fw), f_air=fa, f_water=fw, f_lo=float(np.percentile(f, 1)),
                    out=float(np.mean(1 / np.maximum(G, 1e-12) < RP_MIN)), rp_med=float(np.median(1 / np.maximum(G, 1e-12))))
    if d.readout == 'charge':
        m = d.m(*D.soil_eps(th, sw, T, d.f), gap, u)[0]
        return dict(c_air=d.m(*air(d.f))[0][0], c_water=d.m(*wat(d.f))[0][0], m_med=float(np.median(m)),
                    out=float(np.mean(m > FDC1004_MAX)))
    return {}


def main(n=4000):
    ds = designs()
    L = ['design                                           |  RMSE  bias   p95 ideal |    EC     T  cont  unit   [% VWC]   | electrical']
    res = {}
    for d in ds:
        r = {name: D.stats(D.run(d, src, n)[1]) for name, src in D.SOURCE_SETS}
        op = operating(d, n)
        res[d.key] = (r, op)
        if 'f_air' in op:
            el = (f"C {op['c_air']*1e12:.1f}-{op['c_water']*1e12:.0f} pF, f {op['f_air']/1e6:.2f} (air) {op['f_water']/1e6:.2f} (water) MHz, "
                  f"median Rp {op['rp_med']/1e3:.2f} k, below {RP_MIN/1e3:.2f} k in {100*op['out']:.0f} % of readings")
        elif op:
            el = (f"reads {op['c_air']*1e12:.1f} pF air, {op['c_water']*1e12:.0f} pF water, median {op['m_med']*1e12:.0f} pF in substrate, "
                  f"over {FDC1004_MAX*1e12:.0f} pF in {100*op['out']:.0f} % of readings")
        else: el = ''
        a = r['all']
        L.append(f"{d.key:9s} {d.label[:38]:38s} | {a['rmse']:5.2f} {a['bias']:5.2f} {a['p95']:5.2f} {r['ideal_contact']['rmse']:5.2f} | "
                 f"{r['EC']['rmse']:5.2f} {r['T']['rmse']:5.2f} {r['contact']['rmse']:5.2f} {r['unit']['rmse']:5.2f}            | {el}")
    # the same boards in a substrate with its own relaxation (median organic-soil shape, moving with salinity)
    keep = dict(D.DISPERSION)
    D.DISPERSION.update(a=3.09, alpha=0.75, fr=1e6, ec=1.0)
    L.append('\nwith substrate relaxation (median organic-soil shape, relaxation frequency following salinity): RMSE all / EC only')
    for d in designs():
        L.append(f"{d.key:9s} {D.stats(D.run(d, ('EC', 'T', 'contact', 'unit'), n)[1])['rmse']:5.2f} / {D.stats(D.run(d, ('EC',), n)[1])['rmse']:5.2f}")
    D.DISPERSION.update(keep)
    L.append('\nnormalized reading x at theta = 0.1, 0.3, 0.5 for pore-water EC 0.3 / 1 / 4 dS/m (1 = water calibration point)')
    for d in ds:
        L.append(f"{d.key:9s} " + '   '.join('/'.join(f"{d.x(np.array([t]), sw, D.T_REF)[0][0]:6.2f}" for sw in (0.03, 0.10, 0.40)) for t in (0.1, 0.3, 0.5)))
    txt = '\n'.join(L)
    open(os.path.join(D.RESULTS, 'existing_boards.txt'), 'w').write(txt + '\n')
    print(txt)


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 4000)
