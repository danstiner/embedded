# soil_probe — capacitive soil-moisture probe design package

Self-contained: physics solver, sweeps, error budget, oscillator SPICE, schematics, BOMs.
Start with `DESIGN.md` (conclusions + error budget), then `CLAUDE.md` (how to work on it).

```
soil_probe/
  DESIGN.md                  design summary, error budgets, recommendation, open items
  CLAUDE.md                  instructions/context for Claude Code
  TEST_PLAN.md               home validation plan (oven, beakers, reference liquids, scale)
  data/measurements.csv      logging template for the test plan
  hardware/
    probe_geometry.md        PCB strip layout for KiCad
    schematic_clapp.md       discrete 70-85 MHz Clapp head (verified in ngspice)
    schematic_fdc2212.md     FDC2212 head at 10 MHz
    bom_clapp.csv, bom_fdc2212.csv   candidate MPNs, estimated prices (flagged for verification)
  scripts/
    soil_probe_sim.py        2-D complex-permittivity finite-volume solver (the core; verified vs closed form)
    run_sweeps.py            geometry/soil/gap/frequency/nail/insertion sweeps -> results/fig*.png, results.csv
    error_budget.py          S_eps/S_sigma vs frequency; EC/T/gap/mask errors; Rp
    lumped_values.py         C, G, D, Rp for real probe lengths/coats -> feeds SPICE and tank design
    expected_liquids.py      predicted readings in reference liquids (TEST_PLAN Phase 1)
    analyze_calibration.py   fits and error terms from data/measurements.csv
  spice/
    clapp_osc.cir            ngspice netlist (parameterised)
    run_clapp.py             sweeps probe cases, reports f, Vpp, start-up, pulling, salinity residual, tempco
  results/                   all generated figures, CSVs and text logs (regenerable)
```

## Reproduce

```
pip install numpy scipy matplotlib        # solver + plots
sudo apt install ngspice                  # oscillator sim (ngspice 42 used)
cd scripts && python run_sweeps.py        # ~75 s on one core, 548 solves -> ../results (run from scripts/)
python error_budget.py                    # ~40 s
python lumped_values.py                   # ~10 s
cd ../spice && python run_clapp.py        # ~2 min, ~40 ngspice runs
```
`run_sweeps.py` writes into `./out` relative to its cwd; copy to `results/` (or edit `OUT`).

## Model summary (see DESIGN.md §1)
2-D cross-section, quasi-static, ε* = ε₀εr(1−j tanδ) − jσ/ω, Neumann far field, electrodes Dirichlet.
OSH Park 2-layer stack as published. Soil: CRIM mixing model (porosity 0.7) + Archie/Rhoades EC.
Validated: two-wire capacitance −0.5 % (domain truncation); mesh/domain doubling <0.5 %.
