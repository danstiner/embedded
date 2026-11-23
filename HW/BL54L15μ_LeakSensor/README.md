# Leak sensor

## 1. Scope

Battery-powered leak and humidity sensor built on the Ezurio BL54L15μ (nRF54L15) module.
Two contacts on the bottom detect water, immediately triggering a report over Matter
and optionally an alarm buzzer. An SHT40 measures temperature and humidity for mold detection.

The board stands on the end of a CR2 cell in a printed case. Two metal pins in the case's
floor touch the water and press on two dome contacts on the board (5.7).

This is revision **2026v5**, in design. The baseline is 2026v4, the first leak board,
fabricated as the hygrometer's 2026v4 (tag `fab/BL54L15μ-hygrometer/2026v4`, firmware
board `bl54l15u_hygrometer@2026v4`).

## 2. Changes from 2026v4

| Item          | 2026v4                                   | 2026v5                                                  |
| ------------- | ---------------------------------------- | ------------------------------------------------------- |
| Size          | 48 mm circle                             | 18 × 16 mm, stands on the end of the cell (5.6)         |
| Battery       | CR2 in a Keystone 1011 holder            | CR2 on wires to two pads on the back                    |
| Leak contacts | 6 mm domes on the back, driven one way   | 4 mm domes on the front, driven either way (4.1)        |
| Leak pins     | drive P0.01, sense P1.07, 1 MΩ to ground | P1.12 and P1.11 each drive or sense; 1 MΩ to a GPIO     |
| Sensor        | SHT45                                    | SHT40 (5.3)                                             |
| I2C           | SDA P1.14, SCL P1.04                     | unchanged                                               |
| Buzzer        | 8.5 mm, never driven by firmware         | 5 mm, on P1.05, smaller driver parts (5.5)              |
| SWD           | 2×5 1.27 mm box header on the front      | 2×5 1.27 mm pads on the back: header or pogo clip (4.2) |
| Mounting      | two holes                                | none; the case holds the board by its edge              |

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

2026v4 drives one contact through 10 kΩ and senses the other through 10 kΩ, with 1 MΩ to
ground. While dry the drive is held high: no current flows, and a rising edge on the sense
pin wakes the board. Current always flows the same way, which polarizes the contacts and
corrodes the anode. Conductivity cells are driven with alternating polarity for this
reason (Lee and Kester, Analog Dialogue 50-11).

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

A 2×5 1.27 mm box header (CNC Tech 3220-10-0300-00, 4.9 mm tall) on the back would hold
the cell 5 mm off the board. So J1 is a set of pads that takes either that header,
hand-soldered on the first few boards, or a pogo-pin clip clamped on from the left edge.
The case is sized for boards without the header.

Standard header land patterns start at the pin rows, 0.635 mm off center, and run outward
under the bent tails: 0.63 to 3.40 mm in the header's datasheet, 0.75 to 3.15 mm in
KiCad's stock footprint. A clip whose rows are 1.27 mm apart would land on the very ends
of those pads. J1's pads start 0.3 mm off center, so they take clip rows 1.27 or 2.54 mm
apart as well as the header's tails (`Components/LeakSensor.pretty`). The pads on the
edge side stop at 2.6 mm to keep copper 0.381 mm from the edge; the header's tails
overhang them by about 0.15 mm, with no fillet at the toe.

BZ1 sits on the front directly opposite J1, so the clip's other jaw rests on its flat
top. No keep-out is reserved for the clip: it presses lightly and tolerates an uneven
bite.

### 4.3 Supply

The CR2 feeds everything directly: the module takes 1.7 to 3.5 V (Ezurio datasheet 0.7,
table 3) and the SHT40 1.08 to 3.6 V. The firmware reads the cell through the SAADC's VDD
input. There is no reverse-polarity protection; the wires are soldered once.

## 5. Circuit

### 5.1 Leak front end: P1, P2, D1, D2, R1–R4

```
P1 ── ELEC_A ──┬── R1 10 kΩ ── LEAK_A (P1.12, AIN5) ── R3 1 MΩ ── LEAK_A_RET (P1.09)
               D1 TPD1E10B06 to GND
P2 ── ELEC_B ──┬── R2 10 kΩ ── LEAK_B (P1.11, AIN4) ── R4 1 MΩ ── LEAK_B_RET (P1.10)
               D2 TPD1E10B06 to GND
```

| State (A to B; B to A swaps the sides) | LEAK_A   | LEAK_A_RET | LEAK_B           | LEAK_B_RET | Current while dry |
| -------------------------------------- | -------- | ---------- | ---------------- | ---------- | ----------------- |
| Armed                                  | out high | out high   | input, edge wake | out low    | none              |
| Measure                                | out high | out high   | SAADC            | out low    | none              |
| Parked (after water is found)          | out low  | out low    | out low          | out low    | none              |

- **Wake threshold.** The sensing node sits at VDD × R4 / (R4 + R1 + R2 + R_water), which
  does not depend on the cell voltage. With V_IH = 0.7 VDD (to be confirmed in the nRF54L15
  datasheet) the edge fires below about 0.41 MΩ between the contacts.
- **SAADC.** The same divider reads 0.27 V at 10 MΩ, so damp contacts well above the wake
  threshold are still seen (`CONFIG_APP_LEAK_THRESHOLD_MV`). Averaging the two directions
  cancels the contacts' polarization offset.
- **Wet and armed**, at most VDD / 1.02 MΩ ≈ 3 µA flows one way until the firmware parks
  the pins.
- R1 and R2 limit current into the pins; D1 and D2 clamp ESD at the contacts.

### 5.2 MCU module: Ezurio 453-00223R (IC1)

| Pad    | nRF54L15      | Net        | Use                                               |
| ------ | ------------- | ---------- | ------------------------------------------------- |
| 5      | VDD           | VDD        | C2 10 µF, the one capacitor Ezurio requires (5.1) |
| 19     | P1.12 / AIN5  | LEAK_A     | Contact A: drive, edge wake, SAADC                |
| 23     | P1.11 / AIN4  | LEAK_B     | Contact B                                         |
| 22     | P1.09         | LEAK_A_RET | R3's return                                       |
| 21     | P1.10         | LEAK_B_RET | R4's return                                       |
| 18, 17 | P1.14, P1.04  | SDA, SCL   | U1 (firmware `i2c21`), internal pull-ups          |
| 15     | P1.05         | BUZZ       | Q1's gate: BZ1 at 4 kHz (5.5)                     |
| 12, 10 | P1.00, P1.01  | XL1, XL2   | X1, 32.768 kHz, internal load capacitors          |
| 27, 25 | SWDIO, SWDCLK | –          | J1 2, 4                                           |
| 32     | nRESET        | –          | J1 10                                             |
| 42     | P2.07         | SWO        | J1 6                                              |

- **Nordic's pin rules** decide which pins can be used: a peripheral reaches pins of its
  own port only, so I2C and PWM are on port 1; port 2 cannot wake the chip; SCL must be on
  a clock pin (Nordic DevZone, section 9). Within those rules the pads are taken in the
  order the traces leave the module: I2C toward U1, then the leak nets.
- **LEAK_A_RET** takes inner pad 22 and a via under the module, as a fourth net cannot
  leave the bottom pad row on the front. It is a static line.
- **Analog channels.** The AIN numbers are from the Ezurio pin table. 2026v4 confirmed
  P1.07 = AIN3 on hardware; AIN4 and AIN5 are unconfirmed (section 8). A wrong channel
  reads near VDD, which looks like a leak.
- **Firmware** sees this in a new board revision's overlay: the leak node's four pins and
  two SAADC channels, and the buzzer as a PWM on P1.05. The I2C pins are 2026v4's.
- All other pins are open and flagged no-connect. The module's DC/DC inductor is inside.

### 5.3 Temperature and humidity: SHT40-AD1F (U1)

U1 is at address 0x44 with C1 100 nF beside it, on I2C through the module's 13 kΩ
pull-ups. It is typically within ±1.8 %RH and ±0.2 °C (SHT4x datasheet, tables 1 and 2),
enough to watch for mold; 2026v4's SHT45 was more accurate than needed. The AD1F version
has a membrane over the sensor opening. Idle current is 0.08 µA typical (table 4).

Self-heating is negligible: the board averages about 0.05 mW. What matters is how freely
room air reaches U1. The case has one small vent beside it (5.7), so U1 follows the room
slowly. BZ1 is 2 mm away, so an alarm warms U1 for some minutes (7.1).

### 5.4 SWD pads (J1)

The Arm 10-pin Cortex debug pinout: 1 VDD, 2 SWDIO, 3, 5 and 9 GND, 4 SWDCLK, 6 SWO,
10 nRESET; 7 and 8 have pads but no connection. Land pattern in 4.2.

### 5.5 Battery and buzzer: BT1, BZ1, Q1, D3, R7

BT1 is a CR2 on wires: two 2 mm pads on the back, BAT+ (VDD) and BAT− (GND). There are no
test pads; VDD and GND are at BT1 and J1, the signals at J1 and on the parts' pads.

```
VDD ── JP1 ──┬── BZ1 + ── BZ1 − ──┬── BUZZER− ── Q1 drain   Q1 DMN2004TK, source to GND
  (BUZZER+)  ├──── D3 DLLFSD01T ──┘   (cathode to BUZZER+)
             └── C3 100 µF, not fitted ── GND
BUZZ (P1.05) ──┬── Q1 gate
               └── R7 1 MΩ to GND
```

- **BZ1**, Same Sky CMT-5023S-SMT: a magnetic transducer, 5 × 5 × 2 mm, rated 3 V at
  4 kHz, 110 mA at most, 80 dBA at least at 10 cm (datasheet). In open air that is 60 dBA
  at 1 m: R-9 with nothing to spare for the case. It has no oscillator of its own: the
  firmware drives P1.05 with a 4 kHz square wave, and Q1 switches BZ1's low side. Its
  third terminal is mechanical and left unconnected.
- **Q1**, DMN2004TK: 20 V, 0.54 A N-channel FET in SOT-523, gate protected to 2 kV. On
  resistance at most 0.7 Ω with 2.5 V on the gate and 0.9 Ω with 1.8 V: under 0.2 V lost
  at the coil's peak.
- **D3**, DLLFSD01T, an 80 V, 300 mA switching diode in SOD-523, clamps the coil's flyback
  when Q1 turns off. A low-drop diode also works, but lets the coil's current decay more
  slowly: by simulation about 10 % more cell current and 10 % less swing in the coil.
- **R7** holds Q1 off while P1.05 floats (reset, or the pin left disconnected in sleep).
- **JP1 and C3**, on the back, are an optional filter for BZ1's feed. As built, JP1 is a
  copper bridge between 0402 pads and C3 is not fitted. If BZ1's pulses turn out to
  disturb the radio (7.1), cut the bridge, solder a 2.2 to 4.7 Ω resistor across JP1's
  pads and fit a 100 µF 1206 at C3. C3 then supplies the pulses and the resistor keeps
  them out of the cell: by simulation the module's ripple falls from about 100 mV to 23
  to 35 mV with 2.2 Ω and 12 to 17 mV with 4.7 Ω, for 3 to 7 % less coil current. The
  module's own feed does not pass through JP1. When fitted, C3 leaks up to about 0.6 µA
  and stands where a J1 header's shroud goes, so a board gets one or the other and is
  flashed before C3 goes on. There are 2.0 mm between the board and the case's divider:
  check the capacitor's height.
- **Other 5 mm buzzers** were compared from their datasheets and one distributor's
  single-piece prices on 2026-11-23. All are 4 kHz magnetic transducers rated near 3 V,
  so the driver stays the same.
  - **Ole Wolff OWMB-505020S-40-12D**: 80 dB at 10 cm for $1.79 against BZ1's $3.79. The
    part to try for the next revision. Its recommended land pattern is 6.5 × 5.2 mm, which
    at BZ1's place runs past the board's edge and over SDA, SCL and BUZZ, and it is 0.1 mm
    taller. Its leads do land on BZ1's present pads, overhanging their ends by up to
    0.1 mm, so a few can be tried on a 2026v5 board first. The datasheet is one page, with
    no coil resistance, current or reflow limit.
  - Same terminals as BZ1, by their drawings: Same Sky CSS-0575A-SMT (76 dBA, $3.71),
    Mallory AST0540MW-03TRQ (75 dB, $3.11) and AST0540MW-3.6TRQ (80 dB at 3.6 V, 3.0 mm
    tall, $3.04).
  - Same leads as the Ole Wolff part: Same Sky CMT-0502-75-SMT (75 dB, $2.71) and
    CMT-0525-75-SMT (75 dB, 2.5 mm tall, $2.36).

### 5.6 PCB layout

Two layers, 1.6 mm, routed by hand. Positions are in mm from the cell's axis, +y up, seen
from the front (KiCad X = 100 + x, Y = 100 − y).

- **Outline.** 18 × 16 mm: square top corners, straight sides, and a half-ellipse bottom
  7.4 mm deep that follows the case's inner curve 0.1 mm in (5.7). The cell (Ø15.6) lies
  behind the board on its axis; the board reaches 1.2 mm past it at each side.
- **Front.** The module lies flat in the top right with its antenna end at the right
  edge. U1 and C1 are in the top left corner, by the case's vent. X1 and C2 are just left
  of the module. BZ1 is at the left edge with D3, Q1 and R7 in a row under it. The leak
  parts stand in two columns below the module, and the domes P1 and P2 are at the bottom,
  7.9 mm apart.
- **Back.** J1's pads at the left edge, behind BZ1; JP1 and C3 below them; BT1's two wire
  pads between the domes' feet. Nothing on the back is reflowed.
- **Rules** (`BL54L15μ_LeakSensor.kicad_dru`): tracks and clearance 0.1524 mm, copper at
  least 0.381 mm from the edge. Courtyards may overlap in four places where parts are
  packed on purpose: X1 and C2 against IC1's; parts inside the domes' margins; R3 and R4
  in IC1's margin; JP1 and C3 inside J1's header outline. Two DRC exclusions: J1's silk
  past the left edge and U1's label against its own outline.
- **Module and antenna.** The chip antenna is in the corner of the module's antenna end
  on pin 1's side (datasheet figure 10), which is the board's top right corner. The
  module's end is 0.18 mm from the right edge, as close as the edge rule lets its end
  ground pads come, and pin 1's side is 0.5 mm from the top. The footprint's 3 × 5 mm
  keep-out and the strip above it carry no copper on either layer. Seen from the front,
  the antenna is about 3.4 mm outside the cell's outline.
- **Leak front end.** Each contact's parts stand end to end in the chain's order: the
  1 MΩ resistor, the 10 kΩ, then the TVS diode with a ground via beside it. The two
  columns are 1.2 mm apart, so equal values sit side by side for hand assembly.
- **Domes.** The 4 mm dome footprint has a center pad and two feet in plated slots; the
  center pad is tied to both feet. Each dome is tilted 24.5° so its feet follow the bottom
  curve. The slots are 0.254 mm wide, under OSH Park's 0.508 mm minimum for drilled slots,
  as 2026v4's were. The water's resistance hardly depends on the contacts' spacing.
- **J1** sits at the left edge, not behind the module, whose under-body vias would land in
  its pads.
- **Supply.** From BT1+ along the back to JP1 and J1's pin 1, up between J1's pad
  columns, and through a via by C1 to U1, C2 and the module: about 50 mΩ. BZ1's + pad and
  D3's cathode reach JP1 and C3 through their own via.
- **Crystal.** X1's two legs are matched, 2.8 mm on the back and 2.1 mm on the front
  each, with ground poured around them on both layers.
- **Ground.** Pours on both layers outside the keep-out, stitched with 26 vias. The point
  of either pour farthest from a via is 4.8 mm away, inside the 5.3 mm (λ/8 at 2.4 GHz)
  used on the USB CO2 board (`Sim/layout.py`). Pads on the back have thermal reliefs for
  hand soldering.
- **Silkscreen.** References at 0.75 mm beside their parts, + and − at BT1, and the
  title, revision and company on the back.

### 5.7 Case

`Case/build_case.py` builds the case in FreeCAD from the parameters at its top, saves
`Case/LeakSensor_2026v5.FCStd` and checks the fits. The file also holds the board (KiCad's
STEP export), the cell, the battery contacts and the leak pins as reference parts.

The case is an open-top body with a lid that slides on from the rear, 21.3 × 56.5 ×
18.45 mm. The board stands across the front with the cell lying behind it. The board sets
the width and height: 1.5 mm walls, a 1.0 mm floor and a 1.2 mm lid around it. The bottom
is a half ellipse, 8.5 mm deep outside, which the board's bottom edge follows; both ends
are half domes of the same section.

- **Printing.** With no flat on the bottom, the body needs supports either way up. The
  print plate (`LeakSensor_2026v5.3mf`) has it upside down on its rim: the whole outside
  then prints without support, and the supports go inside, under the floor and the
  panels' top edges, all reachable from the open top. The bosses and the cell's seats are
  shaped to print without any.
- **Board slot.** The board drops in from the top between 0.4 mm lips, front and back,
  along its sides and bottom, and rests 0.1 mm above the floor. The front lip is cut away
  where parts stand close to the edge (the module's end, D3 and BZ1). The domes push the
  board back, so its front face is the datum: crush ribs behind it hold it against the
  front lip. The dome press then depends on two faces of one print, not on the board's
  thickness. The least gap between the case and any front-side part is 0.28 mm.
- **Leak pins.** Two Ø2.5 × 6 mm flat-ended metal pins stand upright just in front of the
  domes. Each is pushed up from below into a blind bore in a boss on the front wall. The
  side of each pin presses its dome's apex through a gap in the bore: 0.1 mm of press on a
  dome assumed 0.3 mm high (`DomeApex`, `PinPress`). The pins' ends are flush with the
  bottom curve where they exit, 0.28 mm above the table, so water has to stand that deep
  to reach them.
- **Cell.** Keystone 209 leaf spring (−) on a 1.6 mm divider behind the board and 228
  button (+) on a 1.6 mm rear panel; both clip onto 1.52–1.78 mm panels. The 209 is
  assumed compressed to 2.5 mm. The cell rests in two V-shaped saddles, and two ribs
  under the lid hold it down.
- **Wiring.** BT1's pads face the divider across a 2.0 mm gap, where the 209's tab is.
  The + wire runs from the 228's tab behind the rear panel forward over both panels, in
  the bay's upper left corner.
- **Vent.** One 1.0 × 2.0 mm slot in the left wall beside U1 (5.3). There is no other
  opening: BZ1 sounds through the closed case.
- **Lid.** A 1.2 mm plate with a tongue under each side, just inside the walls. A 45°
  ridge on each tongue runs in a groove in the wall, so the lid cannot lift, and a bump
  on each tongue snaps into a notch at the end of travel. The lid also carries the top of
  the rear dome. The fits are those proven on the hygrometer 2026v3's case: sliding faces
  drawn line to line, and only the groove cut 0.05 mm larger.
- **Checks.** The script checks that the body, lid, board and its parts, cell, contacts,
  pins and + wire do not overlap, that the board drops in and the lid slides off without
  touching anything else, and that both parts mesh to closed solids. BZ1's model is not a
  solid and Q1 has none, so boxes stand in for them. J1's header is left out: a board
  with a header does not fit.

## 6. Bill of materials

| Ref     | Value                   | Part                                    | Footprint            | Description                           |
| ------- | ----------------------- | --------------------------------------- | -------------------- | ------------------------------------- |
| IC1     | BL54L15μ                | Ezurio 453-00223R                       | module               | nRF54L15 module, chip antenna (5.2)   |
| U1      | SHT40                   | SHT40-AD1F-R2                           | DFN-4 1.5 mm         | Temperature and humidity (5.3)        |
| X1      | 32.768 kHz, 9 pF        | CM7V-T1A-LOW-ESR-32.768KHZ-9PF-20-TA-QC | 3.2 × 1.5 mm         | Low-frequency crystal                 |
| C1      | 100 nF                  | GRM155R61A104KA01J                      | 0402                 | U1 decoupling                         |
| C2      | 10 µF                   | CL10A106KP8NNNC                         | 0603                 | Module supply                         |
| D1, D2  | TVS                     | TPD1E10B06DPYR                          | 0402                 | ESD clamp at the contacts (5.1)       |
| R1, R2  | 10 kΩ                   | RC0402FR-0710KL                         | 0402                 | Contact series resistors (5.1)        |
| R3, R4  | 1 MΩ                    | RC0402FR-071ML                          | 0402                 | Sense pull-downs to GPIO (5.1)        |
| P1, P2  | 4 mm metal dome         | to be chosen                            | TriangleDome 4 mm    | Leak contacts (5.6)                   |
| J1      | 2×5 1.27 mm, optional   | CNC Tech 3220-10-0300-00                | custom pads (4.2)    | SWD; hand-soldered on a few boards    |
| BZ1     | Buzzer, 3 V, 4 kHz      | Same Sky CMT-5023S-SMT-TR               | 5 × 5 mm, 3 pads     | Magnetic transducer (5.5)             |
| Q1      | DMN2004TK               | DMN2004TK-7                             | SOT-523              | Buzzer switch (5.5)                   |
| D3      | DLLFSD01T               | DLLFSD01T-7                             | SOD-523              | Flyback clamp across BZ1 (5.5)        |
| R7      | 1 MΩ                    | RC0402FR-071ML                          | 0402                 | Q1 gate pull-down (5.5)               |
| BT1     | CR2 on wires            | –                                       | two 2 mm pads        | Cell (5.5)                            |
| JP1     | copper bridge           | –                                       | 0402 pads, bridged   | Optional: cut, fit 2.2 to 4.7 Ω (5.5) |
| C3      | 100 µF, not fitted      | to be chosen                            | 1206                 | Optional reservoir for BZ1 (5.5)      |

The case adds two Ø2.5 × 6 mm pins, Keystone 209 and 228 contacts and two wires (5.7).

3D models: U1 uses Sensirion's SHT45-AD1F model, the same package
(`Components/SHT45_AD1F_R2`). D1 and D2 use KiCad's 0402 resistor model, the same
1.0 × 0.6 mm body. BZ1 uses Same Sky's (`Components/Same_Sky_CMT-5023S-SMT-TR`) and Q1
the DMN2004TK's from Ultra Librarian (`Components/ul_DMN2004TK-7`), turned 90° to match
the footprint.

## 7. Verification

### 7.1 By calculation and simulation

`Sim/sim.py` runs the circuit checks (ngspice for the buzzer driver and the leak front
end), `Sim/layout.py` the layout checks with KiCad's Python, and `Case/build_case.py` the
fits (5.7). Values no datasheet gives are marked ASSUMED in the scripts and listed below.

| Check                         | Result                                                              | Verdict |
| ----------------------------- | ------------------------------------------------------------------- | ------- |
| ERC, DRC, schematic parity    | 0 errors and warnings, 0 unconnected, 0 parity issues; 2 exclusions (5.6) | pass |
| Edge wake threshold           | sense node at 0.7 VDD below 0.41 MΩ, back under 0.3 VDD above 2.3 MΩ | as designed (R-1) |
| Leak settling                 | 99 % in 71 µs at 10 MΩ, faster below; the firmware waits 100 µs     | pass |
| SAADC, 40 µs acquisition      | −1.3 % at 10 MΩ with a 2.5 pF sampling capacitor, −7 % at 10 pF     | pass (R-4) |
| False leak from leakage       | 10 nA into the sense pin reads as 300 MΩ; 100 MΩ of film reads as itself | pass |
| ESD at a dome, 8 kV contact   | about 30 A in the TVS, clamped near 22 V; 1.9 mA through R1 into the pin | pass |
| Buzzer, coil current          | peak 124 to 227 mA, 45 to 94 mA from the cell, for 3 to 0.3 mH       | within 110 mA |
| Buzzer, Q1 and D3             | drain clamped at 3.9 V; Q1 under 12 mW; D3 13 to 41 mA average       | pass |
| Buzzer, brown-out             | module stays above 1.7 V up to 8 Ω of cell resistance at 3.0 V, 4 Ω at 2.4 V | pass |
| Buzzer, supply ripple         | 60 to 120 mV peak to peak at the module on a 0.5 Ω cell             | **over Ezurio's 10 mV** |
| The same, JP1 and C3 fitted   | 23 to 35 mV with 2.2 Ω and 100 µF; 12 to 17 mV with 4.7 Ω           | optional fix (5.5) |
| Buzzer, heat                  | about 170 mW beside U1; the board warms roughly 1 K in 10 s, 5 K in 60 s | **U1 reads high** |
| Buzzer, charge                | about 1 mAh a minute at 1 mH, up to 1.8 mAh at the rated 110 mA      | note |
| I2C rise time                 | 91 to 115 ns on 8.5 pF with the 13 to 16 kΩ pull-ups; 300 ns allowed | pass at 400 kHz |
| Crystal load                  | board stray adds about 0.5 pF: 6 ppm fast unless trimmed out         | trim in firmware |
| Dome press                    | 0.1 mm nominal with 0.1 mm spread: no contact on 16 % of pins       | **too little** |
| Ground stitching              | farthest pour point 4.8 mm from a via; 6.1 % over 3 mm               | pass (5.3 mm) |
| Ground under traces           | back pour under 62 to 82 % of the leak and I2C traces; gaps at most 1.8 mm | fine at these speeds |
| Case fits                     | no overlap; least gap to a front part 0.28 mm; board drops in, lid slides off | pass |

- **Assumed values.** The buzzer coil's inductance (1 mH, swept from 0.3 to 3 mH; Same
  Sky gives only its 12 ± 3 Ω), the cell's resistance (0.5 Ω), V_IH (0.7 VDD) and the
  SAADC's sampling capacitor, 5 pF for the pin and trace, the board as one thermal lump
  (1.5 J/K losing 12 mW/K), and the print's spread at the domes (0.08 mm for the bore,
  0.05 mm for the slot, 0.03 mm for the dome).
- **Supply ripple.** The cell's resistance sets it; C2 is 8 Ω at 4 kHz and does little.
  Ezurio's table 3 allows 10 mV of ripple on VDD "that does not disturb the radio", so the
  firmware should beep between radio events.
- **Heat.** The firmware should mark temperature and humidity as suspect during an alarm
  and for some minutes after.
- **Low cell.** With the worst gate threshold (1.0 V) on a 2.0 V cell, Q1 still switches
  fully.
- **Leak front end.** The node capacitance (12 pF of TVS plus the pin and trace) holds
  the SAADC's sample, so the reading is right even though 1 MΩ is over Nordic's 800 kΩ
  for a 40 µs acquisition.
- **Dome press.** With the assumed spread, a 0.2 mm nominal press misses on 2 % of pins
  and 0.25 mm on 0.6 %. A dome pressed flat still connects, so more press costs nothing
  electrically; `PinPress` stays at 0.1 mm until a dome is chosen.
- **Not simulated.** The antenna (the RSSI test below decides), battery life (needs
  2026v4's measured current), and the sound level through the closed case.

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

- **Antenna.** The chip antenna is in the board's corner, where the datasheet prefers the
  center of an edge (sections 5.2, 5.3.1, 6.2), and the cell is a few millimeters behind
  it. Metal within 20 mm "will begin to significantly degrade performance" (5.3.2): BZ1, a
  coil and magnet, is about 14 mm from the chip, X1 10 mm, the right leak pin 12 mm. The
  RSSI test decides whether this layout holds.
- **Battery life** is a target, not an estimate: the module idles at 3 µA (Ezurio
  datasheet, section 2.1) and the SHT40 at 0.08 µA, which leaves about 12 µA for Thread
  polling and reports. A 2026v4 current measurement comes first.
- **Input threshold.** V_IH and any input hysteresis are to be read from the nRF54L15
  datasheet. A slowly wetting contact holds the sense node near the threshold, so the
  firmware should debounce the edge.
- **Dome.** The 4 mm dome part is not chosen. The case's 0.3 mm dome height and 0.1 mm
  press need checking against its drawing and a test print; expect to raise the press to
  0.2 mm or more (7.1).
- **Pogo clip.** J1's pads accept rows 1.27 or 2.54 mm apart; check against the clip used,
  and that BZ1 takes its other jaw.
- **Buzzer.** The CR2's resistance cold and partly used is not known, and it sets both
  the brown-out margin and the ripple (7.1). Whether that ripple costs packets is not
  known either; JP1 and C3 are there if it does (5.5). BZ1 meets R-9 in open air with
  nothing to spare, and its level through the closed case is untested. It also costs
  about twice what an Ole Wolff part of the same rating does (5.5).
- **Analog channels.** AIN4 (P1.11) and AIN5 (P1.12) have not been read on hardware.
- **Firmware.** Needs a new board revision, a leak driver for four pins and both
  directions, and the buzzer as a 4 kHz PWM on P1.05, sounded between radio events.
  Whether the board keeps the name `bl54l15u_hygrometer` is open.
- **Case.** Unprinted. The contacts' dimensions come from Keystone's catalog drawing, not
  parts in hand, and the lid's slide fit and detent need a test print. On a table the
  case rests on the lowest line of its curved bottom, and the pins need water about
  0.28 mm deep.

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
  updated 4 November 2025, and the Same Sky CSS-0575A-SMT, CMT-0502-75-SMT and
  CMT-0525-75-SMT and Mallory Sonalert AST0540MW-03TRQ and AST0540MW-3.6TRQ datasheets:
  ratings and drawings of the other 5 mm buzzers (5.5).
- [CNC Tech 3220-XX-0300-00 drawing](https://cnctech.us/pdfs/3220-XX-0300-00_.pdf), revision D,
  10 April 2023: P.C.B layout (pads 0.65 × 2.77 mm, 6.80 mm across), tails 5.50 ± 0.30 mm
  across (4.2).
- Diodes Incorporated DMN2004TK datasheet (DS30936): gate threshold 0.5 to 1.0 V, on
  resistance 0.7 Ω at 2.5 V and 0.9 Ω at 1.8 V at most, 2 kV gate protection; SOT-523
  outline, body up to 0.8 mm with up to 0.1 mm standoff (5.5, 5.7, 7.1).
- Diodes Incorporated DLLFSD01T datasheet: 80 V, 300 mA forward continuous, 0.82 V at
  10 mA (5.5).
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
  stitching distance and the module's distance from the edge (5.6).
- `HW/BL54L15μ_Hygrometer/Case/Hygrometer_2026v3.FCStd` in this repository: the slide-in
  lid this case follows (5.7).
