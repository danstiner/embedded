#!/usr/bin/env python3
"""End-to-end model of the probe: soil state -> complex permittivity -> strip-line admittance
(probe.py) -> oscillator frequency and detector voltage (ngspice table from
spice/characterize.py) -> what the firmware computes -> volumetric water content.

Firmware model, in order:
  1. two-point calibration per probe: x = (f^-2 - f_air^-2) / (f_water^-2 - f_air^-2) and
     q = det / det_air cancel that unit's inductor, stray capacitance and detector gain;
  2. (x, q) -> medium permittivity e' and bulk EC through a 2-D table that is the same for
     every unit (here from the nominal model; on the bench from reference liquids);
  3. e' -> theta by a mixing model with the water permittivity at the measured temperature.
Step 2 can ignore the detector ("f only"): x is then read through the lossless column.

Outputs: one-at-a-time error budget and a Monte Carlo over fab tolerance, component tolerance,
salinity, temperature, contact and readout noise.  ../results/system_sim.txt, fig_system.png"""
import os, sys
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from scipy.optimize import brentq
import soil_probe_sim as s
import probe as p

EPS0 = s.EPS0
MEDIA = {                       # CRIM parameters (porosity, solid permittivity), theta range
    'potting mix': dict(porosity=0.70, er_solid=4.0, th_max=0.60),
    'mineral soil': dict(porosity=0.45, er_solid=5.0, th_max=0.42),
}
SIGMA_REF = 0.05                # pore-water EC the generic curve assumes, S/m
WATER_CAL = (s.water_er(25.0), 0.005, 0.0)      # low-EC tap / deionised water at 25 C
TC_ELECTRONICS = -45e-6         # df/f per C: BJT (ngspice, -20 ppm) + wirewound L (+50 ppm/C in L)


def soil(theta, sigma_w=SIGMA_REF, T=25.0, medium='potting mix'):
    m = MEDIA[medium]
    er = s.crim_er(theta, m['porosity'], m['er_solid'], s.water_er(T))
    return (er, s.soil_sigma(theta, sigma_w) * (1 + 0.02 * (T - 25.0)), 0.0)


def theta_from_er(er, T=25.0, medium='potting mix'):
    m = MEDIA[medium]
    return (np.sqrt(np.maximum(er, 1.0)) - (1 - m['porosity']) * np.sqrt(m['er_solid']) - m['porosity']) / (np.sqrt(s.water_er(T)) - 1)


class Oscillator:
    """ngspice table f(C, G), detector(C, G); unit-to-unit and drift perturbations on top."""

    def __init__(self, tag='nominal'):
        d = np.load(f'{p.RESULTS}/osc_table_{tag}.npz')
        ok = np.isfinite(d['f']).all(axis=0)
        self.C, self.G = d['C'], d['G'][ok]
        self.Gmax = self.G[-1]
        ax = (self.C * 1e12, self.G * 1e3)
        self._y = RegularGridInterpolator(ax, 1e18 / (2 * np.pi * d['f'][:, ok])**2, method='cubic')   # 1/w^2, ns^2
        self._det = RegularGridInterpolator(ax, d['det'][:, ok] * 1e3, method='cubic')
        self._amp = RegularGridInterpolator(ax, d['amp'][:, ok] * 1e3, method='cubic')
        # tank inductance seen by the probe: slope of 1/w^2 against C
        self.L = (self._y([30.0, 0.0])[0] - self._y([10.0, 0.0])[0]) * 1e-18 / 20e-12

    def read(self, C, G, dL=0.0, dC0=0.0, dtau=0.0, dT=0.0, amp_scale=1.0, det_off=0.0):
        """(f [Hz], det [V]) for probe load C [F], G [S].  dL fractional, dC0 [F], dtau [s].
        Loads beyond the table are clamped; stalled() says whether the oscillator would stop."""
        pt = [np.clip((C + dC0) * 1e12, 0, self.C[-1] * 1e12), np.clip(G * 1e3, 0, self.Gmax * 1e3)]
        y = (self._y(pt)[0] * 1e-18 + self.L * dtau * G) * (1 + dL)
        f = 1 / (2 * np.pi * np.sqrt(y)) * (1 + TC_ELECTRONICS * dT)
        return f, self._det(pt)[0] * 1e-3 * amp_scale + det_off

    def stalled(self, C, G):
        return G > self.Gmax or C > self.C[-1]

    def G_from_det(self, det, C):
        """Invert the nominal detector curve at capacitance C."""
        g = np.linspace(0, self.Gmax, 60)
        d = self._det(np.c_[np.full_like(g, min(C, self.C[-1]) * 1e12), g * 1e3]) * 1e-3
        return float(np.interp(det, d, g))          # det rises monotonically (toward 0) with G


OSC = None


def _settle(Yfun, unit=None, dT=0.0):
    """Self-consistent oscillation frequency: the load depends on frequency through the line
    and through sigma/w.  Returns (f, det, C, G)."""
    u = unit or {}
    def load(f):
        Y = Yfun(f)
        return Y.imag / (2 * np.pi * f), Y.real
    h = lambda f: OSC.read(*load(f), dT=dT, **u)[0] - f
    f = brentq(h, 40e6, 160e6, xtol=50.0)
    C, G = load(f)
    return (f, OSC.read(C, G, dT=dT, **u)[1], C, G)


def measure(mat, unit=None, exposed_mm=0.0, mix=None, variant='nominal', dT=0.0):
    """Oscillator frequency and detector voltage for the probe in medium `mat`
    (nan, nan if the load stalls the oscillator)."""
    f, det, C, G = _settle(lambda f: p.feed_Y(mat, f, variant=variant, exposed_mm=exposed_mm, mix=mix), unit, dT)
    return (np.nan, np.nan) if OSC.stalled(C, G) else (f, det)


_NOMINAL = {}


def nominal_map():
    """Design-wide lookup the firmware carries: normalised frequency x and detector ratio q
    over a grid of medium permittivity and conductivity, from the nominal model."""
    if not _NOMINAL:
        ers = np.exp(np.linspace(0, np.log(85), 34))
        sigs = np.concatenate([[0], np.exp(np.linspace(np.log(5e-4), np.log(0.6), 26))])
        f_air, det_air = measure(s.AIR)
        f_w = measure(WATER_CAL)[0]
        X = np.full((len(ers), len(sigs)), np.nan); Q = X.copy()
        for i, er in enumerate(ers):
            for j, sg in enumerate(sigs):
                f, det, C, G = _settle(lambda fr: p.feed_Y((er, sg, 0.0), fr))
                X[i, j] = (f**-2 - f_air**-2) / (f_w**-2 - f_air**-2)
                Q[i, j] = det / det_air if not OSC.stalled(C, G) else 0.0
        _NOMINAL.update(ers=ers, sigs=sigs, X=X, Q=Q, f_air=f_air, f_w=f_w, det_air=det_air)
    return _NOMINAL


class Firmware:
    """Calibration constants one unit carries (its own air and water readings) and the
    conversion it runs on (frequency, detector, temperature)."""

    def __init__(self, unit=None, mix=None, per_probe=True, medium='potting mix'):
        self.medium = medium
        n = nominal_map()
        if per_probe:
            self.f_air, self.det_air = measure(s.AIR, unit, mix=mix)
            self.f_w = measure(WATER_CAL, unit, mix=mix)[0]
        else:
            self.f_air, self.det_air, self.f_w = n['f_air'], n['det_air'], n['f_w']

    def theta(self, f, det, T, use_det=True):
        """Returns (theta, bulk EC [S/m] or nan)."""
        n = nominal_map()
        f = f * (1 - TC_ELECTRONICS * (T - 25.0))
        x = (f**-2 - self.f_air**-2) / (self.f_w**-2 - self.f_air**-2)
        if not use_det:                                   # read through the lossless column
            return theta_from_er(np.interp(x, n['X'][:, 0], n['ers']), T, self.medium), np.nan
        q = det / self.det_air
        # along each conductivity column find the permittivity that gives x, then pick the
        # column whose detector ratio matches
        er_j = np.array([np.interp(x, n['X'][:, j], n['ers']) for j in range(len(n['sigs']))])
        q_j = np.array([np.interp(er_j[j], n['ers'], n['Q'][:, j]) for j in range(len(n['sigs']))])
        d = q_j - q
        k = np.where((d[:-1] > 0) & (d[1:] <= 0))[0]
        if len(k) == 0:
            j0, t = (0, 0.0) if d[0] <= 0 else (len(d) - 2, 1.0)
        else:
            j0 = k[0]; t = d[j0] / (d[j0] - d[j0 + 1])
        er = er_j[j0] + t * (er_j[j0 + 1] - er_j[j0])
        sig = n['sigs'][j0] + t * (n['sigs'][j0 + 1] - n['sigs'][j0])
        return theta_from_er(er, T, self.medium), sig


UNIT_SIGMA = dict(dL=0.02 / 2, dC0=1.0e-12, dtau=25e-12, amp_scale=0.03, det_off=1.5e-3)   # 1-sigma
MIX_SIGMA = {'prepreg+10': 0.5, 'dk+5': 0.5, 'mask+33': 0.5, 'etch-50um': 0.5}             # in units of the variant


def random_unit(rng):
    unit = {k: rng.normal(0, v) for k, v in UNIT_SIGMA.items()}
    unit['amp_scale'] += 1.0
    return unit, {k: rng.normal(0, v) for k, v in MIX_SIGMA.items()}


def budget(out):
    fw = Firmware()
    rows = [
        ('pore-water EC 0.05 -> 0.10 S/m', dict(sigma_w=0.10)),
        ('pore-water EC 0.05 -> 0.30 S/m', dict(sigma_w=0.30)),
        ('soil +10 C, NTC reads true T', dict(T=35.0)),
        ('soil +10 C, NTC 2 C low', dict(T=35.0, T_meas=33.0)),
        ('air gap 0.05 mm, one face', dict(variant='gap50')),
        ('air gap 0.10 mm, one face', dict(variant='gap100')),
        ('air gap 0.10 mm, both faces', dict(variant='gap100x2')),
        ('water film 0.10 mm, one face', dict(variant='film100')),
        ('3 mm of strip above the soil', dict(exposed_mm=3.0)),
        ('prepreg +10 %, uncalibrated', dict(mix={'prepreg+10': 1.0}, cal=False)),
        ('prepreg +10 %, 2-point cal', dict(mix={'prepreg+10': 1.0})),
        ('laminate Dk +5 %, 2-point cal', dict(mix={'dk+5': 1.0})),
        ('mask +33 %, 2-point cal', dict(mix={'mask+33': 1.0})),
        ('inner etch -50 um, 2-point cal', dict(mix={'etch-50um': 1.0})),
        ('L +2 %, C0 +2 pF, uncalibrated', dict(unit=dict(dL=0.02, dC0=2e-12), cal=False)),
        ('L +2 %, C0 +2 pF, 2-point cal', dict(unit=dict(dL=0.02, dC0=2e-12))),
        ('oscillator delay +25 ps', dict(unit=dict(dtau=25e-12))),
        ('detector gain +5 %', dict(unit=dict(amp_scale=1.05), cal_unit={})),
        ('detector offset +2 mV after cal', dict(unit=dict(det_off=2e-3), cal_unit={})),
        ('electronics 10 C from soil NTC', dict(dT_elec=10.0)),
    ]
    ths = (0.10, 0.25, 0.40, 0.55)
    hdr = f"{'perturbation (potting mix)':34s} | " + '  '.join(f'th={t:.2f}' for t in ths) + '  | ' + '  '.join(f'th={t:.2f}' for t in ths)
    out(f"\nApparent-theta error [% VWC].  Left: frequency only.  Right: frequency + detector.\n{hdr}")
    base = {t: None for t in ths}
    for name, kw in [('(model self-check, no perturbation)', {})] + rows:
        kw = dict(kw)
        cal = kw.pop('cal', True); unit = kw.pop('unit', None); mix = kw.pop('mix', None)
        cal_unit = kw.pop('cal_unit', unit)
        T = kw.pop('T', 25.0); T_meas = kw.pop('T_meas', T); dT_elec = kw.pop('dT_elec', 0.0)
        sw = kw.pop('sigma_w', SIGMA_REF)
        f_w = Firmware(cal_unit, mix, per_probe=cal) if (unit or mix) else fw
        e_f, e_d = [], []
        for t in ths:
            f, det = measure(soil(t, sw, T), unit, mix=mix, dT=T - 25.0 + dT_elec, **kw)
            if not np.isfinite(f): e_f.append(np.nan); e_d.append(np.nan); continue
            a = f_w.theta(f, det, T_meas, use_det=False)[0] - t
            b = f_w.theta(f, det, T_meas, use_det=True)[0] - t
            if base[t] is None: base[t] = (a, b)
            e_f.append(100 * (a - base[t][0])); e_d.append(100 * (b - base[t][1]))
        if name.startswith('(model'):
            e_f = [100 * base[t][0] for t in ths]; e_d = [100 * base[t][1] for t in ths]
        out(f"{name:34s} | " + '  '.join(f'{e:+7.2f}' for e in e_f) + '  | ' + '  '.join(f'{e:+7.2f}' for e in e_d))


def monte_carlo(out, n=600, medium='potting mix', seed=7):
    rng = np.random.default_rng(seed)
    th_max = MEDIA[medium]['th_max']
    res = {k: [] for k in ('none_f', 'cal_f', 'cal_fd', 'theta', 'sigma_w', 'ec_true', 'ec_est', 'gap')}
    fw_nom = Firmware(per_probe=False, medium=medium)
    for i in range(n):
        unit, mix = random_unit(rng)
        fw = Firmware(unit, mix, medium=medium)
        th = rng.uniform(0.03, th_max)
        sw = np.exp(rng.uniform(np.log(0.02), np.log(0.40)))
        T = rng.uniform(5, 40)
        gap = min(rng.exponential(0.02), 0.10)                       # mm, one face, residual after firming
        mx = dict(mix); mx['gap100'] = gap / 0.10
        mat = soil(th, sw, T, medium)
        f, det = measure(mat, unit, exposed_mm=abs(rng.normal(0, 1.5)), mix=mx, dT=T - 25.0 + rng.normal(0, 3))
        if not np.isfinite(f): continue
        f *= 1 + rng.normal(0, 2e-5); det += rng.normal(0, 0.3e-3)
        Tm = T + rng.normal(0, 1.0)
        res['none_f'].append(fw_nom.theta(f, det, Tm, False)[0] - th)
        res['cal_f'].append(fw.theta(f, det, Tm, False)[0] - th)
        t_d, ec = fw.theta(f, det, Tm, True)
        res['cal_fd'].append(t_d - th)
        res['theta'].append(th); res['sigma_w'].append(sw); res['gap'].append(gap)
        res['ec_true'].append(mat[1]); res['ec_est'].append(ec)
    r = {k: np.array(v) for k, v in res.items()}
    out(f"\nMonte Carlo, {medium}, {len(r['theta'])} of {n} draws oscillating: theta 0.03-{th_max}, pore-water EC 0.02-0.4 S/m (log-uniform), "
        f"5-40 C, air gap exp(mean 0.02 mm), unit and fab tolerances 1-sigma {UNIT_SIGMA} / {MIX_SIGMA}")
    for key, label in (('none_f', 'no per-probe calibration, frequency only'),
                       ('cal_f', '2-point calibration, frequency only'),
                       ('cal_fd', '2-point calibration, frequency + detector')):
        e = 100 * r[key]
        out(f"  {label:44s} bias {e.mean():+5.2f}  sd {e.std():4.2f}  RMSE {np.sqrt((e**2).mean()):4.2f}  95 % within +/-{np.percentile(np.abs(e), 95):4.2f} % VWC")
    wet = r['ec_true'] > 0.005
    rel = r['ec_est'][wet] / r['ec_true'][wet] - 1
    out(f"  bulk EC estimate where EC_b > 0.05 dS/m: median error {100*np.median(rel):+.0f} %, 68 % within +/-{100*np.percentile(np.abs(rel), 68):.0f} %")
    return r


def figures(mc):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 10, 'figure.dpi': 140, 'axes.grid': True, 'grid.alpha': 0.3})
    fig, ax = plt.subplots(1, 3, figsize=(13, 4))
    th = np.linspace(0, 0.6, 25)
    for sw, c in ((0.02, 'tab:blue'), (0.05, 'tab:green'), (0.3, 'tab:red')):
        fd = np.array([measure(soil(t, sw)) for t in th])
        ax[0].plot(th, fd[:, 0] / 1e6, color=c, label=f'pore-water EC {sw*10:.1f} dS/m')
        ax[1].plot(th, -fd[:, 1] * 1e3, color=c)
    fa, fwat = measure(s.AIR)[0], measure(WATER_CAL)[0]
    ax[0].axhline(fa / 1e6, color='k', ls=':', lw=0.8); ax[0].axhline(fwat / 1e6, color='k', ls=':', lw=0.8)
    ax[0].text(0.01, fa / 1e6 - 3, 'air', fontsize=8); ax[0].text(0.01, fwat / 1e6 + 1, 'water', fontsize=8)
    ax[0].set_xlabel('volumetric water content'); ax[0].set_ylabel('oscillator frequency [MHz]'); ax[0].legend(fontsize=8)
    ax[0].set_title('Transfer curve, potting mix, 25 C')
    ax[1].set_xlabel('volumetric water content'); ax[1].set_ylabel('detector |V_ref - V_e| [mV]'); ax[1].set_title('Loss channel')
    for key, c, lab in (('cal_f', 'tab:orange', 'frequency only'), ('cal_fd', 'tab:blue', 'frequency + detector')):
        ax[2].scatter(mc['theta'], 100 * mc[key], s=5, color=c, alpha=0.5, label=lab)
    ax[2].axhline(0, color='k', lw=0.8); ax[2].set_ylim(-8, 8)
    ax[2].set_xlabel('true volumetric water content'); ax[2].set_ylabel('error [% VWC]'); ax[2].legend(fontsize=8)
    ax[2].set_title('Monte Carlo, 2-point calibrated units')
    fig.tight_layout(); fig.savefig(f'{p.RESULTS}/fig_system.png'); plt.close(fig)


if __name__ == '__main__':
    OSC = Oscillator()
    lines = []
    def out(x): print(x); lines.append(x)
    fa, da = measure(s.AIR); fwat, dw = measure(WATER_CAL)
    out(f"air {fa/1e6:.2f} MHz (detector {da*1e3:.1f} mV), water {fwat/1e6:.2f} MHz ({dw*1e3:.1f} mV); prescaler /1024 -> {fa/1024e3:.1f} / {fwat/1024e3:.1f} kHz")
    out(f"{'theta':>5s} {'EC_w':>5s} {'f MHz':>8s} {'det mV':>7s} {'C pF':>6s} {'G mS':>6s}")
    for sw in (0.05, 0.30):
        for t in (0.05, 0.15, 0.25, 0.35, 0.45, 0.55):
            f, det = measure(soil(t, sw)); Y = p.feed_Y(soil(t, sw), f)
            out(f"{t:5.2f} {sw:5.2f} {f/1e6:8.3f} {det*1e3:7.1f} {Y.imag/(2*np.pi*f)*1e12:6.2f} {Y.real*1e3:6.2f}")
    budget(out)
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    mc = monte_carlo(out, n)
    monte_carlo(out, n // 2, 'mineral soil')
    figures(mc)
    with open(f'{p.RESULTS}/system_sim.txt', 'w') as fh: fh.write('\n'.join(lines) + '\n')
