"""Leak sensor 2026v5 case: an open-top body with half-dome ends and a lid that slides on from the rear, checked against
the board, the cell, the battery contacts and the leak pins.

Run (from this folder): kicad-cli pcb export step --grid-origin --subst-models -o board.step ../BL54L15μ_LeakSensor.kicad_pcb
     OUT=$PWD/LeakSensor_2026v5.FCStd STEP=$PWD/board.step [EXPORT=dir for STL/STEP and the case.3mf print plate] freecadcmd build_case.py
Axes: X right as seen from the front (the board's x), Y from the front toward the rear (along the cell),
Z up from the table. The board's front face is at Y = 0; its sketch coordinates (x, y) map to (X, Z = y + AxisZ).
The parameter values are recorded in the "Params" variable set; geometry is rebuilt by rerunning this script.
"""
import math, os
import FreeCAD, Part
from FreeCAD import Vector as V

P = dict(
    # board (README 5.6): 18 x 16, centered on the cell's axis; square top corners, straight sides, and a half ellipse
    # BoardBotB deep for a bottom, concentric with the case's inner bottom
    BoardW2=9.0, BoardTop=8.15, BoardBot=-7.85, BoardBotB=7.4, BoardT=1.6,
    # body
    Wall=1.5,            # walls, sides and domes: 0.85 mm stays behind the track's groove (1.0 would leave 0.35)
    Floor=1.0, FloorGap=0.1, TopGap=0.15, LidT=1.2, Clear=0.15,
    BottomB=8.5,         # the bottom is a half ellipse, OW wide and this deep outside (the inside concentric): flatter at
                         # the bottom than a semicircle, and fuller, so it still clears the board's round bottom
    # both ends are half domes: the cross-section turned about a vertical axis, so seen from above they are semicircles
    # and every cut through the axis shows the side's curve. The front one's axis is 1.5 mm in front of the board, so
    # the module's end (2.1 mm tall, 0.18 mm from the board's edge) clears the wall; the rear one's is DomeIn in front
    # of the cell's rear end
    FrontDomeY=-1.5, DomeIn=1.0,
    BackGap=2.0,         # board back to the divider: the 209's solder ear and the BT1 wire joints
    PanelT=1.6,          # Keystone snap-on contacts fit 1.52-1.78 mm panels
    SpringGap=2.5,       # 209 leaf, compressed: divider face to the cell's negative end (assumed; free height about 6.5)
    CellD=15.6, CellL=27.0,   # CR2 maximum
    ButtonGap=0.85,      # 228: 0.25 mm plate plus 0.6 mm button
    PanelTop=5.3,        # top edge of both contact panels above the cell axis (228: button 6.1 above its lower edge, 11.4 tall)
    # board slot. The domes push the board back, so the front face is the datum: crush ribs behind hold it on the
    # front lip, and the dome press then depends on two faces of one printed part, not on the board's thickness
    Lip=0.4, LipT=0.8, Tol=0.1, DomeRelief=2.4, RailTop=7.3, RibR=0.3, RibCrush=0.1,
    # the front lip is cut away beside parts that stand in its 0.4 mm, and each side's rib is only as long as the lip
    # left opposite it: on the right the lip stops at LipFreeY (the module's antenna end is 0.18 mm from the board's
    # edge from y 1.35 up); on the left it is open from LipLeftY0 to LipLeftY1 (D3 and BZ1, 0.5 to 0.6 mm from the edge)
    LipFreeY=0.9, LipLeftY0=-2.0, LipLeftY1=5.9,
    # leak pins
    PinD=2.5, PinL=6.0, PinX=3.95, DomeY=-4.85, DomeApex=0.3, PinPress=0.1, BossWall=0.8,   # flat-ended stock pins
    PinCap=0.6,          # bore cap over the pin
    BossBack=1.1,        # boss face toward the board: clear of the domes' feet and of Q1 (0.9 mm tall at most), which
                         # ends just above the left boss. The pin stands 0.9 mm proud of it, onto the dome
    # cell cradle; the + wire runs over both panels in the bay's upper left corner, inside the dome's curve
    CradleT=1.2, CradleInset=5.0, WireD=1.2, WireX=-7.0,
    # one small vent in the left wall into the gap in front of the board, beside U1: approximate humidity is enough
    VentW=1.0, VentH=2.0, VentZ=6.6, VentY=-1.75,   # slot width (along the case) and height; its center (sketch y, level
                                                     # with U1's lower half, 0.7 mm of wall over it) and along the case
    # BZ1 has no 3D model in the board's STEP: its body as a box for the fit checks (center, size, height)
    BzX=-5.9, BzY=3.08, BzW=5.0, BzH=2.0,
    # slide-in lid after the hygrometer 2026v3's, its track turned inside out: the side walls run up to the lid's plate
    # outside, and a tongue under the plate runs just inside each wall, its 45 degree ridge facing out into a groove in
    # the wall's inner face. The lid slides on from the rear and stops where the grooves end, behind the board (in
    # front of it the tongues would meet the board's top corners); the plate covers the front dome (as part of the lid
    # its curve would sweep through the walls), and the lid takes the rear dome's top
    SeamY=5.5,           # the tongues reach down to here (sketch y), as does the lid's share of the rear dome: under the
                         # cell hold-downs, so they slide out over the dome's rim, and 0.2 mm over the contact panels
    TrackY0=2.6,         # where the grooves start: just behind the board slot's back lip
    RailT=0.8, RailV=0.6,                # tongue thickness; ridge depth (its flanks span 2 x RailV down from the plate)
    # fits as on 2026v3: faces that slide or bear are line to line; only the groove is cut 0.05 deeper (and 0.1 taller)
    # than the ridge, and the detent's notch 0.05 deeper than its bump
    GrooveC=0.05,
    BumpH=0.5, BumpZ=1.4, BumpY=5.0,     # 60 degree bump on each tongue: height, how far up from its foot (it ends 0.2 mm
                                         # under the ridge), apex ahead of the track's rear entry
    NotchC=0.05, RampD=0.6,              # the wall's notch under the bump, behind a lead-in ramp RampD deep at the entry
    HoldW=4.0, HoldGap=0.1,   # ribs under the lid over the cell saddles: the board, not the cell, sets the bay's height
)
P['AxisZ'] = -P['BoardBot'] + P['FloorGap'] + P['Floor']
# where the board's straight sides start: the bottom ellipse's center (sketch y)
P['BoardSideY'] = P['BoardBot'] + P['BoardBotB']
P['IW'] = P['BoardW2'] + P['Clear']
P['OW'] = P['IW'] + P['Wall']
P['Ztop'] = P['AxisZ'] + P['BoardTop'] + P['TopGap'] + P['LidT']
P['Zb'] = P['Ztop'] - P['LidT']
P['Yf'] = P['FrontDomeY']
P['Yfo'] = P['Yf'] - P['OW']
P['Yd0'] = P['BoardT'] + P['BackGap']
P['Yd1'] = P['Yd0'] + P['PanelT']
P['Yc0'] = P['Yd1'] + P['SpringGap']
P['Yc1'] = P['Yc0'] + P['CellL']
P['Yr0'] = P['Yc1'] + P['ButtonGap']
P['Yr1'] = P['Yr0'] + P['PanelT']
P['Ydome'] = P['Yc1'] - P['DomeIn']
P['Yend'] = P['Ydome'] + P['OW']
P['SeamZ'] = P['AxisZ'] + P['SeamY']
P['PinY'] = -(P['DomeApex'] - P['PinPress'] + P['PinD'] / 2)


def outer_z(x, y):
    """Height of the case's outer bottom at (x, y): the half ellipse across, turned about each dome's axis."""
    yd = P['FrontDomeY'] if y < P['FrontDomeY'] else (P['Ydome'] if y > P['Ydome'] else y)
    rho = min(math.hypot(x, y - yd), P['OW'])
    return P['BottomB'] * (1 - math.sqrt(1 - (rho / P['OW']) ** 2))


# the pins go in until their flat ends are flush with the lowest point of the curve where they exit: nothing stands
# proud, and the outer part of each end sits inside its hole by however much the curve rises across the pin
P['PinZ0'] = min(outer_z(P['PinX'] + P['PinD'] / 2 * i / 10 * math.cos(math.radians(a)),
                         P['PinY'] + P['PinD'] / 2 * i / 10 * math.sin(math.radians(a))) for i in range(11) for a in range(0, 360, 5))
P['PinZ1'] = P['PinZ0'] + P['PinL']
g = lambda k: P[k]
AZ = g('AxisZ')


def box(x0, x1, y0, y1, z0, z1):
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))


def cylY(x, z, r, y0, y1):
    return Part.makeCylinder(r, y1 - y0, V(x, y0, z), V(0, 1, 0))


def cylZ(x, y, r, z0, z1):
    return Part.makeCylinder(r, z1 - z0, V(x, y, z0), V(0, 0, 1))


def u_edges(w2, zb, zt, b, s, y0):
    """Half the case's section in XZ at y0, bottom center to top center (s = -1 mirrors it): a quarter ellipse w2 wide
    and b deep from the bottom at zb, then a straight side up to the square top at zt."""
    c = V(0, y0, zb + b)
    u0, u1 = (-math.pi / 2, 0) if s > 0 else (-math.pi, -math.pi / 2)
    arc = Part.ArcOfEllipse(Part.Ellipse(c + V(w2, 0, 0), c + V(0, 0, b), c), u0, u1)
    side, top = V(s * w2, y0, zb + b), V(s * w2, y0, zt)
    return [arc.toShape(), Part.LineSegment(side, top).toShape(), Part.LineSegment(top, V(0, y0, zt)).toShape()]


def u_prism(w2, zb, zt, b, y0, y1):
    """The section extruded along Y."""
    e = u_edges(w2, zb, zt, b, 1, y0) + u_edges(w2, zb, zt, b, -1, y0)
    return Part.Face(Part.Wire(Part.__sortEdges__(e))).extrude(V(0, y1 - y0, 0))


def u_dome(w2, zb, zt, b, yc, s=1):
    """Half the section turned 180 degrees about the vertical axis at yc, toward the rear (s = 1) or the front (s = -1):
    a half dome that continues u_prism without a seam."""
    e = u_edges(w2, zb, zt, b, s, yc) + [Part.LineSegment(V(0, yc, zt), V(0, yc, zb)).toShape()]
    return Part.Face(Part.Wire(Part.__sortEdges__(e))).revolve(V(0, yc, 0), V(0, 0, 1), 180)


def lid_space():
    """The lid's share of the outer shape: everything above the walls' tops, and above the seam over the rear dome."""
    w = g('OW') + 1
    return box(-w, w, g('Yfo') - 1, g('Yend') + 1, g('Zb'), g('Ztop') + 1).fuse(
        box(-w, w, g('Ydome'), g('Yend') + 1, g('SeamZ'), g('Ztop') + 1))


def track(groove):
    """Both tracks, from TrackY0 to the rear dome: the lid's tongues just inside the walls, ridges and all (groove = False),
    or the walls' grooves, GrooveC deeper at the ridge's apex and 2 GrooveC lower at its foot, so only the upper flank
    and the faces either side touch (groove = True)."""
    xi, zb, v = g('IW'), g('Zb'), g('RailV')
    if groove:
        c = g('GrooveC')
        sec = [(xi - 0.05, zb - 2 * v - 2 * c), (xi, zb - 2 * v - 2 * c), (xi + v + c, zb - v - c), (xi, zb), (xi - 0.05, zb)]
    else:                                    # up into the plate: a tongue that stops at its underside breaks the fuse
        sec = [(xi - g('RailT'), g('SeamZ')), (xi, g('SeamZ')), (xi, zb - 2 * v), (xi + v, zb - v), (xi, zb), (xi, zb + 0.5),
               (xi - g('RailT'), zb + 0.5)]
    # the tongues run on into the rear dome's wall until it covers their ends, so they join it in volume
    y1 = g('Ydome') + (0 if groove else math.sqrt(xi ** 2 - (xi - g('RailT')) ** 2) + 0.1)
    out = []
    for sx in (-1, 1):
        pts = [V(sx * x, g('TrackY0'), z) for x, z in sec]
        out.append(Part.Face(Part.makePolygon(pts + [pts[0]])).extrude(V(0, y1 - g('TrackY0'), 0)))
    return out[0].fuse(out[1])


def detent(cut):
    """The 2026v3 detent turned inside out, both sides: a 60 degree bump on each tongue's face under the ridge, near its
    rear end (cut = False, for the lid), or the wall's notch over it, NotchC deeper, behind a lead-in ramp from the
    track's rear entry (cut = True), so the bump rides the wall only for the last few millimeters."""
    xr, yb, t60 = g('IW'), g('Ydome') - g('BumpY'), math.tan(math.radians(60))
    if cut:
        hn = g('BumpH') + g('NotchC')
        sec = [(xr - 0.01, yb - hn * t60), (xr + hn, yb), (xr, yb + hn * t60), (xr + g('RampD'), g('Ydome') + 0.01),
               (xr - 0.01, g('Ydome') + 0.01)]
        z0, z1 = g('SeamZ'), g('SeamZ') + g('BumpZ') + 0.3
    else:
        sec = [(xr - 0.01, yb - g('BumpH') * t60), (xr + g('BumpH'), yb), (xr - 0.01, yb + g('BumpH') * t60)]
        z0, z1 = g('SeamZ'), g('SeamZ') + g('BumpZ')
    out = []
    for sx in (-1, 1):
        pts = [V(sx * x, y, z0) for x, y in sec]
        out.append(Part.Face(Part.makePolygon(pts + [pts[0]])).extrude(V(0, 0, z1 - z0)))
    return out[0].fuse(out[1])


def outline(d, n=48):
    """Board outline offset by d (sketch coordinates): square top corners, straight sides, a half ellipse for a bottom.
    Each point of the ellipse moves d along its normal."""
    w, t, a, b, cy = g('BoardW2') + d, g('BoardTop') + d, g('BoardW2'), g('BoardBotB'), g('BoardSideY')
    pts = [(w, t)]
    for i in range(n + 1):                                   # right to left, through the bottom
        u = -math.pi * i / n
        nx, ny = math.cos(u) / a, math.sin(u) / b
        k = d / math.hypot(nx, ny)
        pts.append((a * math.cos(u) + k * nx, cy + b * math.sin(u) + k * ny))
    pts.append((-w, t))
    return pts


def outline_prism(d, y0, y1):
    pts = []
    for x, y in outline(d):
        if not pts or (V(x, y0, y + AZ) - pts[-1]).Length > 1e-6:
            pts.append(V(x, y0, y + AZ))
    pts.append(pts[0])
    return Part.Face(Part.makePolygon(pts)).extrude(V(0, y1 - y0, 0))


# ============================ body ============================
def capsule(w2, zb, zt, b):
    return u_prism(w2, zb, zt, b, g('Yf'), g('Ydome')).fuse([u_dome(w2, zb, zt, b, g('Yf'), -1),
                                                             u_dome(w2, zb, zt, b, g('Ydome'), 1)])


outer = capsule(g('OW'), 0, g('Ztop'), g('BottomB'))


def cavity(zt):
    return capsule(g('IW'), g('Floor'), zt, g('BottomB') - g('Floor'))


body = outer.cut(cavity(g('Zb') + 0.5))     # kept inside the outer shell, clear of its top

# inner parts stand on the curved floor: built from the bottom up, then trimmed to the outside
adds = []
for y0, y1 in ((g('Yd0'), g('Yd1')), (g('Yr0'), g('Yr1'))):                      # contact panels
    adds.append(box(-g('IW'), g('IW'), y0, y1, 0, AZ + g('PanelTop')))
for yc in (g('Yc0') + g('CradleInset'), g('Yc1') - g('CradleInset')):              # cell saddles
    adds.append(box(-g('IW'), g('IW'), yc - g('CradleT') / 2, yc + g('CradleT') / 2, 0, AZ).cut(
        cylY(0, AZ, g('CellD') / 2 + 0.2, yc - 1, yc + 1)))
# board slot: lips 0.4 mm over the board's sides and bottom curve, front and back; open above the straight sides
frame = box(-g('IW'), g('IW'), -g('LipT'), g('BoardT') + g('LipT'), 0, AZ + g('RailTop'))
frame = frame.cut(outline_prism(-g('Lip'), -5, 5))
frame = frame.cut(outline_prism(g('Tol'), 0, g('BoardT') + g('Tol')))
frame = frame.cut(box(-g('BoardW2') - g('Tol'), g('BoardW2') + g('Tol'), 0, g('BoardT') + g('Tol'), AZ + g('BoardSideY'), AZ + 30))
for sx in (-1, 1):                                       # front lip relief around each dome
    frame = frame.cut(cylY(sx * g('PinX'), AZ + g('DomeY'), g('DomeRelief'), -g('LipT') - 0.1, 0.0))
frame = frame.cut(box(0, g('IW') + 1, -g('LipT') - 0.1, 0.0, AZ + g('LipFreeY'), AZ + 30))   # no front lip beside the module
frame = frame.cut(box(-g('IW') - 1, 0, -g('LipT') - 0.1, 0.0, AZ + g('LipLeftY0'), AZ + g('LipLeftY1')))   # nor beside D3 and BZ1
adds.append(frame)
# leak pin bosses: in front of the board, out to the front dome's wall, bore blind at the top, open toward the dome
for sx in (-1, 1):
    x = sx * g('PinX')
    adds.append(box(x - g('PinD') / 2 - g('BossWall'), x + g('PinD') / 2 + g('BossWall'), g('Yfo'), -g('BossBack'),
                    0, g('PinZ1') + g('PinCap')))
for a in adds:
    body = body.fuse(a.common(outer))

subs = []
for sx in (-1, 1):                                       # pin bores
    subs.append(cylZ(sx * g('PinX'), g('PinY'), g('PinD') / 2, -1, g('PinZ1')))
vy = g('VentY')                                          # side vent
subs.append(box(-g('OW') - 1, -g('IW') + 1, vy - g('VentW') / 2, vy + g('VentW') / 2, AZ + g('VentZ') - g('VentH') / 2, AZ + g('VentZ') + g('VentH') / 2))
subs += [lid_space(), track(True), detent(True)]
for s in subs:
    body = body.cut(s)

# ============================ lid ============================
lid = outer.cut(cavity(g('Zb'))).common(lid_space()).fuse([track(False), detent(False)])
hr, hw = g('CellD') / 2 + g('HoldGap'), g('HoldW')
for yc in (g('Yc0') + g('CradleInset'), g('Yc1') - g('CradleInset')):              # cell hold-downs, drawn as a profile:
    y = yc - g('CradleT') / 2                                                       # cutting a cylinder out left the lid unorientable
    zs = AZ + math.sqrt(hr ** 2 - hw ** 2)
    zt = g('Zb') + 0.5                                                              # well into the plate: a sliver breaks the fuse
    e = [Part.Arc(V(-hw, y, zs), V(0, y, AZ + hr), V(hw, y, zs)), Part.LineSegment(V(hw, y, zs), V(hw, y, zt)),
         Part.LineSegment(V(hw, y, zt), V(-hw, y, zt)), Part.LineSegment(V(-hw, y, zt), V(-hw, y, zs))]
    lid = lid.fuse(Part.Face(Part.Wire([x.toShape() for x in e])).extrude(V(0, g('CradleT'), 0)))
# crush ribs on the back lip along the straight sides, with a rounded top as the lead-in; fused after the fit checks
ribs = []
for sx in (-1, 1):
    x, y = sx * (g('BoardW2') - g('RibR')), g('BoardT') - g('RibCrush') + g('RibR')   # clear of the slot's side wall: tangent faces break the fuse
    # opposite what is left of the front lip on the straight sides: the top on the left, the bottom on the right
    z0 = AZ + (g('LipLeftY1') if sx < 0 else g('BoardSideY'))
    z1 = AZ + (g('RailTop') if sx < 0 else g('LipFreeY')) - g('RibR')
    ribs.append(cylZ(x, y, g('RibR'), z0, z1).fuse(Part.makeSphere(g('RibR'), V(x, y, z1))))
ribs = ribs[0].fuse(ribs[1])
try:                                  # not the lid: refined, it looks valid but every boolean against it comes back empty.
    refined = body.copy().removeSplitter()  # Cosmetic, and on curved ends it has thrown, or turned its input inside
    if refined.isValid() and abs(refined.Volume - body.Volume) < 1:   # out in place (hence the copy)
        body = refined
except Part.OCCError:
    pass

# ============================ references (not printed) ============================
refs = {}
s = Part.read(os.environ['STEP'])
top = max(s.Solids, key=lambda x: x.Volume).BoundBox.ZMax          # KiCad's board body is 1.51 mm: place it by its front face
m = FreeCAD.Matrix(); m.rotateX(math.pi / 2); m.move(V(0, top, AZ))
keep = [x for x in s.Solids if x.BoundBox.ZMin > -0.05]              # drop J1's header: production boards have none
refs['board'] = Part.makeCompound([x.transformGeometry(m) for x in keep])
front_parts = Part.makeCompound([x.transformGeometry(m) for x in keep if x.BoundBox.ZMax > top + 0.05])   # all but the bare board
refs['header'] = Part.makeCompound([x.transformGeometry(m) for x in s.Solids if x.BoundBox.ZMin <= -0.05])
refs['cell'] = cylY(0, AZ, g('CellD') / 2, g('Yc0'), g('Yc1'))
refs['pins'] = cylZ(-g('PinX'), g('PinY'), g('PinD') / 2, g('PinZ0'), g('PinZ1')).fuse(cylZ(g('PinX'), g('PinY'), g('PinD') / 2, g('PinZ0'), g('PinZ1')))
refs['buzzer'] = box(g('BzX') - g('BzW') / 2, g('BzX') + g('BzW') / 2, -g('BzH'), 0, AZ + g('BzY') - g('BzW') / 2, AZ + g('BzY') + g('BzW') / 2)
refs['wire'] = cylY(g('WireX'), AZ + g('PanelTop') + g('WireD') / 2 + 0.05, g('WireD') / 2, g('Yd0'), g('Yr1'))
pt = AZ + g('PanelTop')
c209 = box(-3.95, 3.95, g('Yd0') - 0.3, g('Yd0'), pt - 9.0, pt + 0.3).fuse(box(-3.95, 3.95, g('Yd0') - 0.3, g('Yd1') + 0.3, pt, pt + 0.3)) \
    .fuse(box(-3.95, 3.95, g('Yd1'), g('Yc0'), pt + 0.3 - 12.1, pt + 0.3))
c228 = box(-3.95, 3.95, g('Yr0') - 0.25, g('Yr0'), pt + 0.25 - 11.4, pt + 0.25).fuse(box(-3.95, 3.95, g('Yr0') - 0.25, g('Yr1') + 0.25, pt, pt + 0.25)) \
    .fuse(box(-3.95, 3.95, g('Yr1'), g('Yr1') + 0.25, pt + 0.25 - 9.5, pt + 0.25)) \
    .fuse(cylY(0, pt + 0.25 - 11.4 + 6.1, 2.2, g('Yc1'), g('Yr0') - 0.25))
refs['contacts'] = c209.fuse(c228)

# ============================ checks ============================
def vol(a, b):
    try:
        return a.common(b).Volume
    except Exception:
        return -1


print('PART body solids %d valid %s vol %.0f bbox %s' % (len(body.Solids), body.isValid(), body.Volume, body.BoundBox))
print('PART lid solids %d valid %s vol %.0f bbox %s' % (len(lid.Solids), lid.isValid(), lid.Volume, lid.BoundBox))
print('SIZE %.2f x %.2f x %.2f mm (width x length x height)' % (2 * g('OW'), g('Yend') - g('Yfo'), g('Ztop')))
for name, part in (('body', body), ('lid', lid)):        # the checks below are booleans: make sure they see the part at all
    probe = vol(part, box(-0.1, 0.1, -10, 60, -1, 30))
    print('CHECK %s probe (0.2 mm slab across the middle) %.3f mm3' % (name, probe))
    assert probe > 1, 'booleans against the %s fail' % name
    assert part.isValid() and part.Volume > 0 and part.BoundBox.ZMax < g('Ztop') + 0.01, 'the %s came out broken' % name
print('CHECK body/lid overlap %.3f (line-to-line fits touch)' % vol(body, lid))
for k, r in refs.items():
    if k == 'header':
        continue
    vb, vl = vol(body, r), vol(lid, r)
    print('CHECK %-8s body %.3f lid %.3f' % (k, vb, vl))
    for name, part in (('body', body), ('lid', lid)):
        c = part.common(r)
        if c.Volume > 1e-3:
            for so in c.Solids:
                if so.Volume > 1e-3:
                    b = so.BoundBox
                    print('  hit %s %.3f mm3 at x %.2f..%.2f y %.2f..%.2f z %.2f..%.2f (sketch y %.2f..%.2f)' % (name, so.Volume, b.XMin, b.XMax, b.YMin, b.YMax, b.ZMin, b.ZMax, b.ZMin - AZ, b.ZMax - AZ))
print('CHECK pins/board %.3f, pins/buzzer %.3f, pins/cell %.3f, contacts/cell %.3f, wire/cell %.3f, wire/contacts %.3f' % (
    vol(refs['pins'], refs['board']), vol(refs['pins'], refs['buzzer']), vol(refs['pins'], refs['cell']),
    vol(refs['contacts'], refs['cell']), vol(refs['wire'], refs['cell']), vol(refs['wire'], refs['contacts'])))
for k, r in (('front parts', front_parts), ('buzzer', refs['buzzer'])):
    print('CHECK %s: least gap to the body %.2f mm, to the lid %.2f mm' % (k, r.distToShape(body)[0], r.distToShape(lid)[0]))
for so in front_parts.Solids:                   # which parts are close, and where (sketch coordinates)
    d, pts, _ = so.distToShape(body)
    if d < 0.5:
        print('  %.2f mm at x %.2f, y %.2f, %.2f mm in front of the board' % (d, pts[0][0].x, pts[0][0].z - AZ, -pts[0][0].y))
dome_gap = -refs['pins'].BoundBox.YMax          # pin surface to the board's front face
print('CHECK pin surface %.2f mm in front of the board face; dome apex at %.2f: %.2f mm press' % (dome_gap, g('DomeApex'), g('DomeApex') - dome_gap))
print('CHECK pins %.2f..%.2f mm above the table (ends flush with the curve\'s lowest point where they exit)' % (g('PinZ0'), g('PinZ1')))
hits = []
for dz10 in range(5, 260, 5):                   # the board drops in from the top
    mm_ = FreeCAD.Matrix(); mm_.move(V(0, 0, dz10 / 10.0))
    v = vol(body, refs['board'].transformGeometry(mm_)) + vol(body, refs['buzzer'].transformGeometry(mm_))
    if v > 0.01:
        hits.append((dz10 / 10.0, round(v, 3)))
print('CHECK board drop-in collisions (height above seat, mm3):', hits[:10], 'count', len(hits))
others = body.fuse([refs[k] for k in ('board', 'cell', 'contacts', 'wire')])
hits = []
for dy10 in range(2, int(10 * (g('Yend') - g('Yfo'))), 2):  # the lid slides out to the rear
    mm_ = FreeCAD.Matrix(); mm_.move(V(0, dy10 / 10.0, 0))
    v = vol(others, lid.transformGeometry(mm_))
    if v > 0.001:
        hits.append((dy10 / 10.0, round(v, 3)))
print('CHECK lid slide-out collisions (mm moved, mm3; the bumps ride the ramps at first):', hits, 'count', len(hits))
print('CHECK slide-out ends after %.1f mm (the bumps leave the tracks after BumpY + their half length)' % (hits[-1][0] if hits else 0))
print('CHECK ribs: crest at y %.2f, %.2f mm into a %.1f mm board; vs other refs %.3f' % (
    ribs.BoundBox.YMin, g('BoardT') - ribs.BoundBox.YMin, g('BoardT'), sum(vol(ribs, refs[k]) for k in ('cell', 'pins', 'contacts'))))
body = body.fuse(ribs)          # removeSplitter() here leaves an invalid solid
print('PART body with ribs: solids %d valid %s' % (len(body.Solids), body.isValid()))

# ============================ save ============================
doc = FreeCAD.newDocument('LeakSensorCase')
vs = doc.addObject('App::VarSet', 'Params')
for k, v in P.items():
    vs.addProperty('App::PropertyFloat', k, 'Build', 'mm; rerun build_case.py to apply'); setattr(vs, k, float(v))
for name, shp, show in (('Body', body, True), ('Lid', lid, True), ('Board', refs['board'], True), ('Cell', refs['cell'], True),
                        ('Pins', refs['pins'], True), ('Contacts', refs['contacts'], True), ('Wire', refs['wire'], True),
                        ('BZ1_envelope', refs['buzzer'], True),
                        ('J1_header', refs['header'], False)):
    o = doc.addObject('Part::Feature', name); o.Shape = shp
    o.Visibility = show
doc.recompute()
doc.saveAs(os.environ['OUT'])
exp = os.environ.get('EXPORT')
if exp:
    import Mesh, MeshPart
    for name, shp in (('body', body), ('lid', lid), ('board', refs['board']), ('cell', refs['cell']), ('pins', refs['pins']), ('contacts', refs['contacts']), ('wire', refs['wire'])):
        mesh = MeshPart.meshFromShape(Shape=shp, LinearDeflection=0.02, AngularDeflection=0.08)
        if name in ('body', 'lid'):         # what the slicer gets: a valid solid can still mesh with open or shared edges
            print('CHECK %s mesh: solid %s, non-manifold %s' % (name, mesh.isSolid(), mesh.hasNonManifolds()))
            assert mesh.isSolid() and not mesh.hasNonManifolds(), 'the %s does not mesh to a closed solid' % name
        mesh.write('%s/%s.stl' % (exp, name))
    body.exportStep('%s/body.step' % exp); lid.exportStep('%s/lid.step' % exp)
    # print plate: the body on its floor, the lid on its top beside it
    lp = lid.copy(); lp.rotate(V(0, 0, 0), V(0, 1, 0), 180)
    lp.translate(V(2 * g('OW') + 5, 0, -lp.BoundBox.ZMin))
    # written by hand: FreeCAD's 3MF export leaves the objects unnamed
    import zipfile
    objs, items = '', ''
    for i, (name, shp) in enumerate((('body', body), ('lid', lp)), 1):
        pts, tris = MeshPart.meshFromShape(Shape=shp, LinearDeflection=0.02, AngularDeflection=0.08).Topology
        objs += '<object id="%d" name="%s" type="model"><mesh><vertices>%s</vertices><triangles>%s</triangles></mesh></object>' % (
            i, name, ''.join('<vertex x="%.4f" y="%.4f" z="%.4f"/>' % (p.x, p.y, p.z) for p in pts),
            ''.join('<triangle v1="%d" v2="%d" v3="%d"/>' % t for t in tris))
        items += '<item objectid="%d"/>' % i
    xml = '<?xml version="1.0" encoding="UTF-8"?>'
    with zipfile.ZipFile('%s/case.3mf' % exp, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', xml + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr('_rels/.rels', xml + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr('3D/3dmodel.model', xml + '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
                   '<resources>%s</resources><build>%s</build></model>' % (objs, items))
print('SAVED', os.environ['OUT'])
