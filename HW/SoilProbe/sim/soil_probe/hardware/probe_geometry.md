# Probe PCB geometry (baseline, as simulated)

- OSH Park 2-layer, 12.0 mm wide. Sensing section 80 mm (Clapp) or 50 mm (FDC2212); head above it.
- Top copper: SENSE strip x = −5.5 … −0.5 mm, GND strip x = +0.5 … +5.5 mm (5 mm wide, 1 mm gap), full sensing length.
- Bottom copper: identical, mirrored; stitch each strip to its top twin with vias every ~10 mm.
- Solder mask: default (leave on). Then dip/brush a 0.3 mm epoxy or acrylic conformal coat over the sensing section
  (εr ≈ 3, tanδ ≤ 0.02). The FEM assumed coat also fills the 36 µm recess beside the strips.
- No ground pour under or beside the strips; ground pour only under the head electronics, ≥5 mm from the strips.
- Optional variant to evaluate: strips 4.0 mm wide, 3.0 mm gap (x = ±1.5 … ±5.5). Better gap/water immunity,
  ~40 % lower C — re-run scripts/lumped_values.py and re-tune L.
- Tip: round the tip; the FEM ignores end effects (~one board width of extra effective length).
- Also on the board: 4-electrode EC pads (existing design) and a 10 k NTC at the tip for temperature.
