#!/usr/bin/env python3
"""Compare complete capacitive soil-moisture probe designs (electrode cross-section x readout
principle) on the accuracy they can reach in potting mix under nominal conditions.

Every design gets the same treatment:
  probe      2-D complex-permittivity field solution tabulated over the medium's e' - j e'',
             80 mm of strip as an open-ended transmission line (L' from the vacuum solution)
  readout    an idealized model of what the circuit reports from the feed admittance Y(f)
  calibration per unit: air and water readings, x = (m - m_air) / (m_water - m_air)
             per medium: x -> theta curve taken in the reference state, linear temperature term
  evaluation Monte Carlo over water content, pore-water EC, temperature, contact and
             unit-to-unit tolerance, all sources together and one at a time

Writes ../results/design_comparison.{txt,json} and the manuscript figures in ../paper/figures."""
import functools, json, os, sys
from multiprocessing import Pool
import numpy as np
from scipy.interpolate import RegularGridInterpolator
import soil_probe_sim as s

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, '..', 'results')
FIGS = os.path.join(HERE, '..', 'paper', 'figures')
MU0 = 4e-7 * np.pi
LENGTH = 0.080                                   # m of strip in the medium, all designs
TAU = 170e-12                                    # s, delay of the cross-coupled pair (spice/characterize.py)

# nominal conditions for container-grown plants in peat-based mix
POROSITY, ER_SOLID = 0.70, 4.0
T_REF, SIGMA_REF = 22.0, 0.10                    # C; pore-water EC 1.0 dS/m
TH_RANGE = (0.05, 0.55)
SIGMA_LN_SD, SIGMA_CLIP = 0.5, (0.03, 0.40)      # lognormal about SIGMA_REF: 0.3-4 dS/m
T_SD, T_CLIP = 4.0, (10.0, 35.0)
GAP_MEAN, GAP_MAX = 0.02, 0.10                   # mm of air on one face, exponential
T_ERR_SD = 1.0                                   # C, thermistor error
G_GAIN_SD, G_NOISE = 0.05, 1e-4                  # loss channel of the complex readout

EPS_RE = np.array([1, 1.4, 2, 3, 4.5, 6.5, 9, 13, 18, 26, 36, 50, 66, 85.0])
EPS_IM = np.concatenate([[0], np.geomspace(0.5, 5e5, 17)])


def _strips(w, g):
    return [('S', -g / 2 - w, -g / 2), ('G', g / 2, g / 2 + w)]


def _fingers(n=6, w=1.0, g=1.0, x0=-5.5):
    return [('S' if i % 2 == 0 else 'G', x0 + i * (w + g), x0 + i * (w + g) + w) for i in range(n)]


def _prepreg(k):
    (t0, m0), (t1, m1), (t2, m2) = s.OSHPARK_4L['dielectrics']
    return dict(s.OSHPARK_4L, dielectrics=[(t0 * k, m0), (t1, m1), (t2 * k, m2)])


# cross-sections.  tol: the scene override for one unit of manufacturing deviation, and the
# standard deviation of a unit in those units (fab tolerance bands taken as +/-3 sd; a hand-
# dipped coat as +/-30 % at 1 sd)
GEOMS = {
    'outer12':  dict(label='outer strips, 12 mm', stack=s.OSHPARK_2L, ifc=(0, 1), W=12.0, strips=_strips(5.0, 1.0),
                     tol=dict(stack=dict(s.OSHPARK_2L, t_mask=0.0152 * 1.33)), tol_sd=1 / 3),
    'idc12':    dict(label='interdigitated, 12 mm', stack=s.OSHPARK_2L, ifc=(0, 1), W=12.0, strips=_fingers(),
                     tol=dict(stack=dict(s.OSHPARK_2L, t_mask=0.0152 * 1.33)), tol_sd=1 / 3),
    'coat12':   dict(label='dip-coated strips, 12 mm', stack=s.OSHPARK_2L, ifc=(0, 1), W=12.0, strips=_strips(5.0, 1.0),
                     coat=(0.3, s.COAT), tol=dict(coat=(0.39, s.COAT)), tol_sd=1.0),
    'outer20':  dict(label='outer strips, 20 mm', stack=s.OSHPARK_2L, ifc=(0, 1), W=20.0, strips=_strips(5.5, 7.0),
                     tol=dict(stack=dict(s.OSHPARK_2L, t_mask=0.0152 * 1.33)), tol_sd=1 / 3),
    'buried20': dict(label='buried strips, 20 mm', stack=s.OSHPARK_4L, ifc=(1, 2), W=20.0, strips=_strips(5.5, 7.0),
                     tol=dict(stack=_prepreg(1.1)), tol_sd=1 / 3),
}
GAP_NODES = (0.005, 0.01, 0.02, 0.05, 0.10)      # mm: air-layer thicknesses solved directly
VARIANTS = ('nom', 'gap5', 'gap10', 'gap20', 'gap50', 'gap100', 'tol')

# (key, geometry, readout, frequency Hz, label)
DESIGNS = [
    ('A', 'outer12',  'charge',  25e3,  'Outer strips, 25 kHz charge transfer'),
    ('B', 'outer12',  'divider', 1.5e6, 'Outer strips, 1.5 MHz RC divider'),
    ('C', 'idc12',    'divider', 1.5e6, 'Interdigitated, 1.5 MHz RC divider'),
    ('D', 'coat12',   'cp',      10e6,  'Dip-coated strips, 10 MHz parallel LC'),
    ('E', 'coat12',   'ser',     75e6,  'Dip-coated strips, 75 MHz series LC'),
    ('F', 'outer12',  'par',     100e6, 'Outer strips 12 mm, 100 MHz parallel LC'),
    ('G', 'outer20',  'par',     100e6, 'Outer strips 20 mm, 100 MHz parallel LC'),
    ('H', 'buried20', 'par',     100e6, 'Buried strips 20 mm, 100 MHz parallel LC'),
    ('I', 'buried20', 'complex', 100e6, 'Buried strips 20 mm, 100 MHz LC + loss'),
]


# same electrodes and frequency, readout changed: isolates the resonance topology and the delay term
CONTROLS = [
    ('E1', 'coat12',   'cp',  75e6,  'coat12, 75 MHz, ideal parallel C'),
    ('E2', 'coat12',   'ser', 75e6,  'coat12, 75 MHz, series C'),
    ('H1', 'buried20', 'cp',  100e6, 'buried20, 100 MHz, ideal parallel C'),
    ('H2', 'buried20', 'par', 100e6, 'buried20, 100 MHz, parallel C + delay'),
    ('H3', 'buried20', 'ser', 100e6, 'buried20, 100 MHz, series C'),
    ('G1', 'outer20',  'cp',  100e6, 'outer20, 100 MHz, ideal parallel C'),
    ('G3', 'outer20',  'ser', 100e6, 'outer20, 100 MHz, series C'),
]


def scene(geom, mat, variant='nom', **kw):
    g = dict(GEOMS[geom])
    if variant == 'tol': g.update(g['tol'])
    if variant.startswith('gap'): kw['gap_top'] = int(variant[3:]) / 1000
    if 'coat' in g: kw['coat'] = g['coat']
    st = g['strips']
    return s.stack_scene(g['stack'], {i: st for i in g['ifc']}, mat, W=g['W'], **kw)


def _solve(a):
    geom, variant, er, eim = a
    f = 100e6
    w = 2 * np.pi * f
    return s.solve(scene(geom, (er, eim * w * s.EPS0, 0.0), variant), f)['Y'] / (1j * w)


@functools.lru_cache(maxsize=None)
def table(geom, variant):
    """C*'(e', e'') [F/m] interpolator, cached on disk."""
    path = f'{RESULTS}/dc_table_{geom}_{variant}.npz'
    if os.path.exists(path):
        Cs = np.load(path)['Cs']
    else:
        with Pool() as p:
            Cs = np.array(p.map(_solve, [(geom, variant, a, b) for a in EPS_RE for b in EPS_IM])).reshape(len(EPS_RE), len(EPS_IM))
        os.makedirs(RESULTS, exist_ok=True)
        np.savez(path, Cs=Cs)
    ax = (np.log(EPS_RE), np.log1p(EPS_IM / 2))
    re = RegularGridInterpolator(ax, Cs.real * 1e12, method='cubic')
    im = RegularGridInterpolator(ax, Cs.imag * 1e12, method='cubic')
    def f(er, eim):
        pt = np.stack([np.log(np.clip(er, 1, 85)), np.log1p(np.clip(eim, 0, 5e5) / 2)], axis=-1)
        return (re(pt) + 1j * im(pt)) * 1e-12
    return f


@functools.lru_cache(maxsize=None)
def Lpul(geom):
    g = GEOMS[geom]
    vac = dict(dielectrics=[(t, s.AIR) for t, _ in g['stack']['dielectrics']], cu=g['stack']['cu'], t_mask=0.0)
    st = g['strips']
    C0 = s.solve(s.stack_scene(vac, {i: st for i in g['ifc']}, s.AIR, W=g['W'], Lx=80, Ly=80), 1e6)['C']
    return MU0 * s.EPS0 / C0


# optional relaxation of the substrate itself, shaped on measured spectra of organic soils
# (organic_soil_spectra.py): e_b from the mixing model is taken as the 1 GHz value and multiplied
# by rel(f) / Re rel(1 GHz), rel = 1 + a / (1 + (j f / f_r)^(1 - alpha)).  The relaxation
# frequency moves with pore-water conductivity as sigma_w^ec (ec = 1: Maxwell-Wagner; 0: not at
# all) and with temperature as exp(tc (T - 25)).
DISPERSION = dict(a=0.0, fr=1e6, alpha=0.75, ec=1.0, tc=0.02)


def _rel(f, fr):
    return 1 + DISPERSION['a'] / (1 + (1j * f / fr) ** (1 - DISPERSION['alpha']))


def quarter_wave(geom):
    """Frequency at which the 80 mm strips are a quarter wave long in the water calibration medium."""
    cw = table(geom, 'nom')(np.array([s.water_er(T_REF)]), np.array([0.0]))[0].real
    return 1 / (4 * GEOMS[geom].get('length', LENGTH) * np.sqrt(Lpul(geom) * cw))


def soil_eps(theta, sigma_w, T, f):
    """(e', e'') of the potting mix: CRIM mixing, Archie-type bulk EC, 2 %/C."""
    er = s.crim_er(theta, POROSITY, ER_SOLID, s.water_er(T))
    sig = s.soil_sigma(theta, sigma_w) * (1 + 0.02 * (T - 25.0))
    eim = sig / (2 * np.pi * f * s.EPS0)
    if DISPERSION['a']:
        fr = DISPERSION['fr'] * (np.asarray(sigma_w) / SIGMA_REF) ** DISPERSION['ec'] * np.exp(DISPERSION['tc'] * (T - 25.0))
        rel = _rel(f, fr) / _rel(1e9, DISPERSION['fr']).real
        er, eim = er * rel.real, eim - er * rel.imag
    return er, eim


def feed_Y(geom, er, eim, f, gap=0.0, unit=0.0):
    """Admittance of the 80 mm open-ended strip pair.  gap in mm (one face), unit in tolerance units."""
    nom = table(geom, 'nom')(er, eim)
    cs = nom
    if np.any(gap):                                  # piecewise linear between directly solved gaps
        nodes = np.array((0.0,) + GAP_NODES)
        vals = [nom] + [table(geom, f'gap{int(round(g * 1000))}')(er, eim) for g in GAP_NODES]
        gap = np.broadcast_to(np.asarray(gap, float), np.shape(nom))
        k = np.clip(np.searchsorted(nodes, gap, side='right') - 1, 0, len(nodes) - 2)
        t = (gap - nodes[k]) / (nodes[k + 1] - nodes[k])
        lo, hi = np.choose(k, vals[:-1]), np.choose(k, vals[1:])
        cs = lo + t * (hi - lo)
    if np.any(unit): cs = cs + np.asarray(unit) * (table(geom, 'tol')(er, eim) - nom)
    w = 2 * np.pi * f
    Z, Yp = 1j * w * Lpul(geom), 1j * w * cs
    return np.sqrt(Yp / Z) * np.tanh(np.sqrt(Z * Yp) * GEOMS[geom].get('length', LENGTH))


def observe(readout, Y, f):
    """What each circuit reports.  Second value is the loss channel (complex readout only)."""
    w = 2 * np.pi * f
    C, G = Y.imag / w, Y.real
    if readout == 'charge':        # charge moved in one half cycle of a square excitation
        return C + G / (2 * f), None
    if readout == 'divider':       # fixed square wave through 10 k into the probe, peak-detected
        return 1 - np.abs(1 / (1 + 1e4 * Y)), None
    if readout == 'cp':            # ideal parallel-capacitance meter
        return C, None
    if readout == 'par':           # parallel-resonant oscillator: parallel C, plus delay x loss
        return C + TAU * G, None
    if readout == 'ser':           # series-resonant oscillator: series-equivalent C
        return -1 / (w * (1 / Y).imag), None
    if readout == 'complex':
        return C + TAU * G, G
    raise ValueError(readout)


class Design:
    def __init__(self, key, geom, readout, f, label):
        self.key, self.geom, self.readout, self.f, self.label = key, geom, readout, f, label
        self.th = np.linspace(0.0, 0.64, 81)
        self.x_ref = self.x(self.th, SIGMA_REF, T_REF)[0]
        self.mono = bool(np.all(np.diff(self.x_ref) > 0))
        # the water calibration point must lie below the strips' quarter-wave resonance
        yw = feed_Y(geom, np.array([s.water_er(T_REF)]), np.array([0.005 / (2 * np.pi * f * s.EPS0)]), f)[0]
        self.usable = self.mono and yw.imag > 0 and f < quarter_wave(geom)
        if readout == 'complex':
            self.sw = np.geomspace(0.01, 0.8, 30)
            xg = [self.x(self.th, sw, T_REF) for sw in self.sw]
            self.Xg = np.array([a for a, _ in xg]); self.Gg = np.array([b for _, b in xg])
        # linear temperature term fitted in the reference medium
        tg = np.linspace(0.08, 0.52, 12)
        slope = (self._theta_raw(*self.x(tg, SIGMA_REF, T_REF + 8)) - self._theta_raw(*self.x(tg, SIGMA_REF, T_REF - 8))) / 16
        self.kT = np.polyfit(tg, slope, 1)

    def m(self, er, eim, gap=0.0, unit=0.0):
        return observe(self.readout, feed_Y(self.geom, er, eim, self.f, gap, unit), self.f)

    def x(self, theta, sigma_w, T, gap=0.0, unit=0.0):
        """Normalized reading of a unit calibrated in air and in water at the reference temperature."""
        one = np.ones_like(np.asarray(theta, float) + np.asarray(unit, float))
        m, g = self.m(*soil_eps(theta, sigma_w, T, self.f), gap, unit)
        ma = self.m(one, 0 * one, 0.0, unit)[0]
        mw = self.m(s.water_er(T_REF) * one, 0.005 / (2 * np.pi * self.f * s.EPS0) * one, 0.0, unit)[0]
        return (m - ma) / (mw - ma), g

    def _theta_raw(self, x, G=None):
        if self.readout != 'complex':
            return np.interp(x, np.maximum.accumulate(self.x_ref), self.th)
        # per conductivity column: theta from x; then the column whose loss matches
        th_j = np.array([np.interp(x, np.maximum.accumulate(self.Xg[j]), self.th) for j in range(len(self.sw))])
        g_j = np.array([np.interp(th_j[j], self.th, self.Gg[j]) for j in range(len(self.sw))])
        d = g_j - G
        j = np.clip((d < 0).sum(axis=0) - 1, 0, len(self.sw) - 2)
        k = np.arange(d.shape[1])
        t = np.clip(-d[j, k] / (d[j + 1, k] - d[j, k] + 1e-30), 0, 1)
        return th_j[j, k] + t * (th_j[j + 1, k] - th_j[j, k])

    def estimate(self, x, G, T_meas):
        th = self._theta_raw(np.atleast_1d(x), None if G is None else np.atleast_1d(G))
        return th - np.polyval(self.kT, th) * (T_meas - T_REF)


def draw(rng, n, sources):
    """Conditions for n readings; sources not listed stay at their reference value."""
    th = rng.uniform(*TH_RANGE, n)
    sw = np.clip(SIGMA_REF * np.exp(rng.normal(0, SIGMA_LN_SD, n)), *SIGMA_CLIP) if 'EC' in sources else np.full(n, SIGMA_REF)
    T = np.clip(rng.normal(T_REF, T_SD, n), *T_CLIP) if 'T' in sources else np.full(n, T_REF)
    Tm = T + (rng.normal(0, T_ERR_SD, n) if 'T' in sources else 0)
    gap = np.minimum(rng.exponential(GAP_MEAN, n), GAP_MAX) if 'contact' in sources else np.zeros(n)
    unit = rng.normal(0, 1, n) if 'unit' in sources else np.zeros(n)
    return th, sw, T, Tm, gap, unit


def run(d, sources, n=4000, seed=11):
    rng = np.random.default_rng(seed)
    th, sw, T, Tm, gap, unit = draw(rng, n, sources)
    x, G = d.x(th, sw, T, gap, unit * GEOMS[d.geom]['tol_sd'])
    if G is not None:
        G = G * (1 + rng.normal(0, G_GAIN_SD, n) * ('unit' in sources)) + rng.normal(0, G_NOISE, n)
    return th, 100 * (d.estimate(x, G, Tm) - th)


SOURCE_SETS = [('all', ('EC', 'T', 'contact', 'unit')), ('ideal_contact', ('EC', 'T', 'unit')), ('EC', ('EC',)),
               ('T', ('T',)), ('contact', ('contact',)), ('unit', ('unit',)), ('none', ())]


def robustness(designs):
    """Total RMSE when the assumed spread of salinity or the mean air gap is halved or doubled."""
    g = globals()
    out = {}
    for name, key, vals in (('EC spread, sd of ln', 'SIGMA_LN_SD', (0.25, 0.5, 1.0)), ('mean air gap, mm', 'GAP_MEAN', (0.01, 0.02, 0.04))):
        keep = g[key]
        for v in vals:
            g[key] = v
            out[f'{name} = {v}'] = {d.key: stats(run(d, ('EC', 'T', 'contact', 'unit'))[1])['rmse'] for d in designs}
        g[key] = keep
    return out


def _boot(fn, n, nb=300, seed=3):
    rng = np.random.default_rng(seed)
    v = np.array([fn(rng.integers(0, n, n)) for _ in range(nb)])
    return float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))


def stats(e, ci=False):
    out = dict(bias=float(e.mean()), sd=float(e.std()), rmse=float(np.sqrt((e**2).mean())),
               p95=float(np.percentile(np.abs(e), 95)))
    if ci: out['ci'] = _boot(lambda i: np.sqrt((e[i]**2).mean()), len(e))
    return out


def paired_difference(d1, d2, sources=('EC', 'T', 'contact', 'unit')):
    """RMSE(d1) - RMSE(d2) on the same draws, with a paired bootstrap 95 % interval."""
    e1, e2 = run(d1, sources)[1], run(d2, sources)[1]
    lo, hi = _boot(lambda i: np.sqrt((e1[i]**2).mean()) - np.sqrt((e2[i]**2).mean()), len(e1))
    return float(np.sqrt((e1**2).mean()) - np.sqrt((e2**2).mean())), lo, hi


# (label, a, alpha, ec): shapes from organic_soil_spectra.py (median, weakest and strongest third
# of 24 moist organic-soil spectra); f_r = 1 MHz at the reference state in all of them
DISPERSION_CASES = [('none', 0.0, 0.75, 1.0), ('median shape, f_r ~ EC', 3.09, 0.75, 1.0),
                    ('weak shape, f_r ~ EC', 2.15, 0.68, 1.0), ('strong shape, f_r ~ EC', 5.65, 0.55, 1.0),
                    ('median shape, f_r fixed', 3.09, 0.75, 0.0)]
RATIO_MEDIAN = (1.37, 1.18, 1.11)                 # measured e'(20, 100, 300 MHz) / e'(1 GHz), median


def refit_shape(fr):
    """(a, alpha) reproducing RATIO_MEDIAN for a relaxation anchored at fr instead of 1 MHz."""
    from scipy.optimize import least_squares
    fq = np.array([20e6, 100e6, 300e6])
    r = lambda p, f: 1 + p[0] / (1 + (1j * f / fr) ** (1 - p[1]))
    res = lambda p: r(p, fq).real / r(p, 1e9).real - RATIO_MEDIAN
    return least_squares(res, [3.0, 0.7], bounds=([0.05, 0.2], [200, 0.9])).x
TC_MEASURED = 0.15                                # %/K, e'(100 MHz) of moist organic soil, 5-25 C


def _tc_100MHz(tc):
    DISPERSION['tc'] = tc
    e = [soil_eps(0.30, SIGMA_REF, T, 100e6)[0] for T in (5.0, 25.0)]
    return 100 * np.log(e[1] / e[0]) / 20


def dispersion_study():
    """RMSE of every design (all sources / ideal contact / EC only / T only) when the substrate
    has its own relaxation; designs are recalibrated in the dispersive medium at the reference
    state.  The temperature coefficient of f_r is set to reproduce the measured coefficient of
    e'(100 MHz)."""
    from scipy.optimize import brentq
    out = {}
    cases = [c + (1e6,) for c in DISPERSION_CASES]
    for fr in (0.1e6, 10e6):                         # the 1 MHz anchor is not identified by the spectra
        a, alpha = refit_shape(fr)
        cases.append((f'median shape, anchor {fr/1e6:g} MHz', float(a), float(alpha), 1.0, fr))
    for label, a, alpha, ec, fr0 in cases:
        DISPERSION.update(a=a, alpha=alpha, ec=ec, tc=0.02, fr=fr0)
        tc = brentq(lambda t: _tc_100MHz(t) - TC_MEASURED, 0.0, 0.5) if a else 0.02
        DISPERSION['tc'] = tc
        e20, e100, e1g = (float(soil_eps(0.30, SIGMA_REF, 25.0, f)[0]) for f in (20e6, 100e6, 1e9))
        ds = [Design(*x) for x in DESIGNS]
        out[label] = dict(tc=tc, a=a, alpha=alpha, fr=fr0, ratio20=e20 / e1g, ratio100=e100 / e1g,
                          rmse={d.key: [stats(run(d, src)[1])['rmse'] for src in (SOURCE_SETS[0][1], SOURCE_SETS[1][1], ('EC',), ('T',))] for d in ds})
    DISPERSION.update(a=0.0, alpha=0.75, ec=1.0, tc=0.02, fr=1e6)
    return out


def frequency_sweep(geoms=('outer12', 'outer20', 'buried20'), freqs=np.geomspace(1e5, 3e8, 36)):
    """RMSE of an ideal parallel-capacitance reading against frequency, EC and temperature varying."""
    out = {}
    for g in geoms:
        rm = []
        for f in freqs:
            d = Design('-', g, 'cp', f, '')
            rm.append(stats(run(d, ('EC', 'T'), 2000)[1])['rmse'] if d.usable else float('nan'))
        out[g] = rm
    return freqs, out


def as_built(n=400, seed=5):
    """The built design through the full model of system_sim.py (ngspice oscillator table,
    stub, physics-based table and water-permittivity temperature correction)."""
    import probe as p, system_sim as S
    S.OSC = S.Oscillator()
    rng = np.random.default_rng(seed)
    th, sw, T, Tm, gap, unit = draw(rng, n, ('EC', 'T', 'contact', 'unit'))
    err = {'f': [], 'fd': []}
    for i in range(n):
        u, mix = S.random_unit(rng)
        fw = S.Firmware(u, mix)
        f, det = S.measure(S.soil(th[i], sw[i], T[i]), u, mix=dict(mix, **S.gap_mix(gap[i])), dT=T[i] - 25.0)
        if not np.isfinite(f): continue
        f *= 1 + rng.normal(0, 2e-5); det += rng.normal(0, 0.3e-3)
        err['f'].append(100 * (fw.theta(f, det, Tm[i], False)[0] - th[i]))
        err['fd'].append(100 * (fw.theta(f, det, Tm[i], True)[0] - th[i]))
    return {k: stats(np.array(v)) for k, v in err.items()}


def tables_md(designs, res, built, ctl, rob, disp):
    """Markdown bodies of the manuscript's result tables, from the numbers just computed."""
    short = {d.key: f"{d.geom}, {d.label.split(', ', 1)[1]}" for d in designs}
    t4 = ['| | Design | RMSE (95 % interval) | Bias | 95 % within | Ideal contact | EC | T | Contact | Unit |', '|---|---|---|---|---|---|---|---|---|---|']
    for d in designs:
        r = res[d.key]; a = r['all']
        t4.append(f"| {d.key} | {short[d.key]} | {a['rmse']:.1f} ({a['ci'][0]:.1f}–{a['ci'][1]:.1f}) | {a['bias']:+.1f} | {a['p95']:.1f} | "
                  f"{r['ideal_contact']['rmse']:.1f} | {r['EC']['rmse']:.1f} | {r['T']['rmse']:.1f} | {r['contact']['rmse']:.1f} | {r['unit']['rmse']:.1f} |")
    for k, lab in (('f', 'as I, circuit-level model, frequency only'), ('fd', 'as I, circuit-level model, with loss')):
        b = built[k]; t4.append(f"| J | {lab} | {b['rmse']:.1f} | {b['bias']:+.1f} | {b['p95']:.1f} | | | | | |")
    keys = [d.key for d in designs]
    t5 = ['| Assumption | ' + ' | '.join(keys) + ' |', '|---' * (len(keys) + 1) + '|']
    for k, v in rob.items(): t5.append(f"| {k} | " + ' | '.join(f'{v[x]:.1f}' for x in keys) + ' |')
    t6 = ['| Electrodes, frequency, readout | All sources | EC only | Ideal contact |', '|---|---|---|---|']
    for c in CONTROLS: t6.append(f"| {c[4]} | {ctl[c[0]]['all']:.1f} | {ctl[c[0]]['EC']:.1f} | {ctl[c[0]]['ideal_contact']:.1f} |")
    k7 = [k for k in keys if k != 'C']
    t7 = ["| Relaxation | ε′(100 MHz)/ε′(1 GHz) | " + ' | '.join(k7) + ' |', '|---' * (len(k7) + 2) + '|']
    for k, v in disp.items(): t7.append(f"| {k} | {v['ratio100']:.2f} | " + ' | '.join(f"{v['rmse'][x][0]:.1f} / {v['rmse'][x][2]:.1f}" for x in k7) + ' |')
    return dict(T4=t4, T5=t5, T6=t6, T7=t7)


def update_manuscript(tables):
    """Replace the table bodies between <!-- Tn --> markers in paper/manuscript.md."""
    import re
    path = os.path.join(HERE, '..', 'paper', 'manuscript.md')
    if not os.path.exists(path): return
    txt = open(path, encoding='utf8').read()
    for k, rows in tables.items():
        txt = re.sub(rf'(<!-- {k} -->\n).*?(<!-- /{k} -->)', lambda m: m.group(1) + '\n'.join(rows) + '\n' + m.group(2), txt, flags=re.S)
    open(path, 'w', encoding='utf8').write(txt)


# ---------------------------------------------------------------------------- figures
INK, MUTED, GRID, SURFACE = '#0b0b0b', '#52514e', '#e4e3df', '#fcfcfb'
BLUE, ORANGE, AQUA, YELLOW = '#2a78d6', '#eb6834', '#1baf7a', '#eda100'
BLUES = ['#86b6ef', '#2a78d6', '#104281']


def _style():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 9, 'figure.dpi': 200, 'axes.edgecolor': MUTED, 'axes.labelcolor': INK,
                         'text.color': INK, 'xtick.color': MUTED, 'ytick.color': MUTED, 'axes.grid': True,
                         'grid.color': GRID, 'grid.linewidth': 0.6, 'axes.spines.top': False, 'axes.spines.right': False,
                         'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE, 'savefig.facecolor': SURFACE,
                         'axes.axisbelow': True, 'legend.frameon': False})
    return plt


def figures(designs, res, sweep, built):
    plt = _style()
    os.makedirs(FIGS, exist_ok=True)
    from matplotlib.patches import Rectangle

    # Fig 1: cross-sections, vertical scale x4
    fig, axs = plt.subplots(len(GEOMS), 1, figsize=(3.6, 5.6))
    for ax, (k, g) in zip(axs, GEOMS.items()):
        H = sum(t for t, _ in g['stack']['dielectrics']); W = g['W']; n = len(g['stack']['dielectrics'])
        zi = np.concatenate([[0], np.cumsum([t for t, _ in g['stack']['dielectrics']])]) - H / 2
        tc = g['coat'][0] if 'coat' in g else 0
        if tc: ax.add_patch(Rectangle((-W / 2 - tc, -H / 2 - tc - 0.05), W + 2 * tc, H + 2 * tc + 0.1, fc='#c3c2b7', ec='none'))
        ax.add_patch(Rectangle((-W / 2, -H / 2), W, H, fc='#d9e6d2', ec=MUTED, lw=0.5))
        for i in g['ifc']:
            y = zi[0] - 0.06 if i == 0 else zi[n] if i == n else zi[i] if zi[i] < 0 else zi[i] - 0.06
            for kind, x0, x1 in g['strips']:
                ax.add_patch(Rectangle((x0, y), x1 - x0, 0.06, fc=ORANGE if kind == 'S' else BLUE, ec='none'))
        ax.set_xlim(-11.5, 11.5); ax.set_ylim(-1.5, 1.5); ax.set_aspect(4); ax.grid(False)
        ax.set_yticks([]); ax.spines['left'].set_visible(False)
        ax.text(-11.3, 1.05, g['label'], fontsize=8.5, va='bottom')
        if ax is not axs[-1]: ax.set_xticks([]); ax.spines['bottom'].set_visible(False)
    axs[-1].set_xlabel('mm across the blade (thickness x4)')
    fig.tight_layout(); fig.savefig(f'{FIGS}/fig1_cross_sections.png'); plt.close(fig)

    # Fig 2: normalised response, one panel per design, three salinities
    fig, axs = plt.subplots(3, 3, figsize=(7.2, 6.4), sharex=True, sharey=True)
    th = np.linspace(0.02, 0.58, 60)
    for ax, d in zip(axs.ravel(), designs):
        for sw, c, lab in zip((0.03, 0.10, 0.30), BLUES, ('0.3 dS/m', '1 dS/m', '3 dS/m')):
            ax.plot(th, d.x(th, sw, T_REF)[0], color=c, lw=1.6, label=lab)
        ax.set_title(f'{d.key}  ' + d.label.replace(', ', '\n    '), fontsize=7.5, loc='left'); ax.set_ylim(-0.05, 1.3)
    for ax in axs[-1]: ax.set_xlabel('volumetric water content')
    for ax in axs[:, 0]: ax.set_ylabel('normalized reading x')
    h, l = axs[0, 0].get_legend_handles_labels()
    fig.legend(h, l, title='pore-water EC', ncol=3, fontsize=8, title_fontsize=8, loc='lower center')
    fig.tight_layout(rect=(0, 0.07, 1, 1)); fig.savefig(f'{FIGS}/fig2_response.png'); plt.close(fig)

    # Fig 3: total RMSE, ranked
    rows = [(f'{d.key}  {d.label}', res[d.key]['all']['rmse'] if d.usable else np.inf) for d in designs]
    rows.append(('J  As built: buried 20 mm, full oscillator model, with loss', built['fd']['rmse']))
    rows.sort(key=lambda r: r[1])
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    y = np.arange(len(rows))[::-1]
    ax.barh(y, [r[1] if np.isfinite(r[1]) else 0 for r in rows], height=0.62, color=BLUE)
    for yy, r in zip(y, rows):
        ax.text(r[1] + 0.25 if np.isfinite(r[1]) else 0.25, yy, f'{r[1]:.1f}' if np.isfinite(r[1]) else 'no usable response', va='center', fontsize=8)
    ax.set_yticks(y); ax.set_yticklabels([r[0] for r in rows], fontsize=8, color=INK)
    ax.set_xlim(0, 17); ax.set_xlabel('RMSE, % volumetric water content (all sources)'); ax.grid(axis='y', visible=False)
    fig.subplots_adjust(left=0.50, right=0.97, bottom=0.15, top=0.97); fig.savefig(f'{FIGS}/fig3_rmse.png'); plt.close(fig)

    # Fig 4: contributions by source, grouped
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    src = [('EC', BLUE, 'pore-water EC'), ('T', ORANGE, 'temperature'), ('contact', AQUA, 'contact'), ('unit', YELLOW, 'unit tolerance')]
    shown = [d for d in designs if d.usable]            # a response that is not monotonic has no error budget
    y = np.arange(len(shown))[::-1] * 1.0
    for k, (key, c, lab) in enumerate(src):
        v = [res[d.key][key]['rmse'] for d in shown]
        ax.barh(y + (1.5 - k) * 0.19, v, height=0.17, color=c, label=lab)
    ax.set_yticks(y); ax.set_yticklabels([f'{d.key}  {d.label}' for d in shown], fontsize=8, color=INK)
    ax.set_xlim(0, 15); ax.set_xlabel('RMSE with only this source varying, % VWC')
    ax.grid(axis='y', visible=False); ax.legend(fontsize=8, loc='lower right')
    fig.tight_layout(); fig.savefig(f'{FIGS}/fig4_sources.png'); plt.close(fig)

    # Fig 5: frequency.  No point is drawn where the response is not usable (non-monotonic, or the
    # water calibration point beyond the quarter-wave resonance, marked by the dotted lines)
    freqs, out = sweep
    fig, ax = plt.subplots(figsize=(6.0, 3.6))
    for (g, c) in zip(out, (ORANGE, BLUE, AQUA)):
        ax.plot(freqs / 1e6, out[g], color=c, lw=2, marker='o', ms=3, label=GEOMS[g]['label'])
        ax.axvline(quarter_wave(g) / 1e6, color=c, lw=1, ls=':')
    ax.set_xscale('log'); ax.set_yscale('log'); ax.set_ylim(0.05, 10)
    ax.set_xlabel('measurement frequency, MHz'); ax.set_ylabel('RMSE from EC and temperature, % VWC')
    ax.legend(fontsize=8, loc='lower left', title='dotted: quarter wave in water', title_fontsize=7.5)
    fig.tight_layout(); fig.savefig(f'{FIGS}/fig5_frequency.png'); plt.close(fig)

    # Fig 6: error against water content for three designs
    fig, axs = plt.subplots(1, 3, figsize=(7.2, 2.7), sharey=True)
    for ax, key in zip(axs, ('B', 'F', 'I')):
        d = next(x for x in designs if x.key == key)
        th, e = run(d, ('EC', 'T', 'contact', 'unit'), 1500)
        ax.scatter(th, e, s=3, color=BLUE, alpha=0.35, linewidths=0)
        ax.axhline(0, color=MUTED, lw=0.8); ax.set_ylim(-15, 15)
        ax.set_title(f'{d.key}  ' + d.label.replace(', ', '\n    '), fontsize=7.5, loc='left'); ax.set_xlabel('true water content')
    axs[0].set_ylabel('error, % VWC')
    fig.tight_layout(); fig.savefig(f'{FIGS}/fig6_scatter.png'); plt.close(fig)


if __name__ == '__main__':
    for g in GEOMS:
        for v in VARIANTS: table(g, v)
    designs = [Design(*a) for a in DESIGNS]
    res = {d.key: {name: stats(run(d, src)[1], ci=(name == 'all')) for name, src in SOURCE_SETS} for d in designs}
    lines = [f'nominal: theta {TH_RANGE}, pore-water EC lognormal about {SIGMA_REF} S/m (sd ln {SIGMA_LN_SD}), '
             f'T {T_REF} +/- {T_SD} C, air gap exp({GAP_MEAN} mm), thermistor +/-{T_ERR_SD} C',
             f"{'design':46s} {'x(0.3)':>6s} {'mono':>4s} | {'RMSE':>5s} {'bias':>5s} {'sd':>5s} {'p95':>5s} {'ideal':>5s} | "
             f"{'EC':>5s} {'T':>5s} {'cont':>5s} {'unit':>5s} {'resid':>5s}   [% VWC]"]
    for d in designs:
        r = res[d.key]
        lines.append(f"{d.key} {d.label:44s} {float(np.interp(0.3, d.th, d.x_ref)):6.3f} {str(d.mono)[0]:>4s} | "
                     f"{r['all']['rmse']:5.2f} {r['all']['bias']:+5.2f} {r['all']['sd']:5.2f} {r['all']['p95']:5.2f} {r['ideal_contact']['rmse']:5.2f} | "
                     f"{r['EC']['rmse']:5.2f} {r['T']['rmse']:5.2f} {r['contact']['rmse']:5.2f} {r['unit']['rmse']:5.2f} {r['none']['rmse']:5.2f}")
    print('\n'.join(lines)); sys.stdout.flush()
    lines.append('\ncontrolled readout comparison: RMSE all sources | EC only | ideal contact  [% VWC]')
    ctl = {}
    for c in CONTROLS:
        d = Design(*c)
        ctl[c[0]] = {n: stats(run(d, src)[1])['rmse'] for n, src in SOURCE_SETS[:3]}
        lines.append(f"{c[0]} {c[4]:40s} {ctl[c[0]]['all']:5.2f} | {ctl[c[0]]['EC']:5.2f} | {ctl[c[0]]['ideal_contact']:5.2f}")
    print('\n'.join(lines[-len(CONTROLS) - 1:])); sys.stdout.flush()
    by = {d.key: d for d in designs}
    pairs = {f'{a}-{b}': paired_difference(by[a], by[b]) for a, b in (('F', 'G'), ('G', 'H'), ('H', 'I'), ('E', 'F'))}
    lines.append('\npaired RMSE differences on the same draws [% VWC], 95 % bootstrap interval')
    for k, v in pairs.items(): lines.append(f'  {k}: {v[0]:+.2f} ({v[1]:+.2f} to {v[2]:+.2f})')
    lines.append('95 % interval of total RMSE: ' + ', '.join(f"{d.key} {res[d.key]['all']['ci'][0]:.2f}-{res[d.key]['all']['ci'][1]:.2f}" for d in designs))
    lines.append('quarter-wave frequency in the water calibration medium, MHz: ' + ', '.join(f'{g} {quarter_wave(g)/1e6:.0f}' for g in GEOMS))
    print('\n'.join(lines[-9:])); sys.stdout.flush()
    sweep = frequency_sweep()
    lines.append('\nideal parallel-C reading, RMSE from EC and T [% VWC] vs frequency [MHz]')
    lines.append('f      ' + ' '.join(f'{f/1e6:7.2f}' for f in sweep[0]))
    for g, v in sweep[1].items(): lines.append(f'{g:8s}' + ' '.join(f'{x:7.2f}' for x in v))
    disp = dispersion_study()
    lines.append("\nsubstrate relaxation: RMSE all sources / ideal contact / EC only / T only [% VWC]")
    lines.append(f"{'case':26s} {'tc 1/K':>6s} {'e20/e1G':>7s} {'e100/e1G':>8s} " + ' '.join(f'{d.key:>19s}' for d in designs))
    for k, v in disp.items():
        lines.append(f"{k:26s} {v['tc']:6.3f} {v['ratio20']:7.2f} {v['ratio100']:8.2f} " + ' '.join('{:4.1f}/{:4.1f}/{:4.1f}/{:4.1f}'.format(*v['rmse'][d.key]) for d in designs))
    rob = robustness(designs)
    lines.append('\ntotal RMSE [% VWC] under changed assumptions: ' + ' '.join(f'{d.key:>6s}' for d in designs))
    for k, v in rob.items(): lines.append(f'{k:45s} ' + ' '.join(f'{v[d.key]:6.2f}' for d in designs))
    built = as_built(int(sys.argv[1]) if len(sys.argv) > 1 else 2000)
    lines.append(f"\nJ as built, full model: frequency only {built['f']}; frequency + detector {built['fd']}")
    print('\n'.join(lines[len(designs) + 2:]))
    with open(f'{RESULTS}/design_comparison.txt', 'w') as fh: fh.write('\n'.join(lines) + '\n')
    json.dump(dict(res=res, built=built, robustness=rob, controls=ctl, dispersion=disp, pairs=pairs, sweep=dict(f=list(sweep[0]), **sweep[1])), open(f'{RESULTS}/design_comparison.json', 'w'), indent=1)
    figures(designs, res, sweep, built)
    update_manuscript(tables_md(designs, res, built, ctl, rob, disp))
