#!/usr/bin/env python3
"""The probe as built: differential strips buried on the inner layers of a 4-layer board,
treated as an open-ended lossy transmission line fed from the head.

Per-unit-length shunt admittance comes from the 2-D field solver, tabulated over the complex
permittivity of the surrounding medium; L' from the same cross-section solved in vacuum
(TEM: L' C'_vac = mu0 eps0).  The line model matters: in wet soil the strips are ~0.1
wavelength long at 100 MHz and read 10-25 % more capacitance than C' x length."""
import functools, os
from multiprocessing import Pool
import numpy as np
from scipy.interpolate import RegularGridInterpolator
import soil_probe_sim as s

MU0 = 4e-7 * np.pi
RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'results')

# mm.  stub = strip length between the feed vias and the soil line (inside the potted head)
GEOM = dict(W=20.0, gap=7.0, edge=1.0, length=80.0, stub=6.0)
POTTING = (3.5, 0.0, 0.02)          # epoxy / polyurethane potting compound around the head

EPS_RE = np.array([1, 1.25, 1.6, 2, 2.5, 3.2, 4, 5, 6.5, 8, 10, 13, 16, 20, 25, 32, 40, 50, 64, 85.0])
EPS_IM = np.array([0, 0.25, 0.5, 1, 1.5, 2.5, 4, 6, 9, 13, 20, 30, 45, 70, 100, 150, 250, 512.0])

# cross-section variants for tolerance and contact studies: name -> stack_scene overrides
def _stack(pp=1.0, dk=1.0, mask=1.0):
    (t0, m0), (t1, m1), (t2, m2) = s.OSHPARK_4L['dielectrics']
    f = lambda m: (m[0] * dk, m[1], m[2])
    return dict(s.OSHPARK_4L, dielectrics=[(t0 * pp, f(m0)), (t1, f(m1)), (t2 * pp, f(m2))],
                t_mask=s.OSHPARK_4L['t_mask'] * mask)

VARIANTS = {
    'nominal':    {},
    'prepreg+10': dict(stack=_stack(pp=1.1)),
    'dk+5':       dict(stack=_stack(dk=1.05)),
    'mask+33':    dict(stack=_stack(mask=1.33)),
    'etch-50um':  dict(etch=0.05),                       # each strip edge pulled back 25 um
    'gap5':       dict(gap_top=0.005),                   # air gap, one face
    'gap10':      dict(gap_top=0.01),
    'gap20':      dict(gap_top=0.02),
    'gap50':      dict(gap_top=0.05),
    'gap100':     dict(gap_top=0.10),
    'gap100x2':   dict(gap_top=0.10, gap_bot=0.10),
    'film100':    dict(gap_top=0.10, gap_mat=s.WATER),   # free-water film, one face
}


def strips(etch=0.0, geom=None):
    g = geom or GEOM
    w = (g['W'] - g['gap']) / 2 - g['edge']
    st = [('S', -g['gap'] / 2 - w + etch / 2, -g['gap'] / 2 - etch / 2),
          ('G', g['gap'] / 2 + etch / 2, g['gap'] / 2 + w - etch / 2)]
    return {1: st, 2: st}


def scene(medium_mat, stack=s.OSHPARK_4L, etch=0.0, geom=None, **kw):
    g = geom or GEOM
    return s.stack_scene(stack, strips(etch, g), medium_mat, W=g['W'], **kw)


@functools.lru_cache(maxsize=None)
def Lpul():
    vac = dict(dielectrics=[(t, s.AIR) for t, _ in s.OSHPARK_4L['dielectrics']], cu=s.OSHPARK_4L['cu'], t_mask=0.0)
    C0 = s.solve(s.stack_scene(vac, strips(), s.AIR, W=GEOM['W'], Lx=80, Ly=80), 1e6)['C']
    return MU0 * s.EPS0 / C0


def cstar_direct(eps, variant='nominal', f=100e6):
    """Complex per-unit-length capacitance C*' = Y'/(jw) [F/m] in a medium of complex relative
    permittivity eps = e' - j e''."""
    w = 2 * np.pi * f
    mat = (eps.real, -eps.imag * w * s.EPS0, 0.0)
    return s.solve(scene(mat, **VARIANTS[variant]), f)['Y'] / (1j * w)


def _job(a):
    return cstar_direct(complex(a[1], -a[2]), a[0])


class Table:
    """C*'(eps*) interpolated on a (log e', log(1 + e''/2)) grid; built once and cached."""

    def __init__(self, variant='nominal'):
        path = f'{RESULTS}/probe_table_{variant}.npz'
        key = repr(({k: GEOM[k] for k in ('W', 'gap', 'edge')}, VARIANTS[variant], list(EPS_RE), list(EPS_IM)))
        if os.path.exists(path) and str(np.load(path)['key']) == key:
            Cs = np.load(path)['Cs']
        else:
            with Pool() as p:
                Cs = np.array(p.map(_job, [(variant, a, b) for a in EPS_RE for b in EPS_IM])).reshape(len(EPS_RE), len(EPS_IM))
            os.makedirs(RESULTS, exist_ok=True)
            np.savez(path, Cs=Cs, key=key)
        ax = (np.log(EPS_RE), np.log1p(EPS_IM / 2))
        # in pF/m: the spline solver's tolerances are absolute
        self._re = RegularGridInterpolator(ax, Cs.real * 1e12, method='cubic')
        self._im = RegularGridInterpolator(ax, Cs.imag * 1e12, method='cubic')

    def cstar(self, er, eim):
        p = np.stack([np.log(np.clip(er, 1, 85)), np.log1p(np.clip(eim, 0, 512) / 2)], axis=-1)
        return (self._re(p) + 1j * self._im(p)) * 1e-12


def line_Y(cstar_sections, lengths_mm, f):
    """Input admittance of cascaded line sections, listed from the open end toward the feed."""
    w = 2 * np.pi * f
    Z = 1j * w * Lpul()
    Y = 0j
    for cs, ell in zip(cstar_sections, lengths_mm):
        Yp = 1j * w * cs
        gam, Y0 = np.sqrt(Z * Yp), np.sqrt(Yp / Z)
        t = np.tanh(gam * ell * 1e-3)
        Y = Y0 * (Y + Y0 * t) / (Y0 + Y * t)
    return Y


def eps_star(mat, f):
    er, sigma, tand = mat
    return er, er * tand + sigma / (2 * np.pi * f * s.EPS0)


@functools.lru_cache(maxsize=None)
def table(variant='nominal'):
    return Table(variant)


def feed_Y(mat, f, variant='nominal', exposed_mm=0.0, mix=None, length_mm=None):
    """Admittance at the feed vias for the probe inserted in medium `mat` (er, sigma, tan_d).
    exposed_mm: sensing length left above the soil (in air).  mix: {variant: weight} linear
    blend of cross-section variants, for tolerance sampling."""
    def cs(m):
        er, eim = eps_star(m, f)
        c = table(variant).cstar(er, eim)
        if mix:
            c0 = table('nominal').cstar(er, eim)
            c = c + sum(wt * (table(v).cstar(er, eim) - c0) for v, wt in mix.items())
        return complex(np.ravel(c)[0])
    secs, lens = [cs(mat)], [(length_mm or GEOM['length']) - exposed_mm]
    if exposed_mm > 0:
        secs.append(cs(s.AIR)); lens.append(exposed_mm)
    secs.append(cs(POTTING)); lens.append(GEOM['stub'])
    return line_Y(secs, lens, f)


if __name__ == '__main__':
    f = 100e6
    t = table()
    rng = np.random.default_rng(1)
    worst = 0
    for _ in range(12):
        er, eim = np.exp(rng.uniform(0, np.log(80))), np.expm1(rng.uniform(0, np.log1p(100))) * 2
        d = cstar_direct(complex(er, -eim)); i = complex(np.ravel(t.cstar(er, eim))[0])
        worst = max(worst, abs(i / d - 1))
    print(f"table interpolation: worst |error| over 12 random media = {100*worst:.3f} %")
    print(f"L' = {Lpul()*1e9:.0f} nH/m, sensing length {GEOM['length']:.0f} mm + {GEOM['stub']:.0f} mm stub, f = {f/1e6:.0f} MHz")
    print(f"{'medium':28s} {'C_pF':>6s} {'G_mS':>6s} {'D':>5s} {'line/quasi-static':>17s}")
    cases = [('air', s.AIR), ('water 25 C, 0.05 S/m', (78.3, 0.05, 0))]
    cases += [(f'potting mix th={th:.2f} sw={sw}', s.soil_material(th, sw)) for sw in (0.05, 0.3, 0.6) for th in (0.05, 0.25, 0.45, 0.60)]
    for name, mat in cases:
        Y = feed_Y(mat, f); w = 2 * np.pi * f
        er, eim = eps_star(mat, f)
        qs = complex(np.ravel(t.cstar(er, eim))[0]).real * GEOM['length'] * 1e-3
        print(f"{name:28s} {Y.imag/w*1e12:6.2f} {Y.real*1e3:6.2f} {Y.real/Y.imag:5.2f} {Y.imag/w/qs:17.3f}")
