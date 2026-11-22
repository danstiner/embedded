# Leak sensor

## 1. Scope

A battery leak and humidity sensor built on the Ezurio BL54L15μ (nRF54L15) module. Two
contacts near the bottom detect water and wake the board at once; a buzzer can sound the
alarm on the spot; an SHT45 reports temperature and humidity. Firmware: `SW/hygrometer`
(Matter over Thread or BTHome).

This is revision **2026v5**, in design. The baseline is 2026v4, the first leak board,
fabricated as the hygrometer's 2026v4 (tag `fab/BL54L15μ-hygrometer/2026v4`, firmware
board `bl54l15u_hygrometer@2026v4`).

## 2. Changes from 2026v4

| Item          | 2026v4                                          | 2026v5                                                   |
| ------------- | ----------------------------------------------- | -------------------------------------------------------- |
| Size          | 48 mm square                                    | 20 × 18 mm, round bottom, stands on the end of the cell (5.6) |
| Battery       | CR2 in a Keystone 1011 holder                   | CR2 on wires, BAT+ and BAT− pads on the back             |
| Leak contacts | 6 mm domes on the back, driven one way          | 4 mm domes on the front, either way (4.1)                |
| Leak pins     | drive P0.01, sense P1.07, 1 MΩ to ground        | P1.07 and P1.04 each drive or sense; 1 MΩ to a GPIO      |
| I2C           | SDA P1.14, SCL P1.04                            | SDA P1.10, SCL P1.12 (5.2)                               |
| Buzzer        | BZ1, Q1, D3, R7 (never driven by firmware)      | CMT-5023S-SMT on the front over J1, on P1.11 (5.5)       |
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
| R-6 | Board 20 × 18 mm standing on the end of a CR2 (Ø15.6 max) lying on its side              |
| R-7 | SWD through a soldered 2×5 1.27 mm header or a pogo-pin clip from the side               |
| R-8 | Front parts in one reflow pass; the back has only pads and the optional J1               |
| R-9 | A buzzer the firmware can sound when it finds water                                     |

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

The odd pads reach the 0.381 mm edge rule, so the clip's outer row lands as close to the
edge as the copper allows; a fitted header's shroud overhangs the edge. BZ1 sits on the
front directly opposite J1, so the clip's other jaw rests on its flat 5 × 5 mm top and the
press is spread evenly. The clip needs more room around its pins than the board gives
(about 4 mm past the pin rows), but it presses lightly and tolerates an uneven bite, so no
keep-out is reserved for it.

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
| 23     | P1.11         | BUZZ       | Q1's gate: BZ1 at 4 kHz (5.5)              |
| 12, 10 | P1.00, P1.01  | XL1, XL2   | X1, 32.768 kHz, internal load capacitors   |
| 27, 25 | SWDIO, SWDCLK | –          | J1 2, 4                                    |
| 32     | nRESET        | –          | J1 10                                      |
| 42     | P2.07         | SWO        | J1 6                                       |

- The AIN numbers are from the Ezurio pin table; 2026v4 confirmed P1.07 = AIN3 on
  hardware. All four leak pins are on port 1, like 2026v4's sense pin; the 2026v4
  overlay's gpio0 (drive) node goes and the buzzer moves from gpio2 to P1.11.
- Pins chosen for routing (5.6). Both contacts' 1 MΩ resistors stand in the middle of
  the board under the module's bottom-right corner, so RET_A (pad 15), LEAK_B (pad 17)
  and RET_B (pad 18) leave that corner in the order the parts need, and LEAK_A reaches
  its node on the back through pad 8's fan-out via. Pad 17 was SCL, so SCL moves to
  P1.12 (pad 19), also a clock pin. SDA moves to P1.10 (pad 21), just above SCL, so the
  two reach U1's pads without crossing (U1's pin order is fixed: SDA must arrive on the
  left-hand side). P1.06 and P1.08 are now unused. BUZZ takes P1.11 (pad 23), just above
  SDA on the same column, and crosses under the I2C on the back. Firmware only sees this
  in the new board revision's overlay (`i2c21` pinctrl, leak node pins, SAADC channels
  and the buzzer's PWM pin).
- All other pins are open. The module's DC/DC inductor is inside.

### 5.3 Temperature and humidity: SHT45-AD1F (U1)

Unchanged from 2026v4: address 0x44, C1 100 nF beside it, I2C through the module's 13 kΩ
pull-ups. Idle current 0.08 µA typical (SHT4x datasheet, table 4).

No thermal isolation: the board averages about 0.06 mW (R-4). The USB CO2 board's thermal
model put its SHT4x about 1 °C above ambient at 37 mW, roughly 0.03 °C per mW; scaled, this
board warms U1 by a few thousandths of a degree, and radio bursts of a few milliseconds
average out in the board's heat capacity. What matters is how freely room air reaches U1.
The sensor watches for mold conditions, so approximate humidity is enough: the case has
one small vent in its right wall, just below U1 (5.7), and U1 follows the room slowly.

### 5.4 SWD pads (J1)

The Arm 10-pin Cortex debug pinout, as 2026v4: 1 VDD, 2 SWDIO, 3, 5 and 9 GND, 4 SWDCLK,
6 SWO, 10 nRESET; 7 and 8 have pads but no connection. Land pattern in 4.2.

### 5.5 Battery and buzzer: BT1, BZ1, Q1, D3, R7

BT1 is a CR2 on wires: two 2 mm pads on the back, BAT+ (VDD) and BAT− (GND). There are no
test pads; VDD and GND are at BT1 and J1, the signals at J1 and on the parts' pads.

```
VDD ──┬── BZ1 + ── BZ1 − ──┬── BUZZER− ── Q1 drain      Q1 DMG1012T, source to GND
      └──── D3 1N4148WT ───┘   (cathode to VDD)
BUZZ (P1.11) ──┬── Q1 gate
               └── R7 1 MΩ to GND
```

- **BZ1**, Same Sky CMT-5023S-SMT: a magnetic transducer, 5 × 5 × 2 mm, rated 3 V at
  4 kHz, 110 mA at most, 80 dB at 10 cm (datasheet). It has no oscillator of its own: the
  firmware drives P1.11 with a 4 kHz square wave. 110 mA is far beyond a GPIO's drive, so
  Q1 switches BZ1's low side.
- **Q1**, DMG1012T: 20 V, 0.63 A N-channel FET with an ESD-protected gate, in SOT-523.
- **D3**, 1N4148WT, clamps the coil's flyback when Q1 turns off.
- **R7** holds Q1 off while P1.11 floats (reset, or the pin left disconnected in sleep),
  so BZ1 stays silent. It draws current only while the buzzer sounds.
- The parts and the land pattern come from the datasheets' recommendations; BZ1's third
  terminal is mechanical and left unconnected.

### 5.6 PCB layout

Coordinates in mm, origin on the cell's axis, +y up, seen from the front (KiCad X = 100 + x,
Y = 100 − y; grid origin on the cell's axis). Placed, routed and silkscreened 2026-11-21,
then cut down to the cell's 15.6 mm by 2026-11-22. Laid out again the same day at
20 × 18 mm to take the buzzer, without test points and routed by hand.

- **Outline**: 20 × 18 mm, x ±10, y −7.85..10.15. Square top corners; the bottom is a
  semicircle, R10 about (0, 2.15), so the straight sides run from y 2.15 to the top. The
  cell (Ø15.6) lies behind the board on its axis: the board reaches 2.2 mm past it at each
  side and 2.35 mm above it. Narrower boards (18 and 19 mm) left no room for the buzzer
  in the top row, and an 18 × 16 mm board with a round bottom cannot take the domes,
  which need 16.4 mm of height. Two layers, 1.6 mm.
- **Rules** (`BL54L15μ_LeakSensor.kicad_dru`): copper at least 0.381 mm from the edge, as
  on the USB CO2 board; courtyard overlaps allowed only for X1 and C2 inside IC1's. A DRC
  exclusion covers J1's silk past the right edge (the header's shroud).

| Part             | Side  | Position                       | Note                                            |
| ---------------- | ----- | ------------------------------ | ----------------------------------------------- |
| IC1              | front | x −9.1..−2.8, y 2.07..9.97     | top left, antenna end up, 0.18 mm from the top edge, 0.9 mm from the left |
| Antenna keep-out | all   | x −8.45..−3.45, y 6.97..9.97   | 3 × 5 mm, the module footprint's own rule area; on the back, out to the left edge |
| U1, C1           | front | (7.87, 9.21), (8.82, 7.44)     | top right corner; U1's SDA and SCL pads face IC1 |
| X1               | front | (−5.625, 0.2)                  | 1.1 mm under IC1's body, centered on the XL1 and XL2 vias |
| C2               | front | (−8.74, 0.75) upright          | left of X1, pad 1 (VDD) at the top              |
| R3, R1, D1       | front | x −0.6, y 1.65, −0.21, −2.07, upright | contact A's column, top to bottom        |
| R4, R2, D2       | front | x 0.6, same y, upright         | contact B's column, beside A's                  |
| P1, P2           | front | (∓3.95, −4.85), turned 180° ∓ 24.5° | 7.9 mm apart, feet below center along the round bottom |
| BZ1              | front | (6.85, 4.1)                    | right edge, over J1; mounting terminal top left |
| D3, Q1, R7       | front | (5.8, 0.55), (8.2, −0.25) turned 90°, (6.58, −1.6) upright | under BZ1 |
| J1               | back  | center (6.97, 4.1)             | right edge, odd column outboard, pin 1 at the top |
| BT1              | back  | + (0, −3.9), − (0, −6.4)       | between the domes' inner feet                   |

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
  about 5.2 mm outside the cell's outline. BZ1 and J1 are at the right edge, away from it.
  The back pour stays out of the strip between the keep-out and the left edge.
- **Module mirrored from the sketch.** The module's SDA, SCL, SWDIO and SWDCLK pads are
  on one side; turned toward the open middle of the board, I2C runs on the front to U1
  with no vias, and SWD crosses to J1 on the back.
- **Leak front end in two columns.** Each contact's parts stand upright end to end below
  the module, in the chain's order: the 1 MΩ resistor at the top, then the 10 kΩ, then
  the TVS diode with its ground pad facing down. The columns are 1.2 mm apart about the
  axis, so the same values sit side by side for hand assembly, and stand high enough that
  D1 and D2 end level with the tops of the domes. Pads that meet share a net, so each
  column's links are short stubs. RET_A runs from pad 15 under pad 17 into R3; LEAK_B
  leaves pad 17 over R3 and runs down the gap between the columns to the R4–R2 joint;
  RET_B drops from pad 18 into R4; LEAK_A comes from pad 8's via along the back, round
  the outside of X1's fence, and up through a via into the R3–R1 joint. ELEC_A and ELEC_B
  leave the resistor-diode joints at 45° for the domes' center pads. D1's and D2's ground
  pads each get a via just outboard.
- **Domes.** The 4 mm dome footprint (`MetalDomeSwitch:TriangleDome_Diameter4mm`) has its
  two feet 2 mm either side of center, 0.4 mm off it. Turned 180°, the feet are below
  center; each dome is tilted 24.5° so its feet follow the round bottom, about 1.2 mm in
  from the edge. The domes are 7.9 mm apart, their inner feet clear of BT1's pads on the
  back; the water's resistance between the pins hardly depends on their spacing (it grows
  with its logarithm). The center pad is tied to both feet. The feet are plated slots
  0.254 mm wide, under OSH Park's 0.508 mm minimum for drilled slots; 2026v4's 6 mm domes
  had the same slots.
- **J1 and the clip.** J1 sits at the right edge, not behind the module: the module's
  under-body vias would land in its pads. Its outboard pads (odd: VDD, ground, key) reach
  the edge rule at pin 9's corner, where the round bottom begins (4.2). nRESET comes down
  the gap between J1's columns to pin 10, which cuts pins 3 and 5 off from the rest of the
  back pour; a via in pin 3 ties them to the front pour under BZ1. Pin 9 joins the main
  back pour. The pogo pins land 0.64 or 1.27 mm either side of J1's center line, and BZ1
  on the front opposite takes the clip's other jaw.
- **BZ1 and its driver.** BZ1 sits over J1 with its + pad at the bottom left, its − pad
  at the bottom right and its unconnected mounting terminal at the top left. VDD comes up
  from BT1+ through a via below the + pad, which also feeds D3's cathode. D3, Q1
  and R7 sit under BZ1, inside the round bottom: the − pad drops to Q1's drain, with D3's
  anode on the way. BUZZ leaves pad 23 on the front, crosses under the I2C on the back
  between two vias, and comes down to R7 and Q1's gate. Q1's source and R7's ground end
  share a ground via.
- **X1 and C2 under the module.** X1 sits about 1.1 mm below the module's body, centered
  between the XL1 and XL2 fan-out vias: each leg runs straight down the back to a via
  1.4 mm above X1, then a 0.2 mm front stub drops onto its pad, so the two legs match.
  Eight ground vias fence X1 on the left, right and bottom; the module and the crystal's
  vias close the top. C2 stands left of X1; VDD runs from pad 5 onto C2's top pad and on
  to a via left of C2. Both lie inside the module's courtyard (which reaches 1 mm past its
  body); a custom rule allows exactly that.
- **Fan-out.** The vias under the module for XL1, XL2, nRESET, SWO and ground are
  2026v4's, copied in the module's frame. Pad 8's via (LEAK_A) moved 0.4 mm into the
  module's open middle so that pad 4, a ground pad boxed in by signal pads, can reach a
  via of its own, as on the USB CO2 board.
- **Routing.** Front: RET_A, LEAK_B and RET_B from the module's bottom-right corner to
  the columns; I2C from pads 21 and 19 across the board's middle and up the left of BZ1
  into U1's left pads; VDD from pad 5 to C2, and from BZ1's + pad up under BZ1's middle
  to C1 and round U1's right side, clear of the keep-out under U1's body; the
  dome ties. Back: SWD and SWO to J1's inboard pads; nRESET just under and right of the
  antenna keep-out, across the top and down between J1's columns; XL1/XL2; LEAK_A round
  X1's fence; BUZZ under the I2C; VDD from C2's via down the left edge and across to BT1+,
  then from BT1+ up to the via below BZ1, with a via onto J1's pin 1. Tracks 0.15 mm,
  power 0.3 mm; 0.25 mm in the driver, 0.2 mm into U1 and C1, for the crystal stubs and
  the dome ties.
- **Silkscreen.** References at 0.75 mm (the board minimum) beside their parts: X1's on
  its body between its pads, the column parts' upright outboard of their columns, P1's and
  P2's above the domes' outer feet, BZ1's under the part (hidden once fitted). BT1 has its
  + and −, and the back carries "Leak Sensor", `${REVISION}` and `${COMPANY}` from the
  board's literal title block. J1's back outline is the header's shroud and runs past the
  right edge.
- **Ground.** Pours on both layers outside the keep-out, 0.1524 mm clearance as on
  2026v4. Thermal reliefs on the front only for through-hole pads (it is reflowed); on
  the back for every pad, so J1 and BT1's wires can be hand-soldered. 30 ground vias:
  X1's fence, the module's, the diodes', the driver's, J1's pin 3, and stitching placed
  farthest-first until every point of either pour is within 3 mm of a via, except over
  the domes, in the antenna corner, in U1's corner and under J1's pads.

### 5.7 Case

`Case/build_case.py` builds the case in FreeCAD from the parameters at its top and saves
`Case/LeakSensor_2026v5.FCStd`. The file also holds the board (KiCad's STEP export), the
cell, the battery contacts and the leak pins as reference parts, and the script checks all
of them against each other. The case is an open-top body with a half-dome rear end and a
lid that slides on from the rear, 24.7 × 50.25 × 20.45 mm. The board stands across the
front with the cell lying behind it. The board sets the width and height: its 20 mm plus 0.15 mm clearance and a
2.2 mm wall each side, its 18 mm plus a 1.0 mm floor, a 1.2 mm lid and the slot's 0.1 mm
under the board and 0.15 mm over it.

The bottom follows the board's: inside and out, it is an arc tangent to the sides, R10.15
inside (0.05 mm off the board's center) and R12.35 outside. Outside, the arc gives way to
straight lines where it would overhang more than 60° when printed, leaving a 6.6 mm flat
for the body to print upright on (`MaxOverhang`; 90 gives the full curve, which needs
supports). The rear end is a half dome: the same section turned about a vertical axis
1.0 mm in front of the cell's rear end, so the bowl clears the cell's rear edge by 0.1 mm
(the floor clears the cell by 0.15 mm) and the 228 contact. The bottom's front edge is rounded 2 mm, the top's edges
1 mm.

- **Board slot.** 0.4 mm lips front and back along the board's sides and bottom; the
  board drops in from the top and rests 0.1 mm above the floor. The side lips stop at
  y 7.3, 2.85 mm below the board's top. The domes push the board back, so its
  front face is the datum: two crush ribs behind the straight sides, 0.1 mm into a 1.6 mm
  board, hold it against the front lip. The dome press then depends on two faces of one
  print, not on the board's thickness or the slot's fit.
- **Leak pins.** Ø2.5 × 6 mm metal pins stand upright at x ±3.95, just in front of the
  domes. Each is pushed up from below into a blind bore in the front wall and stands
  0.2 mm proud of the bottom, so the case rests on the pins and a film of water reaches
  them first. The side of each pin presses its dome's apex: the pin surface is 0.2 mm off
  the board and the dome is assumed 0.3 mm high, a 0.1 mm press (`DomeApex`, `PinPress`).
  The bore opens toward the dome through a 2.0 mm gap, narrower than the pin, and the
  bore's wall stops 0.7 mm short of the board, over the domes. The pin top is 1.7 mm
  above the dome center, and the bosses clear X1, C2 and the diodes.
- **Cell.** Keystone 209 leaf spring (−) on a 1.6 mm divider behind the board, 228 button
  (+) on a 1.6 mm rear panel; both clip onto 1.52–1.78 mm panels and are listed for CR2.
  The 209 is assumed compressed to 2.5 mm between the divider and the cell. Two saddles
  under the cell, and two ribs under the lid over them, 0.1 mm off the cell: the board,
  not the cell, sets the bay's height, which leaves 2.5 mm above the cell.
- **Wiring.** BT1's pads face the divider across a 2.0 mm gap, where the 209's tab is.
  The 228's tab sits in the dome's bowl behind the rear panel; its wire runs forward over
  both panels in the bay's upper left corner, 1.55 mm in from the wall to clear the dome's
  curve, 2.8 mm clear of the cell and below the lid.
- **Vent.** One 1.0 × 2.0 mm slot in the right wall, into the gap between the front wall
  and the board, just under the seam and 2.3 mm below U1 (5.3). There is no other
  opening: BZ1 sounds through the closed case.
- **Lid.** A 1.2 mm plate that slides on from the rear, after the hygrometer 2026v3's
  case. The top 3.7 mm of each side wall is a 0.8 mm rail with a 45° ridge, 0.6 mm deep,
  facing out from its top 1.2 mm; the lid's skirts take the outer 1.4 mm of the wall and
  carry the matching groove, so the lid cannot lift. It rests on the rails' tops and stops
  against the front wall, which stands the full height. The lid also takes the dome's
  top, so the seam runs at one height all round, 4.9 mm below the top: just under the two
  ribs that hold the cell down (above), which slide out over the dome's rim.
- **Fits, as on 2026v3.** Faces that slide or bear are drawn line to line: the skirts on
  the rails' faces, the plate on the rails' tops, the skirts' feet on the walls' shoulders.
  Only the groove is cut larger than the ridge, 0.05 mm deeper and 0.1 mm taller, so its
  upper flank bears and its lower flank clears. The detent is 2026v3's too: a 60° bump,
  0.5 mm high, on each rail 5 mm behind the front wall, and in each skirt a notch 0.05 mm
  deeper behind a lead-in ramp, 0.8 mm deep at the lid's front end and running out over
  4 mm, so the bump rides the skirt only for the last few millimeters.
- **Checks.** No overlap between the body, lid, board and its parts, cell, contacts, pins
  and a Ø1.2 mm + wire. The board drops in from 25 mm above without touching anything but
  the ribs, and the lid slides out to the rear touching only where the bumps ride the
  ramps (the line-to-line faces touch without overlapping). J1's header model
  is left out: a board with a header does not fit. The script first checks that booleans
  against each part work at all: refined with `removeSplitter()`, the lid looked valid but
  every check against it came back empty.

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
| BZ1     | Buzzer, 3 V, 4 kHz      | Same Sky CMT-5023S-SMT-TR               | 5 × 5 mm, 3 pads     | Magnetic transducer (5.5)            |
| Q1      | DMG1012T                | DMG1012T-7                              | SOT-523              | Buzzer switch (5.5)                  |
| D3      | 1N4148WT                | 1N4148WT-7                              | SOD-523              | Flyback clamp across BZ1 (5.5)       |
| R7      | 1 MΩ                    | RC0402FR-071ML                          | 0402                 | Q1 gate pull-down (5.5)              |
| BT1     | CR2 on wires            | –                                       | two 2 mm pads        | Cell (5.5)                           |

3D models: U1 uses Sensirion's (`Components/SHT45_AD1F_R2`, with the download's license, as
on the USB CO2 board); KiCad ships none for its SHT4x footprint. D1 and D2 use KiCad's 0402
resistor model as a stand-in: KiCad has no 0402 diode model, and TI's X1SON (DPY) body is
the same 1.0 × 0.6 mm. BZ1 and Q1 have no model yet (KiCad ships none for SOT-523): to be
downloaded from DigiKey.

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
| Buzzer at 4 kHz in the closed case, on a partly used CR2                   | R-9      | audible across a room; no brown-out            |

## 8. Known limitations and open questions

- **Antenna.** The module sits at the top left with its chip antenna toward the corner,
  where the datasheet prefers edge center (sections 5.2, 5.3.1, 6.2). The board is wider
  and taller than the cell, so seen from the front the antenna keep-out lies outside the
  cell's outline (its inner corner just touches it) and the chip is about 5.2 mm outside
  it. The cell is still within a few millimeters behind, and the 209 contact is behind the
  board. Metal within 20 mm "will begin to significantly degrade performance" (5.3.2);
  BZ1, a coil and magnet, is about 13 mm from the chip at its nearest corner. The RSSI
  test in section 7 decides whether this layout holds.
- **Battery life** is a target, not an estimate: the module idles at 3 µA (Ezurio
  datasheet, section 2.1) and the SHT45 at 0.08 µA, which leaves about 16 µA for Thread
  polling and reports. A 2026v4 current measurement comes first.
- **Input threshold.** V_IH and any input hysteresis are to be read from the nRF54L15
  datasheet. A slowly wetting contact holds the sense node near the threshold, so the
  firmware should debounce the edge, as for 2026v4.
- **Dome press.** The 4 mm dome part is not chosen. A dome travels only a few tenths of a
  millimeter, so the case's 0.3 mm height and 0.1 mm press (5.7) need checking against
  the chosen part's drawing and a test print.
- **Pogo clip.** J1's pads accept rows 1.27 or 2.54 mm apart; check against the clip used,
  and that BZ1 takes its other jaw.
- **Buzzer.** BZ1's land pattern, Q1 and D3 come from datasheets, not parts in hand. BZ1
  draws up to 110 mA from the CR2: check that the cell's sag on a cold, partly used cell
  keeps the module above 1.7 V, or limit the alarm's duty.
- **Firmware.** New board revision, a leak driver for four pins and both directions, and
  the buzzer moved to P1.11 as a 4 kHz PWM. Whether the board keeps the name
  `bl54l15u_hygrometer` is open; 2026v5 was also the name of the battery CO2 hygrometer in
  PR 23, closed and never built.
- **Case.** Unprinted. The 209's compressed length and both contacts' tab positions come
  from Keystone's catalog drawing, not parts in hand. Boards with J1 fitted do not fit.
  The lid's line-to-line slide fit and its detent need a test print; how loud BZ1 is
  through the closed case is untested. The 60° overhang under the bottom is steeper than
  the usual 45° rule for printing without supports.

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
- `HW/BL54L15μ_Hygrometer/Case/Hygrometer_2026v3.FCStd` in this repository: the slide-in lid
  with ridged rails that this case follows (5.7).
