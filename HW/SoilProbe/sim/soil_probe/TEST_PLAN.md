# Validation test plan — oven, beakers, kitchen scale

Goal: find out, in order, (1) whether the field model matches the built probe, (2) whether the
front end behaves as simulated under real loss, (3) what the probe actually does in soil, and
(4) what the residual errors are after correction. Each phase has a pass criterion; don't move
on until the previous phase passes, or you'll be debugging three things at once.

Predicted numbers for every phase come from `scripts/` (`results/expected_liquids.txt`,
`results/lumped_values.txt`, `results/clapp_spice_results.txt`). Record everything in
`data/measurements.csv` (template provided) and run `scripts/analyze_calibration.py`.

## Equipment

Have: Rigol DHO914S (AWG + Bode up to 25 MHz), Nordic PPK2, nRF54L15 node, calipers.
Buy/borrow (~$60): kitchen scale 0.1 g / ≥2 kg; oven thermometer; 6 × 600 mL tall beakers or
1 L wide-mouth jars (≥60 mm inner diameter, ≥110 mm tall); cling film; zip bags; spray bottle;
2 mm kitchen sieve; EC/TDS pen (any $15 one, calibrate with 1 g/L NaCl ≈ 2.0 mS/cm at 25 °C);
0.1 mm PET film (overhead-transparency sheet) and 0.05 mm Kapton tape; reference liquids:
mineral oil, 99 % isopropanol (not 70 %), glycerol, distilled water, table salt; a water-soluble
fertiliser. A food dehydrator or the oven-light-only trick gives 35–45 °C; the oven's lowest
setting (~75 °C) is for drying. A thermometer you trust to 0.5 °C (the probe's NTC, once calibrated
in ice water and body-temperature water, is fine).

## Sample preparation

Soils: your potting mix (target), play sand (mineral, low surface conductivity, dry εr ≈ 2.5–3),
and a garden loam or a peat-heavy mix. Sieve to 2 mm.

Drying: mineral soils 105 °C ≥ 24 h; potting mix / peat 70 °C ≥ 48 h (organic matter starts to
oxidise above ~80 °C and you lose dry mass). Dry until two weighings 4 h apart agree within 0.5 g.
Store dry soil in sealed bags.

Bulk density and volumetric water content — weigh, don't guess:
- Calibrate each beaker's volume at the fill mark with water mass (1.00 g/mL).
- Pack dry soil to the mark with a fixed ritual (fill loose, drop the beaker 5 mm onto the counter
  20 times, top up, level). ρ_b = m_dry / V. Potting mix ≈ 0.3–0.4 g/cm³, sand ≈ 1.5.
- Water content batches: put m_dry of soil in a zip bag, spray in m_w of water, knead, seal, wait
  24 h at room temperature, then pack into the beaker with the same ritual. θ_v = m_w / (V·ρ_w).
  Check by weighing the packed beaker: m_w = m_total − m_beaker − m_dry.
- Targets (potting mix): θ_v = 0.05, 0.10, 0.20, 0.30, 0.40, saturated (sand tops out ~0.35).
- Salinity batches: (a) tap water (measure with the pen; Spokane tap is a few hundred µS/cm),
  (b) fertiliser solution at label rate, measured with the pen (aim 2–3 mS/cm ≈ 0.2–0.3 S/m).
  Optional (c) distilled water for a near-zero-EC point.
- Cover beakers with cling film between readings; re-weigh before each session to catch evaporation.

## Phase 0 — bench, no soil (1 evening)

1. Probe in air, head powered: log f (or FDC C) for 1 h. Pass: drift < 0.1 % (Clapp) / < 0.05 pF (FDC).
2. Supply 2.7 → 3.3 V: Δf < 0.05 % (SPICE says 0.03 %).
3. Compare the nRF counter against the Rigol frequency measurement at the ÷16 output
   (never put a scope probe on the tank node — 10 pF of probe pulls the oscillator ~20 %; if you must
   look at the tank, use a 1 kΩ resistor at the tip and accept the loading). Pass: agree to 10⁻⁴.
4. PPK2: energy per reading with power gating. Expect ~45 µC (Clapp + LVC) or ~10 µC per FDC conversion
   plus the 40 MHz oscillator's warm-up.
5. Squeeze the probe between fingers: f must move smoothly; if it jumps or stops, the oscillator is marginal.

## Phase 1 — reference liquids (1 evening) — validates geometry, coat, parasitics

Immerse to the 80 mm mark (50 mm for the FDC probe), probe centred, ≥25 mm from glass.

| liquid | εr (25 °C) | predicted C, 80 mm coated, 76 MHz | predicted Clapp f | FDC (50 mm, 10 MHz) C / f |
|---|---|---|---|---|
| air | 1.0 | 11.7 pF | 87.7 MHz | 9.6 pF / 10.4 MHz |
| mineral oil | 2.2 | 13.4 | 85.0 | 10.6 / 10.1 |
| isopropanol 99 % | 18.3 | 26.0 | 75.1 | 18.5 / 8.6 |
| glycerol | 42.5 | 33.7 | 72.5 | 23.3 / 8.0 |
| distilled water | 78.5 | 38.6 | 71.4 | 26.4 / 7.6 |

(The Clapp f column carries a ×0.9 factor for the transistor's junction capacitances; SPICE puts the
offset at −9…−12 %. Treat the absolute f as ±5 %, the *ratios* between liquids as the real test.)

- Pass: C(oil)/C(air), C(IPA)/C(air), C(water)/C(air) within ±10 % of predicted after one free
  parameter (C_par) is fitted. If water/IPA ratio is off but oil/air is right, the coat thickness is
  wrong — the water point is dominated by the coat's series capacitance. Fit the coat thickness in
  `expected_liquids.py` and update DESIGN.md.
- Insertion linearity: glycerol at 20/40/60/80 mm → C should be linear (12.9, 19.9, 26.8, 33.7 pF)
  with intercept ≈ C_par. Non-linearity means the head or cable is picking up field.
- Loss series: distilled water, tap water, then NaCl at 0.1, 0.5, 1 g/L (σ ≈ 0.02, 0.1, 0.2 S/m at 25 °C).
  Record f and Vpk (Clapp) or the IDRIVE code that centres the amplitude (FDC). Predicted Clapp:
  Rp 4 kΩ → 0.5 kΩ, D 0.01 → 0.10, Vpk should fall monotonically and f should move < 1 %.
  FDC: still oscillating at 1 g/L (Rp ≈ 7.5 kΩ at 10 MHz, coated). Pass: no dropouts, Vpk monotonic in σ.
- Temperature of liquids: note it; εr of water drops 0.4 %/°C, IPA ~0.6 %/°C.

## Phase 2 — dispersion with the Rigol (1 evening) — validates the frequency argument

AWG (sine, 0.5 Vpp) → 1 kΩ series resistor → probe sense strip; ground strip to AWG ground.
CH1 on the AWG side, CH2 on the probe side with a 10× probe. Bode sweep 100 kHz → 25 MHz.
First run with the probe in air to capture the CH2 probe capacitance and strays (subtract as a
parallel C). Then Y_probe = (1/R)·(V1/V2 − 1) − Y_stray; C = Im(Y)/ω, G = Re(Y).
Do it in: air, glycerol, potting mix at θ ≈ 0.25 (tap water), same at fertiliser EC.
Pass: in moist soil C_eff falls with frequency and flattens by 10–25 MHz, and the two salinities
converge toward the same C at the top of the sweep (fig3 shape). If C is flat from 100 kHz up,
the soil is much drier or lower-EC than you think — check the EC pen.

## Phase 3 — soil calibration matrix (2–3 weekends)

3 soils × 6 water contents × 2 salinities = 36 beakers; do potting mix first (12 beakers).
Per beaker, per reading session:
1. Weigh the beaker (evaporation check). Temperature from the NTC.
2. Insert to the mark in one push, wait 30 s, log 10 readings (f, Vpk or C, IDRIVE), bulk EC from the
   4-electrode pads, NTC.
3. Withdraw, re-insert in a fresh spot 20 mm away, repeat — 5 insertions per beaker.
   The spread across insertions is your contact term; the mean is the calibration point.
4. Log bulk EC at every point: it is the correction input.

Pass / interpretation:
- Re-insertion scatter ≤ ±3 % VWC (1σ) in potting mix, ≤ ±2 % in sand. Larger → contact; go to Phase 4.
- Tap-water vs fertiliser curves: FDC at 10 MHz should differ by ≤ 5 % VWC at θ = 0.25, Clapp ≤ 4 %
  uncorrected; after the σ correction (`analyze_calibration.py --correct`) ≤ 1.5 %.
- Fit θ(C) per soil with a cubic; RMS residual ≤ 2 % VWC. Compare the fitted curve with the CRIM
  prediction (`results/results.csv`, config F); if the shape matches but the scale is off, it is bulk
  density / porosity — enter your measured ρ_b into `soil_material()` and re-check.

## Phase 4 — contact and gap (1 evening)

- Air-gap surrogate: slide a 0.1 mm PET film sleeve over the probe (εr ≈ 3.2; predict it with
  `pcb_scene(..., gap_top=0.1, gap_bot=0.1, gap_mat=(3.2, 0, 0.005))`). Then a 0.2 mm (two layers).
- Loosened hole: insert, wiggle ±5° ten times, re-read without re-seating. Predicted −3…−4 % VWC
  per 0.1 mm of effective gap; a wiggled hole in potting mix is typically 0.2–0.5 mm.
- Water film: dip the probe in water, shake once, insert into a θ ≈ 0.25 beaker. Predicted +2 % (coated).
- Compaction: same batch packed loose vs. tapped 40 times. Records how much of the "soil model" error is ρ_b.
Pass: signs and magnitudes match the model within a factor of 2. These are the numbers that go
into the final uncertainty statement; there is no design fix below ~±3 % for planar electrodes.

## Phase 5 — temperature (1 weekend, mostly waiting)

Two beakers sealed with cling film: (a) probe in mineral oil — measures the electronics' tempco
alone; (b) potting mix θ ≈ 0.25, tap water. Points: fridge 5 °C, room 22 °C, dehydrator/oven-light
35–45 °C. Equilibrate ≥ 3 h per point (NTC stable for 30 min), read without disturbing the probe.
Predicted: electronics < 0.2 % f over 0–50 °C; soil at 76 MHz ≈ −0.6 % VWC per +10 °C (water εr);
soil at 10 MHz ≈ 0 (σ and εr terms cancel); at 2 MHz +2 % VWC per +10 °C.
Pass: |Δθ| ≤ 1 % VWC per 10 °C after the NTC correction. If the oil beaker drifts, it's L1 or the
FDC reference — swap the inductor for a C0G-cored part before blaming the soil.

## Phase 6 — drying curve on a scale (1–2 weeks, unattended)

A real pot with a plant on the kitchen scale (or a beaker of potting mix on a scale, no plant), probe
left in place, readings every 10 min over BLE. Mass loss = water loss, so the scale gives a continuous
θ reference (θ_v(t) = θ_v(0) − Δm/(V·ρ_w)). This is the field-realistic test: gradients, root growth,
fertiliser, temperature swings.
Pass: probe θ tracks the scale θ within ±4 % VWC over the whole drying cycle; hysteresis between
wetting and drying < 3 %. Expect the probe to read low at the very top of the cycle (surface dries
first, the probe averages over its length).

## Data format

`data/measurements.csv`: phase, soil, batch, theta_v, ec_w_Sm, ec_bulk_Sm, temp_C, insertion_mm,
gap_mm, repeat, f_Hz, C_pF, vpk_V, idrive, notes. One row per reading; `analyze_calibration.py`
groups by (soil, batch, ec_w) and reports fit, residuals, insertion scatter, salinity and
temperature slopes.

## Effort

Phases 0–2: three evenings, no soil prep. Phase 3: the long one — batch prep 2 h, 24 h wait,
readings ~3 h per 12 beakers. Phases 4–5: one weekend. Phase 6 runs by itself.
Total ≈ 3 weekends of hands-on time.
