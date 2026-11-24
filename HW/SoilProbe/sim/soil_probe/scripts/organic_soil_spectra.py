#!/usr/bin/env python3
"""Parametrise the substrate relaxation used in design_comparison.py from measured spectra of
organic soils: Dielectric Database of Organic Arctic Soils (Savin et al. 2020, Earth Syst. Sci.
Data 12, 3481; data doi:10.5281/zenodo.3819912, CC BY 4.0).  The files give refractive index n
and normalised attenuation k against frequency for a range of volumetric moisture W and
temperature; e* = (n - jk)^2.

The dispersion between 15 MHz and 1 GHz is broad, so single-spectrum Cole-Cole fits are not
identifiable.  Instead the script reports model-independent quantities, the ratio of e' at
20, 100 and 300 MHz to its value at 1 GHz and the temperature coefficient of e'(100 MHz), and
fits the three parameters of the relaxation term
    e*(f) = e_hf [1 + a / (1 + (j f / f_r)^(1 - alpha))]
to the median ratios of the moist samples.  Writes ../results/organic_soil_fit.json and
../paper/figures/fig7_spectra.png."""
import json, os, urllib.request
import numpy as np
from scipy.optimize import least_squares
import xlrd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'results', 'ddoas')
URL = 'https://zenodo.org/api/records/3819912/files/{}/content'
SAMPLES = {'TM': 38, 'SI': 30, 'MS2': 35, 'BV': 50, 'MS1': 61, 'AK1': 80, 'AK2': 90}      # % organic matter
EPS0 = 8.8541878128e-12


def load(sample, sheet='t=25'):
    os.makedirs(DATA, exist_ok=True)
    path = f'{DATA}/{sample}.xls'
    if not os.path.exists(path): urllib.request.urlretrieve(URL.format(sample + '.xls'), path)
    b = xlrd.open_workbook(path)
    if sheet not in b.sheet_names(): return None
    sh = b.sheet_by_name(sheet)
    hdr = [str(x).lower() for x in sh.row_values(1)]
    cn = next(i for i, h in enumerate(hdr) if h.startswith('refractive'))
    ck = next(i for i, h in enumerate(hdr) if 'attenuation' in h)
    W = np.array([w for w in sh.row_values(2)[cn:ck] if isinstance(w, float)])
    rows = [r for r in (sh.row_values(i) for i in range(4, sh.nrows)) if isinstance(r[2], float)]
    num = lambda a: np.array([[x if isinstance(x, float) else np.nan for x in r] for r in a])
    f = np.array([r[2] for r in rows])
    n, k = num([r[cn:cn + len(W)] for r in rows]), num([r[ck:ck + len(W)] for r in rows])
    return f, W, (n - 1j * k)**2


FQ = np.array([20e6, 100e6, 300e6, 1e9])


def at(f, e, fq):
    """e at the frequencies fq, median over +/-5 % in frequency; nan where the data are unusable."""
    out = []
    for q in fq:
        m = (f > 0.95 * q) & (f < 1.05 * q) & np.isfinite(e) & (np.abs(e) < 150)
        out.append(np.median(e[m].real) + 1j * np.median(e[m].imag) if m.sum() else np.nan)
    return np.array(out)


def relax(p, f):
    a, fr, alpha = p
    return 1 + a / (1 + (1j * f / fr)**(1 - alpha))


def fit_ratios(target):
    """Cole-Cole parameters reproducing e'(f)/e'(1 GHz) at 20, 100 and 300 MHz."""
    res = lambda p: (relax(p, FQ[:3]).real / relax(p, FQ[3:]).real - target)
    r = least_squares(res, [1.0, 20e6, 0.5], bounds=([0.05, 1e6, 0.2], [20, 2e8, 0.75]), x_scale=[1, 1e7, 0.1])
    return r.x


if __name__ == '__main__':
    rows, keep = [], {}
    print(f"{'sample':6s} {'OM %':>4s} {'W':>5s} | e'(20M) e'(100M) e'(300M) e'(1G) | ratio to 1 GHz: 20M  100M  300M | e''(100M) | d ln e'(100M)/dT 5-25 C, %/K")
    for sname, om in SAMPLES.items():
        try:
            d25, d5 = load(sname), load(sname, 't=5')
        except Exception as ex:
            print(sname, 'unavailable:', ex); continue
        if d25 is None: continue
        f, W, E = d25
        for j, w in enumerate(W):
            if not 0.2 <= w <= 0.5: continue
            e = at(f, E[:, j], FQ)
            if not np.all(np.isfinite(e)) or e.real.min() < 2: continue
            tc = np.nan
            if d5 is not None and j < d5[2].shape[1]:
                e5 = at(d5[0], d5[2][:, j], FQ[1:2])[0]
                if np.isfinite(e5) and e5.real > 2: tc = 100 * np.log(e[1].real / e5.real) / 20
            r = e.real[:3] / e.real[3]
            rows.append(dict(sample=sname, om=om, W=float(w), ratio=list(map(float, r)), eim100=float(-e.imag[1]), tc=float(tc)))
            keep.setdefault(sname, (f, W, E))
            print(f"{sname:6s} {om:4d} {w:5.2f} | {e.real[0]:7.1f} {e.real[1]:8.1f} {e.real[2]:8.1f} {e.real[3]:6.1f} | {r[0]:19.2f} {r[1]:5.2f} {r[2]:5.2f} | {-e.imag[1]:9.1f} | {tc:6.2f}")
    R = np.array([r['ratio'] for r in rows])
    summary = {}
    for name, sel in (('all moist samples', np.ones(len(rows), bool)),
                      ('weakest third', R[:, 1] <= np.quantile(R[:, 1], 1 / 3)),
                      ('strongest third', R[:, 1] >= np.quantile(R[:, 1], 2 / 3))):
        tgt = np.median(R[sel], axis=0)
        p = fit_ratios(tgt)
        got = relax(p, FQ[:3]).real / relax(p, FQ[3:]).real
        summary[name] = dict(n=int(sel.sum()), target=list(map(float, tgt)), a=float(p[0]), fr=float(p[1]), alpha=float(p[2]))
        print(f"{name:18s} n={sel.sum():2d}  median ratios {np.round(tgt, 2)} -> a = {p[0]:.2f}, f_r = {p[1]/1e6:.1f} MHz, alpha = {p[2]:.2f} (reproduces {np.round(got, 2)})")
    tcs = np.array([r['tc'] for r in rows]); tcs = tcs[np.isfinite(tcs)]
    print(f"temperature coefficient of e'(100 MHz), 5-25 C: median {np.median(tcs):+.2f} %/K, quartiles {np.percentile(tcs, 25):+.2f} / {np.percentile(tcs, 75):+.2f} (n = {len(tcs)})")
    summary['tc_100MHz_pct_per_K'] = float(np.median(tcs))
    os.makedirs(os.path.join(HERE, '..', 'results'), exist_ok=True)
    json.dump(dict(rows=rows, summary=summary), open(os.path.join(HERE, '..', 'results', 'organic_soil_fit.json'), 'w'), indent=1)

    import design_comparison as D
    plt = D._style()
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 3.2))
    for (sname, c) in zip(keep, (D.BLUE, D.ORANGE, D.AQUA, D.YELLOW)):
        f, W, E = keep[sname]
        j = int(np.argmin(abs(W - 0.33)))
        m = (f >= 15e6) & (f <= 1.2e9) & (np.abs(E[:, j]) < 150)
        e1 = at(f, E[:, j], FQ[3:])[0].real
        axs[0].plot(f[m] / 1e6, E[m, j].real / e1, '-', lw=1.4, color=c, label=f'{sname}: {SAMPLES[sname]} % OM, W = {W[j]:.2f}')
        axs[1].plot(f[m] / 1e6, -E[m, j].imag, '-', lw=1.4, color=c)
    ff = np.geomspace(15e6, 1.2e9, 80)
    p = [summary['all moist samples'][k] for k in ('a', 'fr', 'alpha')]
    axs[0].plot(ff / 1e6, relax(p, ff).real / relax(p, FQ[3:]).real, '--', lw=1.2, color=D.INK, label='relaxation term, fitted to the medians')
    axs[0].set_ylabel("e' relative to 1 GHz"); axs[1].set_ylabel("loss e''"); axs[1].set_yscale('log')
    for ax in axs: ax.set_xscale('log'); ax.set_xlabel('frequency, MHz')
    axs[0].legend(fontsize=7)
    fig.tight_layout(); fig.savefig(f'{D.FIGS}/fig7_spectra.png'); plt.close(fig)
