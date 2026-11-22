"""3D model of the Same Sky CMT-5023S-SMT magnetic buzzer (the manufacturer publishes none), drawn from its datasheet's
mechanical drawing: 5.0 x 5.0 x 2.0 mm LCP body, a 45 degree chamfer on one corner, a 0.8 mm sound hole on top, three
tin-plated terminals at the other corners.

Run (from this folder): freecadcmd build_model.py
Writes CMT-5023S-SMT.step (for STEP export and the case's fit checks) and CMT-5023S-SMT.wrl (colored, for KiCad's 3D
view; KiCad substitutes the STEP of the same name on export). Footprint frame: x right, y up (top view), z up from the
board; + terminal bottom left, - bottom right, mounting terminal top left, chamfer top right.
"""
import os
import Part
from FreeCAD import Vector as V

HERE = os.path.dirname(os.path.abspath(__file__))
B, Hb, CH = 5.0, 2.0, 1.0            # body side, height, chamfer legs (a 1.4 mm face at 45 degrees)
TW, TL, TT, TU = 1.3, 0.8, 0.1, 0.5  # terminal width (x), length (y), thickness, height up the body's side

h = B / 2
body = Part.Face(Part.makePolygon([V(-h, -h, 0), V(h, -h, 0), V(h, h - CH, 0), V(h - CH, h, 0), V(-h, h, 0),
                                   V(-h, -h, 0)])).extrude(V(0, 0, Hb))
body = body.cut(Part.makeCylinder(0.4, 1.0, V(0, 0, Hb - 0.6)))
terms = []
for sx, sy in ((-1, -1), (1, -1), (-1, 1)):
    x0 = -h if sx < 0 else h - TW
    y0 = -h if sy < 0 else h - TL
    pad = Part.makeBox(TW, TL, TT, V(x0, y0, 0))
    side = Part.makeBox(TT, TL, TU, V(-h - TT if sx < 0 else h, y0, 0))   # the tab folds up the body's side
    terms.append(pad.fuse(side))
Part.makeCompound([body] + terms).exportStep(os.path.join(HERE, 'CMT-5023S-SMT.step'))


def wrl_shape(shape, rgb, spec=0.2):
    pts, tris = shape.tessellate(0.01)
    s = 1 / 2.54                       # KiCad's VRML unit is 0.1 inch
    coords = ', '.join('%.4f %.4f %.4f' % (p.x * s, p.y * s, p.z * s) for p in pts)
    index = ', '.join('%d, %d, %d, -1' % t for t in tris)
    return ('Shape { appearance Appearance { material Material { diffuseColor %.3f %.3f %.3f specularColor %.2f %.2f %.2f '
            'shininess 0.3 } } geometry IndexedFaceSet { coord Coordinate { point [ %s ] } coordIndex [ %s ] } }\n'
            % (rgb + (spec, spec, spec) + (coords, index)))


with open(os.path.join(HERE, 'CMT-5023S-SMT.wrl'), 'w') as f:
    f.write('#VRML V2.0 utf8\n')
    f.write(wrl_shape(body, (0.08, 0.08, 0.09), 0.1))
    for t in terms:
        f.write(wrl_shape(t, (0.78, 0.78, 0.76), 0.6))
print('written')
