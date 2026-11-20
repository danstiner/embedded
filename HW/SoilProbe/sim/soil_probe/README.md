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
