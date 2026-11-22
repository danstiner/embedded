# Leak sensor

## 1. Scope

A battery leak and humidity sensor built on the Ezurio BL54L15μ (nRF54L15) module. Two
contacts near the bottom detect water and wake the board at once; an SHT45 reports
temperature and humidity. Firmware: `SW/hygrometer` (Matter over Thread or BTHome).

This is revision **2026v5**, in design. The baseline is 2026v4, the first leak board,
fabricated as the hygrometer's 2026v4 (tag `fab/BL54L15μ-hygrometer/2026v4`, firmware
board `bl54l15u_hygrometer@2026v4`).

## 2. Changes from 2026v4

| Item          | 2026v4                                          | 2026v5                                                   |
| ------------- | ----------------------------------------------- | -------------------------------------------------------- |
| Size          | 48 mm square                                    | 17.0 × 19.5 mm, stands on the end of the cell (5.6)      |
| Battery       | CR2 in a Keystone 1011 holder                   | CR2 on wires, BAT+ and BAT− pads on the back             |
| Leak contacts | 6 mm domes on the back, driven one way          | 4 mm domes on the front, either way (4.1)                |
| Leak pins     | drive P0.01, sense P1.07, 1 MΩ to ground        | P1.07 and P1.04 each drive or sense; 1 MΩ to a GPIO      |
| I2C           | SDA P1.14, SCL P1.04                            | SDA P1.10, SCL P1.12 (5.2)                               |
| Buzzer        | BZ1, Q1, D3, R7 (never driven by firmware)      | removed                                                  |
| SWD           | 2×5 1.27 mm box header on the front             | 2×5 1.27 mm pads on the back: header or pogo clip (4.2)  |
| Mounting      | H1, H2                                          | none; the case holds the board by its edge               |

## 3. Requirements

| ID  | Requirement                                                                              |
| --- | ---------------------------------------------------------------------------------------- |
| R-1 | Wake on water across the contacts from a pin edge, without polling                       |
| R-2 | Measure the resistance between the contacts with the SAADC, in both directions           |
| R-3 | No current through the contacts while dry; while measuring, equal current each way       |
| R-4 | Average current at most 19 µA: 5 years on one CR2 (850 mAh); 10 years needs 9.7 µA        |
| R-5 | Temperature and humidity as on 2026v4: SHT45 on `i2c21` with MCU pull-ups                |
| R-6 | Board 17.0 × 19.5 mm standing on the end of a CR2 (Ø15.6 max) lying on its side          |
| R-7 | SWD through a soldered 2×5 1.27 mm header or a pogo-pin clip from the side               |
| R-8 | Front parts in one reflow pass; the back has only pads and the optional J1               |

## 4. Design trades

### 4.1 Leak front end

2026v4 drives one contact from P0.01 through 10 kΩ and senses the other on P1.07 through
10 kΩ, with 1 MΩ to ground. While dry the drive is held high, so no current flows and a
rising edge on the sense pin wakes the board; once wet the firmware parks the drive low.
Current always flows the same way, which polarizes the contacts and corrodes the anode:
conductivity cells are driven with alternating polarity for this reason (Lee and Kester,
Analog Dialogue 50-11).

2026v5 makes both sides identical, so either can drive and either can sense:

- **1 MΩ returned to a GPIO, not ground.** While armed, the driving side's 1 MΩ would
  otherwise sit across the cell and draw 3 µA, 15 % of R-4. With its return pin at the
  same level as the drive it draws nothing.
- **Two return pins, not one.** One shared return cannot sit high for the driving side and
  low for the sensing side at the same time.
- **Not the internal pull-down.** At the nRF54L15's 13 kΩ typical (Ezurio datasheet, I2C
  note) the sense node could never reach the input-high level through 20 kΩ of series
  resistance.
- **Both sense pins analog-capable** (AIN3, AIN0), since each side senses in one direction.

Reversing the drive is standard practice for conductivity cells. This particular wake and
reversal scheme has not been checked against patents; do a freedom-to-operate check before
selling it.

### 4.2 Debug connector

2026v4's J1 is a CNC Tech 3220-10-0300-00 box header: 12.7 × 5.05 mm and 4.9 mm tall
(measured from its 3D model in `Components/`). Fitted on 2026v5's back, it would hold the
cell at least 5 mm behind the board.

2026v5 has pads that take either that header or a pogo-pin clip clamped on from the right
edge. The first few boards get a header; the rest are flashed with the clip, and the case
is sized for boards without J1. KiCad's stock 2×5 1.27 mm SMD land pattern (pads from 0.75
to 3.15 mm off center) would miss a clip whose two rows are 1.27 mm apart, as its pins
land 0.635 mm off center. J1's pads run from 0.3 mm off center (the odd ones to 2.6 mm,
the even ones to 3.15 mm), so they catch rows 1.27 or 2.54 mm apart as well as the
header's tails (`Components/LeakSensor.pretty`). The back gets no paste: J1 is soldered by
hand.

### 4.3 Supply

As on 2026v4, the CR2 feeds everything directly: the module takes 1.7 to 3.6 V (Ezurio
datasheet, schematic checklist) and the SHT45 1.08 to 3.6 V. The firmware reads the cell
through the SAADC's VDD input, as before. There is no reverse-polarity protection; the
wires are soldered once.

## 5. Circuit

### 5.1 Leak front end: P1, P2, D1, D2, R1–R4

```
P1 ── ELEC_A ──┬── R1 10 kΩ ── LEAK_A (P1.07, AIN3) ── R3 1 MΩ ── LEAK_A_RET (P1.05)
               D1 TPD1E10B06 to GND
P2 ── ELEC_B ──┬── R2 10 kΩ ── LEAK_B (P1.04, AIN0) ── R4 1 MΩ ── LEAK_B_RET (P1.14)
               D2 TPD1E10B06 to GND
```

| State (A to B; B to A swaps the sides) | LEAK_A   | LEAK_A_RET | LEAK_B             | LEAK_B_RET | Current while dry |
| -------------------------------------- | -------- | ---------- | ------------------ | ---------- | ----------------- |
| Armed                                  | out high | out high   | input, edge wake   | out low    | none              |
| Measure                                | out high | out high   | SAADC              | out low    | none              |
| Parked (after water is found)          | out low  | out low    | out low            | out low    | none              |

- **Wake threshold.** The sensing node sits at VDD × R4 / (R4 + R1 + R2 + R_water), which
  does not depend on the cell voltage. With V_IH = 0.7 VDD (to be confirmed in the nRF54L15
  datasheet) the edge fires below about 0.41 MΩ between the contacts.
- **SAADC.** The same divider reads 0.27 V at 10 MΩ, so damp contacts well above the wake
  threshold are still seen, as on 2026v4 (40 µs acquisition for the 1 MΩ source,
  `CONFIG_APP_LEAK_THRESHOLD_MV`). Averaging the two directions cancels the contacts'
  polarization offset.
- While armed and wet, at most VDD / 1.02 MΩ ≈ 3 µA flows one way until firmware parks the
  pins, as 2026v4 does.
- R1 and R2 limit current into the pins and D1 and D2 clamp ESD at the contacts, as on
  2026v4.

### 5.2 MCU module: Ezurio 453-00223R (IC1)

| Pad    | nRF54L15      | Net        | Use                                        |
| ------ | ------------- | ---------- | ------------------------------------------ |
| 5      | VDD           | VDD        | C2 10 µF, the one capacitor Ezurio requires (5.1) |
| 8      | P1.07 / AIN3  | LEAK_A     | Contact A: drive, edge wake, SAADC         |
| 17     | P1.04 / AIN0  | LEAK_B     | Contact B                                  |
| 15     | P1.05         | LEAK_A_RET | R3's return                                |
| 18     | P1.14         | LEAK_B_RET | R4's return                                |
| 21, 19 | P1.10, P1.12  | SDA, SCL   | U1 (firmware `i2c21`), internal pull-ups   |
| 12, 10 | P1.00, P1.01  | XL1, XL2   | X1, 32.768 kHz, internal load capacitors   |
| 27, 25 | SWDIO, SWDCLK | –          | J1 2, 4                                    |
| 32     | nRESET        | –          | J1 10                                      |
| 42     | P2.07         | SWO        | J1 6                                       |

- The AIN numbers are from the Ezurio pin table; 2026v4 confirmed P1.07 = AIN3 on
  hardware. All four leak pins are on port 1, like 2026v4's sense pin; the 2026v4
  overlay's gpio0 (drive) and gpio2 (buzzer) nodes go.
- Pins chosen for routing (5.6). Both contacts' 1 MΩ resistors stand in the middle of
  the board under the module's bottom-right corner, so RET_A (pad 15), LEAK_B (pad 17)
  and RET_B (pad 18) leave that corner in the order the parts need, and LEAK_A reaches
  its node on the back through pad 8's fan-out via. Pad 17 was SCL, so SCL moves to
  P1.12 (pad 19), also a clock pin. SDA moves to P1.10 (pad 21), just above SCL, so the
  two reach U1's pads without crossing (U1's pin order is fixed: SDA must arrive on the
  left-hand side). P1.06 and P1.08 are now unused. Firmware only sees this in the new
  board revision's overlay (`i2c21` pinctrl, leak node pins and SAADC channels).
- All other pins are open. The module's DC/DC inductor is inside.

### 5.3 Temperature and humidity: SHT45-AD1F (U1)

Unchanged from 2026v4: address 0x44, C1 100 nF beside it, I2C through the module's 13 kΩ
pull-ups. Idle current 0.08 µA typical (SHT4x datasheet, table 4).

### 5.4 SWD pads (J1)

The Arm 10-pin Cortex debug pinout, as 2026v4: 1 VDD, 2 SWDIO, 3, 5 and 9 GND, 4 SWDCLK,
6 SWO, 10 nRESET; 7 and 8 have pads but no connection. Land pattern in 4.2.

### 5.5 Battery and test pads

- BT1: CR2 on wires, two 2 mm pads on the back, BAT+ (VDD) and BAT− (GND).
- TP1 SDA and TP2 SCL on the front, on their traces, labeled with the signal names; TP3
  LEAK_A and TP4 LEAK_B on the back, labeled TP3 and TP4 (the names don't fit there);
  1.0 mm pads. VDD and GND are at BT1 and J1.

### 5.6 PCB layout

Coordinates in mm, origin on the cell's axis, +y up, seen from the front (KiCad X = 100 + x,
Y = 100 − y; grid origin on the cell's axis). Placed and routed 2026-11-21; silkscreen not tidied yet.

- **Outline**: x ±8.5; flat top at y 11 with R1.5 corners; straight sides down to y 0;
  an R8.5 semicircle below, centered on the cell axis. Two layers, 1.6 mm. The cell
  (Ø15.6) lies behind the board.
- **Rules** (`BL54L15μ_LeakSensor.kicad_dru`): copper at least 0.381 mm from the edge, as
  on the USB CO2 board; C2 may sit inside IC1's and X1's courtyards (below).

| Part             | Side  | Position                       | Note                                            |
| ---------------- | ----- | ------------------------------ | ----------------------------------------------- |
| IC1              | front | x −7.15..−0.85, y 2.92..10.82  | top left, antenna end up, 0.18 mm from the top edge |
| Antenna keep-out | all   | x −6.5..−1.5, y 7.82..10.82    | 3 × 5 mm, the module footprint's own rule area  |
| U1, C1           | front | (5.8, 8.6), (7.6, 8.6) upright | top right; U1's SDA and SCL pads face IC1       |
| X1               | front | (−3.675, 1.6)                  | just under IC1, centered on XL2 and XL1 (pads 10, 12) |
| C2               | front | (−6.1, 1.6) upright            | just left of X1, pad 1 (VDD) at the top         |
| D1, R1, R3       | front | (−3.85, −1.45), (−1.9, −1.45), (−0.9, 0.05) upright | contact A, the mirror of contact B about the center line |
| D2, R2, R4       | front | (3.85, −1.45), (1.9, −1.45), (0.9, 0.05) upright | contact B: D2 over P2, R2 toward the center, R4 up toward pads 15 and 17 |
| P1, P2           | front | (±3.85, −4.8), turned ∓36°     | 7.7 mm apart                                    |
| TP1, TP2         | front | (3.45, 9.0), (1.5, 6.47)       | on the SDA and SCL traces                       |
| J1               | back  | center (4.96, 3.5)             | right edge, odd column outboard, pin 1 at the top |
| TP3, TP4         | back  | (−4.75, 3.2), (0.0, −1.05)     | on LEAK_A's back trace and LEAK_B's via         |
| BT1              | back  | + (0.25, −3.6), − (−2.25, −3.6)| clear of the domes' through-hole feet           |

- **Module at the top left**, mirrored from the sketch. The module's SDA, SCL, SWDIO and
  SWDCLK pads are on one side; turned toward the open middle of the board, I2C runs on the
  front straight to U1 with no vias and SWD reaches J1 in about 5 mm on the back. At the
  top right those pads faced the edge, where one track fits beside them, and I2C and SWD
  would have crossed under the module.
- **Module end.** As close to the edge as the module's end ground pads allow: their
  copper ends 0.2 mm from the module's end, so the 0.381 mm edge rule puts the module
  0.18 mm in from the top edge (the DevKit uses 0.23 mm). The keep-out's lower edge is
  then at y 7.82, just above the cell's outline (radius 7.8).
- **J1 and the clip.** J1 sits at the right edge, not behind the module: the module's
  under-body vias would land in its pads. The odd pads (outboard: VDD, ground, key) end
  0.55 mm short of the even ones, so the back ground pour runs between them and the edge
  and reaches pins 3, 5 and 9; nRESET comes down the gap between the columns to pin 10.
  The pogo pins land 0.64 or 1.27 mm either side of J1's center line. The front opposite
  carries no parts, only traces and TP2, so the clip's other jaw lands flat. A fitted box
  header spans y −2.85 to 9.85 and stays inside the outline.
- **X1 and C2 under the module.** X1's pads sit 0.62 mm below the module's bottom row and
  C2 stands just left of X1, 0.2 mm off its pad; VDD runs diagonally from pad 5 onto C2's
  top pad. Both lie inside the module's courtyard (which reaches 1 mm past its body) and
  each other's; a custom rule allows exactly those overlaps.
- **Domes.** The 4 mm dome footprint (`MetalDomeSwitch:TriangleDome_Diameter4mm`) has
  its two feet 2 mm either side of center. Unrotated at (±3.85, −4.8), the outer foot
  lands outside the board; turned 36° so the feet run along the edge, both foot pads stay
  at least 0.5 mm inside. The center pad is tied to both feet. The feet are plated slots
  0.254 mm wide, under OSH Park's 0.508 mm minimum for drilled slots; 2026v4's 6 mm domes
  had the same slots.
- **Fan-out.** The vias under the module for XL1, XL2, nRESET, SWO and ground are
  2026v4's, copied in the module's frame. Pad 8's via (LEAK_A) moved 0.4 mm into the
  module's open middle so that pad 4, a ground pad boxed in by signal pads, can reach a
  via of its own, as on the USB CO2 board.
- **Routing.** Front: RET_A, LEAK_B and RET_B straight down from the module's
  bottom-right corner to the two front ends, I2C, VDD from pad 5 to C2 and from the right
  edge to U1 and C1, the dome ties. Back: SWD to J1, XL1/XL2 from the module's vias to
  vias under X1's body, LEAK_A from pad 8 down through TP3 and under X1 to its node, and
  VDD from C2's via down the left edge to BT1 and across to the right edge. Tracks
  0.15 mm, power 0.3 mm.
- **Ground.** Pours on both layers outside the keep-out, 0.1524 mm clearance as on
  2026v4, thermal reliefs on through-hole pads only. Stitching vias around the edge; none
  under a dome or J1.

## 6. Bill of materials

| Ref     | Value                   | Part                                    | Footprint            | Description                          |
| ------- | ----------------------- | --------------------------------------- | -------------------- | ------------------------------------ |
| IC1     | BL54L15μ                | Ezurio 453-00223R                       | module               | nRF54L15 module, chip antenna (5.2)  |
| U1      | SHT45                   | SHT45-AD1F-R2                           | DFN-4 1.5 mm         | Temperature and humidity (5.3)       |
| X1      | 32.768 kHz, 9 pF        | CM7V-T1A-LOW-ESR-32.768KHZ-9PF-20-TA-QC | 3.2 × 1.5 mm         | Low-frequency crystal                |
| C1      | 100 nF                  | GRM155R61A104KA01J                      | 0402                 | U1 decoupling                        |
| C2      | 10 µF                   | CL10A106KP8NNNC                         | 0603                 | Module supply                        |
| D1, D2  | TVS                     | TPD1E10B06DPYR                          | 0402                 | ESD clamp at the contacts (5.1)      |
| R1, R2  | 10 kΩ                   | RC0402FR-0710KL                         | 0402                 | Contact series resistors (5.1)       |
| R3, R4  | 1 MΩ                    | RC0402FR-071ML                          | 0402                 | Sense pull-downs to GPIO (5.1)       |
| P1, P2  | 4 mm metal dome         | to be chosen                            | TriangleDome 4 mm    | Leak contacts (5.6)                  |
| J1      | 2×5 1.27 mm, optional   | CNC Tech 3220-10-0300-00                | custom pads (4.2)    | SWD; hand-soldered on a few boards   |
| BT1     | CR2 on wires            | –                                       | two 2 mm pads        | Cell (5.5)                           |
| TP1–TP4 | Test pad                | –                                       | 1.0 mm pad           | SDA, SCL, LEAK_A, LEAK_B             |

## 7. Verification

Not started. Planned:

| Test                                                                       | Checks   | Pass                                           |
| -------------------------------------------------------------------------- | -------- | ---------------------------------------------- |
| Sleep current, leak armed, then parked                                     | R-3, R-4 | no measurable difference                       |
| Resistance box across P1–P2, both directions: largest value that wakes     | R-1      | about 0.4 MΩ; record it                        |
| SAADC reading at 10 kΩ, 100 kΩ, 1 MΩ and 10 MΩ, both directions            | R-2      | within 10 % of the divider, both ways          |
| Tap water across the contacts                                              | R-1, R-3 | report within a second, pins parked after      |
| Average current on Thread over 24 h                                        | R-4      | at most 19 µA                                  |
| RSSI with and without a CR2 behind the antenna (first on a 2026v4 board)   | 8        | record the difference                          |
| Flash through a soldered header, then through the pogo clip                | R-7      | both work                                      |
| SHT45 against a reference thermometer                                      | R-5      | within 0.5 °C                                  |

## 8. Known limitations and open questions

- **Antenna.** The module sits on the top edge right of center, where the datasheet prefers
  edge center (sections 5.2, 5.3.1, 6.2). The cell is metal within 20 mm, which the
  datasheet says "will begin to significantly degrade performance" (5.3.2). The RSSI test
  in section 7 decides whether this layout holds.
- **Battery life** is a target, not an estimate: the module idles at 3 µA (Ezurio
  datasheet, section 2.1) and the SHT45 at 0.08 µA, which leaves about 16 µA for Thread
  polling and reports. A 2026v4 current measurement comes first.
- **Input threshold.** V_IH and any input hysteresis are to be read from the nRF54L15
  datasheet. A slowly wetting contact holds the sense node near the threshold, so the
  firmware should debounce the edge, as for 2026v4.
- **Contacts.** The 4 mm dome part and how the case brings the domes to the floor are not
  chosen.
- **Pogo clip.** J1's pads accept rows 1.27 or 2.54 mm apart; check against the clip used.
- **Firmware.** New board revision, a leak driver for four pins and both directions, and
  the buzzer node removed. Whether the board keeps the name `bl54l15u_hygrometer` is open;
  2026v5 was also the name of the battery CO2 hygrometer in PR 23, closed and never built.
- **Case.** Not started; sized for boards without J1.

## 9. References

- [Ezurio BL54L15µ datasheet](https://www.ezurio.com/documentation/datasheet-bl54l15u),
  version 0.6, 18 March 2025: section 2.1 (System ON idle 3 µA), the pin table (AIN
  mapping), the schematic checklist (13 kΩ pull-ups), sections 5.1 (one mandatory 10 µF),
  5.2, 5.3.1, 5.3.2 and 6.2.
- [Sensirion SHT4x datasheet](https://sensirion.com/resource/datasheet/sht4x), version
  7.3, June 2026: table 4 (supply range, idle current).
- Nordic Semiconductor nRF54L15 datasheet: GPIO electrical specification, to be read for
  V_IH (5.1, 8).
- R. Lee and W. Kester,
  [Fully Automatic Self-Calibrated Conductivity Measurement System](https://www.analog.com/en/resources/analog-dialogue/articles/fully-automatic-self-calibrated-conductivity-measurement-system.html),
  Analog Dialogue 50-11, November 2016: DC on conductivity electrodes causes polarization
  and electrode damage; AC excitation with no DC offset (4.1).
- Panasonic CR2 datasheet: Ø15.6 mm maximum, 850 mAh (R-4, R-6), as given in the design
  notes; not re-read.
- OSH Park's [two-layer service rules](https://docs.oshpark.com/services/two-layer/) and
  [board outline](https://docs.oshpark.com/submitting-orders/board-outline/) page: edge
  clearance (5.6).
- `HW/BL54L15μ_USB_CO2` and `HW/BL54L15μ_DevKit` in this repository: the edge rule, the
  stitching grid and the module's distance from the edge (5.6).
