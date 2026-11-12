# Capacitive soil-moisture probe — design summary

Status: 2026-09-04. Field solver and oscillator SPICE are verified; no hardware built yet.
Everything numerical here is reproducible from `scripts/` and `spice/` (see README.md).

## 1. What the physics says (drives every decision below)

1. **Moist potting mix is a conductor below ~10 MHz.** σ/(ωε₀) at θ = 0.25, low-EC water:
   73 @ 2 MHz, 7 @ 20 MHz, 2.1 @ 70 MHz. Below ~10 MHz a "capacitive" probe measures the
   Maxwell-Wagner relaxation of (coating capacitance) × (soil resistance), i.e. conductivity.
   Sensitivity split S_ε / S_σ (∂lnC/∂lnε′, ∂lnC/∂lnσ) at θ = 0.25: 0.44/0.67 @ 2 MHz,
   0.77/0.10 @ 8 MHz, 0.83/0.00 @ 70 MHz. → Run the FDC2212 at its 10 MHz ceiling, or
   use a 50–100 MHz oscillator. Commercial FDR probes sit at 70–100 MHz for this reason.
2. **Best cross-section: two wide coplanar strips, mirrored on both faces, no ground ring,
   no back pour.** Field-energy fraction in soil 62 % (vs 9 % for pad + ground back, 25 % with
   a ground ring, 41 % interdigitated). Interdigitated fingers and ground rings put the field
   in the first millimetre and are 3–4× more sensitive to air gaps / water films.
3. **Contact is the accuracy floor.** Best layout at 70 MHz: −4 % VWC per 0.1 mm air gap on one
   face, +7 % for a 0.1 mm water film. Widening strip spacing to 3 mm: −3.1 % / +4.0 %.
   Potting-mix grains are ≫ the 15 µm mask, so treat ±3 % as the expected scatter.
4. **A 0.2–0.3 mm coat is required for either front end** in fertilised wet soil: uncoated
   Rp at 10 MHz falls to 140 Ω (FDC can't drive it); at 70 MHz the uncoated D = G/ωC reaches 0.66
   (oscillator pulls 10–25 %). Coat costs sensitivity (ratio 4.5 → 2.5) and adds a small
   Maxwell-Wagner EC term (+2.9 % VWC at EC×6, see §5).
5. **Steel nails** don't beat the gap floor (−4/−9 % VWC for a 0.1/0.3 mm loose hole), bare nails are
   an EC probe not a moisture probe, and coating integrity is the failure mode. Not pursued.
6. **Bulk-EC correction works and is well-conditioned above ~8 MHz** (10 % σ error → 0.3 % VWC);
   at 2 MHz the same σ error costs 3–7 % VWC. Correction form: ln C_corr = ln C − S_σ(θ)·ln(σ_b/σ_ref).

## 2. Probe geometry (OSH Park 2-layer)

Stack (docs.oshpark.com/services/two-layer): 1.524 mm KB6167F core Dk 4.5, 35.6 µm Cu, 15.2 µm
Taiyo PSR-4000BN mask (±0.2 mil; ±33 % mask → ±0.2 % VWC at ≥8 MHz, harmless).

| Item | Baseline (simulated) | Better variant (simulated, not re-tuned) |
|---|---|---|
| Board width | 12 mm | 12 mm |
| Strips (top and bottom, mirrored, via-stitched every ~10 mm) | 2 × 5.0 mm wide, 1.0 mm gap | 2 × 4.0 mm, 3.0 mm gap |
| Sensing length | 80 mm (Clapp) / 50 mm (FDC2212) | same |
| Coat over sensing region | 0.3 mm epoxy/acrylic dip, εr ≈ 3, low loss | 0.1–0.2 mm to be evaluated (task) |
| Head | electronics on the same board, ground pour only under the electronics, ≥5 mm keep-out to the strips, oscillator ≤10 mm from the sense strip | |
| Sensitivity ratio C(θ=0.40)/C(0.05), 70 MHz | 2.5 (coated) / 4.5 (bare) | 5.1 bare |
| Gap error 0.1 mm / water film 0.1 mm (70 MHz) | −4.1 % / +6.8 % bare, −3.0 % / +2.2 % coated | −3.1 % / +4.0 % bare |

Lumped values for the 80 mm coated probe at 60 MHz (+6 pF head parasitic), from `results/lumped_values.txt`:
dry 14.2 pF / 0.19 mS, moist lo-EC 21.7 pF / 0.71 mS, moist hi-EC 22.5 pF / 1.90 mS,
saturated lo-EC 28.6 pF / 0.93 mS, saturated hi-EC 31.1 pF / 2.71 mS (D ≤ 0.23, Rp ≥ 370 Ω).
50 mm coated at 10 MHz: 11–30 pF, Rp 1.9–10 kΩ.

## 3. Front end A — FDC2212 at 10 MHz (low-risk)

- Tank: 12 µH + 10 pF C0G fixed + probe (50 mm coated) → 7.3–10 MHz over the moisture range.
  Verify the datasheet's f_REF/f_SENSOR ratio constraint with the 40 MHz external reference.
- External 40 MHz oscillator (gated), IDRIVE set by the Rp search; Rp stays ≥1.9 kΩ with the coat.
- Read frequency; C = 1/(L(2πf)²) − C_fixed − C_par. Correct with bulk EC from the 4-electrode probe.
- Schematic: `hardware/schematic_fdc2212.md`, BOM: `hardware/bom_fdc2212.csv`.

## 4. Front end B — discrete Clapp oscillator + nRF54L15 counter (best cheap sensor)

Common-collector Clapp, MMBT3904, L = 470 nH in series with the probe, C1 = C2 = 22 pF,
Re = 390 Ω (Ie ≈ 2.5 mA), 22 k/22 k bias, 10 nF DC block in the resonator. Verified in ngspice
(`spice/run_clapp.py`, results in `results/clapp_spice_results.txt`):

| soil case | Cp | Gp | f_osc | Vpp(e) | start |
|---|---|---|---|---|---|
| dry | 14.2 pF | 0.19 mS | 84.6 MHz | 2.6 V | 60 ns |
| moist lo-EC | 21.7 | 0.71 | 76.6 | 2.6 | 70 ns |
| moist hi-EC | 22.5 | 1.90 | 75.8 | 1.7 | 70 ns |
| sat lo-EC | 28.6 | 0.93 | 72.4 | 2.7 | 70 ns |
| sat hi-EC | 31.1 | 2.71 | 71.5 | 2.2 | 90 ns |

Frequency vs supply: 0.03 % over 2.7–3.3 V. Transistor tempco: −0.36 % f over 0–50 °C (≈0.2 % VWC).
Output squared by a self-biased 74LVC1G04, ÷16 by a 74LVC161 → 4.5–5.3 MHz into GPIOTE → PPI →
TIMER (count mode), gated 2 ms by a second timer from the 32 MHz crystal: ~10⁴ counts, 10⁻⁴ resolution.
Whole chain power-gated (P-FET or GPIO); ~15 mA for 3 ms ≈ 45 µC per reading (LVC161 dynamic
current dominates; a 74LVC1G74 ÷2 in front of a slower counter halves it).
Peak detector (BAT54 + 100 pF ∥ 100 kΩ → SAADC) reads Vpk, which falls 2.6 → 1.7 V lo→hi EC: a
salinity signal *at the sensing frequency* for a 2-parameter (f, Vpk) → (θ, σ) calibration.

Design notes that came out of the SPICE: divider capacitance is the lever on loss pulling
(68 pF: −2.6 % f at D = 0.26; 47 pF: −1.5 %; 22 pF: −0.4 %); 100 pF fails to start (negative
resistance −gm/(ω²C1C2) too small); Ie < 2 mA fails at D ≈ 0.26. Transistor Cje/Cjc add a constant
≈10 % offset from the ideal LC formula — calibrates out.
Schematic: `hardware/schematic_clapp.md`, BOM: `hardware/bom_clapp.csv`.

## 5. Error budget (apparent-θ error, % VWC, true θ = 0.25 unless noted)

| term | FDC2212 @ 2 MHz (typical DIY tank) | FDC2212 @ 10 MHz, coated 50 mm | Clapp @ ~76 MHz, coated 80 mm |
|---|---|---|---|
| readout resolution / noise | <0.1 | <0.1 | 0.05 |
| reference / inductor tempco (20 °C) | <0.1 | <0.1 | <0.1 |
| supply | — | — | 0.03 |
| transistor / IC tempco | — | small | 0.2 |
| mask thickness ±33 % (board-to-board) | ±1.5 | ±0.2 | ±0.2 |
| soil T +10 °C | +2.1 | −0.2 | ≈0 (ε_w term −0.6 at 70 MHz) |
| pore-water EC ×2 (fertilising) | +4.4 | +0.7 (bare) ¹ | ≈+1.3 (est. from ×6) |
| pore-water EC ×6 | +21 | +4.9 (bare) ¹ | +3.8 (1.1 pulling + 2.9 coat MW) |
| … after σ correction (EC probe ±10 %) | ±3–7 | ±0.3 | est. ±1 with (f, Vpk) fit |
| 0.1 mm air gap, one face | −0.8 (misleading; conductive regime) | −2.4 (bare) / ≈−3 (coated) | −3 |
| 0.1 mm water film | +2.8 | ≈+2 (coated) | +2 |
| soil model, generic vs per-mix calibration | ±5–8 / ±3 | ±5–8 / ±3 | ±5–8 / ±3 |
| oscillation failure (Rp / Q) | wet soil, uncoated | none with coat | none with coat |
| **realistic total, per-mix calibration, EC-corrected** | **±8–15** | **±3–4** | **±3–4 (contact-limited)** |

¹ 10 MHz EC numbers were run on the bare geometry; the coated 10 MHz case is an open task
(expect a few % from the coat MW term, like the Clapp).

Both good options end up contact-limited at ±3–4 % VWC. The Clapp wins on cost (<$1 vs a few $
plus a reference oscillator), energy, and on having the σ signal at the right frequency;
the FDC2212 wins on zero RF design risk.

## 6. Recommendation

- Data this month: FDC2212 at 10 MHz, 50 mm coated probe, EC correction from the 4-electrode probe.
- Best cheap probe: build the Clapp head on the same 12 mm board; one spin is likely enough
  given the SPICE margins. Keep the FDC footprint option on the first spin if you want both.
- Either way: 2-sided coplanar strips, 0.3 mm coat, 4-electrode EC + NTC on the same board,
  per-mix 3-point gravimetric calibration at two salinities.

## 7. Open items (see CLAUDE.md for the task list)

- Coat thickness trade (0 / 0.1 / 0.2 / 0.3 mm) at 70–85 MHz: S_σ and D vs coat, then SPICE pulling.
- Re-tune L for the 4 mm / 3 mm strip variant (lower C → shift L up).
- Coated 10 MHz FDC EC numbers; FDC f_REF ratio and IDRIVE table check.
- Confirm 74LVC161 f_max at 3.0 V (or use 74LVC1G74 stages); confirm nRF54L15 GPIOTE input rate.
- 2-parameter (f, Vpk) calibration model and inversion code.
- Soil model: replace CRIM/Archie defaults with measured potting-mix data once the probe exists.
