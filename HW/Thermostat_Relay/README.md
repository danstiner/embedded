# Thermostat relay board

## 1. Scope

Control board for two 24 VAC HVAC relays that can be driven by ESP32 GPIO pins. Compatible with
any single-stage gas furnace. Heat pumps are out of scope, they require additional relay channels.
Powering the ESP32 is also out of scope.

## 2. Background

Furnaces take mains power and step it down to 24 VAC. This is supplied on the R wire to a thermostat,
which can close the circuit with the W return wire to call for heat. In a modern furnace this is an
input to a digital control board and only draws a few milliamps. In older furnaces this directly
drives a relay coil and can draw an ampere or more of current.

## 3. Requirements

| ID   | Requirement                                                                                 |
| ---- | ------------------------------------------------------------------------------------------- |
| R-1  | Switch two independent circuits, R–W and R–G, each from one 3.3 V GPIO; high = closed       |
| R-2  | A circuit is open when its input is low or floating, or the MCU is off, in reset or booting |
| R-3  | Carry 1.5 A RMS continuously per circuit at 60 °C, and switch loads as small as 1 mA        |
| R-4  | Withstand 45 V peak (Class 2 transformer limit: 30 V RMS open-circuit, 42.4 V peak)         |
| R-5  | Survive switching off a 1.5 A inductive load                                                |
| R-6  | Leak less than 100 µA through an open circuit                                               |
| R-7  | Galvanically isolate the MCU from the 24 VAC side                                           |
| R-8  | Draw no more than 10 mA per closed circuit from the MCU                                     |
| R-9  | Interrupt a short on the field wiring without damage to the wiring                          |
| R-10 | Surface-mount parts that can be reflowed on a hot plate; through-hole connectors            |

Notes
- 1.5 A and 60 °C figures are conservative assumptions for absolute peak inductive load and heat
- 30 V RMS maximum for thermostat circuits follows from them being Class 2 under UL 5085-3

## 4. Design trades

### 4.1 24 VAC switch

|                          | Relay    | **PhotoMOS** | Driver + FETs | TPSI8830    | TRIAC       |
| ------------------------ | -------- | ------------ | ------------- | ----------- | ----------- |
| Hold current (R-8)       | 70–90 mA | 5–10 mA      | ~5 mA         | ~5 mA       | ~10 mA      |
| 1 mA load (R-3)          | marginal | ✓            | ✓             | ✓           | ✗           |
| Leakage (R-6)            | ✓        | ✓            | ✓             | ✓           | ✗ (snubber) |
| Parts per channel        | 4        | 4            | ~10           | 3–4         | 5+          |
| Available to buy         | ✓        | ✓            | ✓             | ✗ (preview) | ✓           |
| Short-circuit protection | rugged   | none         | possible      | built in    | none        |

**Chosen: PhotoMOS.** An LED inside the package lights a photovoltaic cell that turns on two
back-to-back MOSFETs. It meets every requirement with only four parts per channel, making it easy
to use for bringing up a v1 board. A separate fuse is added for short-circuit protection.
Downsides of PhotoMOS are slightly higher cost and photo degradation failure modes.

TI's reference designs for 24 VAC thermostat switching (section 10) both use discrete MOSFET pairs
with a separate isolated gate drive. This is likely a lower cost design at scale production,
using either small transformers or capacitive isolation instead of optocouplers. It also enables
microsecond switching for power-stealing, potential to add current-sensing circuitry, and ability
to share one isolated supply across all channels. None of these are relevant to a v1 prototype.

TI's upcoming TPSI8830 is worth watching: it integrates a capacitively isolated driver with
back-to-back MOSFETs and overcurrent protection into a single package with 30 mΩ on resistance.

## 5. Circuit

Two identical channels share one fused R input. Only one channel is shown.

```
 logic side (3.3 V, USB ground) :        furnace side (24 VAC, floating)
                                :
 HEAT_EN o--+--[R1 220Ω]---+    :    +------+--- [F1 3A]-- o R
            |            1 | U1 :    | 6    |
         [R2 10k]        [LED]~~:~~[FETs]  [D1 TVS]
            |            2 |    :    | 4    |
 GND     o--+--------------+    :    +------+------------- o W
```

### 5.1 Switch: Toshiba TLP3109A (U1)

| Datasheet value                 |                               | Requirement     |
| ------------------------------- | ----------------------------- | --------------- |
| Off-state voltage               | 100 V max                     | 45 V peak (R-4) |
| On-state current, AC connection | 3 A at 25 °C, 1.95 A at 60 °C | 1.5 A (R-3)     |
| On-resistance                   | 50 mΩ typ, 65 mΩ max          | –               |
| LED trigger current             | 3 mA max                      | see 5.2         |
| Off-state leakage, capacitance  | 1 µA max, 460 pF              | see 5.7         |
| Isolation                       | 1500 V RMS                    | galvanic (R-7)  |
| Pulse current                   | 9 A for 100 ms                | see 5.6         |

- Pins 4 and 6 (the two drains) are the switch; pin 5 (common source) is left open. That
  puts the two MOSFETs in series back to back, which is what lets the part block and
  conduct both polarities of AC.
- Heat: at 1.5 A and the maximum 65 mΩ the switch generates about 0.15 W of heat
- 100 V off-state max was chosen to have margin to clamp surges over the expected 42.4 V peak
  Class 2 transformer output, similar to TI reference design TIDA-010085.

Parts considered (DigiKey, 2026-11-12, quantity 1):

| Part         | Rating       | At 60 °C | R_on max | Isolation | Price           | Outcome     |
| ------------ | ------------ | -------- | -------- | --------- | --------------- | ----------- |
| **TLP3109A** | 100 V, 3 A   | 1.95 A   | 65 mΩ    | 1500 V    | $4.14, in stock | chosen      |
| TLP3546A     | 100 V, 3.5 A | 2.3 A    | 80 mΩ    | 2500 V    | $4.11, no stock | unavailable |

### 5.2 LED resistor: 220 Ω (R1)

The TLP3109A datasheet recommends 5 to 25 mA. `I = (V_GPIO − V_LED) / R`:

| Case            | V_GPIO | V_LED  | I      |
| --------------- | ------ | ------ | ------ |
| Worst-case low  | 3.0 V  | 1.80 V | 5.4 mA |
| Nominal         | 3.3 V  | 1.65 V | 7.5 mA |
| Worst-case high | 3.47 V | 1.50 V | 9.0 mA |

### 5.3 Pull-down: 10 kΩ (R2)

Pull-down to hold the LED input at ~0 V when not being driven (R-2). Overrides the pull-up
glitch during boot that some ESP32 pins exhibit. Cannot override a pin that actively drives high
during boot, those high-level glitch pins should be avoided.

### 5.4 Optional indicator: 2.2 kΩ and a red LED

One LED per channel, from the control input to ground, lit while the ESP32 commands the
channel closed. At 2.2 kΩ it draws about 0.7 mA.

### 5.5 Clamp: Bidirectional TVS (D1)

When the switch opens on a relay coil or gas valve, the coil's inductance creates a voltage
spike across the switch. A bidirectional TVS across the switch limits that voltage (R-5).

|                        | SMBJ48CA   | Requirement                       |
| ---------------------- | ---------- | --------------------------------- |
| Does not conduct below | 48 V       | ≥ 45 V peak                       |
| Clamps at, for 2.1 A   | about 64 V | ≤ 80 V (switch's recommended max) |
| Leakage                | 1 µA max   | see 5.7                           |

Littelfuse SMBJ datasheet (rev. 07/04/25): breakdown 53.3 to 58.9 V at 1 mA, 77.4 V max at
7.8 A. The 64 V figure is interpolated between those points at 2.1 A, the peak of 1.5 A RMS.
TI measured about ±46 V on a relay coil with a 40 V TVS in TIDA-010085.

An RC snubber is ruled out by R-6: a typical 100 nF passes about 1.1 mA at 60 Hz with the
switch open, which could trigger a phantom call for heat on a modern furnace control board.

### 5.6 Fuse: 3 A very fast-acting (F1)

Protects the thermostat cable and transformer from a short of W or G to C while that
channel is closed (R-9); older furnaces may have no fuse of their own. One fuse on R serves
both channels. A short from R to C does not pass through this board.

| Littelfuse 0451003.MRL      | Datasheet                 | Needed                                                              |
| --------------------------- | ------------------------- | ------------------------------------------------------------------- |
| Voltage rating              | 125 VAC                   | 30 V RMS (R-4)                                                      |
| Interrupting rating         | 50 A at 125 VAC           | transformer short-circuit current: unmeasured, estimated 10 to 20 A |
| Continuous current at 60 °C | 2.2 A (3 A × 75 % × 97 %) | 1.7 A                                                               |
| Opens at 200 % (6 A)        | within 5 s                | –                                                                   |
| Melting I²t                 | 1.65 A²s                  | below the switch's 8 A²s                                            |
| Cold resistance             | 23 mΩ                     | –                                                                   |

- Sizing: F1 carries at most about 1.7 A: 1.5 A on one channel (R-3) plus a fan relay on
  the other, or everything a 40 VA transformer can supply. The datasheet derates 25 % for
  continuous operation and about 3 % more at 60 °C (read off its curve). A 2.5 A fuse
  would leave 1.8 A, too little margin. Furnace control boards commonly use 3 A too.
- Overloads: 3 A is above the switch's 1.95 A hot rating, so the fuse protects against
  shorts, not sustained overloads.
- Shorts: the switch tolerates 9 A for 100 ms, about 8 A²s. At 9 A the fuse melts in
  roughly 20 ms (1.65 A²s / (9 A)²), so the switch should survive a short the transformer
  limits to 9 A. Above 9 A the switch is outside its rating however fast the fuse clears.
  For scale, TI measured about 7 A peak from a shorted 20 VA transformer in TIDA-010085.

Why not a resettable PTC:

|                                      | Fuse, 3 A (chosen) | PTC, e.g. 2920L110/60 (1.1 A hold)      |
| ------------------------------------ | ------------------ | --------------------------------------- |
| Carries 1.5 A at 60 °C               | yes                | no: hold current falls to roughly 0.8 A |
| Clears a 9 A short in                | about 20 ms        | about 0.5 s (listing figure)            |
| Lets through (switch survives 8 A²s) | about 1.65 A²s     | tens of A²s                             |
| After a fault                        | replace the part   | resets itself                           |

A PTC large enough to carry 1.5 A hot trips more slowly still, so it would protect the
wiring but not the switch. A fuse drawn as a thin PCB trace is not an option: it has no
defined rating and fails by burning the board.

### 5.7 Leakage when open (R-6)

At 30 VAC, 60 Hz: 1 µA (switch) + 5.2 µA (its 460 pF) + 1 µA (TVS) + about 6 µA (TVS
capacitance, about 500 pF read off the datasheet graph) ≈ 13 µA, against a 100 µA limit.

### 5.8 Isolation (R-7)

Isolation is needed because the two sides have unrelated references. The furnace's 24 VAC
secondary is often bonded to chassis earth at C, and the ESP32's USB ground can reach earth
through a PC or charger; a shared connection would tie the two together, and R, W and G
swing up to ±42 V against it, far outside what a GPIO tolerates. A switch for AC also has
to float with the line it switches.

The only link between the two sides is the light path inside U1 and U2, rated 1500 V RMS.
That is far above anything a 24 VAC Class 2 circuit produces, but it is functional
isolation, not a safety rating. The datasheet does not state the package's creepage
distance. The field side is never connected to logic ground; C is a parking terminal. For
the PCB: keep logic and field copper as far apart as the package allows and route no
copper under U1 and U2.

## 6. Bill of materials

| Ref    | Value                     | Part                                  | Package                    |
| ------ | ------------------------- | ------------------------------------- | -------------------------- |
| U1, U2 | TLP3109A                  | Toshiba TLP3109A(TP,F                 | 2.54SOP6 (Toshiba 11-7C1S) |
| R1, R3 | 220 Ω 1 %                 | any                                   | 0603                       |
| R2, R4 | 10 kΩ                     | any                                   | 0603                       |
| D1, D2 | SMBJ48CA                  | Littelfuse SMBJ48CA or equivalent     | SMB                        |
| R5, R6 | 2.2 kΩ                    | any; optional                         | 0603                       |
| D3, D4 | red LED                   | any high-brightness; optional         | 0603                       |
| F1     | 3 A very fast             | Littelfuse 0451003.MRL                | Nano2                      |
| J1     | 1×3 pin header            | any                                   | 2.54 mm, through-hole      |
| J2     | 4-position screw terminal | Phoenix MKDS 1,5/4-5,08 or equivalent | 5.08 mm, through-hole      |

About $11 in parts, of which the two PhotoMOS relays are $8.28. KiCad has no stock
footprint for the TLP3109A's package, so `Components/TLP3109A/footprints.pretty` holds one drawn from
Toshiba's 2.54SOP6 land pattern (0.8 × 1.2 mm pads, rows 6.3 mm apart, 2.54 mm pitch).
The schematic reuses KiCad's TLP3546 symbol, which has the same pin functions.

## 7. Connections

| J1 (to ESP32) |         | J2 (to furnace) |                           |
| ------------- | ------- | --------------- | ------------------------- |
| 1             | HEAT_EN | 1               | R (24 VAC hot)            |
| 2             | FAN_EN  | 2               | C (parked, not connected) |
| 3             | GND     | 3               | W (heat)                  |
|               |         | 4               | G (fan)                   |

ESP32 pin choice: use pins that are high-impedance at boot, for example GPIO 25 and 26 on
a classic ESP32 dev board. Avoid strapping pins (0, 2, 5, 12, 15), pins that emit signals
at boot (1, 3, 14), flash pins (6–11) and input-only pins (34–39). Other ESP32 variants
differ; check the module's datasheet.

## 8. Verification

Not yet run. Bench first, on a spare 24 VAC transformer, then the furnace.

| Test                                                             | Checks        | Pass                                                 |
| ---------------------------------------------------------------- | ------------- | ---------------------------------------------------- |
| Inputs open: resistance R–W, R–G                                 | R-2           | open circuit                                         |
| Resistance from J1 GND to every J2 terminal                      | R-7           | open circuit                                         |
| Input driven to 3.3 V through an ammeter                         | R-8           | 6.5–9.5 mA; R–W below 0.5 Ω                          |
| Input tied to 3.3 V through 47 kΩ                                | R-2           | stays open                                           |
| Open channel, µA meter in series with a 1 kΩ load                | R-6           | < 100 µA                                             |
| Closed into 22 kΩ, scope the load                                | R-3           | clean sine                                           |
| Closed into 16 Ω, 50 W (1.5 A) for 30 min                        | R-3           | drop < 0.3 V, case rise < 50 °C                      |
| Switch a 24 VAC relay coil off 20 times, scope across the switch | R-5           | peak ≤ 80 V                                          |
| Reset and unplug the ESP32 while a channel is closed             | R-2           | load drops, no pulse at boot                         |
| Channel closed, short W to C (last: blows the fuse)              | R-9           | fuse opens, wiring undamaged; switch may not survive |
| On the furnace: idle 10 min, then G, then W, then reset mid-call | R-1, R-2, R-6 | no phantom call; normal cycles; call drops on reset  |

## 9. Known limitations and open questions

- A hard short on W or G while that channel is closed may destroy the PhotoMOS before the
  fuse clears.
- Both channels at 1.5 A together (3 A through F1) is not supported; the fuse is sized for
  about 2.2 A continuous in total.
- A sustained overload above the switch's 1.95 A rating can overheat a PhotoMOS without
  blowing the fuse, which holds 3 A indefinitely.
- A firmware hang with an output high keeps that channel closed until the watchdog fires.
- This board is not a safety device; the furnace's own limit and flame safeties remain in
  charge.
- To confirm by test or datasheet: hot on-resistance, coil energy, TVS capacitance,
  transformer short-circuit current, the TLP3109A's creepage distance.

## 10. How this document maps to the usual process

A small board normally gets one design document like this one, written before the
schematic and updated as the design is built and tested:

1. Requirements: what it must do, with numbers (section 3).
2. Architecture and trade-offs: the options and why one won (section 4).
3. Detailed design: part selection and worst-case calculations from datasheets (5, 6).
4. Schematic capture and electrical rules check (done: `Thermostat_Relay.kicad_sch`).
5. Design review, then PCB layout and design rules check.
6. Build, bring-up and verification against the requirements (section 8).
7. Record what was learned; revise.

Further reading:

- TI reference design guides for this same application, which are good models of the
  format: [TIDA-00751, 24 V AC solid-state relay](https://www.ti.com/lit/pdf/tidub92) and
  [TIDA-010085, 24 VAC multi-channel SSR](https://www.ti.com/lit/pdf/tiduez1). Both run
  system description → specifications → design theory and calculations → test results.
- Hunter Scott, *Designing Electronics That Work* (No Starch Press): the practical
  process from requirements through bring-up and manufacturing.
- [NASA Systems Engineering Handbook](https://www.nasa.gov/reference/systems-engineering-handbook/):
  the formal version of requirements, trade studies and verification, far heavier than a
  hobby board needs but the source of the vocabulary.
- [KiCad documentation](https://docs.kicad.org/): schematic capture, ERC, layout and DRC.
- [Toshiba TLP3109A datasheet](https://toshiba.semicon-storage.com/info/docget.jsp?did=65124&prodName=TLP3109A),
  the source for section 5.1.
- [Littelfuse SMBJ48CA product page](https://www.littelfuse.com/products/overvoltage-protection/tvs-diodes/surface-mount/smbj/smbj48ca),
  which links the SMBJ series datasheet, the source for section 5.5.
- Littelfuse 451/453 series fuse datasheet (rev. 08/23/21), the source for section 5.6.
