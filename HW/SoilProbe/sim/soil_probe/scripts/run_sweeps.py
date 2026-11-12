#!/usr/bin/env python3
"""Run the design sweeps for the soil probe and write CSV + figures to ./out."""
import csv, os, time
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import soil_probe_sim as s

OUT = 'out'; os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({'font.size': 11, 'figure.dpi': 150, 'axes.grid': True, 'grid.alpha': 0.3})

F_FDC, F_FDR = 2e6, 70e6          # FDC2212 tank regime  vs  commercial FDR probes (EC-5/TEROS ~70 MHz)
SIG_LO, SIG_HI = 0.05, 0.30       # pore-water EC: rain-fed  vs  fertilised potting mix  [S/m]
THETAS = np.round(np.arange(0.02, 0.47, 0.04), 2)

W = 12.0
S5 = [('S', -5.5, -0.5), ('G', 0.5, 5.5)]
def fingers(n=6, w=1.0, g=1.0, x0=-5.5):
    return [('S' if i % 2 == 0 else 'G', x0 + i * (w + g), x0 + i * (w + g) + w) for i in range(n)]

CONFIGS = {
    'A pad / gnd back':     dict(top=[('S', -5.5, 5.5)], bot=[('G', -5.5, 5.5)]),
    'B coplanar 1-side':    dict(top=S5, bot=[]),
    'C coplanar 2-side':    dict(top=S5, bot=S5),
    'D interdig 1mm':       dict(top=fingers(), bot=[]),
    'E guard ring+gnd back': dict(top=[('G', -5.5, -3.0), ('S', -2.4, 2.4), ('G', 3.0, 5.5)], bot=[('G', -5.5, 5.5)]),
    'F = C + 0.3mm coat':   dict(top=S5, bot=S5, coat=(0.3, s.COAT)),
}
NAILS = {
    'N bare 3.5mm x 20mm':   dict(r=1.75, spacing=20, coat=0.0),
    'N coat 0.1mm':          dict(r=1.75, spacing=20, coat=0.1),
    'N coat 0.5mm (shrink)': dict(r=1.75, spacing=20, coat=0.5),
}

rows = []
def rec(study, name, f, theta, sig_w, gap, extra, r):
    rows.append(dict(study=study, config=name, f_Hz=f, theta=theta, sigma_w=sig_w, gap=gap,
                     note=extra, C_pF_per_m=r['C'] * 1e12, G_mS_per_m=r['G'] * 1e3,
                     frac_soil=r['frac']['soil'], frac_fr4=r['frac']['fr4'],
                     frac_mask=r['frac']['mask'], frac_coat=r['frac']['coat']))
    return r

def pcb(name, theta, sig_w, f, **kw):
    cfg = dict(CONFIGS[name]); cfg.update(kw)
    soil = s.soil_material(theta, sig_w) if theta is not None else s.AIR
    return s.solve(s.pcb_scene(cfg.pop('top'), cfg.pop('bot'), soil, W=W, **cfg), f)

t0 = time.time()
# ---------------------------------------------------------------- 1. C(theta), G(theta)
cal = {}   # (name, f, sig) -> (thetas, C, G)
for name in CONFIGS:
    for f in (F_FDC, F_FDR):
        for sig in (SIG_LO, SIG_HI):
            C, G = [], []
            for th in THETAS:
                r = rec('theta', name, f, th, sig, 0, '', pcb(name, th, sig, f))
                C.append(r['C']); G.append(r['G'])
            cal[(name, f, sig)] = (THETAS, np.array(C), np.array(G))
        r = rec('air', name, f, None, 0, 0, 'in air', pcb(name, None, 0, f, medium=s.AIR))
        cal[(name, f, 'air')] = r['C']
print(f'theta sweeps done {time.time()-t0:.0f}s')

# ---------------------------------------------------------------- 2. gap / water film sensitivity
TH0 = 0.25
GAPS = [('0.05 mm air, 1 side', dict(gap_top=0.05)),
        ('0.1 mm air, 1 side',  dict(gap_top=0.1)),
        ('0.3 mm air, 1 side',  dict(gap_top=0.3)),
        ('0.1 mm air, 2 sides', dict(gap_top=0.1, gap_bot=0.1)),
        ('0.1 mm water film',   dict(gap_top=0.1, gap_mat=s.WATER))]
gap_err = {}   # (name, f) -> list of apparent-theta errors
for name in CONFIGS:
    for f in (F_FDC, F_FDR):
        th, Ccal, _ = cal[(name, f, SIG_LO)]
        order = np.argsort(Ccal)
        errs = []
        for label, kw in GAPS:
            r = rec('gap', name, f, TH0, SIG_LO, kw.get('gap_top'), label, pcb(name, TH0, SIG_LO, f, **kw))
            th_app = np.interp(r['C'], Ccal[order], th[order])
            errs.append(th_app - TH0)
        gap_err[(name, f)] = errs
print(f'gap sweeps done {time.time()-t0:.0f}s')

# ---------------------------------------------------------------- 3. frequency dispersion
FREQS = np.logspace(5, 8.7, 16)
disp = {}
for name in ('C coplanar 2-side', 'A pad / gnd back'):
    for sig in (SIG_LO, SIG_HI):
        C, G = [], []
        for f in FREQS:
            r = rec('freq', name, f, TH0, sig, 0, '', pcb(name, TH0, sig, f))
            C.append(r['C']); G.append(r['G'])
        disp[(name, sig)] = (np.array(C), np.array(G))
    C, G = [], []
    for f in FREQS:
        r = rec('freq', name, f, 0.05, SIG_LO, 0, 'dry', pcb(name, 0.05, SIG_LO, f))
        C.append(r['C']); G.append(r['G'])
    disp[(name, 'dry')] = (np.array(C), np.array(G))
print(f'freq sweeps done {time.time()-t0:.0f}s')

# ---------------------------------------------------------------- 4. nails
ncal = {}
for name, kw in NAILS.items():
    for f in (F_FDC, F_FDR):
        C, G = [], []
        for th in THETAS:
            r = rec('nail', name, f, th, SIG_LO, 0, '', s.solve(s.nail_scene(s.soil_material(th, SIG_LO), **kw), f))
            C.append(r['C']); G.append(r['G'])
        ncal[(name, f)] = (np.array(C), np.array(G))
    # high-salinity conductance for the bare pair
    if kw['coat'] == 0:
        G = [rec('nail', name, F_FDC, th, SIG_HI, 0, 'hi-EC', s.solve(s.nail_scene(s.soil_material(th, SIG_HI), **kw), F_FDC))['G'] for th in THETAS]
        ncal[(name, 'GHI')] = np.array(G)
nail_gap = {}
for name in ('N coat 0.1mm', 'N coat 0.5mm (shrink)'):
    for f in (F_FDC, F_FDR):
        th = THETAS; Ccal = ncal[(name, f)][0]; order = np.argsort(Ccal)
        errs = []
        for g in (0.1, 0.3):
            r = rec('nail_gap', name, f, TH0, SIG_LO, g, f'{g} mm loose hole',
                    s.solve(s.nail_scene(s.soil_material(TH0, SIG_LO), gap=g, **NAILS[name]), f))
            errs.append(np.interp(r['C'], Ccal[order], th[order]) - TH0)
        nail_gap[(name, f)] = errs
print(f'nail sweeps done {time.time()-t0:.0f}s')

# ---------------------------------------------------------------- 5. write CSV
with open(f'{OUT}/results.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

# ================================================================ FIGURES
cols = plt.cm.tab10(np.arange(len(CONFIGS)))

# Fig 1: C(theta) and G(theta) at both frequencies
fig, ax = plt.subplots(2, 2, figsize=(9, 8))
for i, f in enumerate((F_FDC, F_FDR)):
    for c, name in zip(cols, CONFIGS):
        th, C, G = cal[(name, f, SIG_LO)]
        ax[0, i].plot(th, C * 1e12, '-', color=c, label=name)
        ax[1, i].plot(th, G * 1e3, '-', color=c)
        th, C, G = cal[(name, f, SIG_HI)]
        ax[0, i].plot(th, C * 1e12, '--', color=c, lw=1)
        ax[1, i].plot(th, G * 1e3, '--', color=c, lw=1)
    ax[0, i].set_title(f'{f/1e6:.0f} MHz   solid EC_w={SIG_LO}, dashed {SIG_HI} S/m', fontsize=10)
    ax[0, i].set_ylabel('C  [pF per m inserted]'); ax[1, i].set_ylabel('G  [mS per m inserted]')
    ax[1, i].set_xlabel('volumetric water content θ'); ax[1, i].set_yscale('log')
ax[0, 0].legend(fontsize=8)
fig.suptitle('Per-unit-length C and G vs soil water content, OSH Park 2-layer, 12 mm wide probe')
fig.tight_layout(); fig.savefig(f'{OUT}/fig1_C_G_vs_theta.png'); plt.close(fig)

# Fig 2: apparent-theta error from gaps / water film
fig, ax = plt.subplots(1, 2, figsize=(10, 4.5), sharey=True)
xg = np.arange(len(GAPS)); bw = 0.13
for i, f in enumerate((F_FDC, F_FDR)):
    for k, (c, name) in enumerate(zip(cols, CONFIGS)):
        ax[i].bar(xg + (k - 2.5) * bw, np.array(gap_err[(name, f)]) * 100, bw, color=c, label=name)
    ax[i].set_xticks(xg); ax[i].set_xticklabels([g[0] for g in GAPS], rotation=25, ha='right', fontsize=8)
    ax[i].set_title(f'{f/1e6:.0f} MHz'); ax[i].axhline(0, color='k', lw=0.8)
ax[0].set_ylabel('apparent θ error  [% VWC]  (true θ = 25 %)'); ax[1].legend(fontsize=7, loc='lower left')
fig.suptitle('Reading error when the probe is loose: air gap or water film between board and soil')
fig.tight_layout(); fig.savefig(f'{OUT}/fig2_gap_error.png'); plt.close(fig)

# Fig 3: dispersion
fig, ax = plt.subplots(1, 2, figsize=(10, 4.2))
for name, ls in (('C coplanar 2-side', '-'), ('A pad / gnd back', ':')):
    for key, c, lab in ((SIG_LO, 'tab:blue', f'θ=0.25, EC_w={SIG_LO}'), (SIG_HI, 'tab:red', f'θ=0.25, EC_w={SIG_HI}'), ('dry', 'tab:brown', 'θ=0.05')):
        C, G = disp[(name, key)]
        ax[0].plot(FREQS / 1e6, C * 1e12, ls, color=c, label=f'{name}: {lab}' if ls == '-' else None)
        ax[1].plot(FREQS / 1e6, G / (2 * np.pi * FREQS * C), ls, color=c)
for a in ax:
    a.set_xscale('log'); a.set_xlabel('frequency [MHz]')
    a.axvspan(1, 10, color='orange', alpha=0.12); a.axvspan(50, 100, color='green', alpha=0.12)
ax[0].set_yscale('log'); ax[0].set_ylabel('C_eff [pF/m]'); ax[0].legend(fontsize=7)
ax[1].set_yscale('log'); ax[1].set_ylabel('dissipation factor  G/ωC')
ax[1].axhline(1, color='k', lw=0.8)
fig.suptitle('Frequency dispersion (orange: FDC2212 tank range, green: commercial FDR probes; solid C, dotted A)')
fig.tight_layout(); fig.savefig(f'{OUT}/fig3_dispersion.png'); plt.close(fig)

# Fig 4: nails
fig, ax = plt.subplots(1, 3, figsize=(12, 4))
for name, c in zip(NAILS, ('k', 'tab:green', 'tab:purple')):
    for f, ls in ((F_FDC, '-'), (F_FDR, '--')):
        C, G = ncal[(name, f)]
        ax[0].plot(THETAS, C * 1e12, ls, color=c, label=f'{name} @ {f/1e6:.0f} MHz')
        ax[1].plot(THETAS, G * 1e3, ls, color=c)
ax[1].plot(THETAS, ncal[('N bare 3.5mm x 20mm', 'GHI')] * 1e3, '-', color='gray', label=f'bare, EC_w={SIG_HI}')
# PCB config C for comparison
th, C, G = cal[('C coplanar 2-side', F_FDC, SIG_LO)]
ax[0].plot(th, C * 1e12, '-', color='tab:orange', lw=2, alpha=0.6, label='PCB C coplanar 2-side @ 2 MHz')
ax[1].plot(th, G * 1e3, '-', color='tab:orange', lw=2, alpha=0.6)
ax[0].set_ylabel('C [pF/m]'); ax[1].set_ylabel('G [mS/m]'); ax[1].set_yscale('log'); ax[0].set_yscale('log')
ax[0].legend(fontsize=6); ax[1].legend(fontsize=7)
for a in ax[:2]: a.set_xlabel('θ')
xg = np.arange(2); k = 0
for name, c in (('N coat 0.1mm', 'tab:green'), ('N coat 0.5mm (shrink)', 'tab:purple')):
    for f, hatch in ((F_FDC, ''), (F_FDR, '//')):
        ax[2].bar(xg + (k - 1.5) * 0.2, np.array(nail_gap[(name, f)]) * 100, 0.2, color=c, hatch=hatch,
                  label=f'{name} @ {f/1e6:.0f} MHz'); k += 1
ax[2].set_xticks(xg); ax[2].set_xticklabels(['0.1 mm loose hole', '0.3 mm loose hole'])
ax[2].set_ylabel('apparent θ error [% VWC]'); ax[2].legend(fontsize=6); ax[2].axhline(0, color='k', lw=0.8)
fig.suptitle('Steel nails (3.5 mm dia, 20 mm apart): capacitance, conductance, loose-hole error')
fig.tight_layout(); fig.savefig(f'{OUT}/fig4_nails.png'); plt.close(fig)

# Fig 5: field maps (dry soil, lossless-ish) for four PCB configs
fig, ax = plt.subplots(2, 2, figsize=(10, 6.5), constrained_layout=True)
for a, name in zip(ax.ravel(), ('A pad / gnd back', 'C coplanar 2-side', 'D interdig 1mm', 'E guard ring+gnd back')):
    cfg = dict(CONFIGS[name]); sc = s.pcb_scene(cfg['top'], cfg['bot'], s.soil_material(0.05, SIG_LO), W=W)
    r = s.solve(sc, F_FDC)
    phi = r['phi']
    Ex = np.zeros_like(phi); Ey = np.zeros_like(phi)
    Ex[:, 1:-1] = (phi[:, 2:] - phi[:, :-2]) / (sc.xc[2:] - sc.xc[:-2])[None, :]
    Ey[1:-1, :] = (phi[2:, :] - phi[:-2, :]) / (sc.yc[2:] - sc.yc[:-2])[:, None]
    E = np.log10(np.abs(Ex)**2 + np.abs(Ey)**2 + 1e-12) / 2
    E[sc.elec != 0] = np.nan
    pm = a.pcolormesh(sc.xe, sc.ye, E, cmap='magma', vmin=-2.5, vmax=1.0, shading='flat')
    a.contour(sc.xc, sc.yc, phi.real, levels=np.linspace(0.05, 0.95, 10), colors='w', linewidths=0.4, alpha=0.6)
    a.set_xlim(-8, 8); a.set_ylim(-4, 4); a.set_aspect('equal')
    a.set_title(f"{name}\nenergy: soil {100*r['frac']['soil']:.0f}%  FR4 {100*r['frac']['fr4']:.0f}%  mask {100*r['frac']['mask']:.0f}%", fontsize=9)
    a.grid(False)
fig.colorbar(pm, ax=ax, label='log10 |E|  [V/mm at 1 V]', shrink=0.8)
fig.suptitle('Where the field lives (dry soil θ=0.05, 2 MHz).  White: equipotentials')
fig.savefig(f'{OUT}/fig5_fields.png'); plt.close(fig)

# Fig 6: insertion depth (analytic along z) + energy partition
fig, ax = plt.subplots(1, 2, figsize=(10, 4))
Lp, Cpar = 80.0, 5e-12
Lins = np.linspace(0, Lp, 41)
for name, c in (('C coplanar 2-side', cols[2]), ('A pad / gnd back', cols[0])):
    Cair = cal[(name, F_FDC, 'air')]
    for th, ls in ((0.05, ':'), (0.25, '-'), (0.40, '--')):
        Cs = np.interp(th, *cal[(name, F_FDC, SIG_LO)][:2])
        Ct = Cs * Lins * 1e-3 + Cair * (Lp - Lins) * 1e-3 + Cpar
        ax[0].plot(Lins, Ct * 1e12, ls, color=c, label=f'{name}, θ={th}')
ax[0].set_xlabel('inserted length [mm] of an 80 mm probe'); ax[0].set_ylabel('total C [pF]  (+5 pF parasitic)')
ax[0].legend(fontsize=7); ax[0].set_title('Insertion depth (2 MHz, low EC)')
names = list(CONFIGS); fr = np.array([[cal_r for cal_r in (pcb(n, 0.05, SIG_LO, F_FDC)['frac'][k] for k in ('soil', 'fr4', 'mask', 'coat'))] for n in names])
bottom = np.zeros(len(names))
for k, (lab, c) in enumerate((('soil', 'tab:brown'), ('FR4', 'tab:green'), ('mask', 'tab:purple'), ('coat', 'tab:gray'))):
    ax[1].bar(np.arange(len(names)), fr[:, k] * 100, bottom=bottom, color=c, label=lab); bottom += fr[:, k] * 100
ax[1].set_xticks(np.arange(len(names))); ax[1].set_xticklabels([n.split()[0] for n in names])
ax[1].set_ylabel('% of field energy'); ax[1].legend(fontsize=8); ax[1].set_title('Energy partition, dry soil')
fig.tight_layout(); fig.savefig(f'{OUT}/fig6_insertion_energy.png'); plt.close(fig)

# ---------------------------------------------------------------- summary table
def apparent_theta(name, f, C):
    th, Ccal, _ = cal[(name, f, SIG_LO)]; o = np.argsort(Ccal)
    return np.interp(C, Ccal[o], th[o])

print('\n== PCB configs at true θ=0.25, calibrated in low-EC soil.  Rp for 100 mm inserted ==')
print(f"{'config':24s} {'f':>5s} {'C_dry':>7s} {'C_wet':>7s} {'ratio':>6s} {'Rp':>6s} {'soil%':>5s} {'gap0.1':>7s} {'water':>7s} {'EC x6':>7s} {'T+10C':>7s}")
summary = []
for name in CONFIGS:
    for f in (F_FDC, F_FDR):
        th, C, G = cal[(name, f, SIG_LO)]
        Cd, Cw = np.interp(0.05, th, C), np.interp(0.40, th, C)
        G25 = np.interp(0.25, th, G)
        fs = pcb(name, 0.05, SIG_LO, f)['frac']['soil']
        e = gap_err[(name, f)]
        e_ec = apparent_theta(name, f, np.interp(0.25, *cal[(name, f, SIG_HI)][:2])) - 0.25
        er, sig, _ = s.soil_material(0.25, SIG_LO)
        cfg = dict(CONFIGS[name]); rT = s.solve(s.pcb_scene(cfg.pop('top'), cfg.pop('bot'), (er, sig * 1.2, 0.0), W=W, **cfg), f)
        e_T = apparent_theta(name, f, rT['C']) - 0.25
        summary.append((name, f, Cd, Cw, Cw / Cd, 1 / (G25 * 0.1), fs, e[1], e[4], e_ec, e_T))
        print(f'{name:24s} {f/1e6:4.0f}M {Cd*1e12:7.0f} {Cw*1e12:7.0f} {Cw/Cd:6.2f} {1/(G25*0.1):5.0f}Ω {100*fs:4.0f}% {100*e[1]:+6.1f}% {100*e[4]:+6.1f}% {100*e_ec:+6.1f}% {100*e_T:+6.1f}%')
with open(f'{OUT}/summary_table.csv', 'w', newline='') as fh:
    w = csv.writer(fh); w.writerow(['config', 'f_Hz', 'C_dry_pF_m', 'C_wet_pF_m', 'ratio', 'Rp_100mm_ohm', 'soil_energy_frac',
                                    'err_gap0.1mm', 'err_waterfilm0.1mm', 'err_EC_x6', 'err_T_plus10C']); w.writerows(summary)
print('\n== nails ==')
for name in NAILS:
    for f in (F_FDC, F_FDR):
        C, G = ncal[(name, f)]
        print(f'{name:24s} {f/1e6:5.0f}M C_dry={C[1]*1e12:7.1f} C_wet={np.interp(0.40, THETAS, C)*1e12:7.1f} ratio={np.interp(0.40, THETAS, C)/C[1]:5.2f}  Rp(100mm,θ=.25)={1/(np.interp(0.25, THETAS, G)*0.1):8.0f}Ω')

# ---------------------------------------------------------------- 6. strip width / spacing on the 2-sided coplanar geometry (70 MHz)
print('\n== 2-sided coplanar strips: width / spacing sweep at 70 MHz, true θ=0.25 ==')
print(f"{'W':>3s} {'strip':>5s} {'gap':>4s} {'C_dry':>6s} {'C_wet':>6s} {'ratio':>5s} {'soil%':>5s} {'err 0.1mm':>9s} {'err 0.3mm':>9s} {'err water':>9s}")
for Wb, wst, gst in [(12, 5, 1), (12, 4, 3), (12, 3, 5), (12, 2, 7), (16, 6, 3), (20, 7, 5)]:
    strips = [('S', -gst/2 - wst, -gst/2), ('G', gst/2, gst/2 + wst)]
    Cc = np.array([s.solve(s.pcb_scene(strips, strips, s.soil_material(th), W=Wb), F_FDR)['C'] for th in THETAS]); o = np.argsort(Cc)
    def err(**kw):
        r = s.solve(s.pcb_scene(strips, strips, s.soil_material(TH0), W=Wb, **kw), F_FDR)
        return np.interp(r['C'], Cc[o], THETAS[o]) - TH0
    fs = s.solve(s.pcb_scene(strips, strips, s.soil_material(0.05), W=Wb), F_FDR)['frac']['soil']
    Cd, Cw = np.interp(0.05, THETAS, Cc), np.interp(0.40, THETAS, Cc)
    print(f"{Wb:3d} {wst:5.0f} {gst:4.0f} {Cd*1e12:6.0f} {Cw*1e12:6.0f} {Cw/Cd:5.2f} {100*fs:4.0f}% {100*err(gap_top=0.1):+8.1f}% {100*err(gap_top=0.3):+8.1f}% {100*err(gap_top=0.1, gap_mat=s.WATER):+8.1f}%")

print(f'\ntotal {time.time()-t0:.0f}s, {len(rows)} solves')
