# Bench validation

The order matters: each phase checks one layer of the model before the next one depends on
it. Predictions come from `scripts/expected_liquids.py` and `scripts/system_sim.py`.

Equipment: scope with a frequency counter (FOUT is 80-126 kHz, 3 V), DMM with 0.1 mV
resolution, bench supply with current readout or a power profiler, kitchen scale (0.1 g),
tall beakers or jars at least 60 mm across, 99 % isopropanol, distilled water, table salt.

## Phase 0: electronics, unpotted, in air

| Check | Expect | If not |
|---|---|---|
| Current with EN high | 20-30 mA | much lower: oscillator not running, see FOUT |
| FOUT | 126 kHz +/-5 % | above 137 kHz: raise C4. No output: check VCM (2.5 V) and VE (about 1.75 V) |
| REF - AMP | 30-50 mV | near 0: stalled. Above 90 mV: amplitude too high, check R3 |
| FOUT with a finger across the blade | drops smoothly, no jumps | a jump of 2x or more is a mode hop: stop and report, do not pot |
| Supply 3.1 to 3.6 V | FOUT moves under 0.05 % | |
| FOUT over 10 minutes | drift under 0.02 % | |
| EN to first valid FOUT period | under 3.5 ms | |

Then pot the head and seal the edges (../../README.md) and repeat the first three rows.

## Phase 1: reference media (validates field model, line model, oscillator table)

Blade immersed to the soil line, centered, at least 25 mm from the container wall.

| Medium | FOUT kHz | REF - AMP mV |
|---|---|---|
| air | 126.0 | 40 |
| isopropanol 99 % | 102.1 | 60 |
| distilled water | 79.7 | 81 |
| tap water, 0.3 mS/cm | 79.6 | 62 |
| salt 0.5 g/L | 79.1 | 37 |
| salt 1 g/L | 77.9 | 20 |
| salt 2 g/L | 74.5 | 8 |

- Compute `x` for isopropanol from the air and distilled-water readings
  (`x = (f^-2 - f_air^-2) / (f_w^-2 - f_air^-2)`). Predicted 0.35. Within 0.03: the geometry
  and line model hold. Outside: the prepreg thickness or the stray capacitance differs; refit
  `C_STRAY` and the stack in the scripts before trusting the table.
- Water must not show a frequency near 240 kHz or erratic counts: that is the second tank
  mode (DESIGN.md section 6). Try it cold and warm, and with the supply at both limits.
- The salt series is the detector's calibration: REF - AMP must fall monotonically. Replace
  the model's `q` column with these points.
- Immersion depth in tap water, 20/40/60/80 mm: 109.3 / 95.4 / 86.8 / 81.5 MHz at the
  oscillator. This is not linear in depth; it is the line model's signature.

## Phase 2: soil

Oven-dry the medium (potting mix at 70 C, mineral soil at 105 C, to constant mass), sieve to
2 mm, and make batches by mass: dry mass into a bag, add water, knead, rest a day, pack into a
jar of known volume with a fixed ritual. theta = water mass / jar volume. Six points from
0.05 to saturation, each at tap water and at fertilizer solution near 3 mS/cm.

- Insert, read, pull out, repack the hole, reinsert, five times per jar. The scatter is the
  contact term; the model's assumption is about 1 % VWC.
- Fit the medium curve (permittivity to theta) on the tap-water points.
- The fertilizer points should land on the same curve within 1 % VWC when the detector is
  used, and 1-3 % high when it is not.

## Phase 3: temperature and time

- A sealed moist jar from 5 to 40 C: after the water-permittivity correction the reading
  should move under 0.5 % VWC.
- A pot left to dry on a scale for two weeks: reading against mass loss.
- Leave one blade in wet fertilized mix for a month and repeat phase 1: the air and water
  points should return within 0.2 %. Drift here is moisture getting into the laminate edge.
