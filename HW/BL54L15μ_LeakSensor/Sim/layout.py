"""Layout checks for the leak sensor 2026v5 (README 7.1): ground under each trace, ground stitching, and how far metal
is from the chip antenna. Run with KiCad's Python: python3 layout.py ../BL54L15μ_LeakSensor.kicad_pcb

Sketch coordinates as in the README: origin on the cell's axis, +y up (KiCad X = 100 + x, Y = 100 - y).
"""
import collections, math, sys
import pcbnew

b = pcbnew.LoadBoard(sys.argv[1])
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
mm, T = pcbnew.FromMM, pcbnew.ToMM
F, B = pcbnew.F_Cu, pcbnew.B_Cu
gnd = [z for z in b.Zones() if not z.GetIsRuleArea() and z.GetNetname() == 'GND']


def poured(layer, x, y):
    p = pcbnew.VECTOR2I(mm(100 + x), mm(100 - y))
    return any(z.GetFirstLayer() == layer and z.HitTestFilledArea(layer, p) for z in gnd)


def S(p):
    return T(p.x) - 100, 100 - T(p.y)


# ---- ground on the other layer under every signal trace, sampled every 0.1 mm
runs = collections.defaultdict(lambda: [0.0, 0.0, 0.0])          # length, length over ground, longest gap
for t in b.GetTracks():
    if t.GetClass() != 'PCB_TRACK' or t.GetNetname() in ('GND', ''):
        continue
    (x0, y0), (x1, y1) = S(t.GetStart()), S(t.GetEnd())
    n = max(1, int(math.hypot(x1 - x0, y1 - y0) / 0.1))
    other, r, gap = (B if t.GetLayer() == F else F), runs[t.GetNetname()], 0.0
    for i in range(n):
        d = math.hypot(x1 - x0, y1 - y0) / n
        ok = poured(other, x0 + (x1 - x0) * (i + 0.5) / n, y0 + (y1 - y0) * (i + 0.5) / n)
        r[0] += d; r[1] += d * ok
        gap = 0.0 if ok else gap + d
        r[2] = max(r[2], gap)
print('Ground on the other layer under each net (mm of trace, share over ground, longest stretch without)')
for net in sorted(runs, key=lambda k: runs[k][1] / runs[k][0]):
    l, g, gap = runs[net]
    print('  %-14s %5.1f mm  %3.0f %%  %4.1f mm' % (net, l, 100 * g / l, gap))

# ---- stitching: distance from every poured point (0.25 mm grid, either layer) to the nearest ground via or hole
vias = [S(t.GetPosition()) for t in b.GetTracks() if t.GetClass() == 'PCB_VIA' and t.GetNetname() == 'GND']
vias += [S(p.GetPosition()) for f in b.GetFootprints() for p in f.Pads() if p.GetNetname() == 'GND' and p.HasHole()]
bb = b.GetBoardEdgesBoundingBox()
x0, x1, y0, y1 = T(bb.GetLeft()) - 100, T(bb.GetRight()) - 100, 100 - T(bb.GetBottom()), 100 - T(bb.GetTop())
worst, far, total = (0, 0, 0), 0, 0
for i in range(int((x1 - x0) / 0.25) + 1):
    for j in range(int((y1 - y0) / 0.25) + 1):
        x, y = x0 + 0.25 * i, y0 + 0.25 * j
        if poured(F, x, y) or poured(B, x, y):
            d = min(math.hypot(x - vx, y - vy) for vx, vy in vias)
            total += 1; far += d > 3.0
            worst = max(worst, (d, x, y))
print('Stitching: %d ground vias; the pour point farthest from one is %.1f mm away at (%.1f, %.1f); %.1f %% of the pour is over 3 mm away' % (
    len(vias), worst[0], worst[1], worst[2], 100 * far / total))

# ---- antenna: the chip sits in the module's antenna-end corner on pin 1's side (Ezurio datasheet figure 10)
ic = [f for f in b.GetFootprints() if f.GetReference() == 'IC1'][0]
ax, ay = S(ic.GetPosition())
chip = (ax - 0.22, ay + 3.15 - 0.5)              # 0.22 mm in from the end, 0.5 mm in from pin 1's side: read off figure 10
print('Chip antenna at about (%.1f, %.1f): %.1f mm from the right edge, %.1f mm from the top' % (chip[0], chip[1], x1 - chip[0], y1 - chip[1]))
print('  %.1f mm outside the cell\'s outline (radius 7.8 about the origin, behind the board)' % (math.hypot(*chip) - 7.8))
for ref in ('BZ1', 'X1', 'P2', 'J1', 'BT1'):
    f = [f for f in b.GetFootprints() if f.GetReference() == ref][0]
    d = min(math.hypot(chip[0] - px, chip[1] - py) for p in f.Pads() for px, py in [S(p.GetPosition())])
    print('  %s: nearest pad center %.1f mm away' % (ref, d))
