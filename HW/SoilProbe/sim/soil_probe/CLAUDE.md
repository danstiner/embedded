# CLAUDE.md — working notes for this folder

## What this is
Design package for an ultra-low-power capacitive soil-moisture probe (potting mix, nRF54L15 node,
BTHome/BLE, energy-harvested). Two front ends: FDC2212 at 10 MHz (low risk) and a discrete
Clapp oscillator at 71–85 MHz counted by the nRF (best cheap). Read DESIGN.md first; it has the
numbers and the reasoning. Nothing has been built yet.

## Ground truth vs estimate
- Verified numerically: everything in `results/` (field solver validated against the two-wire
  closed form; ngspice runs for the Clapp).
- Verified from primary sources: OSH Park stack (docs.oshpark.com/services/two-layer),
  FDC2212 IDRIVE/amplitude mechanism (TI datasheet).
- Estimates to verify: all BOM prices (`verify_on_digikey` column), 74LVC161 f_max at 3.0 V,
  nRF54L15 GPIOTE max input rate, FDC2212 f_REF/f_SENSOR constraint, inductor Q/SRF for LQW18ANR47G00D,
  Taiyo PSR-4000BN Dk (3.9 assumed), the "±1 % VWC after (f, Vpk) correction" figure.

## Test plan
TEST_PLAN.md is phased (bench → liquids → dispersion → soil matrix → contact → temperature → drying
curve) with pass criteria and predicted values; data goes in data/measurements.csv.

## Conventions
- Geometry in mm, materials SI; solver returns per-metre C and G. Cross-section is x (width) × y (thickness);
  probe length is multiplied in afterwards (`lumped_values.py`).
- Config names A–F and N are defined in `scripts/run_sweeps.py`; "config C" = two 5 mm strips, 1 mm gap, both faces.
- θ = volumetric water content (fraction). "EC lo/hi" = pore-water σ_w 0.05 / 0.30 S/m.
- Apparent-θ error = read the perturbed C through the unperturbed low-EC calibration curve.
- SPICE probe model: Cp ∥ (1/Gp) at the oscillation frequency, values from `results/lumped_values.txt`.

## Prioritised next tasks
1. Coat-thickness trade for the Clapp: run config C with coat 0 / 0.1 / 0.2 / 0.3 mm at 70–85 MHz
   (`lumped_values.py` + `error_budget.py` style), then `run_clapp.py` for each; minimise
   total EC×6 error (probe MW term + oscillator pulling) subject to Vpp ≥ 1 V in the sat hi-EC case.
2. Re-tune L for the 4 mm / 3 mm strip variant (probe_geometry.md); target 60–90 MHz, keep ÷16 output ≤ 6 MHz.
3. Coated 50 mm FDC2212 case at 10 MHz: EC×2/×6, gap, T errors (currently only bare numbers).
4. 2-parameter calibration: build f(θ, σ) and Vpk(θ, σ) tables from SPICE + FEM, write the inversion,
   quantify residual with ±5 % Vpk error and ±0.1 mm gap.
5. Verify the "estimates" list above against datasheets/DigiKey and update the BOMs.
6. KiCad: probe footprint per `hardware/probe_geometry.md`; Clapp head per `hardware/schematic_clapp.md`.
7. Firmware sketch (schematic_clapp.md §nRF54L15) → Zephyr/nRF Connect implementation.
8. When measurements arrive: run scripts/analyze_calibration.py, refit C_par and coat thickness from
   Phase 1 (expected_liquids.py), refit S_SIGMA from Phase 3, and update DESIGN.md §5 with measured numbers.

## Don't
- Don't lower the excitation frequency to make the FDC easier; DESIGN.md §1 explains why (S_σ).
- Don't add a ground ring or back pour under the strips (halves soil energy, doubles gap sensitivity).
- Don't remove the coat for sensitivity without re-checking Rp / D (uncoated: Rp 140 Ω, D 0.66 in hi-EC wet soil).
- Don't treat `results/*.csv` as measurements; they are model outputs.
