# Capacitive soil-moisture probe: design notes

Status 2026-11-16: simulated, not built. Everything numerical is reproducible from `scripts/`
and `spice/` (README.md); the outputs land in `results/`, which is not tracked.

## 1. Goal and assumptions

Accurate, robust moisture reading for potting mix and garden soil from a cheap PCB probe on an
nRF54L15 node, with soil temperature and a salinity estimate.

Assumptions I made where nothing was specified:

- Media: soilless potting mix (porosity about 0.7, theta up to 0.6) and mineral soil.
- Pore-water EC up to 3 dS/m (fertigated containers) must read correctly; up to 6 dS/m must at
  least oscillate at field moisture.
- 5-40 C soil temperature.
- Fab is OSH Park (direct KiCad upload); hand assembly; one board spin should have a good
  chance of working.
- The probe is a peripheral with a 7-wire interface, not a complete node. No bare EC electrodes
  on this board.

## 2. What the literature says, and what this design takes from it

- Capacitance probes read water because water's permittivity (78 at 25 C) dwarfs that of
  solids (3-5) and air [Topp 1980]. Below roughly 50 MHz wet soil is more conductor than
  dielectric and a "capacitive" probe reads salinity and contact; texture and salinity effects
  shrink as frequency rises, and a 70 MHz capacitance sensor held about 2 % VWC up to high
  solution EC with one calibration for mineral soils [Kizito 2008*; Bogena 2007; Kelleners
  2005; Chen and Or 2006]. Low-cost probes built on a 555 run two orders of magnitude lower
  and are salinity- and temperature-sensitive [Gonzalez-Teruel 2019*; Placidi 2020].
  **Taken: oscillator at 80-130 MHz, as high as the divider logic allows.**
- Electrodes embedded inside the circuit board, not on its surface, are what published
  low-cost research sensors use for isolation from the soil [Bogena 2017*; Gonzalez-Teruel
  2019*]. **Taken: strips on the inner layers of a 4-layer board.**
- Sensor-to-sensor spread is a first-order error and is removed by calibrating every sensor in
  reference media of known permittivity, then using one permittivity-to-water-content model
  for all [Bogena 2017*; Jones 2005; Sakaki 2008]. **Taken: per-unit air and water points plus
  a common table.**
- With that calibration the remaining temperature effect is the permittivity of water itself,
  removable with a temperature reading [Bogena 2017*; Rosenbaum 2011]. **Taken: NTC at the
  soil line, correction with the water permittivity [Malmberg and Maryott 1956].**
- The sampling volume is weighted to the electrode surface, so air gaps are the practical
  accuracy limit of any blade probe [Sakaki 2008]. **Taken: widest practical electrode
  spacing; the rest is installation.**
- Pore-water EC follows from bulk permittivity and bulk EC [Hilhorst 2000]. **Taken in part:
  the detector gives bulk EC at the oscillation frequency, through the insulation. A
  low-frequency measurement on bare electrodes would be the standard method and is not on this
  board.**

## 3. Approaches considered

| | Electrodes | Front end | Why not / why |
|---|---|---|---|
| First iteration in this PR | outer-layer strips, 12 mm board, hand-dipped 0.3 mm coat | single-transistor series Clapp at 70-85 MHz, or FDC2212 at 10 MHz | The coat sets the calibration and varies by +/-50 % by hand (2-3 % VWC, `geometry_study.py`). The series-resonant Clapp reads the series-equivalent capacitance, which moves 5-34 % with probe loss and not monotonically (`characterize.py --pulling`). 10 MHz is conduction-dominated in wet soil. Its /16 output at 5 MHz is above what a GPIOTE-to-TIMER event path counts reliably |
| Fork (slot between the strips) | buried | any | 0.6 % VWC better on water film, nothing on air gap, and two prongs that can splay (`geometry_study.py`) |
| Fixed-frequency drive with gain/phase detection | buried | vector detector | Measures the complex admittance directly, but needs an RF detector IC or a mixer and its own calibration. More parts and more risk than a frequency count plus one DC voltage |
| **Chosen** | **buried strips, 20 mm board** | **cross-coupled pair on a parallel tank, comparator, /1024, amplitude detector** | below |

## 4. Electrodes

`geometry_study.py`, 70 MHz, potting mix, errors in % VWC at theta 0.25:

| Cross-section | C wet/dry | 0.1 mm air gap | 0.1 mm water film | EC x6 | Loss D, wet saline | Fab tolerance |
|---|---|---|---|---|---|---|
| 2-layer, mask only, 12 mm board, 1 mm gap | 5.1 | -4.0 | +4.5 | +0.2 | 0.64 | 0.2 |
| 2-layer + 0.2 mm dipped coat, 20 mm, 7 mm gap | 5.0 | -1.7 | +1.2 | +0.8 | 0.47 | 1.4 |
| 4-layer buried, 12 mm, 1 mm gap | 3.5 | -3.5 | +2.8 | +1.3 | 0.35 | 0.5 |
| **4-layer buried, 20 mm, 7 mm gap** | 5.4 | -1.9 | +1.4 | +0.8 | 0.49 | 0.2 |
| 4-layer buried, 25 mm, 9 mm gap | 5.8 | -1.6 | +1.1 | +0.6 | 0.53 | 0.2 |

- Spreading the strips is what reduces contact error: the field reaches further (90 % of the
  response within 14 mm of the faces, against 7 mm) so the first 0.1 mm matters less. Past
  20 mm the return is small for the extra board.
- Burying the strips under the factory prepreg gives the dipped coat's halved water-film error
  with a seventh of its tolerance, and no metal near the soil.
- The price of any insulation is a Maxwell-Wagner term: salinity raises the apparent
  capacitance. It falls as 1/f^2; section 8 has the numbers at the real frequency.

As built: strips 5.5 mm wide, 7 mm apart, 1 mm from the board edge, on In1 and In2, 86 mm long
of which 80 mm is below the soil line. No vias and no outer copper in the sensing area.
Driven differentially, so neither strip is circuit ground and the reading does not depend on
how the node is wired or grounded.

## 5. The strips are a transmission line

`probe.py`. Per-unit-length admittance comes from the 2-D solver, inductance (766 nH/m) from
the same cross-section in vacuum. In wet soil the 80 mm strips are a tenth of a wavelength at
100 MHz and the feed sees 10-35 % more capacitance than length times C' (30 % in water at
its 82 MHz).
That is harmless for the wanted mode and is in every number below, but it has two consequences:

- Loss partly cancels the line enhancement, which reduces the salinity error of the frequency
  reading relative to a lumped estimate.
- The line is a quarter wave long at 160-600 MHz depending on the medium, which gives the
  tank a second resonance. Section 6.

## 6. Oscillator

`spice/osc.py`, `characterize.py`, `scripts/tank_modes.py`, `spice/verify_line.py`. Transistor
models are the manufacturer's Gummel-Poon chip parameters plus the SOT-23 package network.

**Topology.** A cross-coupled pair is a two-terminal negative conductance, so the circuit runs
at the tank's parallel resonance: it reads the probe's parallel capacitance, which is the
quantity that salinity moves least. Loss still pulls the frequency through the delay of the
pair, as an apparent capacitance tau x G with tau = 170 ps: 11 pF of probe reads 1.7 % high
per mS of loss, linearly. The series Clapp on the same transistor swings between -8 % and
+34 %.

**Parasitic mode 1: GHz emitter-follower oscillation.** With bases wired straight to the
opposite collectors the pair oscillates at 3.4 GHz through the SOT-23 lead inductance and the
wanted mode dies. 22 R base stoppers cure it (4.7 R does not, 10 R does). The stoppers times
the Miller-doubled collector-base capacitance are most of tau, which is why the transistor is
a BFR181 (Ccb 0.32 pF, tau 100-170 ps) and not a BFR92 (0.95 pF, 215 ps) or a general-purpose
part.

**Parasitic mode 2: the strip line's second resonance.** With a capacitor and a parallel
damping resistor across the tank, the second resonance (230 MHz in water, 250-320 MHz in wet
soil) is as lightly damped as the wanted one, and the transient simulation with a distributed
line hops to it in water and in saturated low-salinity soil. Moving the damping resistor in
series with the tank capacitor (R3 15 R + C4 33 pF) makes its loss rise as f^2:

| Medium | Wanted mode | Least-damped other mode |
|---|---|---|
| air | 132 MHz, 10.3 mS | 819 MHz, 58 mS |
| mix theta 0.45, low EC | 101 MHz, 8.4 mS | 304 MHz, 33 mS |
| mix theta 0.60, high EC | 93 MHz, 16.1 mS | 274 MHz, 33 mS |
| deionized water | 82 MHz, 5.9 mS | 244 MHz, 25 mS |

The other modes are at least 2.1 times lossier everywhere (1.9 with the strips 5 % long), and
the distributed-line transient stays on the wanted mode in all eleven media tried, at tail
currents from 2.6 to 3.7 mA. The pair offers 30 mS, so in water the second mode could still
start if the wanted one were absent; it relies on mode competition there. This is the item I
would watch first on the bench.

**Operating point.** 3.1 mA tail (R6), collectors fed through R2 so the comparator sees a
common mode 0.5 V below its supply. Amplitude 0.10-0.35 V peak differential, always below
base-collector conduction. Runs up to 16 mS of probe loss.

| | air | theta 0.25 | theta 0.45, 3 dS/m | water |
|---|---|---|---|---|
| f_osc, MHz | 129.0 | 112.8 | 99.5 | 81.6 |
| REF - AMP, mV | 40 | 45 | 23 | 78 |

Sensitivities (`osc.py` variants on the first tank; the pair is unchanged): temperature
-20 ppm/C from the transistors, about -45 ppm/C with the inductors; supply -190 ppm per
+1.5 %; 1 pF of stray on each node -0.7 %. All but temperature are constants of a unit and
drop out in the two-point calibration; temperature is corrected with the NTC.

**Detector.** The common-emitter node of a switching pair rides up with amplitude. Q3 is the
same transistor at half the tail current with no RF, so REF - AMP cancels supply and Vbe
temperature drift to first order. No RF part touches the tank for this.

## 7. Readout

Comparator (TLV3601: inputs valid to 0.2 V beyond the rails, 325 MHz toggle), two
flip-flops (/4, 160 MHz guaranteed against 129 MHz in air), ripple counter (/256, 75 MHz
guaranteed against 33 MHz). The host times 64 periods of the 80-126 kHz output: 1e-4
resolution in 0.6 ms, which is 0.03 % VWC. The LDO (3.0 V) is also the power switch.

## 8. Error budget

`system_sim.py`: soil state to permittivity to line admittance to oscillator table to the
firmware arithmetic. Apparent-theta error in % VWC, potting mix:

| Perturbation | theta 0.10 | 0.25 | 0.40 | 0.55 |
|---|---|---|---|---|
| pore-water EC 0.5 to 3 dS/m, frequency only | +0.2 | +0.7 | +1.4 | +3.0 |
| same, frequency + detector | 0.0 | 0.0 | 0.0 | -0.1 |
| soil +10 C, corrected, NTC 2 C low | 0.0 | -0.1 | -0.2 | -0.3 |
| air gap 0.05 mm, one face | -0.3 | -1.1 | -2.6 | -4.9 |
| air gap 0.10 mm, one face | -0.5 | -1.9 | -4.4 | -7.9 |
| water film 0.10 mm, one face | +2.2 | +1.5 | +1.1 | +0.8 |
| 3 mm of strip left above the soil | -0.4 | -0.7 | -1.0 | -1.3 |
| inductor +2 % and stray +2 pF, uncalibrated unit | +7.1 | +5.4 | +4.8 | +4.8 |
| same, 2-point calibrated | 0.0 | 0.0 | 0.0 | 0.0 |
| prepreg +10 %, 2-point calibrated | +0.5 | +0.8 | +0.9 | +0.9 |
| laminate Dk +5 %, 2-point calibrated | -0.2 | -0.4 | -0.4 | -0.5 |
| detector gain +5 % or offset 2 mV after calibration | 0.2 | 0.1 | 0.1 | 0.1 |
| electronics 10 C away from the NTC | +0.1 | +0.1 | +0.1 | +0.1 |

Monte Carlo over all of it (800 draws: theta 0.03-0.6, pore-water EC 0.2-4 dS/m, 5-40 C, air
gap exponential with 0.02 mm mean, insertion error, fab and component tolerances, readout
noise):

| Calibration | Bias | sd | 95 % within |
|---|---|---|---|
| none, frequency only | -0.6 | 2.7 | 5.5 |
| 2-point per unit, frequency only | -0.4 | 1.4 | 3.2 |
| 2-point per unit, frequency + detector | -1.1 | 1.3 | 4.0 |

Mineral soil: sd 0.9 with the 2-point calibration. The negative bias is the air gap and
insertion terms, which only ever lower the reading; a calibration made in real soil absorbs
it. Frequency-only looks less biased because its positive salinity error happens to offset
them. Contact dominates either way, and the per-unit air/water calibration is the single most
valuable step.

Bulk EC from the detector: within 12 % (68 % of draws) in the model.

The air layer is interpolated between directly solved thicknesses (0.005 to 0.10 mm); a
single 0.10 mm table understates thin layers. `paper/manuscript.md` compares this design with
eight others under one calibration and has the fuller treatment, including a dispersive
substrate.

## 9. What the model does not cover

- Soil permittivity is taken as frequency-independent with a DC conductivity. Clay and
  organic media disperse below a few hundred MHz [Kelleners 2005; Chen and Or 2006]; expect a
  medium-specific curve to be needed there.
- The field model is 2-D. End effects at the tip, the feed region and the head's ground plane
  are not modeled; the two-point calibration absorbs a scale error but not a shape error.
- The oscillator table is for a lumped load. Against the distributed-line transient it is
  within 0.8 % in frequency and 4 mV on the detector (`verify_line.py`); the difference is
  harmonic current in the line. It is smooth in moisture, so an empirical table absorbs it.
- Stray capacitance on the tank nodes is a guess (2.5 pF per node).
- No comparator kickback, no startup-from-noise, no layout extraction.
- The air-gap statistics in the Monte Carlo are an assumption, not data.

## References

Entries marked * were read in full text during this work. The others are cited from the
literature as I know it; check them before relying on a specific number.

- Bogena et al. 2007, J. Hydrol. 344:32-42. Evaluation of a low-cost soil water content sensor for wireless network applications.
- Bogena et al. 2017*, Sensors 17(1):208. Effective calibration of low-cost soil water content sensors.
- Chen and Or 2006, Water Resour. Res. 42:W06424. Effects of Maxwell-Wagner polarization on soil complex dielectric permittivity under variable temperature and electrical conductivity.
- Gonzalez-Teruel et al. 2019*, Sensors 19(3):491. Design and calibration of a low-cost SDI-12 soil moisture sensor.
- Hilhorst 2000, Soil Sci. Soc. Am. J. 64:1922-1925. A pore water conductivity sensor.
- Jones et al. 2005, Vadose Zone J. 4:1048-1058. Standardizing characterization of electromagnetic water content sensors: Part 1. Methodology.
- Kelleners et al. 2005, Soil Sci. Soc. Am. J. 69:67-76. Frequency dependence of the complex permittivity and its impact on dielectric sensor calibration in soils.
- Kizito et al. 2008* (abstract), J. Hydrol. 352:367-378. Frequency, electrical conductivity and temperature analysis of a low-cost capacitance soil moisture sensor.
- Malmberg and Maryott 1956, J. Res. Natl. Bur. Stand. 56:1-8. Dielectric constant of water from 0 to 100 C.
- Placidi et al. 2020, Sensors 20(12):3585. Characterization of low-cost capacitive soil moisture sensors for IoT networks.
- Rosenbaum et al. 2011, Vadose Zone J. 10:582-593.
- Roth et al. 1990, Water Resour. Res. 26:2267-2273. Calibration of time domain reflectometry for water content measurement using a composite dielectric approach.
- Sakaki et al. 2008, Water Resour. Res. 44:W00D08.
- Topp, Davis and Annan 1980, Water Resour. Res. 16:574-582. Electromagnetic determination of soil water content.
- Datasheets: Siemens BFR 181 and BFR 92P (1996, SPICE parameters); TI TLV3601 (SNOSDB1), SN74LVC1G80 (SCES221), SN74LV4040A, TPS7A05 (SBVS254); Murata LQW18A.
- OSH Park 4-layer and 2-layer service specifications, docs.oshpark.com/services.
