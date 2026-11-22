"""Leak sensor 2026v5 case: an open-top body and a snap-on lid, checked against the board, the cell, the
battery contacts and the leak pins.

Run (from this folder): kicad-cli pcb export step --grid-origin --subst-models -o board.step ../BL54L15μ_LeakSensor.kicad_pcb
     OUT=$PWD/LeakSensor_2026v5.FCStd STEP=$PWD/board.step [EXPORT=dir for STL/STEP] freecadcmd build_case.py
Axes: X right as seen from the front (the board's x), Y from the front toward the rear (along the cell),
Z up from the table. The board's front face is at Y = 0; its sketch coordinates (x, y) map to (X, Z = y + AxisZ).
The parameter values are recorded in the "Params" variable set; geometry is rebuilt by rerunning this script.
"""
import math, os
import FreeCAD, Part
from FreeCAD import Vector as V

P = dict(
    # board (README 5.6): 17.0 x 16.0, centered on the cell's axis
    BoardW2=8.5, BoardTop=8.0, BoardBot=-8.0, BoardRT=0.3, BoardRB=1.5, BoardT=1.6,
    # body
    Wall=1.5, Floor=1.0, FloorGap=0.1, TopGap=0.15, LidT=1.2, CornerR=3.0, InR=1.5, Clear=0.15,
    FrontGap=2.7,        # board front face to the front wall: the module stands 2.08 mm off the board, the pin bores need 2.7
    FrontT=1.5,
    BackGap=2.0,         # board back to the divider: the 209's solder ear and the BT1 wire joints
    PanelT=1.6,          # Keystone snap-on contacts fit 1.52-1.78 mm panels
    SpringGap=2.5,       # 209 leaf, compressed: divider face to the cell's negative end (assumed; free height about 6.5)
    CellD=15.6, CellL=27.0,   # CR2 maximum
    ButtonGap=0.85,      # 228: 0.25 mm plate plus 0.6 mm button
    EarGap=2.0,          # behind the rear panel: the 228's solder ear and its wire
    RearT=1.5,
    PanelTop=5.3,        # top edge of both contact panels above the cell axis (228: button 6.1 above its lower edge, 11.4 tall)
    # board slot. The domes push the board back, so the front face is the datum: crush ribs behind hold it on the
    # front lip, and the dome press then depends on two faces of one printed part, not on the board's thickness
    Lip=0.4, LipT=0.8, Tol=0.1, DomeRelief=2.4, RailTop=7.5, RibR=0.3, RibCrush=0.1,
    # leak pins
    PinD=2.5, PinL=6.0, PinX=3.85, DomeY=-5.8, DomeApex=0.3, PinPress=0.1, PinCap=0.8, BossWall=0.8,
    PinProud=0.2,        # also keeps the pin's top end 0.25 mm below D1 and D2
    BossBack=0.7,        # boss face toward the board, clear of D1 and D2: the pin stands 0.5 mm proud of it, onto the dome
    # cell cradle; the + wire runs along the bay's lower left corner (no room under the cell)
    CradleT=1.2, CradleInset=5.0, WireW=1.2,
    # vents (in front of and above U1)
    SlotW=0.8, SlotH=3.0, VentY=5.6,
    # lid
    RimT=0.8, RimH=1.0, NubR=0.5, NubProud=0.3,
)
P['AxisZ'] = -P['BoardBot'] + P['FloorGap'] + P['Floor']
P['IW'] = P['BoardW2'] + P['Clear']
P['OW'] = P['IW'] + P['Wall']
P['Ztop'] = P['AxisZ'] + P['BoardTop'] + P['TopGap'] + P['LidT']
P['Zb'] = P['Ztop'] - P['LidT']
P['Yfo'] = -(P['FrontGap'] + P['FrontT'])
P['Yfi'] = -P['FrontGap']
P['Yd0'] = P['BoardT'] + P['BackGap']
P['Yd1'] = P['Yd0'] + P['PanelT']
P['Yc0'] = P['Yd1'] + P['SpringGap']
P['Yc1'] = P['Yc0'] + P['CellL']
P['Yr0'] = P['Yc1'] + P['ButtonGap']
P['Yr1'] = P['Yr0'] + P['PanelT']
P['Yw0'] = P['Yr1'] + P['EarGap']
P['Yw1'] = P['Yw0'] + P['RearT']
P['PinY'] = -(P['DomeApex'] - P['PinPress'] + P['PinD'] / 2)
P['PinZ0'] = -P['PinProud']
P['PinZ1'] = P['PinZ0'] + P['PinL']
g = lambda k: P[k]
AZ = g('AxisZ')


def box(x0, x1, y0, y1, z0, z1):
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))


def cylY(x, z, r, y0, y1):
    return Part.makeCylinder(r, y1 - y0, V(x, y0, z), V(0, 1, 0))


def cylZ(x, y, r, z0, z1):
    return Part.makeCylinder(r, z1 - z0, V(x, y, z0), V(0, 0, 1))


def rrect(x0, x1, z0, z1, rb, rt, y0, y1):
    """Rounded rectangle in XZ (bottom corners rb, top corners rt), extruded along Y."""
    r = max(rb, rt)
    s = box(x0, x1, y0, y1, z0 + rb, z1 - rt).fuse(box(x0 + rb, x1 - rb, y0, y1, z0, z1 - rt)).fuse(box(x0 + rt, x1 - rt, y0, y1, z0 + rb, z1))
    for (cx, cz, rr) in ((x0 + rb, z0 + rb, rb), (x1 - rb, z0 + rb, rb), (x0 + rt, z1 - rt, rt), (x1 - rt, z1 - rt, rt)):
        if rr > 0:
            s = s.fuse(cylY(cx, cz, rr, y0, y1))
    return s.removeSplitter()


def outline(d, n=8):
    """Board outline offset by d (sketch coordinates): a rectangle, top corners BoardRT, bottom corners BoardRB."""
    w, t, b = g('BoardW2') + d, g('BoardTop') + d, g('BoardBot') - d
    pts = []
    for (cx, cy, r, a0) in ((w, t, g('BoardRT') + d, 0), (-w, t, g('BoardRT') + d, 90), (-w, b, g('BoardRB') + d, 180), (w, b, g('BoardRB') + d, 270)):
        r = max(r, 0.0)
        ox, oy = cx - math.copysign(r, cx), cy - math.copysign(r, cy)   # corner arc center
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((ox + r * math.cos(a), oy + r * math.sin(a)))
    return pts


def outline_prism(d, y0, y1):
    pts = [V(x, y0, y + AZ) for x, y in outline(d)]
    pts.append(pts[0])
    return Part.Face(Part.makePolygon(pts)).extrude(V(0, y1 - y0, 0))


# ============================ body ============================
outer = rrect(-g('OW'), g('OW'), 0, g('Ztop'), g('CornerR'), g('CornerR'), g('Yfo'), g('Yw1'))
body = outer.common(box(-20, 20, -20, 60, -1, g('Zb')))
body = body.cut(rrect(-g('IW'), g('IW'), g('Floor'), g('Zb') + 5, g('InR'), 0, g('Yfi'), g('Yw0')))

adds = []
for y0, y1 in ((g('Yd0'), g('Yd1')), (g('Yr0'), g('Yr1'))):                      # contact panels
    adds.append(box(-g('IW'), g('IW'), y0, y1, g('Floor') - 0.01, AZ + g('PanelTop')))
for yc in (g('Yc0') + g('CradleInset'), g('Yc1') - g('CradleInset')):              # cell saddles
    adds.append(box(-g('IW'), g('IW'), yc - g('CradleT') / 2, yc + g('CradleT') / 2, g('Floor') - 0.01, AZ).cut(
        cylY(0, AZ, g('CellD') / 2 + 0.2, yc - 1, yc + 1)))
# board slot: lips 0.4 mm over the board's sides and bottom curve, front and back; open above the straight sides
frame = box(-g('IW'), g('IW'), -g('LipT'), g('BoardT') + g('LipT'), g('Floor') - 0.01, AZ + g('RailTop'))
frame = frame.cut(outline_prism(-g('Lip'), -5, 5))
frame = frame.cut(outline_prism(g('Tol'), 0, g('BoardT') + g('Tol')))
frame = frame.cut(box(-g('BoardW2') - g('Tol'), g('BoardW2') + g('Tol'), 0, g('BoardT') + g('Tol'), AZ + g('BoardBot') + g('BoardRB'), AZ + 30))
for sx in (-1, 1):                                       # front lip relief around each dome
    frame = frame.cut(cylY(sx * g('PinX'), AZ + g('DomeY'), g('DomeRelief'), -g('LipT') - 0.1, 0.0))
adds.append(frame)
# leak pin bosses: in front of the board, bore blind at the top, open toward the dome
for sx in (-1, 1):
    x = sx * g('PinX')
    adds.append(box(x - g('PinD') / 2 - g('BossWall'), x + g('PinD') / 2 + g('BossWall'), g('Yfi') - 0.01, -g('BossBack'),
                    g('Floor') - 0.01, g('PinZ1') + g('PinCap')))
for a in adds:
    body = body.fuse(a)

subs = []
for sx in (-1, 1):                                       # pin bores
    subs.append(cylZ(sx * g('PinX'), g('PinY'), g('PinD') / 2, -1, g('PinZ1')))
x0 = -g('IW') + g('InR')        # just inside the bay's corner fillet
subs.append(box(x0, x0 + g('WireW'), g('Yd0') - 0.01, g('Yw0'), g('Floor') - 0.01, g('Floor') + g('WireW')))   # + wire: notches in the panels and saddles
for i in range(4):                                       # front vents in front of U1 (x 5.8)
    x = 4.3 + 1.0 * i
    subs.append(box(x - g('SlotW') / 2, x + g('SlotW') / 2, g('Yfo') - 1, g('Yfi') + 0.01, AZ + g('VentY') - g('SlotH') / 2, AZ + g('VentY') + g('SlotH') / 2))
for s in subs:
    body = body.cut(s)

# ============================ lid ============================
lid = outer.common(box(-20, 20, -20, 60, g('Zb'), g('Ztop') + 1))
ri = g('IW') - g('Tol')
rim = rrect(-ri, ri, g('Zb') - g('RimH'), g('Zb') + 0.01, 0, 0, g('Yfi') + g('Tol'), g('Yw0') - g('Tol'))
rim = rim.cut(rrect(-ri + g('RimT'), ri - g('RimT'), g('Zb') - g('RimH') - 1, g('Zb') + 1, 0, 0, -10, 60))
rim = rim.cut(box(-20, 20, -g('LipT') - 0.3, g('BoardT') + g('LipT') + 0.3, 0, 30))     # clear of the board's top corners
for y in (g('Yc0') + 6, g('Yc1') - 6):
    for sx in (-1, 1):
        rim = rim.fuse(Part.makeSphere(g('NubR'), V(sx * (ri + g('NubProud') - g('NubR')), y, g('Zb') - g('RimH') / 2)))
lid = lid.fuse(rim)
for yc in (g('Yc0') + g('CradleInset'), g('Yc1') - g('CradleInset')):          # ribs that keep the cell down
    lid = lid.fuse(box(-3, 3, yc - 0.6, yc + 0.6, AZ + g('CellD') / 2 + 0.15, g('Zb') + 0.01))
for i in range(4):                                       # vents over U1, in front of the board
    x = 4.3 + 1.0 * i
    lid = lid.cut(box(x - g('SlotW') / 2, x + g('SlotW') / 2, g('Yfi') + 0.4, -0.4, g('Zb') - 1, g('Ztop') + 1))
for y in (g('Yc0') + 6, g('Yc1') - 6):                   # dimples for the nubs
    for sx in (-1, 1):
        body = body.cut(Part.makeSphere(g('NubR') + 0.05, V(sx * (ri + g('NubProud') - g('NubR')), y, g('Zb') - g('RimH') / 2)))
# crush ribs on the back lip along the straight sides, with a rounded top as the lead-in; fused after the fit checks
ribs = []
for sx in (-1, 1):
    x, y = sx * (g('BoardW2') - g('RibR')), g('BoardT') - g('RibCrush') + g('RibR')   # clear of the slot's side wall: tangent faces break the fuse
    z0 = AZ + g('BoardBot') + g('BoardRB')                # where the straight sides start
    ribs.append(cylZ(x, y, g('RibR'), z0, AZ + g('RailTop') - g('RibR')).fuse(Part.makeSphere(g('RibR'), V(x, y, AZ + g('RailTop') - g('RibR')))))
ribs = ribs[0].fuse(ribs[1])
body, lid = body.removeSplitter(), lid.removeSplitter()

# ============================ references (not printed) ============================
refs = {}
s = Part.read(os.environ['STEP'])
top = max(s.Solids, key=lambda x: x.Volume).BoundBox.ZMax          # KiCad's board body is 1.51 mm: place it by its front face
m = FreeCAD.Matrix(); m.rotateX(math.pi / 2); m.move(V(0, top, AZ))
keep = [x for x in s.Solids if x.BoundBox.ZMin > -0.05]              # drop J1's header: production boards have none
refs['board'] = Part.makeCompound([x.transformGeometry(m) for x in keep])
refs['header'] = Part.makeCompound([x.transformGeometry(m) for x in s.Solids if x.BoundBox.ZMin <= -0.05])
refs['cell'] = cylY(0, AZ, g('CellD') / 2, g('Yc0'), g('Yc1'))
refs['pins'] = cylZ(-g('PinX'), g('PinY'), g('PinD') / 2, g('PinZ0'), g('PinZ1')).fuse(cylZ(g('PinX'), g('PinY'), g('PinD') / 2, g('PinZ0'), g('PinZ1')))
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
print('SIZE %.2f x %.2f x %.2f mm (width x length x height)' % (2 * g('OW'), g('Yw1') - g('Yfo'), g('Ztop')))
print('CHECK body/lid overlap %.3f' % vol(body, lid))
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
print('CHECK pins/board %.3f, pins/cell %.3f, contacts/cell %.3f' % (vol(refs['pins'], refs['board']), vol(refs['pins'], refs['cell']), vol(refs['contacts'], refs['cell'])))
dome_gap = -refs['pins'].BoundBox.YMax          # pin surface to the board's front face
print('CHECK pin surface %.2f mm in front of the board face; dome apex at %.2f: %.2f mm press' % (dome_gap, g('DomeApex'), g('DomeApex') - dome_gap))
hits = []
for dz10 in range(5, 260, 5):                   # the board drops in from the top
    mm_ = FreeCAD.Matrix(); mm_.move(V(0, 0, dz10 / 10.0))
    v = vol(body, refs['board'].transformGeometry(mm_))
    if v > 0.01:
        hits.append((dz10 / 10.0, round(v, 3)))
print('CHECK board drop-in collisions (height above seat, mm3):', hits[:10], 'count', len(hits))
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
                        ('Pins', refs['pins'], True), ('Contacts', refs['contacts'], True), ('J1_header', refs['header'], False)):
    o = doc.addObject('Part::Feature', name); o.Shape = shp
    o.Visibility = show
doc.recompute()
doc.saveAs(os.environ['OUT'])
exp = os.environ.get('EXPORT')
if exp:
    import Mesh, MeshPart
    for name, shp in (('body', body), ('lid', lid), ('board', refs['board']), ('cell', refs['cell']), ('pins', refs['pins']), ('contacts', refs['contacts'])):
        MeshPart.meshFromShape(Shape=shp, LinearDeflection=0.03, AngularDeflection=0.3).write('%s/%s.stl' % (exp, name))
    body.exportStep('%s/body.step' % exp); lid.exportStep('%s/lid.step' % exp)
print('SAVED', os.environ['OUT'])
