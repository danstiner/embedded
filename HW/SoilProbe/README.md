# Soil Probe 2026v1

Capacitive soil-moisture probe: a 20 x 126 mm 4-layer blade with the sensing electrodes buried
on the inner layers and a 80-130 MHz LC oscillator in the head. A host MCU (nRF54L15 node)
powers it for a few milliseconds and reads three things:

| Output | What it is | Used for |
|---|---|---|
| `FOUT` | oscillator frequency / 1024, 79 kHz (water) to 126 kHz (air) | volumetric water content |
| `REF - AMP` | oscillation amplitude detector, 8-80 mV | probe loss: bulk EC, salinity correction |
| `NTC` | 10 k thermistor at the soil line | soil temperature, water-permittivity correction |

Nothing has been built yet. Every number here is from simulation (`sim/soil_probe/`), and
`sim/soil_probe/TEST_PLAN.md` lists what to measure first. Design reasoning is in
`sim/soil_probe/DESIGN.md`.

## Predicted performance

| Item | Value | Source |
|---|---|---|
| Range | air to water; soil theta 0-0.6 | `system_sim.py` |
| Error, 2-point calibrated unit, generic medium curve | 1.2 % VWC sd (potting mix), 0.9 % (mineral soil), contact-limited | Monte Carlo, `system_sim.py` |
| Same unit without its own air/water calibration | 2.7 % VWC sd | Monte Carlo |
| Pore-water EC 0.5 to 3 dS/m, frequency only | +0.7 % VWC at theta 0.25, +3 % at 0.55 | error budget |
| Same, using the detector | under 0.1 % | error budget |
| Air gap 0.1 mm on one face | -1.9 % VWC at theta 0.25, -4.4 % at 0.40 | error budget |
| Bulk EC estimate | about +/-10 % (model; the detector is uncalibrated hardware) | Monte Carlo |
| Stops oscillating above | 16 mS probe loss: pore-water EC over about 4 dS/m in saturated potting mix (6 dS/m still runs at theta 0.45) | `characterize.py` |
| Supply | 3.0-3.6 V, about 26 mA for 4 ms per reading (about 100 uC) | datasheet sums |

The contact terms dominate and no circuit fixes them: install the blade in firm, undisturbed
or re-packed soil and do not rock it.

## Host interface (J1, 2.54 mm header pads, wires soldered and potted)

| Pin | Name | Direction | Notes |
|---|---|---|---|
| 1 | VDD | in | 3.0-3.6 V. The LDO is in dropout below 3.1 V, which is fine: frequency moves 190 ppm per 1.5 % of supply |
| 2 | EN | in | high = measure. 1 M pull-down on board |
| 3 | GND | | |
| 4 | NTC | out | 10 k B3380 to GND. Read against a host pull-up, ratiometric to host VDD |
| 5 | AMP | out | detector, 10 k source with 10 nF |
| 6 | REF | out | detector reference, 10 k source with 10 nF. Use `REF - AMP` |
| 7 | FOUT | out | 3.0 V CMOS square wave through 100 R |

Reading sequence:

1. EN high, wait 3.5 ms: LDO start-up is 2.8 ms max (TPS7A05 datasheet), the detector filter
   settles in 0.5 ms.
2. Time 64 periods of FOUT with a TIMER capture on a GPIOTE event (about 0.6 ms, 1e-4
   resolution at 16 MHz). Do not count edges in a TIMER through DPPI at MHz rates; that path
   drops events, which is why the prescaler divides all the way to 100 kHz.
3. Sample AMP, REF and NTC with the SAADC.
4. EN low. No FOUT edges within 1 ms of step 2 means the oscillator is stalled (soil too
   saline and wet): report that instead of a number.

Conversion (details and the reference model in `sim/soil_probe/scripts/system_sim.py`):

- per unit, once: store `f_air`, `f_water`, `det_air` from readings in air and in clean water;
- `x = (f^-2 - f_air^-2) / (f_water^-2 - f_air^-2)`, `q = (REF - AMP) / det_air`;
- `(x, q)` to permittivity and bulk EC through a 2-D table common to all units;
- permittivity to water content with the medium's mixing curve, using the water permittivity at
  the NTC temperature.

## Bill of materials

Passives are 0402 unless noted; any manufacturer.

| Ref | Value | Part | Notes |
|---|---|---|---|
| U1 | 3.0 V LDO, enable | TPS7A0530PDBVR | SOT-23-5. Power gate and regulator in one |
| U2 | 2.5 ns comparator | TLV3601DBVR | SOT-23-5. Squares the 0.1-0.4 V tank signal |
| U3, U4 | D flip-flop | SN74LVC1G80DBVR | SOT-23-5. Divide by 4; 160 MHz guaranteed |
| U5 | 12-stage ripple counter | SN74LV4040APWR | TSSOP-16. Q8 used, divide by 256 |
| Q1, Q2, Q3 | NPN RF, fT 8 GHz, Ccb 0.3 pF | BFR181 | SOT-23. Low Ccb and transit time set the loss pulling; do not substitute a general-purpose NPN |
| L1, L2 | 22 nH 2 %, Q >= 40 at 250 MHz | LQW18AN22NG00 | 0603 wirewound |
| C4 | 33 pF C0G 2 % | any | tank capacitor |
| R3 | 15 R 1 % | any | in series with C4: damps the strip line's second resonance |
| R4, R5, R7 | 22 R 1 % | any | base stoppers |
| R6 | 560 R 1 % | any | tail current, 3.1 mA |
| R8 | 1.1 k 1 % | any | reference transistor at half the tail current |
| R2 | 100 R 1 % | any | collector feed, sets the comparator common mode |
| R11, R12, R13 | 100 R | any | comparator input isolation, FOUT series |
| R9, R10 | 10 k | any | detector filters |
| R1 | 1 M | any | EN pull-down |
| C3, C5, C6 | 10 nF | any | |
| C7-C10 | 100 nF | any | |
| C1, C2 | 1 uF 0603 | any | LDO in and out |
| TH1 | 10 k NTC 1 %, B 3380 | NCP15XH103F03RC | |
| J1 | 1x7 2.54 mm pads | none | solder wires |

## Fabrication

OSH Park 4-layer: FR408HR, 0.2 mm 2113 prepreg over the inner layers, ENIG. The board stackup
in the `.kicad_pcb` matches their published one, and the design rules in the `.kicad_pro` are
their 4-layer limits (5 mil track and space, 10 mil drill, 4 mil annular ring, 10 mil hole to
inner copper).

The prepreg is part of the sensor: it is the 0.2 mm insulation between electrode and soil, and
its thickness tolerance (+/-10 %) is the main unit-to-unit term left after calibration (about
0.5 % VWC). A fab with a different outer prepreg works but shifts the common table: rerun the
simulation with that stack.

The sensing area has no copper on the outer layers and no vias, so nothing metallic touches
the soil even if the mask is scratched.

## Assembly and potting

- Parts are on the front only. There are no reference designators on the silkscreen (no room
  between the 0402s); use the fab layer or the interactive placement in KiCad.
- Pot the head on both faces down to the SOIL LINE mark. The simulation assumes potting
  compound (relative permittivity about 3.5) over the 6 mm of strip above the soil line; the
  two-point calibration absorbs the difference if you use something else, as long as it is
  applied before calibrating.
- Seal the board edges of the blade (conformal coat or a thin epoxy wipe). The strips stop 1 mm
  short of the edge, but exposed FR-4 edges wick water along the glass weave over time.
- Calibrate after potting: one reading in air, one with the blade in clean water up to the soil
  line.

## Bring-up, before any soil

Predicted values from `sim/soil_probe/scripts/expected_liquids.py`:

| Medium | FOUT | REF - AMP |
|---|---|---|
| air | 126.0 kHz | 40 mV |
| isopropanol 99 % | 102.1 kHz | 60 mV |
| tap water (0.3 mS/cm) | 79.6 kHz | 62 mV |
| 1 g/L salt water | 77.9 kHz | 20 mV |

Absolute frequency depends on stray capacitance that the simulation only estimates (2.5 pF per
tank node); expect the air value within +/-5 %. The ratios between media are the real test. If
FOUT in air is above 137 kHz the first flip-flop is being clocked past 140 MHz: raise C4.

Never probe the tank nodes (SA, SB) with a scope probe; 10 pF moves the oscillator 10 %. Look
at FOUT, or at the comparator output with a low-capacitance probe.

## Files

| Path | Contents |
|---|---|
| `SoilProbe.kicad_sch`, `.kicad_pcb`, `.kicad_pro` | KiCad 10 project. ERC and DRC (with schematic parity) are clean |
| `Components/SoilProbe.kicad_sym` | comparator and probe-strip symbols |
| `sim/soil_probe/` | field solver, probe line model, ngspice oscillator model, system simulation, design notes, test plan |

The schematic and board were generated by script from one netlist and then checked with
`kicad-cli`; they are ordinary KiCad files and are meant to be edited by hand from here on.
