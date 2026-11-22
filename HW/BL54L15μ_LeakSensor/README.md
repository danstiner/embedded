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
| Size          | 48 mm square                                    | 15.6 × 15.6 mm, stands on the end of the cell (5.6)      |
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
| R-6 | Board 15.6 × 15.6 mm standing on the end of a CR2 (Ø15.6 max) lying on its side          |
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

No thermal isolation: the board averages about 0.06 mW (R-4). The USB CO2 board's thermal
model put its SHT4x about 1 °C above ambient at 37 mW, roughly 0.03 °C per mW; scaled, this
board warms U1 by a few thousandths of a degree, and radio bursts of a few milliseconds
average out in the board's heat capacity. What matters is how freely room air reaches U1:
the case's vent goes at the top right corner, beside it.

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
Y = 100 − y; grid origin on the cell's axis). Placed, routed and silkscreened 2026-11-21;
shortened from 19.5 to 16.0 mm the same day. Laid out again at 15.6 × 15.6 mm on
2026-11-22, with the leak front end moved from a row above the domes to two columns under
the module's corner, so the case is no taller or wider than the cell needs (5.7).

- **Outline**: 15.6 × 15.6 mm, x ±7.8, y ±7.8, centered on the cell's axis: the cell's
  diameter. Top corners R0.3, so the module's corner ground pad keeps the edge rule. The
  bottom is flat for 3 mm between R6.3 corners, the proportions of R7 on the 17 mm board
  (chosen over R4.5 to R8 and an R30 arc). Two layers, 1.6 mm. The cell (Ø15.6) lies
  behind the board.
- **Rules** (`BL54L15μ_LeakSensor.kicad_dru`): copper at least 0.381 mm from the edge, as
  on the USB CO2 board; courtyard overlaps allowed only where described below: X1 and C2
  inside IC1's, the leak front end inside IC1's and X1's, the domes' over the diodes, X1
  and C2, and a fitted J1 header's over TP4 and BT1.

| Part             | Side  | Position                       | Note                                            |
| ---------------- | ----- | ------------------------------ | ----------------------------------------------- |
| IC1              | front | x −6.9..−0.6, y −0.28..7.62    | top left, antenna end up, 0.18 mm from the top edge, 0.9 mm from the left |
| Antenna keep-out | all   | x −6.25..−1.25, y 4.62..7.62   | 3 × 5 mm, the module footprint's own rule area; on the back, out to the left edge |
| U1, C1           | front | (5.32, 5.4), (7.09, 5.4) upright | top right; U1's SDA and SCL pads face IC1     |
| X1               | front | (−3.425, −1.45)                | just under IC1, centered on XL2 and XL1 (pads 10, 12) |
| C2               | front | (−5.85, −1.6) upright          | just left of X1, pad 1 (VDD) at the top         |
| R3, R1, D1       | front | x −0.35, y −1.2, −3.06, −4.92, upright | contact A's column, top to bottom       |
| R4, R2, D2       | front | x 0.85, y −1.2, −3.06, −4.92, upright  | contact B's column, beside A's           |
| P1, P2           | front | (±3.6, −5.31), turned 180° ∓ 28.5° | 7.2 mm apart, feet below center along the bottom corners |
| TP1, TP2         | front | (3.0, 5.8), (1.75, 3.27)       | on the SDA and SCL traces                       |
| J1               | back  | center (4.45, 0.8)             | right edge, odd column outboard, pin 1 at the top |
| TP3, TP4         | back  | (−4.5, 0.0), (0.25, 0.12)      | on LEAK_A's back trace and LEAK_B's via         |
| BT1              | back  | + (0, −3.8), − (0, −6.3)       | between the domes' inner feet                   |

- **Module at the top left, chip antenna toward the corner.** The chip antenna sits in
  the corner of the module's antenna end on pin 1's side, by ground pad G3 (datasheet
  figure 10; Ezurio's product render and a photo of their development kit agree), which
  is the module's top left here. The end is as close to the top edge as its end ground
  pads allow: their copper ends 0.2 mm from the module's end, so the 0.381 mm edge rule
  puts the module 0.18 mm in (the DevKit uses 0.23 mm). The side is 0.9 mm from the left
  edge, the least that lets the front pour pass the module's left pad column and reach
  ground pad 39 (0.381 edge rule, 0.16 pour neck, 0.1524 clearance, pads 0.2 mm inside
  the body); in the corner itself, pad 39 had no connection. The chip antenna is then
  1.4 mm from the left edge and 0.4 mm from the top, and seen from the front it sits
  about 1.2 mm outside the cell's outline. The back pour stays out of the strip between
  the keep-out and the left edge.
- **Module mirrored from the sketch.** The module's SDA, SCL, SWDIO and SWDCLK pads are
  on one side; turned toward the open middle of the board, I2C runs on the front straight
  to U1 with no vias and SWD reaches J1 in about 3 mm on the back.
- **Leak front end in two columns.** Each contact's parts stand upright end to end under
  the module's bottom-right corner, in the chain's order: the 1 MΩ resistor at the top,
  then the 10 kΩ, then the TVS diode with its ground pad facing down. The columns are
  1.2 mm apart, so the same values sit side by side for hand assembly. Pads that meet
  share a net, so each column's links are 0.3 mm stubs. RET_A comes down from pad 15
  into R3; RET_B leaves pad 18 and drops into R4; LEAK_B leaves pad 17 through TP4's via
  and runs down the 0.56 mm gap between the columns to R4 and R2; LEAK_A comes up from
  the back through a via below X1. ELEC_A and ELEC_B branch from the resistor-diode
  joints to the domes' center pads, so each diode is about 3 mm from its dome. The
  columns sit 0.25 mm right of the axis so that R3's and R1's references fit between
  column A and X1. D1's and D2's ground pads share a via straight into BT1−'s pad on
  the back. With no row above the domes, only the outline limits how low they sit.
- **Domes.** The 4 mm dome footprint (`MetalDomeSwitch:TriangleDome_Diameter4mm`) has its
  two feet 2 mm either side of center, 0.4 mm off it. Turned 180°, the feet are below
  center; each dome is tilted 28.5° so its feet follow the bottom corners, and sits as
  low as its outline silk and its feet's pour passages allow: the feet's copper is 0.4
  to 0.55 mm from the edge, where the pour stops cleanly rather than leaving a neck. The
  domes are 7.2 mm apart, the closest that keeps the inner feet clear of BT1's pads;
  closer domes sit lower in round corners, and the water's resistance between the pins
  hardly depends on their spacing (it grows with its logarithm). The center pad is tied
  to both feet. The feet are plated slots
  0.254 mm wide, under OSH Park's 0.508 mm minimum for drilled slots; 2026v4's 6 mm domes
  had the same slots.
- **J1 and the clip.** J1 sits at the right edge, not behind the module: the module's
  under-body vias would land in its pads. The odd pads (outboard: VDD, ground, key) end
  0.55 mm short of the even ones, so the back ground pour runs between them and the edge
  and reaches pins 3, 5 and 9; nRESET passes over J1, just under the antenna keep-out, and
  comes down the gap between the columns to pin 10, which is why J1 cannot move up. The
  pogo pins land 0.64 or 1.27 mm either side of J1's center line. The front opposite
  carries no parts, only traces, TP2 and the pour, so the clip's other jaw lands flat. A
  fitted box header spans y −5.55 to 7.15: on those few boards it covers TP4 and P2's
  outer foot, and its corner hangs about 0.5 mm past the board's bottom-right corner.
- **X1 and C2 under the module.** X1's pads sit 0.47 mm below the module's bottom row
  and C2 stands just left of X1, 0.2 mm off its pad; VDD runs diagonally from pad 5 onto
  C2's top pad and on to a via left of C2. Both lie inside the module's courtyard (which
  reaches 1 mm past its body) and each other's; a custom rule allows exactly those
  overlaps.
- **Fan-out.** The vias under the module for XL1, XL2, nRESET, SWO and ground are
  2026v4's, copied in the module's frame. Pad 8's via (LEAK_A) moved 0.4 mm into the
  module's open middle so that pad 4, a ground pad boxed in by signal pads, can reach a
  via of its own, as on the USB CO2 board.
- **Routing.** Front: RET_A, LEAK_B and RET_B from the module's bottom-right corner to
  the columns, I2C, VDD from pad 5 to C2 and from the right edge to U1 and C1, the dome
  ties. Back: SWD to J1, XL1/XL2 from the module's vias to vias under X1's body, LEAK_A
  from pad 8 down through TP3 and under X1 to its via, and VDD from C2's via down the left
  edge, under LEAK_A's via, through BT1+ and across to the right edge, above the domes'
  outer feet. Tracks 0.15 mm, power 0.3 mm.
- **Silkscreen.** References at 0.75 mm (the board minimum) beside their parts: X1's
  under it, the resistors' upright beside their columns, the diodes' below them, P1's and
  P2's above the domes' outer feet. The front test pads
  are labeled by signal name, BT1 has its + and −, and the back carries "Leak Sensor",
  `${REVISION}` and `${COMPANY}` from the board's literal title block. The back title and
  BT1's label sit where a fitted J1 box header goes, so they are partly hidden on the
  boards that get a header.
- **Ground.** Pours on both layers outside the keep-out, 0.1524 mm clearance as on
  2026v4. Thermal reliefs on the front only for through-hole pads (it is reflowed); on
  the back for every pad, so J1, BT1's wires and the test pads can be hand-soldered.
  Stitching vias where the domes, J1, BT1 and the back title leave room.

### 5.7 Case

`Case/build_case.py` builds the case in FreeCAD from the parameters at its top and saves
`Case/LeakSensor_2026v5.FCStd`. The file also holds the board (KiCad's STEP export), the
cell, the battery contacts and the leak pins as reference parts, and the script checks all
of them against each other. The case is an open-top body with a snap-on lid,
18.9 × 44.9 × 18.05 mm. The board stands across the front with the cell lying behind it.
Board and cell are both 15.6 mm: the width adds 0.15 mm clearance and a 1.5 mm wall each
side, the height a 1.0 mm floor, a 1.2 mm lid and the slot's 0.1 mm under the board and
0.15 mm over it.

- **Board slot.** 0.4 mm lips front and back along the board's sides and bottom; the
  board drops in from the top and rests 0.1 mm above the floor. The side lips stop 0.5 mm
  below the board's top, under the module's end. The domes push the board back, so its
  front face is the datum: two crush ribs behind the straight sides, 0.1 mm into a 1.6 mm
  board, hold it against the front lip. The dome press then depends on two faces of one
  print, not on the board's thickness or the slot's fit.
- **Leak pins.** Ø2.5 × 6 mm metal pins stand upright at x ±3.6, just in front of the
  domes. Each is pushed up from below into a blind bore in the front wall and stands
  0.2 mm proud of the bottom, so the case rests on the pins and a film of water reaches
  them first. The side of each pin presses its dome's apex: the pin surface is 0.2 mm off
  the board and the dome is assumed 0.3 mm high, a 0.1 mm press (`DomeApex`, `PinPress`).
  The bore opens toward the dome through a 2.0 mm gap, narrower than the pin, and the
  bore's wall stops 0.7 mm short of the board, over the domes. The pin top is 2.2 mm
  above the dome center and 0.9 mm below X1; the bore's 0.6 mm cap keeps the left boss's
  top under C2, which overhangs it.
- **Cell.** Keystone 209 leaf spring (−) on a 1.6 mm divider behind the board, 228 button
  (+) on a 1.6 mm rear panel; both clip onto 1.52–1.78 mm panels and are listed for CR2.
  The 209 is assumed compressed to 2.5 mm between the divider and the cell. Two saddles
  under the cell; the lid's underside, 0.15 mm over it, keeps it down.
- **Wiring.** BT1's pads face the divider across a 2.0 mm gap, where the 209's tab is.
  The 228's tab sits in a 2.0 mm pocket behind the rear panel; its wire runs forward along
  the bay's lower left corner, beside the cell, through 1.2 mm notches in both panels and
  the saddles.
- **Vents.** Four 0.8 mm slots in the front wall in front of U1, and four in the lid over
  the gap in front of the board, so air passes U1 (5.3).
- **Lid.** 1.2 mm, with a 0.8 mm rim inside the walls and four 0.5 mm nubs into dimples
  in the body; the rim stops short of the board.
- **Checks.** No overlap between the body, lid, board and its parts, cell, contacts and
  pins. The board drops in from 25 mm above without touching anything but the ribs.
  J1's header model is left out: a board with a header does not fit.

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

3D models: U1 uses Sensirion's (`Components/SHT45_AD1F_R2`, with the download's license, as
on the USB CO2 board); KiCad ships none for its SHT4x footprint. D1 and D2 use KiCad's 0402
resistor model as a stand-in: KiCad has no 0402 diode model, and TI's X1SON (DPY) body is
the same 1.0 × 0.6 mm.

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

- **Antenna.** The module sits at the top left with its chip antenna toward the corner,
  where the datasheet prefers edge center (sections 5.2, 5.3.1, 6.2). The board is no
  taller or wider than the cell, so the antenna end is in front of the cell's top, with
  only the antenna's corner clear of its outline (the chip about 1.2 mm outside it,
  0.6 mm closer than on the 17 mm board), and the 209 contact is behind the board. Metal
  within 20 mm "will begin to significantly degrade performance" (5.3.2). The 19.5 mm
  board kept the keep-out above the cell; the lower case was chosen over it. The RSSI test
  in section 7 decides whether this layout holds.
- **Battery life** is a target, not an estimate: the module idles at 3 µA (Ezurio
  datasheet, section 2.1) and the SHT45 at 0.08 µA, which leaves about 16 µA for Thread
  polling and reports. A 2026v4 current measurement comes first.
- **Input threshold.** V_IH and any input hysteresis are to be read from the nRF54L15
  datasheet. A slowly wetting contact holds the sense node near the threshold, so the
  firmware should debounce the edge, as for 2026v4.
- **Dome press.** The 4 mm dome part is not chosen. A dome travels only a few tenths of a
  millimeter, so the case's 0.3 mm height and 0.1 mm press (5.7) need checking against
  the chosen part's drawing and a test print.
- **Pogo clip.** J1's pads accept rows 1.27 or 2.54 mm apart; check against the clip used.
- **Firmware.** New board revision, a leak driver for four pins and both directions, and
  the buzzer node removed. Whether the board keeps the name `bl54l15u_hygrometer` is open;
  2026v5 was also the name of the battery CO2 hygrometer in PR 23, closed and never built.
- **Case.** Unprinted. The 209's compressed length and both contacts' tab positions come
  from Keystone's catalog drawing, not parts in hand. Boards with J1 fitted do not fit.

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
- [Keystone Electronics battery contacts catalog](https://docs.rs-online.com/049f/0900766b813ebe31.pdf),
  page 12: snap-on contacts 209 and 228, their size, plate thickness and 1.52–1.78 mm
  panel range (5.7).
- OSH Park's [two-layer service rules](https://docs.oshpark.com/services/two-layer/) and
  [board outline](https://docs.oshpark.com/submitting-orders/board-outline/) page: edge
  clearance (5.6).
- `HW/BL54L15μ_USB_CO2` and `HW/BL54L15μ_DevKit` in this repository: the edge rule, the
  stitching grid and the module's distance from the edge (5.6).
