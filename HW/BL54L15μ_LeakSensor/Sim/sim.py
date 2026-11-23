#!/usr/bin/env python3
"""Circuit checks for the leak sensor 2026v5 (README 7.1). Needs ngspice on the PATH. usage: python3 sim.py

Values not taken from a datasheet are marked ASSUMED where they are set: the results show how much they matter.
"""
import math, os, random, re, subprocess, tempfile

VDD = 3.0


def spice(deck):
    """Run a deck in batch mode and return its .meas results by name."""
    with tempfile.NamedTemporaryFile('w', suffix='.cir', delete=False) as f:
        f.write(deck)
    out = subprocess.run(['ngspice', '-b', f.name], capture_output=True, text=True).stdout
    os.unlink(f.name)
    res = {m.group(1).lower(): float(m.group(2)) for m in re.finditer(r'^(\w+)\s+=\s+([-+0-9.eE]+)', out, re.M)}
    assert res, out[-2000:]
    return res


# ---------------------------------------------------------------- buzzer driver (README 5.5)
# CMT-5023S-SMT: 3 Vo-p, 4 kHz square wave at half duty, 110 mA at most, coil 12 +-3 ohm (datasheet). Its inductance
# is not given: ASSUMED 1 mH, swept. DMG1012T: Vgs(th) 0.5 to 1.0 V, about 0.4 ohm at Vgs 2.5 V (datasheet), as a
# level 1 model. C2: 10 uF X5R, ASSUMED 5 uF left at 3 V bias. GPIO drive ASSUMED 500 ohm.
BUZZ = """buzzer driver
Vbat bat 0 {voc}
Resr bat cell {esr}
Rw1 cell vdd 0.05
C2 vdd c2e 5u
Rc2 c2e 0 0.005
Imod vdd 0 3u
Rw2 cell vbz {rs}
Cb vbz cbe {cb}
Rcb cbe 0 0.01
Vcoil vbz n0 0
Lbz n0 n1 {l}
Rbz n1 drain {rcoil}
Vd3 drain d3a 0
D3 d3a vbz D4148
M1 drain gate 0 0 NM W=1 L=1
Cgs gate 0 55p
Cgd gate drain 6p
Vp p 0 PULSE(0 1 0 20n 20n 125u 250u)
Bg gdrv 0 V=V(vdd)*V(p)
Rg gdrv gate 500
R7 gate 0 1Meg
Bpq pq 0 V=V(drain)*(I(Vcoil)-I(Vd3))
Bpt pt 0 V=V(cell)*(I(Vcoil)-I(Vd3))
.model NM NMOS(LEVEL=1 VTO={vth} KP=1.43 LAMBDA=0.01)
.model D4148 D(IS=2.52n RS=0.568 N=1.752 CJO=4p TT=20n BV=100)
.tran 0.2u 10m 0 0.2u
.meas tran vmin min v(vdd) from=8m to=10m
.meas tran vpp pp v(vdd) from=8m to=10m
.meas tran ibat avg i(Vcoil) from=8m to=10m
.meas tran ipk max i(Vcoil) from=8m to=10m
.meas tran imin min i(Vcoil) from=8m to=10m
.meas tran vdmax max v(drain) from=8m to=10m
.meas tran pq avg v(pq) from=8m to=10m
.meas tran ptot avg v(pt) from=8m to=10m
.meas tran id3 avg i(Vd3) from=8m to=10m
.end
"""


def buzzer(voc=3.0, esr=0.5, l=1e-3, rcoil=12.0, vth=0.75, rs=0.05, cb=1e-12):
    """rs and cb: the optional resistor across JP1 and capacitor C3 in BZ1's own feed (what is left of C3 at 3 V)."""
    return spice(BUZZ.format(voc=voc, esr=esr, l=l, rcoil=rcoil, vth=vth, rs=rs, cb=cb))


def buzzer_report():
    print('== Buzzer driver: 4 kHz, half duty ==')
    print('Coil inductance (cell 3.0 V, 0.5 ohm):')
    print('   L mH  Icoil pk/min mA  cell avg mA  VDD min V  ripple mV  drain max V  Q1 mW  D3 avg mA')
    for l in (0.3e-3, 1e-3, 3e-3):
        r = buzzer(l=l)
        # the cell feeds the coil only while Q1 is on: its share is the coil current less D3's
        print('   %4.1f  %6.0f / %-6.0f  %8.0f  %9.2f  %9.0f  %11.2f  %5.1f  %9.0f' % (
            l * 1e3, r['ipk'] * 1e3, r['imin'] * 1e3, (r['ibat'] - r['id3']) * 1e3, r['vmin'], r['vpp'] * 1e3, r['vdmax'],
            r['pq'] * 1e3, r['id3'] * 1e3))
    print('Cell resistance and voltage (L 1 mH, coil 9 ohm, the lowest): VDD minimum at the module, V')
    print('   ohm   ' + '  '.join('%4.1f V' % v for v in (3.0, 2.7, 2.4)))
    for esr in (0.25, 0.5, 1, 2, 4, 8):
        print('   %4.2f  ' % esr + '  '.join('%6.2f' % buzzer(voc=v, esr=esr, rcoil=9.0)['vmin'] for v in (3.0, 2.7, 2.4)))
    r = buzzer(vth=1.0, voc=2.0, esr=2.0)
    print('Worst gate: Vth 1.0 V, cell 2.0 V and 2 ohm: coil peak %.0f mA, Q1 %.1f mW, VDD min %.2f V' % (
        r['ipk'] * 1e3, r['pq'] * 1e3, r['vmin']))
    print('Optional filter in BZ1\'s feed (JP1 cut and a resistor fitted, C3 fitted; ASSUMED 60 % of C3 left at 3 V):')
    print('   fitted                 ripple mV (L 0.3 / 1 mH)   coil peak, of unfiltered')
    base = {l: buzzer(l=l) for l in (0.3e-3, 1e-3)}
    for name, rs, cb in (('nothing (as built)', 0.05, 1e-12), ('2.2 ohm, 100 uF', 2.2, 60e-6), ('4.7 ohm, 100 uF', 4.7, 60e-6), ('4.7 ohm, 47 uF', 4.7, 28e-6)):
        f = {l: buzzer(l=l, rs=rs, cb=cb) for l in (0.3e-3, 1e-3)}
        print('   %-20s   %5.0f / %-5.0f              %3.0f %%' % (name, f[0.3e-3]['vpp'] * 1e3, f[1e-3]['vpp'] * 1e3, 100 * f[1e-3]['ipk'] / base[1e-3]['ipk']))
    r = buzzer()
    i_cell = (r['ibat'] - r['id3'])
    print('One minute of alarm takes %.2f mAh of the 850 mAh cell (%.0f mA average)' % (i_cell * 1000 / 60, i_cell * 1e3))
    # heat: nearly all of what the cell delivers ends in the coil, D3 and Q1, right beside U1. ASSUMED: board and
    # parts as one lump of 1.5 J/K, losing heat from 6 cm2 on each face at 10 W/m2K (still air in a closed case)
    p, g, c = r['ptot'], 6e-4 * 10 * 2, 1.5
    print('The driver turns %.0f mW into heat; one lump of %.1f J/K losing %.0f mW/K warms %.1f K in 10 s, %.1f K in 60 s' % (
        p * 1e3, c, g * 1e3, p / g * (1 - math.exp(-10 * g / c)), p / g * (1 - math.exp(-60 * g / c))))


# ---------------------------------------------------------------- leak front end (README 5.1)
# TPD1E10B06: 12 pF (datasheet). Pin and trace ASSUMED 5 pF a sense pin. SAADC sampling capacitor ASSUMED 2.5 pF
# behind 1 kohm, swept; TACQ 40 us is Nordic's figure for sources up to 800 kohm.
LEAK = """leak front end, A drives and B senses
Va src 0 PULSE(0 {vdd} 10u 10n 10n 1 2)
Rla src la 500
Rra src ra 500
Rrb rb 0 500
R3 la ra 1Meg
R1 la ea 10k
R4 lb rb 1Meg
R2 lb eb 10k
Rw ea eb {rw}
Cd1 ea 0 12p
Cd2 eb 0 12p
Cla la 0 5p
Clb lb 0 5p
Vs ctl 0 PULSE(0 1 2m 10n 10n {tacq} 1)
S1 lb adc ctl 0 SWM
Cs adc 0 {cs}
.model SWM SW(RON=1k ROFF=1e12 VT=0.5)
.ic v(adc)=0
.tran 0.1u 2.2m 0 0.1u uic
.meas tran vset find v(lb) at=1.99m
.meas tran t99 when v(lb)={v99} rise=1
.meas tran vadc find v(adc) at={tend}
.end
"""


def leak_report():
    print('== Leak front end ==')
    vih, vil = 0.7, 0.3                           # of VDD: ASSUMED, the usual Nordic GPIO thresholds
    rs = lambda frac: 1e6 / frac - 1.02e6          # water resistance that puts the sense node at frac of VDD
    print('Edge wake: sense node reaches %.1f VDD below %.2f Mohm; back under %.1f VDD above %.2f Mohm' % (vih, rs(vih) / 1e6, vil, rs(vil) / 1e6))
    print('  Rw      divider V   settles to 99 %% in   SAADC after 40 us (Cs 2.5 / 5 / 10 pF), error')
    for rw in (1e3, 1e5, 4.1e5, 1e6, 1e7):
        ideal = VDD * 1e6 / (1.02e6 + rw)
        row = []
        for cs in (2.5e-12, 5e-12, 10e-12):
            r = spice(LEAK.format(vdd=VDD, rw=rw, cs=cs, tacq=40e-6, v99=0.99 * ideal, tend=2e-3 + 40e-6))
            row.append('%+.1f %%' % (100 * (r['vadc'] / ideal - 1)))
        print('  %-7s %6.3f      %6.0f us            %s' % ('%g' % rw, ideal, (r['t99'] - 10e-6) * 1e6, '   '.join(row)))
    r3 = spice(LEAK.format(vdd=VDD, rw=1e7, cs=2.5e-12, tacq=3e-6, v99=0.5, tend=2e-3 + 3e-6))
    print('  with TACQ 3 us at 10 Mohm the reading is %+.0f %% off: the long acquisition is what makes 1 Mohm work' % (
        100 * (r3['vadc'] / (VDD * 1e6 / 11.02e6) - 1)))
    print('Errors a dry board could read as water (sense node, 1 Mohm to ground):')
    for name, i in (('pin leakage 10 nA (ASSUMED)', 10e-9), ('100 Mohm across the contacts (film, flux)', VDD / 101e6)):
        v = i * 1e6
        print('  %-42s %5.0f mV, as %.0f Mohm of water' % (name, v * 1e3, (VDD / v * 1e6 - 1.02e6) / 1e6))
    print('  TVS leakage (100 nA max at 5 V, datasheet) loads the driven side only: %.0f mV across R1, up to 0.1 uA from the cell' % (100e-9 * 1e4 * 1e3))
    # IEC 61000-4-2 contact discharge into a dome: TPD1E10B06 clamps, R1 limits the pin. Breakdown and dynamic
    # resistance ASSUMED 7 V and 0.5 ohm from the datasheet's curves
    for kv in (8, 15):
        ipk = kv * 1e3 / 330 * 1.25               # first peak, 3.75 A/kV
        vcl = 7 + 0.5 * ipk
        print('ESD %2d kV: about %.0f A in D1/D2, clamped near %.0f V; %.1f mA through R1 into the pin\'s own clamp' % (
            kv, ipk, vcl, (vcl - VDD - 0.6) / 1e4 * 1e3))


# ---------------------------------------------------------------- I2C, crystal, dome press
def misc_report():
    print('== I2C on the internal pull-ups ==')
    # 13 kohm typical (Ezurio). Bus: 12.5 and 15.2 mm of track (ASSUMED 1 pF/cm beside the pour), MCU pin 4 pF and
    # SHT4x pin 3 pF (ASSUMED)
    for name, mm_ in (('SCL', 12.5), ('SDA', 15.2)):
        c = mm_ / 10 * 1e-12 + 7e-12
        print('  %s: %.1f pF, rise (30 to 70 %%) %.0f ns at 13 kohm, %.0f ns at 16 kohm; 300 ns allowed at 400 kHz' % (
            name, c * 1e12, 0.847 * 13e3 * c * 1e9, 0.847 * 16e3 * c * 1e9))
    print('  the bus could carry %.0f pF before 400 kHz fails at 16 kohm' % (300e-9 / 0.847 / 16e3 * 1e12))
    print('== 32.768 kHz crystal ==')
    # CM7V-T1A, 9 pF load. Each leg: 2.1 mm front, 2.8 mm back, two vias and a 1.8 x 1.0 mm pad: ASSUMED 1.0 pF.
    # Pulling ASSUMED 13 ppm/pF (C1 2.6 fF, C0 1 pF, tuning fork typical)
    stray = 1.0 / 2
    print('  board stray adds about %.1f pF to the load: %.0f ppm fast if the internal capacitors are set for 9 pF, trimmed out by setting them %.1f pF lower' % (
        stray, stray * 13, stray * 2))
    print('== Dome press (README 5.7) ==')
    # nominal: pin surface 0.20 mm off the board, dome 0.30 mm high. ASSUMED one-sigma spreads: printed bore
    # position 0.08, slot datum 0.05, dome height 0.03, pin diameter 0.01
    random.seed(1)
    sigma, n = math.sqrt(0.08 ** 2 + 0.05 ** 2 + 0.03 ** 2 + 0.01 ** 2), 200000
    for nom in (0.10, 0.15, 0.20, 0.25):
        miss = sum(nom + random.gauss(0, sigma) <= 0 for _ in range(n))
        print('  %.2f mm nominal press, sigma %.2f mm: no contact on %.1f %% of pins' % (nom, sigma, 100 * miss / n))


if __name__ == '__main__':
    buzzer_report(); leak_report(); misc_report()
