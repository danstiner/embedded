# soil_probe: simulation and design notes for HW/SoilProbe

Start with `DESIGN.md` (what was decided and why, error budget), then `TEST_PLAN.md`.
The board itself is `../../SoilProbe.kicad_*`, documented in `../../README.md`.

```
scripts/
  soil_probe_sim.py   2-D complex-permittivity finite-volume field solver, soil models
  probe.py            the probe as built: cross-section, admittance table, transmission-line model
  geometry_study.py   electrode trade: outer vs buried strips, board width, spacing, fork
  tank_modes.py       resonant modes of tank + strip line; why R3 is in series with C4
  system_sim.py       soil -> probe -> oscillator -> firmware arithmetic; error budget, Monte Carlo
  expected_liquids.py predicted readings in air, solvents, water, salt water
  design_comparison.py nine electrode x readout designs under one calibration and Monte Carlo (paper/)
  organic_soil_spectra.py substrate relaxation from published organic-soil spectra (downloads ~60 MB, needs xlrd)
  existing_boards.py    the older probe boards under HW/ (front-face strips, FDC1004 / FDC2x12) in the same framework
  run_sweeps.py       earlier survey of outer-layer patterns and nails (background to DESIGN section 4)
  test_models.py      pytest: solver vs closed forms, line limits, end-to-end round trip
spice/
  rf_bjt.lib          BFR181 / BFR92P Gummel-Poon models and SOT-23 package network
  osc.py              ngspice harness: cross-coupled oscillator (and the earlier Clapp)
  characterize.py     oscillator table over the probe's load plane; loss pulling
  verify_line.py      oscillator with a distributed line in every medium vs the table model
paper/
  manuscript.md       journal-style write-up of the design comparison; figures/ are generated
results/              generated, not tracked
```

## Reproduce

Needs Python with numpy, scipy, matplotlib, pytest, and ngspice (47 used) on the PATH.

```
cd scripts
python probe.py                  # builds the admittance tables, ~3 min on 8 cores
python geometry_study.py         # ~2 min
cd ../spice && python characterize.py --pulling     # ~1 min
cd ../scripts
python tank_modes.py
python system_sim.py 800         # budget + Monte Carlo, ~6 min
python expected_liquids.py
python organic_soil_spectra.py   # measured dispersion ratios, Fig. 7
python design_comparison.py      # tables + paper/figures, ~15 min first time; fills the tables in paper/manuscript.md
(cd ../spice && python verify_line.py)
pytest -q
```

Run the scripts as files, not from stdin: the table builders use multiprocessing.

## The older probe boards (`existing_boards.py`)

Strips on the front face only, under solder mask, OSH Park 2-layer stack. Same substrate,
calibration and Monte Carlo as `paper/manuscript.md`; RMSE in % VWC.

| Board + readout | RMSE | Salinity | Contact | Notes |
|---|---|---|---|---|
| Probe_Parallel9mm, 12mm, OneInch + FDC1004; SoilProbe_FDC1004_Parallel9mm | none | | | 25 kHz reads the mask capacitance: response not monotonic in water content; 10-58 % of readings exceed the chip's 115 pF |
| Probe_Parallel9mm + FDC2112/2212 breakout (10 uH, 8.0-6.3 MHz) | 5.6 | 4.1 | 3.6 | |
| Probe_Parallel12mm + FDC2112/2212 breakout | 5.3 | 3.7 | 2.8 | |
| Probe_ParallelOneInch + FDC2112/2212 breakout | 6.0 | 3.2 | 3.6 | tank loss beyond the drive current in 7 % of readings |
| Soily (FDC2212, 18 uH, 6.0-4.4 MHz) | 7.1 | 3.9 | 5.0 | same in 5 % |
| SoilProbe 2026v1 (4-layer, buried, 100 MHz), for reference | 1.2 | 0.3 | 1.2 | |

Estimates, not data-sheet facts: the FDC1004 is modeled as an ideal charge-transfer reading
C + G/2f (its behavior with a lossy load is not specified); the FDC2x12 drive limit is taken
as 1.2 V / 1.56 mA against the probe's loss alone, so with the inductor's own loss the share of
readings beyond it is a lower bound; 5 pF of stray capacitance is assumed on the tank.
On the same 2-layer stack, 5.5 mm strips 7 mm apart on both faces read by the 100 MHz
oscillator (design G of the manuscript) reach 1.4 %.
