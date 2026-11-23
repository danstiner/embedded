# Leak sensor

## 1. Scope

Battery-powered leak and humidity sensor built on the Ezurio BL54L15μ (nRF54L15) module.
Two contacts on the bottom detect water, immediately triggering a report over Matter
and optionally an alarm buzzer. An SHT40 measures temperature and humidity for mold detection.

This is revision **2026v5**, in design. The baseline is 2026v4, the first leak board,
fabricated as the hygrometer's 2026v4 (tag `fab/BL54L15μ-hygrometer/2026v4`, firmware
board `bl54l15u_hygrometer@2026v4`).

## 2. Changes from 2026v4

| Item          | 2026v4                                          | 2026v5                                                   |
| ------------- | ----------------------------------------------- | -------------------------------------------------------- |
| Size          | 48 mm circle                                    | 18 × 16 mm, elliptical bottom, stands on the end of the cell (5.6) |
| Battery       | CR2 in a Keystone 1011 holder                   | CR2 on wires, BAT+ and BAT− pads on the back             |
| Leak contacts | 6 mm domes on the back, driven one way          | 4 mm domes on the front, either way (4.1)                |
| Leak pins     | drive P0.01, sense P1.07, 1 MΩ to ground        | P1.12 and P1.11 each drive or sense; 1 MΩ to a GPIO      |
| I2C           | SDA P1.14, SCL P1.04                            | unchanged (5.2)                                          |
| Buzzer        | BZ1, Q1, D3, R7 (never driven by firmware)      | CMT-5023S-SMT on the front over J1, on P1.05 (5.5)       |
| SWD           | 2×5 1.27 mm box header on the front             | 2×5 1.27 mm pads on the back: header or pogo clip (4.2)  |
| Mounting      | H1, H2                                          | none; the case holds the board by its edge               |

## 3. Requirements

| ID  | Requirement                                                                             |
| --- | --------------------------------------------------------------------------------------- |
| R-1 | Wake on water across the contacts: Edge triggered, not polling                          |
| R-2 | Last 5 years on one CR2 (850 mAh): average current under 15 µA assuming 20% derating    |
| R-3 | Minimize probe corrosion: alternate probe voltage                                       |
| R-4 | Confirm water by measuring resistance with the SAADC, in both directions                |
| R-5 | Temperature and humidity reports from SHT4x over I2C with MCU pull-ups                  |
| R-6 | Minimize case size with small board standing on the end of a CR2 (Ø15.6 max)            |
| R-7 | SWD through a soldered 2×5 1.27 mm header or a pogo-pin clip from the side              |
| R-8 | Front parts in one reflow pass; the back has only pads and optional parts (J1, JP1, C3) |
| R-9 | A buzzer that can optionally sound when it finds water, >=60 dBA at 1 m                 |

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
  otherwise sit across the cell and draw 3 µA, 20 % of R-2. With its return pin at the
  same level as the drive it draws nothing.
- **Two return pins, not one.** One shared return cannot sit high for the driving side and
  low for the sensing side at the same time.
- **External pull-down.** At the nRF54L15's 13 kΩ typical internal pull-down (Ezurio
  datasheet, I2C note) the sense node could never reach the input-high level through
  20 kΩ of series resistance.
- **Both sense pins analog-capable** (AIN5, AIN4), since each side senses in one direction.

### 4.2 Debug connector

2026v4's J1 is a CNC Tech 3220-10-0300-00 box header: 12.7 × 5.05 mm and 4.9 mm tall
(measured from its 3D model in `Components/`). Fitted on 2026v5's back, it would hold the
cell at least 5 mm behind the board.

2026v5 has pads that take either that header or a pogo-pin clip clamped on from the left
edge. The first few boards get a header; the rest are flashed with the clip, and the case
is sized for boards without J1. Header land patterns cover the bent tails, which run
outward from the pin rows 0.635 mm off center: the header's datasheet gives pads from
0.63 to 3.40 mm off center, KiCad's stock 2×5 1.27 mm SMD pattern from 0.75 to 3.15 mm.
A clip whose two rows are 1.27 mm apart would land on the very ends of those pads or
just short of them. J1's pads run from 0.3 mm off center (the odd ones to 2.6 mm, the
even ones to 3.15 mm), so they catch rows 1.27 or 2.54 mm apart as well as the header's
tails (`Components/LeakSensor.pretty`). The tails reach 2.75 ± 0.15 mm off center: on
the odd side they overhang the pads by about 0.15 mm, with no fillet at the toe. The
back gets no paste: J1 is soldered by hand.

The odd pads reach the 0.381 mm edge rule, so the clip's outer row lands as close to the
edge as the copper allows; a fitted header's shroud overhangs the edge. BZ1 sits on the
front directly opposite J1, so the clip's other jaw rests on its flat 5 × 5 mm top and the
press is spread evenly. The clip needs more room around its pins than the board gives
(about 4 mm past the pin rows), but it presses lightly and tolerates an uneven bite, so no
keep-out is reserved for it.

### 4.3 Supply

As on 2026v4, the CR2 feeds everything directly: the module takes 1.7 to 3.5 V (Ezurio
datasheet 0.7, table 3) and the SHT40 1.08 to 3.6 V. The firmware reads the cell
through the SAADC's VDD input, as before. There is no reverse-polarity protection; the
wires are soldered once.

## 5. Circuit

### 5.1 Leak front end: P1, P2, D1, D2, R1–R4

```
P1 ── ELEC_A ──┬── R1 10 kΩ ── LEAK_A (P1.12, AIN5) ── R3 1 MΩ ── LEAK_A_RET (P1.09)
               D1 TPD1E10B06 to GND
P2 ── ELEC_B ──┬── R2 10 kΩ ── LEAK_B (P1.11, AIN4) ── R4 1 MΩ ── LEAK_B_RET (P1.10)
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
| 19     | P1.12 / AIN5  | LEAK_A     | Contact A: drive, edge wake, SAADC         |
| 23     | P1.11 / AIN4  | LEAK_B     | Contact B                                  |
| 22     | P1.09         | LEAK_A_RET | R3's return                                |
| 21     | P1.10         | LEAK_B_RET | R4's return                                |
| 18, 17 | P1.14, P1.04  | SDA, SCL   | U1 (firmware `i2c21`), internal pull-ups; 2026v4's pins |
| 15     | P1.05         | BUZZ       | Q1's gate: BZ1 at 4 kHz (5.5)              |
| 12, 10 | P1.00, P1.01  | XL1, XL2   | X1, 32.768 kHz, internal load capacitors   |
| 27, 25 | SWDIO, SWDCLK | –          | J1 2, 4                                    |
| 32     | nRESET        | –          | J1 10                                      |
| 42     | P2.07         | SWO        | J1 6                                       |

- **Pins chosen for routing** (5.6), within Nordic's rules: a peripheral uses pins of its
  own port, so TWIM and PWM reach port 1 only; port 2 has no TWIM and cannot wake the
  chip; SCL must be on a clock pin (Nordic DevZone, section 9). The module's left pad
  column and bottom rows face the rest of the board, and the pads are used in the order
  the traces leave: I2C first, toward U1, then the leak nets, down to the columns.
- **I2C** keeps 2026v4's pins. SCL (pad 17, a clock pin) leaves to the left; SDA (pad 18)
  drops out below it and follows. They reach U1 with SDA outermost, the order U1's fixed
  pin order needs, with no vias.
- **Leak.** LEAK_A (pad 19) and LEAK_B (pad 23) are the analog pads left in the bottom
  row, with LEAK_B_RET between them on pad 21, which has no analog input. A fourth net
  cannot leave that row on the front, so LEAK_A_RET takes inner pad 22 and a via in the
  module's middle; it is a static line. All four pins are on port 1.
- **BUZZ** is on pad 15: a port 1 pin for the PWM, 1.6 mm from the crystal's pads. Pad 13
  beside it is P2.02, which the PWM cannot reach.
- The AIN numbers are from the Ezurio pin table. 2026v4 confirmed P1.07 = AIN3 on
  hardware; AIN4 and AIN5 are unconfirmed (section 8). A wrong channel reads near VDD,
  which looks like a leak.
- Firmware sees this only in the new board revision's overlay: the leak node's four pins
  and two SAADC channels, and the buzzer as a PWM on P1.05. 2026v4's gpio0 drive node and
  gpio2 buzzer pin go; `i2c21`'s pins stay.
- All other pins are open and flagged no-connect. The module's DC/DC inductor is inside.

### 5.3 Temperature and humidity: SHT40-AD1F (U1)

2026v4 used an SHT45-AD1F. Watching for mold does not need its ±1.0 %RH and ±0.1 °C: the
SHT40 is typically within ±1.8 %RH and ±0.2 °C (SHT4x datasheet, tables 1 and 2). The
AD1F version keeps the membrane over the sensor opening, and the package, footprint and
commands are the same. Otherwise unchanged: address 0x44, C1 100 nF beside it, I2C
through the module's 13 kΩ pull-ups. Idle current 0.08 µA typical (table 4).

No thermal isolation: the board averages about 0.05 mW (R-2). The USB CO2 board's thermal
model put its SHT4x about 1 °C above ambient at 37 mW, roughly 0.03 °C per mW; scaled, this
board warms U1 by a few thousandths of a degree, and radio bursts of a few milliseconds
average out in the board's heat capacity. What matters is how freely room air reaches U1.
The sensor watches for mold conditions, so approximate humidity is enough: the case has
one small vent in its left wall, beside U1 (5.7), and U1 follows the room slowly. BZ1 is
2 mm away: an alarm warms U1 for some minutes (7.1).

### 5.4 SWD pads (J1)

The Arm 10-pin Cortex debug pinout, as 2026v4: 1 VDD, 2 SWDIO, 3, 5 and 9 GND, 4 SWDCLK,
6 SWO, 10 nRESET; 7 and 8 have pads but no connection. Land pattern in 4.2.

### 5.5 Battery and buzzer: BT1, BZ1, Q1, D3, R7

BT1 is a CR2 on wires: two 2 mm pads on the back, BAT+ (VDD) and BAT− (GND). There are no
test pads; VDD and GND are at BT1 and J1, the signals at J1 and on the parts' pads.

```
VDD ── JP1 ──┬── BZ1 + ── BZ1 − ──┬── BUZZER− ── Q1 drain   Q1 DMG1012T, source to GND
  (BUZZER+)  ├──── D3 1N4148WT ───┘   (cathode to BUZZER+)
             └── C3 100 µF, not fitted ── GND
BUZZ (P1.05) ──┬── Q1 gate
               └── R7 1 MΩ to GND
```

- **BZ1**, Same Sky CMT-5023S-SMT: a magnetic transducer, 5 × 5 × 2 mm, rated 3 V at
  4 kHz, 110 mA at most, 80 dBA at least at 10 cm (datasheet). In open air that is 60 dBA
  at 1 m: R-9 with nothing to spare for the case. It has no oscillator of its own: the
  firmware drives P1.05 with a 4 kHz square wave. 110 mA is far beyond a GPIO's drive, so
  Q1 switches BZ1's low side.
- **Other 5 mm buzzers**, compared from their datasheets and one distributor's single-piece
  prices on 2026-11-23. All are 4 kHz magnetic transducers rated near 3 V, with 12 Ω coils
  where stated, so the driver and the supply ripple stay the same.
  - **Ole Wolff OWMB-505020S-40-12D**: 80 dB at 10 cm, $1.79 against BZ1's $3.79. The part
    to try for the next revision; the footprint stays as it is for this one. Its leads
    reach 5.5 mm across in rows 4.2 mm apart, its body is 5.3 ± 0.3 mm square and 2.1 mm
    tall, and its recommended land pattern is 6.5 × 5.2 mm. At BZ1's place that pattern
    runs 0.15 mm past the board's edge and over SDA, SCL and BUZZ, so using it means moving
    BZ1, rerouting those and giving the case 0.1 mm more height. The leads do land on BZ1's
    present pads, overhanging their ends by up to 0.1 mm with no fillet at the toe: a few
    can be tried on a 2026v5 board first. The datasheet is one page, with no coil
    resistance, current or reflow limit.
  - Same terminals as BZ1, by their drawings: Same Sky CSS-0575A-SMT (76 dBA, $3.71),
    Mallory AST0540MW-03TRQ (75 dB, $3.11) and AST0540MW-3.6TRQ (80 dB at 3.6 V, 3.0 mm
    tall, $3.04).
  - Same leads as the Ole Wolff part: Same Sky CMT-0502-75-SMT (75 dB, $2.71) and
    CMT-0525-75-SMT (75 dB, 2.5 mm tall, $2.36).
- **Q1**, DMG1012T: 20 V, 0.63 A N-channel FET with an ESD-protected gate, in SOT-523.
- **D3**, 1N4148WT, clamps the coil's flyback when Q1 turns off.
- **JP1 and C3**, on the back, are an optional filter for BZ1's feed. As built, JP1 is a
  copper bridge between 0402 pads and C3 is not fitted: BZ1 runs straight from the cell
  and nothing on the back is needed. If BZ1's pulses turn out to disturb the radio (7.1),
  cut the bridge, solder a 2.2 to 4.7 Ω resistor across JP1's pads and fit a 100 µF 1206
  at C3. C3 then supplies the pulses and the resistor keeps them out of the cell: by
  simulation the module's ripple falls from about 100 mV to 23 to 35 mV with 2.2 Ω and 12
  to 17 mV with 4.7 Ω, for 3 to 7 % less coil current. The module's own feed does not pass
  through JP1. Costs when fitted: up to about 0.6 µA of leakage in C3; C3 stands where a
  J1 header's shroud goes and just below the clip's pins, so a board gets one or the
  other, and is flashed before C3 goes on; and there are 2.0 mm between the board and the
  case's divider, so check the height of the capacitor chosen (not yet checked against a
  datasheet).
- **R7** holds Q1 off while P1.05 floats (reset, or the pin left disconnected in sleep),
  so BZ1 stays silent. It draws current only while the buzzer sounds.
- The parts and the land pattern come from the datasheets' recommendations; BZ1's third
  terminal is mechanical and left unconnected.

### 5.6 PCB layout

Coordinates in mm, origin on the cell's axis, +y up, seen from the front (KiCad X = 100 + x,
Y = 100 − y; grid origin on the cell's axis). First laid out 2026-11-21 at 20 × 18 mm with
the module upright at the top left. Shrunk on 2026-11-22 to 18 × 16 mm with the module
lying flat, then re-pinned (5.2) and routed by hand.

- **Outline**: 18 × 16 mm, x ±9, y −7.85..8.15. Square top corners and straight sides down
  to y −0.45; below that a half ellipse 7.4 mm deep, the case's inner bottom curve 0.1 mm
  in (5.7). The ellipse is fuller than a semicircle, which at this height left no room for
  the domes. The cell (Ø15.6) lies behind the board on its axis: the board reaches 1.2 mm
  past it at each side and 0.35 mm above it. Two layers, 1.6 mm.
- **Rules** (`BL54L15μ_LeakSensor.kicad_dru`): copper at least 0.381 mm from the edge, as
  on the USB CO2 board. Courtyards may overlap in four places: X1 and C2 at the edge of
  IC1's; parts in the domes' courtyards, which reach 0.8 mm past the 4 mm dome; R3 and R4
  in IC1's 1 mm margin; JP1 and C3 under J1's, which is the header's whole shroud. Two DRC exclusions: J1's silk past the left edge (the header's
  shroud) and U1's label against its own outline.

| Part             | Side  | Position                       | Note                                            |
| ---------------- | ----- | ------------------------------ | ----------------------------------------------- |
| IC1              | front | x 0.9..8.8, y 1.35..7.65       | top right, lying flat: antenna end 0.18 mm from the right edge, pin 1's side 0.5 mm from the top |
| Antenna keep-out | all   | x 5.82..8.82, y 2.0..7.0       | 3 × 5 mm, the module footprint's own rule area; two more keep pours out of the strip above it |
| U1, C1           | front | (−7.17, 7.11), (−5.5, 6.99) upright | top left corner, by the vent; U1's SDA and SCL pads face the left edge |
| X1               | front | (−1.25, 4.18) upright          | 1.3 mm left of IC1, its pads' ends toward it    |
| C2               | front | (−1.56, 7.24)                  | above X1, pad 1 (VDD) toward the module         |
| R3, R1, D1       | front | x −0.6, y −0.35, −2.21, −4.07, upright | contact A's column, top to bottom        |
| R4, R2, D2       | front | x 0.6, same y, upright         | contact B's column, beside A's                  |
| P1, P2           | front | (∓3.95, −4.85), turned 180° ∓ 24.5° | 7.9 mm apart, feet below center along the bottom curve |
| BZ1              | front | (−5.90, 3.08)                  | left edge, over J1; mounting terminal top left  |
| D3, Q1, R7       | front | (−8.0, −1.04) upright, (−5.96, −1.02), (−3.68, −1.02) | in a row under BZ1    |
| J1               | back  | center (−6.02, 2.3)            | left edge, odd column outboard, pin 1 at the bottom |
| JP1, C3          | back  | (−6.71, −1.2), (−5.8, −2.25)   | below J1's bottom pads; optional (5.5)          |
| BT1              | back  | + (0, −3.9), − (0, −6.4)       | between the domes' inner feet                   |

- **Module flat in the top right, antenna end at the right edge.** The chip antenna sits
  in the corner of the module's antenna end on pin 1's side, by ground pad G3 (datasheet
  figure 10; Ezurio's product render and a photo of their development kit agree), which
  is the board's top right corner. The end is as close to the right edge as its end ground
  pads allow: their copper ends 0.2 mm from the module's end, so the 0.381 mm edge rule
  puts the module 0.18 mm in (the DevKit uses 0.23 mm). Pin 1's side is 0.5 mm from the
  top edge. At 0.18 mm, ground pad 39 could not be joined at 0.1524 mm rules; 0.32 mm
  lower, its trace runs over pad 37 (no connection) along the edge rule to pad 46, and
  pads 46 to 48 link along their row and down to pad 36. The chip is then about 0.4 mm
  from the right edge and 1.0 mm from the top, and seen from the front it sits about
  3.4 mm outside the cell's outline (5.2 mm on the 20 × 18 layout). Neither pour enters
  the strip between the keep-out and the top edge; on the back, no track or via does.
- **Why flat.** Upright, the module took the board's full height and its pads faced one
  side. Flat, its left pad column and bottom rows face the rest of the board, U1 takes the
  far top corner by the vent, and the board loses 2 mm each way.
- **Leak front end in two columns.** Each contact's parts stand upright end to end below
  the module, in the chain's order: the 1 MΩ resistor at the top, then the 10 kΩ, then
  the TVS diode with its ground pad facing down. The columns are 1.2 mm apart about the
  axis, so the same values sit side by side for hand assembly. Pads that meet share a net,
  so each column's links are short stubs. LEAK_A leaves pad 19, runs left under the I2C
  pair and down the gap between the columns to the R3–R1 joint; LEAK_B_RET drops from pad
  21 into R4 from the right; LEAK_B leaves pad 23 down the right of its column into the
  R4–R2 joint. LEAK_A_RET goes from inner pad 22 to a via in the module's middle, 5.9 mm
  along the back, and up through a via onto R3's top pad. ELEC_A and ELEC_B leave the
  resistor-diode joints at 45° for the domes' center pads. D1's and D2's ground pads each
  get a via just outboard.
- **Domes.** The 4 mm dome footprint (`MetalDomeSwitch:TriangleDome_Diameter4mm`) has its
  two feet 2 mm either side of center, 0.4 mm off it. Turned 180°, the feet are below
  center; each dome is tilted 24.5° so its feet follow the bottom curve, about 1.3 mm in
  from the edge. The domes are 7.9 mm apart, their inner feet clear of BT1's pads on the
  back; the water's resistance between the pins hardly depends on their spacing (it grows
  with its logarithm). The center pad is tied to both feet. The feet are plated slots
  0.254 mm wide, under OSH Park's 0.508 mm minimum for drilled slots; 2026v4's 6 mm domes
  had the same slots.
- **J1 and the clip.** J1 sits at the left edge, not behind the module: the module's
  under-body vias would land in its pads. Its outboard pads (odd: VDD, ground, key) reach
  the edge rule. The module's supply runs up the gap between J1's columns, which shuts pins
  3 and 5 in: a trace joins them at their outer ends and a via in pin 5's pad ties them
  to the front pour under BZ1. Pin 9 joins the main back pour. The pogo pins land 0.64 or
  1.27 mm either side of J1's center line, and BZ1 on the front opposite takes the clip's other jaw.
- **BZ1 and its driver.** BZ1 sits over J1 with its + pad at the bottom left, its − pad
  at the bottom right and its unconnected mounting terminal at the top left. D3, Q1 and R7
  stand in a row under it, D3 upright at the left edge. The − pad drops to Q1's drain and
  D3's anode; D3's cathode and the + pad share a via between D3 and Q1 to the back,
  where JP1 joins them to the supply and C3's pads wait beside it. D3 is
  within 3 mm of both of BZ1's pads; the few nanohenries of trace are nothing beside the
  coil. BUZZ leaves pad 15, crosses under the I2C pair and LEAK_A on the back between two
  vias, and comes down to R7 and Q1's gate. Q1's source and R7's ground end join the pour.
- **X1 and C2.** X1 stands upright 1.3 mm left of the module. Each leg runs 2.8 mm along
  the back from the module's fan-out via to a via beside X1's pad, then a 2.1 mm front
  stub, 0.2 mm wide, so the two legs match; ground is poured between and around them on
  both layers. C2 lies above X1 with its VDD pad 1.5 mm from pad 5. Both courtyards touch
  the module's, which reaches 1 mm past its body; a custom rule allows that.
- **Fan-out.** Under the module: 2026v4's vias for XL1 and XL2, copied in the module's
  frame, and vias for SWO, nRESET, LEAK_A_RET and ground. Ground pad 4, boxed in by
  signal pads, has a via of its own, as on the USB CO2 board.
- **Routing.** Front: I2C from pads 17 and 18 left under X1, then up under BZ1's body
  between its pads into U1's left pads, SDA round the outside; the leak nets; BZ1's
  feed from its via by D3 to D3 and the + pad; the module's supply from a via by C1 to U1,
  C1, along the top to C2 and pad 5 (about 50 mΩ from BT1 to the module); the dome ties. Back: SWD to J1's pins 2
  and 4; SWO and nRESET from the module's middle over the top and down to pins 6 and 10;
  XL1 and XL2; LEAK_A_RET; BUZZ; the supply from BT1+ up past C3's place and along under
  J1's bottom pads to JP1 and J1's pin 1, then up the gap between J1's columns to the via
  by C1; BZ1's node from JP1 to its via and C3. Tracks 0.15 mm; power
  0.2 to 0.3 mm; 0.25 mm in the driver; 0.2 mm for the crystal stubs and the dome ties.
- **Silkscreen.** References at 0.75 mm (the board minimum) beside their parts; IC1's,
  X1's and BZ1's are under the parts, hidden once fitted. BT1 has its + and −, and the back
  carries "Leak Sensor", `${REVISION}` and `${COMPANY}` from the board's literal title
  block, behind the module. J1's line on the back marks pin 1's side of the shroud: it runs
  past the left edge and stops short of JP1. C3's label is under its body; JP1 has none.
- **Ground.** Pours on both layers outside the keep-out, 0.1524 mm clearance as on
  2026v4. Thermal reliefs on the front only for through-hole pads (it is reflowed); on
  the back for every pad, so J1 and BT1's wires can be hand-soldered. 26 ground vias. The
  point of either pour farthest from one is 4.8 mm away, in U1's corner, inside the
  5.3 mm (λ/8 at 2.4 GHz) used on the USB CO2 board; 6.1 % of the pour is more than 3 mm
  from one (`Sim/layout.py`).

### 5.7 Case

`Case/build_case.py` builds the case in FreeCAD from the parameters at its top and saves
`Case/LeakSensor_2026v5.FCStd`. The file also holds the board (KiCad's STEP export), the
cell, the battery contacts and the leak pins as reference parts, and the script checks all
of them against each other. The case is an open-top body with half-dome ends and a lid that
slides on from the rear, 21.3 × 56.5 × 18.45 mm. The board stands across the front
with the cell lying behind it. The board sets the width and height: its 18 mm plus
0.15 mm clearance and a 1.5 mm wall each side, its 16 mm plus a 1.0 mm floor, a 1.2 mm
lid and the slot's 0.1 mm under the board and 0.15 mm over it.

The bottom is a half ellipse, 21.3 mm wide and 8.5 mm deep outside, the inside concentric
(1.0 mm floor, 1.5 mm sides): flatter at the bottom than a semicircle and fuller. The
board's bottom is the same curve 0.1 mm in, and the cell clears it by 0.1 mm. With no flat, the body needs
supports either way up. The print plate (`LeakSensor_2026v5.3mf`) has it turned over, on its rim: the
whole outside then prints without support, and the supports go inside, under the floor
(about 600 mm²) and the panels' top edges (18 mm spans, which may bridge), all reachable
from the open top. The board slot and the gap behind it bridge themselves; the bosses and
the cell's seats are shaped to need none (below). The rear dome's rim, 2.8 mm above
the bed, needs a low support. Upright, about 880 mm² of the outside would stand on supports.
Both ends are half domes: the same section turned about a vertical axis, so they are
semicircles seen from above and every cut through the axis shows the sides' curve. The
front one's axis is 1.5 mm ahead of the board's front face. On the face, the module's
end, 2.1 mm tall and 0.18 mm from the board's edge, came within 0.09 mm of the curving
wall; now it clears by 0.31 mm, the least gap round any front-side part is 0.28 mm, and
the case's front is 12.15 mm ahead of the board. The rear one's axis is 1.0 mm in front of
the cell's rear end: its bowl clears the cell's rear edge by 0.10 mm and holds the 228
contact, its tab and the + wire. Round ends make the case 7.3 mm longer than the squashed
ones did. The top's edges are square.

- **Board slot.** 0.4 mm lips front and back along the board's sides and bottom; the
  board drops in from the top and rests 0.1 mm above the floor. The side lips stop at
  y 7.3, 0.85 mm below the board's top. The front lip is cut away where parts stand
  within its 0.4 mm: on the right above y 0.9 (the module's end), on the left from
  y −2.0 to 5.9 (D3 and BZ1). The domes push the board back, so its front face is the
  datum: a crush rib behind each straight side, 0.1 mm into a 1.6 mm board and only as
  long as the front lip left opposite it, holds it against that lip. The dome press then depends on two faces of one
  print, not on the board's thickness or the slot's fit.
- **Leak pins.** Ø2.5 × 6 mm flat-ended metal pins, used as they come, stand upright at x
  ±3.95, just in front of the domes. Each is pushed up from below into a blind bore in a
  boss that runs from the front dome's wall back toward the board. Above the bore's cap
  the boss rises at 45° toward the front wall, so that printed on its rim it grows out of
  the wall without support. The side of each pin
  presses its dome's apex: the pin surface is 0.2 mm off the board and the dome is assumed
  0.3 mm high, a 0.1 mm press (`DomeApex`, `PinPress`). The bore opens toward the dome
  through a 2.4 mm gap, narrower than the pin, and the bore's wall stops 1.1 mm short of
  the board, over the domes. That clears Q1, whose body ends 0.2 mm above the left boss
  and stands up to 0.9 mm tall: 0.28 mm at its tallest (at 0.7 mm it collided). The
  bosses also clear R7 and the diodes. The board's domes fix the pins 3.95 mm either side
  of the center line, at the front dome's axis, where the bottom curves up across the
  case: across a pin it rises 0.8 mm. The bore's depth
  sets each pin's end flush with the lowest point of the curve where it exits, 0.28 mm
  above the table, so nothing stands proud; the outer part of the end sits up to 0.8 mm
  inside its hole. Water has to stand 0.28 mm deep to reach the pins. Another length from
  the box only changes the bore's depth (`PinL`).
- **Cell.** Keystone 209 leaf spring (−) on a 1.6 mm divider behind the board, 228 button
  (+) on a 1.6 mm rear panel; both clip onto 1.52–1.78 mm panels and are listed for CR2.
  The 209 is assumed compressed to 2.5 mm between the divider and the cell. Two saddles
  under the cell, 0.2 mm off it, and two ribs under the lid over them, 0.1 mm off it. Below
  45° each saddle's seat leaves the cell's circle along its tangent, a V block that runs
  out into the floor 4 mm from the middle: it prints without support, and the cell bears
  on the two flanks: the board,
  not the cell, sets the bay's height, which leaves 0.5 mm above the cell.
- **Wiring.** BT1's pads face the divider across a 2.0 mm gap, where the 209's tab is.
  The 228's tab sits in the dome's bowl behind the rear panel; its wire runs forward over
  both panels in the bay's upper left corner, 1.55 mm in from the wall to clear the rear
  dome's curve, clear of the cell and below the lid.
- **Vent.** One 1.0 × 2.0 mm slot in the left wall, into the space in front of the
  board, level with U1's lower half (5.3), with 0.7 mm of wall above it. There is no other opening: BZ1 sounds through
  the closed case.
- **Lid.** A 1.2 mm plate that slides on from the rear, after the hygrometer 2026v3's case
  with its track turned inside out: the side walls run up to the plate outside, and a 0.8
  mm tongue under the plate runs just inside each wall, its 45° ridge, 0.6 mm deep, facing
  out from its top 1.2 mm into a groove in the wall's inner face, so the lid cannot lift;
  0.85 mm of the 1.5 mm wall stays behind the groove (a 1.0 mm wall would keep 0.35 mm).
  The tracks run from just behind the board slot's back lip (y 2.6), since further forward
  the tongues would meet the board's top corners, to the rear dome, and the lid stops
  where the grooves end. The plate covers the front dome, which stands to the walls'
  height: as part of the lid, its curve would sweep through the walls while the lid slides
  on. The lid does take the rear dome's top, down to 4.0 mm below the top, under the
  two ribs that hold the cell down (above), which slide out over the rear dome's rim; the
  tongues run on into that part of the dome's wall until it covers their ends, to join it.
  Outside, the seam runs at the plate, 1.2 mm below the top, around the front and along
  the sides, and drops to 4.0 mm where the rear dome begins. The tongues' feet pass 0.2 mm over the
  contact panels.
- **Fits, as on 2026v3.** Faces that slide or bear are drawn line to line: the tongues on
  the walls' inner faces, the plate on the walls' tops, the tongues' feet level with the
  seam. Only the groove is cut larger than the ridge, 0.05 mm deeper and 0.1 mm taller, so
  its upper flank bears and its lower flank clears. The detent is 2026v3's turned inside
  out too: a 60° bump, 0.5 mm high and 1.4 mm tall (it ends 0.2 mm under the ridge), on each tongue
  5 mm ahead of the track's rear entry,
  and in each wall a notch 0.05 mm deeper behind a lead-in ramp, 0.6 mm deep at the entry
  and running out over 4 mm, so the bump rides the wall only for the last 4.2 mm of
  travel. The wall takes the ramp better than the tongue would.
- **Checks.** No overlap between the body, lid, board and its parts, cell, contacts, pins
  and a Ø1.2 mm + wire. BZ1 and Q1 have no 3D model in the board's STEP, so boxes stand
  in for them (Q1's at its tallest), and the build prints the least gap between the
  front-side parts and the case. The board drops in from 25 mm above without touching anything but
  the ribs, and the lid slides out to the rear touching only where the bumps ride the
  ramps (the line-to-line faces touch without overlapping). The build also checks that
  both parts mesh to closed solids for the slicer. J1's header model
  is left out: a board with a header does not fit. The script first checks that booleans
  against each part work at all: refined with `removeSplitter()`, the lid looked valid but
  every check against it came back empty.

## 6. Bill of materials

| Ref     | Value                   | Part                                    | Footprint            | Description                          |
| ------- | ----------------------- | --------------------------------------- | -------------------- | ------------------------------------ |
| IC1     | BL54L15μ                | Ezurio 453-00223R                       | module               | nRF54L15 module, chip antenna (5.2)  |
| U1      | SHT40                   | SHT40-AD1F-R2                           | DFN-4 1.5 mm         | Temperature and humidity (5.3)       |
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
| JP1     | copper bridge           | –                                       | 0402 pads, bridged   | Optional: cut, fit 2.2 to 4.7 Ω (5.5) |
| C3      | 100 µF, not fitted      | to be chosen                            | 1206                 | Optional reservoir for BZ1 (5.5)     |

3D models: U1 uses Sensirion's SHT45-AD1F model, the same package (`Components/SHT45_AD1F_R2`,
with the download's license, as on the USB CO2 board); KiCad ships none for its SHT4x footprint. D1 and D2 use KiCad's 0402
resistor model as a stand-in: KiCad has no 0402 diode model, and TI's X1SON (DPY) body is
the same 1.0 × 0.6 mm. BZ1 and Q1 have no model yet (KiCad ships none for SOT-523): to be
downloaded from DigiKey. Until then the case checks use boxes for them (5.7).

## 7. Verification

### 7.1 By calculation and simulation

Run on the committed board, 2026-11-22, and again after JP1 and C3 were added. `Sim/sim.py` runs the circuit checks (ngspice for
the buzzer driver and the leak front end), `Sim/layout.py` the layout checks with KiCad's
Python, and `Case/build_case.py` the fits (5.7). Values no datasheet gives are marked
ASSUMED in the scripts and named here.

| Check                         | Result                                                              | Verdict |
| ----------------------------- | ------------------------------------------------------------------- | ------- |
| ERC, DRC, schematic parity    | 0 errors and warnings, 0 unconnected, 0 parity issues; 2 exclusions (5.6) | pass |
| Edge wake threshold           | sense node at 0.7 VDD below 0.41 MΩ, back under 0.3 VDD above 2.3 MΩ | as designed (R-1) |
| Leak settling                 | 99 % in 71 µs at 10 MΩ, faster below; 2026v4's driver waits 100 µs  | pass |
| SAADC, 40 µs acquisition      | −1.3 % at 10 MΩ with a 2.5 pF sampling capacitor, −7 % at 10 pF     | pass (R-4)        |
| False leak from leakage       | 10 nA into the sense pin reads as 300 MΩ; 100 MΩ of film reads as itself | pass |
| ESD at a dome, 8 kV contact   | about 30 A in the TVS, clamped near 22 V; 1.9 mA through R1 into the pin | pass |
| Buzzer, coil current          | peak 125 to 232 mA, 45 to 95 mA from the cell, for 3 to 0.3 mH       | within 110 mA |
| Buzzer, Q1 and D3             | drain clamped at 3.9 V; Q1 under 7 mW; D3 13 to 42 mA average        | pass |
| Buzzer, brown-out             | module stays above 1.7 V up to 8 Ω of cell resistance at 3.0 V, 4 Ω at 2.4 V | pass |
| Buzzer, supply ripple         | 60 to 120 mV peak to peak at the module on a 0.5 Ω cell             | **over Ezurio's 10 mV** |
| The same, JP1 and C3 fitted   | 23 to 35 mV with 2.2 Ω and 100 µF; 12 to 17 mV with 4.7 Ω           | optional fix (5.5) |
| Buzzer, heat                  | about 170 mW beside U1; the board warms roughly 1 K in 10 s, 5 K in 60 s | **U1 reads high** |
| Buzzer, charge                | about 1 mAh a minute at 1 mH, up to 1.8 mAh at the rated 110 mA      | note |
| I2C rise time                 | 91 to 115 ns on 8.5 pF with the 13 to 16 kΩ pull-ups; 300 ns allowed | pass at 400 kHz |
| Crystal load                  | board stray adds about 0.5 pF: 6 ppm fast unless trimmed out         | trim in firmware |
| Dome press                    | 0.1 mm nominal with 0.1 mm spread: no contact on 16 % of pins       | **too little** |
| Ground stitching              | farthest pour point 4.8 mm from a via; 6.1 % over 3 mm               | pass (5.3 mm) |
| Case fits                     | no overlap; least gap to a front part 0.28 mm; board drops in, lid slides off | pass |

- **Buzzer inductance.** Same Sky gives the coil's resistance (12 ± 3 Ω) but not its
  inductance: 1 mH is assumed and 0.3 to 3 mH swept. The datasheet's 110 mA fits the low
  end. Q1 is modeled from its datasheet threshold and on-resistance; with the worst
  threshold (1.0 V) on a 2.0 V cell it still switches fully.
- **Supply ripple.** The cell's own resistance sets it (0.5 Ω assumed for the row above);
  C2 is 8 Ω at 4 kHz and does little. Ezurio's table 3 allows 10 mV of ripple on VDD "that
  does not disturb the radio", so the firmware should not transmit or receive while the
  buzzer sounds: beep between radio events.
- **Heat.** A single lump of 1.5 J/K losing 12 mW/K is assumed; it is a rough bound, and
  U1 is 2 mm from BZ1. The firmware should mark temperature and humidity as suspect during
  an alarm and for some minutes after.
- **Leak front end.** The node capacitance (12 pF of TVS, 5 pF assumed for the pin and
  trace) holds the SAADC's sample: the reading is right even though 1 MΩ is over Nordic's
  800 kΩ for a 40 µs acquisition. With 3 µs it would read 11 % low at 10 MΩ. V_IH and the
  SAADC's sampling capacitor are assumed, not read from Nordic's tables.
- **Dome press.** The spread is assumed: 0.08 mm for the printed bore, 0.05 mm for the
  slot, 0.03 mm for the dome. With it, a 0.2 mm nominal press misses on 2 % of pins and
  0.25 mm on 0.6 %. A pressed-flat dome still connects (its center pad shares the net), so
  more press costs nothing electrically; `PinPress` is left at 0.1 until a dome is chosen.
- **Ground under traces.** The back pour lies under 73 and 82 % of LEAK_A and LEAK_B and
  62 to 65 % of the I2C pair; the gaps, at most 1.8 mm, are over the BUZZ and LEAK_A_RET
  hops. Nothing on the board is fast enough for that to matter.
- **Not simulated.** The antenna (no field solver; the RSSI test below decides), battery
  life (needs 2026v4's measured current), and the sound level through the closed case.

### 7.2 On hardware

Not started. Planned:

| Test                                                                       | Checks   | Pass                                           |
| -------------------------------------------------------------------------- | -------- | ---------------------------------------------- |
| Sleep current, leak armed, then parked                                     | R-2, R-3 | no measurable difference                       |
| SAADC on AIN5 and AIN4 with LEAK_A, then LEAK_B, held at a known voltage   | 5.2      | each channel reads its own pin                 |
| Resistance box across P1–P2, both directions: largest value that wakes     | R-1      | about 0.4 MΩ; record it                        |
| SAADC reading at 10 kΩ, 100 kΩ, 1 MΩ and 10 MΩ, both directions            | R-4      | within 10 % of the divider, both ways          |
| Tap water across the contacts                                              | R-1, R-3 | report within a second, pins parked after      |
| Average current on Thread over 24 h                                        | R-2      | under 15 µA                                    |
| RSSI with and without a CR2 behind the antenna (first on a 2026v4 board)   | 8        | record the difference                          |
| Flash through a soldered header, then through the pogo clip                | R-7      | both work                                      |
| U1 against a reference thermometer                                         | R-5      | within 0.5 °C                                  |
| Buzzer at 4 kHz in the closed case, on a partly used CR2                   | R-9      | at least 60 dBA at 1 m; no brown-out           |
| VDD ripple at C2 with the buzzer on; packet loss with and without it       | 7.1      | record both                                    |
| U1's reading through a one-minute alarm and the 10 minutes after           | 7.1      | record the rise and the recovery               |
| Pin to dome continuity on each printed case                                | 7.1      | both pins connect                              |

## 8. Known limitations and open questions

- **Antenna.** The module lies in the top right corner with its chip antenna toward the
  corner, where the datasheet prefers edge center (sections 5.2, 5.3.1, 6.2). Seen from
  the front the chip is about 3.4 mm outside the cell's outline, less than the 5.2 mm of
  the 20 × 18 layout, and the cell is a few millimeters behind. Metal within 20 mm "will
  begin to significantly degrade performance" (5.3.2): BZ1, a coil and magnet, is about
  14 mm from the chip, X1 10 mm, the right leak pin 12 mm. The RSSI test in section 7
  decides whether this layout holds.
- **Battery life** is a target, not an estimate: the module idles at 3 µA (Ezurio
  datasheet, section 2.1) and the SHT40 at 0.08 µA, which leaves about 12 µA for Thread
  polling and reports. A 2026v4 current measurement comes first.
- **Input threshold.** V_IH and any input hysteresis are to be read from the nRF54L15
  datasheet. A slowly wetting contact holds the sense node near the threshold, so the
  firmware should debounce the edge, as for 2026v4.
- **Dome press.** The 4 mm dome part is not chosen. A dome travels only a few tenths of a
  millimeter, so the case's 0.3 mm height and 0.1 mm press (5.7) need checking against
  the chosen part's drawing and a test print. With a plausible print spread, 0.1 mm leaves
  one pin in six without contact (7.1): expect to raise `PinPress` to 0.2 mm or more.
- **Pogo clip.** J1's pads accept rows 1.27 or 2.54 mm apart; check against the clip used,
  and that BZ1 takes its other jaw.
- **Buzzer.** BZ1's land pattern, Q1 and D3 come from datasheets, not parts in hand. BZ1
  draws up to 110 mA from the CR2. By simulation the module stays above 1.7 V unless the
  cell's resistance passes 4 Ω at 2.4 V (7.1); the CR2's resistance cold and partly used
  is not known here. The same current puts 60 to 120 mV of ripple on the module's supply,
  over Ezurio's 10 mV for the radio, and warms U1. Whether that ripple costs packets is
  not known: the firmware should beep between radio events, and JP1 and C3 on the back
  are there to filter BZ1's feed if a board shows it matters (5.5). BZ1 costs about twice
  what an Ole Wolff part of the same rating does; that part needs a wider land pattern, so
  it waits for the next revision (5.5).
- **Analog channels.** AIN4 (P1.11) and AIN5 (P1.12) come from Ezurio's pin table and
  have not been read on hardware. 2026v4 showed that a wrong channel reads near VDD.
- **Firmware.** New board revision, a leak driver for four pins and both directions, and
  the buzzer moved to P1.05 as a 4 kHz PWM, sounded between radio events (7.1). Whether the board keeps the name
  `bl54l15u_hygrometer` is open; 2026v5 was also the name of the battery CO2 hygrometer in
  PR 23, closed and never built.
- **Case.** Unprinted. The 209's compressed length and both contacts' tab positions come
  from Keystone's catalog drawing, not parts in hand. Boards with J1 fitted do not fit.
  The lid's line-to-line slide fit and its detent, now 1.4 mm tall, need a test print; how loud BZ1 is
  through the closed case is untested. The bottom has no flat: it prints with supports (inside, turned over: 5.7),
  and on a table it rests on its lowest line. The pins' ends sit 0.28 mm above the table,
  so the sensor needs water about that deep before it reaches them.

## 9. References

- [Ezurio BL54L15µ datasheet](https://www.ezurio.com/documentation/datasheet-bl54l15u),
  version 0.7, 11 April 2025: section 2.1 (System ON idle 3 µA), the pin table (AIN
  mapping, clock pins), table 3 (supply 1.7 to 3.5 V, 10 mV ripple for the radio), the
  schematic checklist (13 kΩ pull-ups), sections 5.1 (one mandatory 10 µF), 5.2, 5.3.1,
  5.3.2 and 6.2.
- [Sensirion SHT4x datasheet](https://sensirion.com/resource/datasheet/sht4x), version
  7.3, June 2026: tables 1 and 2 (accuracy), table 4 (supply range, idle current).
- Nordic Semiconductor nRF54L15 datasheet: GPIO electrical specification, to be read for
  V_IH (5.1, 8); [port capabilities](https://docs.nordicsemi.com/r/bundle/ps_nrf54l15/page/gpio.html-concept_port_capabilities)
  (each port's power domain; port 2 cannot wake the chip) and
  [clock pins](https://docs.nordicsemi.com/r/bundle/ps_nrf54l15/page/chapters/pin.html-clock_pins) (5.2);
  the SAADC's acquisition time table (40 µs for sources up to 800 kΩ, 7.1).
- Nordic DevZone: [nRF54L15 TWI pin configuration](https://devzone.nordicsemi.com/f/nordic-q-a/120725/nrf54l15-twi-pin-configuration/535144)
  (no TWIM on port 2) and
  [nRF54 TWIM/I2C clock pin assignment](https://devzone.nordicsemi.com/f/nordic-q-a/120600/nrf54-twim-i2c-clock-pin-assignment/539274)
  (SCL on a clock pin) (5.2).
- Same Sky CMT-5023S-SMT datasheet: 3 Vo-p, 4 kHz, 110 mA at most, coil 12 ± 3 Ω (5.5, 7.1).
- [Ole Wolff OWMB-505020S-40-12D datasheet](https://products.owolff.com/acoustics/buzzers-(print)-/@1252/OWMB-505020S-40-12D?output=pdf&delay=3000&recordid393=1252),
  updated 4 November 2025: 80 dB at 10 cm, mechanical drawing and land pattern; Same Sky
  CSS-0575A-SMT, CMT-0502-75-SMT and CMT-0525-75-SMT and Mallory Sonalert AST0540MW-03TRQ
  and AST0540MW-3.6TRQ datasheets: ratings and drawings of the other 5 mm buzzers (5.5).
- [CNC Tech 3220-XX-0300-00 drawing](https://cnctech.us/pdfs/3220-XX-0300-00_.pdf), revision D,
  10 April 2023: P.C.B layout (pads 0.65 × 2.77 mm, 6.80 mm across), tails 5.50 ± 0.30 mm
  across (4.2).
- Diodes Incorporated DMG1012T datasheet and SOT523 package outline: gate threshold 0.5 to
  1.0 V, body up to 0.8 mm with up to 0.1 mm standoff (5.5, 5.7, 7.1).
- Texas Instruments TPD1E10B06 datasheet: 12 pF, 100 nA leakage (7.1).
- R. Lee and W. Kester,
  [Fully Automatic Self-Calibrated Conductivity Measurement System](https://www.analog.com/en/resources/analog-dialogue/articles/fully-automatic-self-calibrated-conductivity-measurement-system.html),
  Analog Dialogue 50-11, November 2016: DC on conductivity electrodes causes polarization
  and electrode damage; AC excitation with no DC offset (4.1).
- Panasonic CR2 datasheet: Ø15.6 mm maximum, 850 mAh (R-2, R-6), as given in the design
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
