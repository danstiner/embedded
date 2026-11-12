#!/usr/bin/env python3
"""
soil_probe_sim.py -- 2-D quasi-static field simulation of capacitive soil-moisture
probe cross-sections: PCB electrodes on the OSH Park 2-layer stack, or steel nails.

Physics
-------
Solves  div( eps*(x,y) grad(phi) ) = 0  on a rectilinear finite-volume grid with
complex permittivity
        eps* = eps0 * er * (1 - j*tan_d)  -  j*sigma/omega
so the answer is the full per-unit-length admittance of the probe cross-section
        Y = G + j*omega*C      [S/m  and  F/m  per metre of inserted length]
Quasi-static is valid while the probe is << wavelength in the soil (fine to
~100 MHz for a 10 cm probe in wet soil).  Electrodes are Dirichlet regions
(sense = 1 V, ground = 0 V).  Outer boundary is Neumann (isolated), so the
domain must be several board-widths wide -- see check_domain().

Units: geometry in mm, materials in SI.  Cross-section is x (width) by
y (thickness); z (probe length / insertion) is handled analytically.

OSH Park 2-layer stack (docs.oshpark.com/services/two-layer, Sep 2026):
  core 60 mil = 1.524 mm Kingboard KB6167F, Dk 4.5 @ 10 MHz
  1 oz copper = 35.6 um each side
  solder resist 0.6 mil = 15.2 um Taiyo PSR-4000BN (Dk ~3.9 typical for PSR-4000)
"""
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

EPS0 = 8.8541878128e-12

# ----------------------------------------------------------------------------
# Materials  (er, sigma [S/m], tan_delta)
# ----------------------------------------------------------------------------
AIR   = (1.0,   0.0,   0.0)
FR4   = (4.5,   0.0,   0.02)    # KB6167F Dk 4.5 (OSH Park), tan_d ~0.02 (1-10 MHz)
MASK  = (3.9,   0.0,   0.025)   # Taiyo PSR-4000 series LPI mask, typical
COAT  = (3.0,   0.0,   0.02)    # generic epoxy / acrylic conformal coat
WATER = (80.0,  0.02,  0.0)     # free water film (rain / irrigation water)
ELEC  = (1e5,   0.0,   0.0)     # huge er => electrode cell is an equipotential

STACK = dict(h_core=1.524, t_cu=0.0356, t_mask=0.0152)   # mm, OSH Park 2-layer

REGIONS = {'soil': 0, 'fr4': 1, 'mask': 2, 'gap': 3, 'coat': 4, 'elec': 5, 'air': 6}


def topp_er(theta):
    """Topp et al. 1980 empirical curve for MINERAL soils (bulk density ~1.3-1.5)."""
    return 3.03 + 9.3 * theta + 146.0 * theta**2 - 76.7 * theta**3


def crim_er(theta, porosity=0.70, er_solid=4.0, er_water=80.0):
    """CRIM / refractive-index mixing model (Birchak 1974, Roth 1990, alpha = 0.5).
    Defaults are a peat/perlite potting mix: porosity ~0.7, solid er ~4.
    sqrt(er) = theta*sqrt(er_w) + (1-porosity)*sqrt(er_s) + (porosity-theta)*1"""
    return (theta * np.sqrt(er_water) + (1 - porosity) * np.sqrt(er_solid) + (porosity - theta))**2


def soil_sigma(theta, sigma_w=0.05, sigma_s=0.02):
    """Bulk EC.  Archie-type pore-water term + a surface-conduction term that
    scales with the water film so it vanishes in dry soil (Rhoades 1989 in spirit):
        sigma_b = sigma_w*theta^2 + sigma_s*theta
    sigma_w = pore-water EC: 0.05 S/m rain-fed ... 0.3 S/m fertilised potting mix
    sigma_s*theta: ~0.005 S/m at theta=0.25 for peaty / clayey media."""
    return sigma_w * theta**2 + sigma_s * theta


def soil_material(theta, sigma_w=0.05, model=crim_er):
    """Bulk soil (er, sigma, tan_d) at volumetric water content theta.
    Swap model=topp_er for a mineral soil."""
    return (model(theta), soil_sigma(theta, sigma_w), 0.0)


def eps_complex(mat, f):
    er, sigma, tand = mat
    w = 2 * np.pi * f
    return EPS0 * er * (1 - 1j * tand) - 1j * sigma / w


# ----------------------------------------------------------------------------
# Grid
# ----------------------------------------------------------------------------
def graded_axis(pts, dmin, dmax, growth=1.3):
    """Cell edges containing every coordinate in pts, with cell size dmin[k]
    at pts[k] growing geometrically to dmax in between."""
    pts = np.asarray(pts, float)
    edges = [pts[0]]
    for k in range(len(pts) - 1):
        a, b = pts[k], pts[k + 1]
        L = b - a
        left, right = [], []
        dl, dr = dmin[k], dmin[k + 1]
        sl = sr = 0.0
        while True:
            if sl <= sr:
                if sl + sr + dl > L: break
                left.append(dl); sl += dl; dl = min(dl * growth, dmax)
            else:
                if sl + sr + dr > L: break
                right.append(dr); sr += dr; dr = min(dr * growth, dmax)
        seq = np.array(left + right[::-1]) if (left or right) else np.array([L])
        seq *= L / seq.sum()
        edges.extend(a + np.cumsum(seq))
    return np.array(edges)


class Scene:
    """Rectilinear cell-centred material map (materials stored as indices)."""

    def __init__(self, xe, ye):
        self.xe, self.ye = xe, ye
        self.xc = 0.5 * (xe[1:] + xe[:-1]); self.yc = 0.5 * (ye[1:] + ye[:-1])
        self.dx = np.diff(xe); self.dy = np.diff(ye)
        self.nx, self.ny = len(self.xc), len(self.yc)
        self.X, self.Y = np.meshgrid(self.xc, self.yc)            # (ny, nx)
        self.mats = []                                            # material table
        self.mid = np.zeros((self.ny, self.nx), dtype=np.int16)   # index into mats
        self.elec = np.zeros((self.ny, self.nx), dtype=np.int8)   # 0 free, 1 sense, 2 gnd
        self.region = np.zeros((self.ny, self.nx), dtype=np.int8)

    def _id(self, mat):
        mat = tuple(mat)
        if mat not in self.mats: self.mats.append(mat)
        return self.mats.index(mat)

    def fill(self, mat, region):
        self.mid[:] = self._id(mat); self.region[:] = REGIONS[region]

    def rect(self, x0, x1, y0, y1, mat=None, region=None, elec=0):
        m = (self.X >= x0) & (self.X < x1) & (self.Y >= y0) & (self.Y < y1)
        self.paint(m, mat, region, elec)

    def disc(self, cx, cy, r, mat=None, region=None, elec=0):
        m = (self.X - cx)**2 + (self.Y - cy)**2 < r**2
        self.paint(m, mat, region, elec)

    def paint(self, m, mat, region, elec=0):
        if elec:
            self.mid[m] = self._id(ELEC); self.elec[m] = elec; self.region[m] = REGIONS['elec']
        else:
            self.mid[m] = self._id(mat); self.region[m] = REGIONS[region]; self.elec[m] = 0

    def eps_array(self, f):
        table = np.array([eps_complex(m, f) for m in self.mats])
        return table[self.mid]


# ----------------------------------------------------------------------------
# Geometry builders
# ----------------------------------------------------------------------------
def pcb_scene(top, bot, soil, W=12.0, gap_top=0.0, gap_bot=0.0, gap_mat=AIR,
              mask=True, coat=None, stack=STACK, medium=None,
              Lx=40.0, Ly=40.0, dmin=0.005, dmax=2.0, growth=1.3):
    """
    top/bot : list of ('S'|'G', x0, x1) copper strips on each face (mm)
    soil    : (er, sigma, tan_d) of the bulk soil filling the domain
    gap_*   : uniform slab of gap_mat between the board face and the soil
    coat    : (thickness_mm, material) extra conformal coat over the mask
    mask    : False => bare (ENIG) copper, no solder resist
    medium  : override soil with e.g. AIR for an in-air calibration
    """
    h, tcu, tm = stack['h_core'], stack['t_cu'], stack['t_mask']
    tm = tm if mask else 0.0
    tc = coat[0] if coat else 0.0
    face = h / 2 + tcu + tm + tc                     # outer surface of the board
    # --- y interfaces ---
    ypts = [-Ly, -(face + gap_bot), -face, -(h/2 + tcu + tm), -(h/2 + tcu), -h/2,
            h/2, h/2 + tcu, h/2 + tcu + tm, face, face + gap_top, Ly]
    ydm = [dmax, 0.01, 0.01, dmin, dmin, 0.01, 0.01, dmin, dmin, 0.01, 0.01, dmax]
    ypts, ydm = _dedupe(ypts, ydm)
    # --- x interfaces ---
    xpts = [-Lx, -W/2, W/2, Lx]; xdm = [dmax, 0.02, 0.02, dmax]
    for _, x0, x1 in top + bot:
        xpts += [x0, x1]; xdm += [0.01, 0.01]
    xpts, xdm = _dedupe(xpts, xdm)
    sc = Scene(graded_axis(xpts, xdm, dmax, growth), graded_axis(ypts, ydm, dmax, growth))
    bulk = medium if medium is not None else soil
    sc.fill(bulk, 'soil' if medium is None else 'air')
    # gap slabs (fill the whole band above the FR4 surface so copper recesses fill too)
    if gap_top > 0: sc.rect(-W/2, W/2, h/2, face + gap_top, gap_mat, 'gap')
    if gap_bot > 0: sc.rect(-W/2, W/2, -(face + gap_bot), -h/2, gap_mat, 'gap')
    # core
    sc.rect(-W/2, W/2, -h/2, h/2, FR4, 'fr4')
    # copper + conformal layers, top then bottom
    for strips, sgn in ((top, 1), (bot, -1)):
        y0, y1 = (h/2, h/2 + tcu) if sgn > 0 else (-(h/2 + tcu), -h/2)
        if mask:                                  # mask over bare laminate
            ym0, ym1 = (h/2, h/2 + tm) if sgn > 0 else (-(h/2 + tm), -h/2)
            sc.rect(-W/2, W/2, ym0, ym1, MASK, 'mask')
        for kind, x0, x1 in strips:
            sc.rect(x0, x1, y0, y1, elec=1 if kind == 'S' else 2)
            if mask:                              # mask over copper
                ym0, ym1 = (h/2 + tcu, h/2 + tcu + tm) if sgn > 0 else (-(h/2 + tcu + tm), -(h/2 + tcu))
                sc.rect(x0, x1, ym0, ym1, MASK, 'mask')
        if coat:                                  # conformal coat over everything
            yc0, yc1 = (h/2 + tcu + tm, face) if sgn > 0 else (-face, -(h/2 + tcu + tm))
            sc.rect(-W/2, W/2, yc0, yc1, coat[1], 'coat')
            # the recess beside copper strips is also coat (coat fills it)
            yr0, yr1 = (h/2 + tm, h/2 + tcu + tm) if sgn > 0 else (-(h/2 + tcu + tm), -(h/2 + tm))
            m = (sc.Y >= yr0) & (sc.Y < yr1) & (np.abs(sc.X) < W/2) & (sc.elec == 0)
            sc.paint(m, coat[1], 'coat')
    return sc


def nail_scene(soil, r=1.75, spacing=20.0, coat=0.0, coat_mat=COAT, gap=0.0,
               gap_mat=AIR, medium=None, L=40.0, dmin=0.02, dmax=2.0, growth=1.3):
    """Two parallel steel nails (radius r, centre spacing) in soil, optional
    insulating coat and a loose-hole gap ring around each."""
    R = r + coat + gap
    cx = spacing / 2
    pts = [-L, -cx - R, -cx - r, -cx, -cx + r, -cx + R, cx - R, cx - r, cx, cx + r, cx + R, L]
    dm = [dmax, dmin, dmin, 0.2, dmin, dmin, dmin, dmin, 0.2, dmin, dmin, dmax]
    xe = graded_axis(*_dedupe(pts, dm), dmax, growth)
    ypts = [-L, -R, -r, 0.0, r, R, L]; ydm = [dmax, dmin, dmin, 0.2, dmin, dmin, dmax]
    ye = graded_axis(*_dedupe(ypts, ydm), dmax, growth)
    sc = Scene(xe, ye)
    bulk = medium if medium is not None else soil
    sc.fill(bulk, 'soil' if medium is None else 'air')
    for x, e in ((-cx, 1), (cx, 2)):
        if gap > 0:  sc.disc(x, 0, r + coat + gap, gap_mat, 'gap')
        if coat > 0: sc.disc(x, 0, r + coat, coat_mat, 'coat')
        sc.disc(x, 0, r, elec=e)
    return sc


def _dedupe(pts, dm):
    order = np.argsort(pts)
    p, d = [], []
    for i in order:
        if p and abs(pts[i] - p[-1]) < 1e-9:
            d[-1] = min(d[-1], dm[i])
        else:
            p.append(pts[i]); d.append(dm[i])
    return p, d


# ----------------------------------------------------------------------------
# Solver
# ----------------------------------------------------------------------------
def solve(sc, f):
    """Return dict: Y [S/m], C [F/m], G [S/m], phi (ny,nx), energy fraction per region."""
    eps = sc.eps_array(f)
    nx, ny = sc.nx, sc.ny
    idx = np.arange(nx * ny).reshape(ny, nx)
    dx, dy = sc.dx, sc.dy
    # face conductances: series combination of the two half-cells (exact for
    # piecewise-constant eps, reduces to the harmonic mean on uniform grids)
    gx = dy[:, None] / (dx[None, :-1] / (2 * eps[:, :-1]) + dx[None, 1:] / (2 * eps[:, 1:]))
    gy = dx[None, :] / (dy[:-1, None] / (2 * eps[:-1, :]) + dy[1:, None] / (2 * eps[1:, :]))
    a = np.concatenate([idx[:, :-1].ravel(), idx[:-1, :].ravel()])
    b = np.concatenate([idx[:, 1:].ravel(), idx[1:, :].ravel()])
    g = np.concatenate([gx.ravel(), gy.ravel()])
    rows = np.concatenate([a, b, a, b]); cols = np.concatenate([a, b, b, a])
    vals = np.concatenate([g, g, -g, -g])
    A = sp.csr_matrix((vals, (rows, cols)), shape=(nx * ny, nx * ny))
    elec = sc.elec.ravel()
    free = np.where(elec == 0)[0]; fixed = np.where(elec != 0)[0]
    V = np.zeros(nx * ny, complex); V[elec == 1] = 1.0
    rhs = -A[free][:, fixed] @ V[fixed]
    V[free] = spla.spsolve(A[free][:, free].tocsc(), rhs)
    Q = A @ V                                            # net outward D-flux per cell
    Qs = Q[elec == 1].sum()                              # charge on sense (V = 1)
    w = 2 * np.pi * f
    Y = 1j * w * Qs                                      # S per metre of length
    phi = V.reshape(ny, nx)
    # field-energy partition: W = 1/2 sum_faces Re(g)|dphi|^2 (discretely exact,
    # C = 2W/V^2 for lossless media); each face's energy split between the two
    # cells' regions -> tells you where the sensitivity actually lives
    er = eps.real
    gxr = dy[:, None] / (dx[None, :-1] / (2 * er[:, :-1]) + dx[None, 1:] / (2 * er[:, 1:]))
    gyr = dx[None, :] / (dy[:-1, None] / (2 * er[:-1, :]) + dy[1:, None] / (2 * er[1:, :]))
    Wx = 0.5 * gxr * np.abs(phi[:, 1:] - phi[:, :-1])**2
    Wy = 0.5 * gyr * np.abs(phi[1:, :] - phi[:-1, :])**2
    Wcell = np.zeros((ny, nx))
    Wcell[:, :-1] += 0.5 * Wx; Wcell[:, 1:] += 0.5 * Wx
    Wcell[:-1, :] += 0.5 * Wy; Wcell[1:, :] += 0.5 * Wy
    frac = {name: float(Wcell[sc.region == k].sum() / Wcell.sum()) for name, k in REGIONS.items()}
    return dict(Y=Y, C=Y.imag / w, G=Y.real, phi=phi, frac=frac, n=nx * ny)


# ----------------------------------------------------------------------------
# Verification against closed forms
# ----------------------------------------------------------------------------
def verify():
    out = []
    # two-wire line in a uniform dielectric:  C/L = pi*eps / acosh(s/2r)
    er = 10.0
    sc = nail_scene((er, 0, 0), r=1.75, spacing=20.0, L=60.0, dmin=0.02, dmax=1.0)
    C = solve(sc, 1e6)['C']
    Ca = np.pi * EPS0 * er / np.arccosh(20.0 / 3.5)
    out.append(('two-wire line, er=10, L=60mm domain', C, Ca))
    sc = nail_scene((er, 0, 0), r=1.75, spacing=20.0, L=120.0, dmin=0.02, dmax=2.0)
    out.append(('two-wire line, er=10, L=120mm domain', solve(sc, 1e6)['C'], Ca))
    # lossy two-wire line: G/L = pi*sigma / acosh(s/2r)
    sig = 0.05
    sc = nail_scene((er, sig, 0), r=1.75, spacing=20.0, L=120.0, dmin=0.02, dmax=2.0)
    r = solve(sc, 1e6)
    out.append(('two-wire G, sigma=0.05', r['G'], np.pi * sig / np.arccosh(20.0 / 3.5)))
    return out


if __name__ == '__main__':
    for name, num, ana in verify():
        print(f'{name:40s} num={num:.4e} analytic={ana:.4e} err={100*(num/ana-1):+.2f}%')
