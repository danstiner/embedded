# CLAUDE.md: working notes for this folder

Simulation behind `HW/SoilProbe` (capacitive soil-moisture probe: buried strips on a 4-layer
blade, 80-130 MHz cross-coupled LC oscillator, frequency + loss-detector outputs for an
nRF54L15 host). Read DESIGN.md first. Nothing has been built or measured.

## Ground truth vs estimate
- Computed here: everything in `results/` (regenerate; it is not tracked).
- From primary sources: OSH Park stackups, BFR181/BFR92P SPICE parameters (Siemens data
  sheets), TLV3601 pinout and input range, SN74LVC1G80 and SN74LV4040A f_max, TPS7A05 start-up.
- Estimates: tank-node stray capacitance (2.5 pF each), inductor Q (35 at 110 MHz), potting
  permittivity (3.5), soil models (CRIM with assumed porosity), air-gap statistics.

## Conventions
- Geometry in mm, materials SI. The field solver returns per-meter values; `probe.py` turns
  them into the admittance at the feed with the line model.
- theta = volumetric water content (fraction). sigma_w = pore-water EC in S/m at 25 C
  (0.05 = 0.5 dS/m).
- Apparent-theta error = perturbed reading through the nominal calibration.
- A change to the cross-section (`probe.GEOM`, stack) invalidates `results/probe_table_*.npz`
  automatically; a change to the oscillator (`spice/osc.py` XCP) needs `characterize.py` rerun.
- The board's strip geometry, C4, R3, R6, L1/L2 and the values in `probe.GEOM`, `osc.XCP` and
  `tank_modes.AS_BUILT` must stay equal.

## Do not
- Put a resistor in parallel with the tank in place of R3-in-series, or drop R3: the oscillator
  then hops to the strip line's second resonance in water (`tank_modes.py`).
- Reduce the base stoppers below 10 R or swap the BFR181 for a slower, higher-Ccb transistor.
- Add copper (pour, vias, traces) on any layer in the sensing area, or a ground pour near the
  strips' top ends.
- Lengthen the strips without rerunning `tank_modes.py`; longer strips lower the second mode.
- Treat `results/` as measurements.

## Next
1. Build and run TEST_PLAN.md phases 0-1; refit stray capacitance and the common table.
2. Zephyr driver: EN, TIMER capture of 64 FOUT periods, SAADC for REF - AMP and NTC.
3. If salinity matters: low-frequency bare-electrode EC channel on a later spin.
