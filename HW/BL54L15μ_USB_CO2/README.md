# USB CO2 sensor

## 1. Scope

A USB-powered indoor air sensor built on the Ezurio BL54L15μ (nRF54L15) module. It measures
CO2 with a Sensirion SCD43, temperature and humidity with an SHT4x, and pressure and gas
resistance with a BME68x. It joins a Thread network as an always-on router.

Revision 2026v2 is in progress: the SHT4x moves from 2026v1's slotted island onto a zigzag
finger cut from the board's left edge (5.5, 5.9), and its traces are not routed yet.
2026v1 was ordered on 2026-11-21 and is tagged `fab/BL54L15μ-usb-co2/2026v1`.

## 2. Background

This board aims to be an accurate, set and forget CO2 sensor. No battery that needs replacement.

Programming and the serial console use the USB-C receptacle that powers the board, with
the pinout of `HW/BL54L15μ_DevKit` mirrored, so `HW/SWD_USBC_InlineAdapter` works
unchanged, plugged in the other way up (5.1).

## 3. Requirements

| ID   | Requirement                                                                         |
| ---- | ----------------------------------------------------------------------------------- |
| R-1  | Report CO2 every 30 s, accuracy at least ±(50 ppm + 3 %) over 400 to 5000 ppm       |
| R-2  | Report temperature and humidity every 30 s, accuracy at least ±0.2 °C and 2 %RH     |
| R-4  | Run from any 5 V USB-C source, drawing under 500 mA peak                            |
| R-5  | Keep the radio powered continuously (Thread router); no battery                     |
| R-6  | SWD, reset, SWO and a UART on the USB-C receptacle, for the DevKit's adapter        |
| R-7  | CO2 sensor supply: holds 205 mA peaks, moves less than 30 mV because of other loads |
| R-9  | Fit a small square enclosure with rounded corners; USB and vents on the rear face   |
| R-10 | Single-sided surface-mount assembly, one reflow pass on a hot plate, no board wash  |
| R-11 | Keep the sensor bus the hygrometer firmware already uses: same pins, MCU pull-ups   |
| R-12 | Module supply: ripple and noise under 10 mV, the limit for an undisturbed radio     |

## 4. Design trades

### 4.1 CO2 sensor

|                          | STCC4                          | SCD41                        | **SCD43**            |
| ------------------------ | ------------------------------ | ---------------------------- | -------------------- |
| Principle                | thermal conductivity           | photoacoustic                | photoacoustic        |
| Accuracy, 400–5000 ppm   | ±(100 ppm + 10 %)              | ±(50 ppm + 2.5 %) ¹          | ±(30 ppm + 3 %)      |
| Average current at 3.3 V | 0.95 mA continuous, 0.1 mA single shot every 10 s | 15 mA periodic, 3.2 mA low power periodic | same as SCD41 |
| Peak current at 3.3 V    | 4.2 mA max                     | 205 mA max                   | 205 mA max           |
| Size                     | 4 × 3 × 1.2 mm                 | 10.1 × 10.1 × 6.5 mm         | 10.1 × 10.1 × 6.5 mm |
| Self-calibration         | automatic, expects fresh air once a week | automatic, same expectation | same as SCD41 |
| Warm-up                  | up to 1 h after 3 h unpowered, 12 h on first use | none specified | none specified |

¹ In its 400–1000 ppm band; ±(50 ppm + 3 %) from 1001 to 2000 ppm and ±(40 ppm + 5 %) above.

Sources (section 9): STCC4 datasheet, tables 1 and 3, sections 1.1.2 to 1.1.4 and figure
3; SCD4x datasheet, tables 1 and 4 and section 3.8.

**Chosen: SCD43.** It is the most accurate of the family over the whole range, and with
USB power its 15 mA average and 205 mA peaks are free. The SCD40, SCD41 and SCD43 share one
package, land pattern and command set, so the footprint also takes an SCD41. The unreleased
SCD5x may be a better choice once released, but its specs are not yet known.

### 4.2 USB receptacle

**Chosen: GCT USB4056-03-A**, the DevKit's 24-contact receptacle (surface-mount front row,
through-hole back row). The DevKit puts SWD on the SuperSpeed TX pairs and the UART on an
RX pair (5.1); a 16-contact USB 2.0 receptacle has no contacts there, so only a full one
can carry the same pinout.

### 4.3 Regulation

|                               | **One LDO** | Two LDOs            | Buck              | SCD43 on VBUS       |
| ----------------------------- | ----------- | ------------------- | ----------------- | ------------------- |
| SCD43 rail moved by other loads | under 1 mV | no                  | plus ripple       | USB source noise    |
| MCU rail sees 205 mA pulses   | yes         | no                  | yes               | no                  |
| Parts                         | 3           | 6                   | 5 or more         | 3                   |
| Heat at 48 mA average         | 94 mW       | 94 mW               | about 25 mW       | 60 mW               |
| I2C levels                    | fine        | fine                | fine              | VIH 3.25 V at 5 V   |

Part counts and heat are calculated (an LDO from 5.25 V to 3.3 V at 48 mA dissipates
94 mW); the rest is from the datasheets in section 9.

**Chosen: one AP2112K-3.3 for the whole board.** The SCD4x datasheet (section 2.3) says the
supply "must not vary by more than 30 mV" because of other loads and recommends a separate
LDO, advice aimed at boards where a radio or motor shares the rail. Here the other loads
step by 10 to 30 mA, which the AP2112's worst-case load regulation of 1 %/A turns into
1 mV at most. The SCD43's own 205 mA pulses dip the shared rail, but the SHT4x
(1.08–3.6 V) and BME680 (1.71–3.6 V) do not mind.

The module could, for all its 1.7–3.5 V range: its datasheet (table 3) allows only 10 mV
of ripple or noise on its supply, at any frequency, as the level that does not disturb the radio (R-12). The 205 mA
step moves the output by 1.4 mV typical and 6.8 mV worst case in steady state. The
AP2112's load-transient figure shows about 10 mV for a 0 to 600 mA step with 1 µF on the
output; here the step is a third of that and the rail carries 21 µF, so the dip should be
smaller. That is an estimate, not a measurement (section 7). If it fails, the fixes are a
separate regulator for the SCD43, as Sensirion recommends, or a small resistor ahead of C3
so the module sits behind its own filter.

A buck would save about 25 mW at typical load, about 0.8 °C of the SHT4x's steady offset
(5.9), which firmware subtracts anyway. Feeding the sensor from VBUS
would put the source's noise on it and raise its I2C threshold to 0.65 × VDD (SCD4x
table 4), 3.25 V at 5 V, which a 3.3 V bus only just meets.

## 5. Circuit

```
 J1 USB-C
  VBUS o--+--[R1 1Ω]------+---- VIN ----[U1 AP2112K-3.3]---- VDD --+-- IC1 module
          |               |                                       +-- U2 SCD43
      [D1 clamp]         [C1]                                     +-- U3 SHT4x
          |               |                                       +-- U4 BME68x
  GND  o--+---------------+---- GND                               +-- SBU2 (VTref)
  CC1  o--[R2 5.1k]-- GND
  CC2  o--[R3 5.1k]-- GND                    IC1 P1.14, P1.04 ---- I2C ---- U2, U3, U4
  TX2+/- o--[D1]-- SWDIO, SWDCLK -- IC1      IC1 P2.04 --[R4]--[D2 LED]
  TX1+/- o-- nRESET (JP1), SWO ---- IC1      IC1 P0.01 ---- SW1 ---- GND
  RX2-/+ o-- UART TXD, RXD -------- IC1
```

### 5.1 USB-C receptacle and debug pinout (J1)

| Contact          | USB-C name | Signal    | Goes to                          |
| ---------------- | ---------- | --------- | -------------------------------- |
| A4, A9, B4, B9   | VBUS       | VBUS      | D1 and R1                        |
| A1, A12, B1, B12 | GND        | GND       | ground, with the shell           |
| A5               | CC1        | CC1       | R2, 5.1 kΩ to ground             |
| B5               | CC2        | CC2       | R3, 5.1 kΩ to ground             |
| B2               | TX2+       | SWDIO     | D1, then module pin 27           |
| B3               | TX2−       | SWDCLK    | D1, then module pin 25           |
| A2               | TX1+       | nRESET    | JP1, then module pin 32          |
| A3               | TX1−       | SWO       | module pin 42 (P2.07)            |
| A10              | RX2−       | UART_TXD  | module pin 21 (P1.10), MCU out   |
| A11              | RX2+       | UART_RXD  | module pin 19 (P1.12), MCU in    |
| B8               | SBU2       | VDD       | 3.3 V reference for the probe    |
| A8               | SBU1       | GND       | ground                           |
| A6, A7, B6, B7   | D+, D−     | –         | not connected                    |
| B10, B11         | RX1−, RX1+ | –         | not connected                    |

- This is the DevKit's J2 pinout mirrored: each debug contact is swapped with its partner
  in the other row (A2 with B2, A10 with B10 and so on), so the inline adapter works
  unchanged when plugged in the other way up. The mirror puts SWD and the UART on the
  receptacle's west half and nRESET and SWO on its east half, the sides of the module
  their pads are on.
- Plugged in the wrong way up, the debug signals land on other contacts and do nothing,
  and the adapter's LED lights.
- The DevKit hands CC1 and CC2 to its PMIC; this board has none, so each gets the 5.1 kΩ
  pull-down (Rd) the USB Type-C specification requires of a sink. Sharing one resistor
  breaks detection with electronically marked cables.
- The nRF54L15 has no USB interface, so D+ and D− are open and no host ever configures
  the board. USB 2.0 (section 7.2.1) holds such a device to one unit load, 100 mA, as "an
  absolute maximum, not an average over time"; the SCD43's pulses take this board to
  about 240 mA. Chargers do not enforce that; whether a computer's port does is untested.
- UART direction is named from the MCU. Both pins are ordinary port 1 GPIOs, so firmware
  can swap them if a cable is wired the other way.
- JP1 is a solder jumper on the bottom, bridged in copper (section 8).
- J1 is the only connector. A USB-C charger or a USB-A to USB-C cable powers the board;
  with `SWD_USBC_InlineAdapter` between cable and board, turned over, SWD, reset, SWO and
  the UART work too.

### 5.2 VBUS input: R1, D1 and C1

| Requirement          | Limit                                   | Source               |
| -------------------- | --------------------------------------- | -------------------- |
| LDO input, operating | 6.0 V                                   | AP2112 line regulation and EN ranges |
| LDO input, absolute  | 6.5 V                                   | AP2112 absolute maximum ratings      |
| VBUS, normal         | 5.5 V max                               | USB Type-C                           |

Plugging a live cable into a ceramic input capacitor makes a series RLC circuit that can
ring to nearly twice the source voltage. C1 (4.7 µF, 0603, 10 V X5R) keeps perhaps 2 µF at
5 V, a typical figure not checked against this part. With about 1 µH of cable the
characteristic impedance √(L/C) is about 0.7 Ω; a cable's own 0.2 Ω gives a damping ratio
near 0.15 and about 60 % overshoot, 8 V, above the regulator's absolute maximum.

- **R1, 1 Ω** raises the damping ratio to about 0.85, under 1 % overshoot. At the 240 mA
  worst-case peak it drops 0.24 V, which still leaves the LDO over 0.6 V of headroom at a
  4.4 V input (4.75 V at the source less the cable drop allowed at 500 mA, R-4). Anything
  from about 0.7 to 2.2 Ω works. The first boards have R1 bridged (section 8).
- **C1 is 4.7 µF**, not the regulator's 1 µF minimum, because damping depends on the
  capacitance left under bias. Keeping only 30 % of its value, C1 still holds the
  overshoot under 5 %; a 2.2 µF 0402 part would leave about 10 %.
- **D1, USBLC6-2SC6**, clamps ESD on VBUS and both SWD lines. Its datasheet (section 2.3)
  wants it "as close as possible to the disturbance source (generally the connector)"
  with short tracks: it reckons 6 nH per 10 mm of track, about 144 V more clamping
  voltage on an 8 kV discharge. Its near pads are 2 mm from the receptacle's pin row.
  - **It is in series with the SWD lines.** Each line enters at one pin of a pair (1 and
    6, 3 and 4, joined inside the package) and leaves from the other, and no board
    copper joins a pair, so a discharge has no path around the clamp. The schematic
    enforces this with separate nets, SWDCLK_USB and SWDIO_USB on the receptacle side,
    so DRC reports any copper joining a pair. SWD therefore needs D1 fitted; without it,
    bridge pads 1 to 6 and 3 to 4.
  - VBUS comes from the receptacle's through-hole VBUS pins on the bottom layer to a via
    under the body and passes pin 5 on its way to R1, 7 mm from the nearer pin.
  - Its ground pin runs 3.4 mm on a 0.3 mm trace to the receptacle's A8 contact, tied to
    ground as the probe's reference, and sits solidly in the top pour.
  - It adds at most 3.5 pF per SWD line and leaks at most 150 nA at 5 V. Its 6 V minimum
    breakdown keeps it off at the 5.5 V VBUS maximum.
- Total capacitance on VBUS is 4.7 µF, under the 10 µF a USB device may present.

### 5.3 Regulator: AP2112K-3.3 (U1)

| Datasheet value        |                                   | Requirement                    |
| ---------------------- | --------------------------------- | ------------------------------ |
| Output                 | 3.3 V ±1.5 %, 600 mA min          | 240 mA peak                    |
| Dropout at 300 mA      | 125 mV typ, 200 mV max            | 0.6 V available                |
| Load regulation        | 0.2 %/A typ, 1 %/A max            | 30 mV (R-7)                    |
| Thermal resistance     | 184 °C/W junction to ambient      | see below                      |
| Enable                 | high above 1.5 V, 3 MΩ pull-down  | tied to VIN                    |
| Capacitors             | 1 µF ceramic, X5R or X7R, in and out | C1 4.7 µF, C2 1 µF          |

- Heat: 1.95 V of drop at 5.25 V in, times an average of 48 mA (18 mA maximum for the
  SCD43 plus an assumed 30 mA for everything else), is 94 mW and a 17 °C junction rise.
  A 205 mA pulse dissipates about 0.46 W for its duration.
- R-7: a 30 mA step from the MCU or the BME68x moves the output by 0.2 mV typical, 1 mV
  worst case. The edge of the SCD43's own pulses is on the test list.
- The enable pin must be driven; it is tied to VIN, so the rail comes up with the cable.

### 5.4 CO2 sensor: Sensirion SCD43-D-R2 (U2)

| Datasheet value           |                                      | Requirement    |
| ------------------------- | ------------------------------------ | -------------- |
| Accuracy, 400–5000 ppm    | ±(30 ppm + 3 % of reading)           | R-1            |
| Update interval           | 5 s periodic, 30 s low-power         | 30 s (R-1)     |
| Supply                    | 2.4–5.5 V, 6.0 V absolute            | 3.3 V          |
| Peak supply current       | 175 mA typ, 205 mA max at 3.3 V      | U1: 600 mA     |
| Average supply current    | 15 mA typ, 18 mA max at 3.3 V        | –              |
| Supply variation unloaded | 30 mV peak to peak max               | see 4.3, 5.3   |
| I2C address               | 0x62, standard and fast mode         | shared bus     |
| Operating range           | −10 to 60 °C, 0–95 %RH               | indoor         |

- VDD and VDDH sit on opposite sides of the package and "must be connected to each other
  close to the sensor". A 0.4 mm bottom-layer trace joins them under the part: 14.5 mm,
  about 18 mΩ.
- The sensor is turned so VDD and the I2C pads face the regulator and the module.
- **Each supply pad has the capacitor that suits it.** VDDH feeds the infrared source and
  draws the 205 mA pulses: C4 (10 µF) is 3 mm of trace away, so the pulses come from the
  capacitor, not through the link. VDD feeds the logic and I2C and is the noise-sensitive
  pad: C5 (100 nF) sits at it, and the supply passes C5 on the way in.
- The DNC pads are soldered to pads that connect to nothing, as the datasheet requires.
- The 0.6 mm circle the datasheet keeps "free from solder and flux" under the sensor's
  thermal relief hole (section 4.2, figure 4) is clear: no pad, paste, mask opening, via
  or trace within 0.3 mm. The pour there is under solder mask.
- It sits in the rear right corner, its center 7.4 mm from the rear edge. At about 50 mW
  in its 5 s mode it is the largest steady heat source; it, the regulator and the BME68x
  share the right side, and the SHT4x has the left side to itself.
- It may be reflowed once, must not be washed, and reads slightly off for up to five days
  after soldering.

### 5.5 Temperature and humidity: SHT4x (U3)

The SCD43 also reports temperature and humidity, but only to ±0.8 °C and ±6 %RH typical,
and it heats itself. The SHT4x is the reference for R-2. It sits at the rear tip of a
finger cut from the board's left edge, behind the vents: the finger joins the board only at
its front end, its path folds into a zigzag, no pour reaches it, and only the sensor's own
traces run along it (5.9). It is 27 mm from the SCD43, 31 mm from the BME68x and 24 mm from
the regulator. Address 0x44, with C6 (100 nF) beside it on the finger.

### 5.6 Pressure and gas: BME680 or BME688 (U4)

Both parts share the 3 × 3 mm LGA-8 package and pinout, numbered clockwise in top view.
Wired for I2C: CSB to VDDIO, SDO to ground for address 0x76, the address the hygrometer
firmware uses. It heats itself when it measures gas, so it sits on the warm right side,
in front of the SCD43, 31 mm from the SHT4x and outside the SHT4x's chamber in the case.

C7 (100 nF) sits at VDD (pin 8) and its neighboring ground; VDDIO (pin 6) joins VDD under
the package, and CSB (pin 2), walled in by SDA and SCL, reaches that link through two vias.
The datasheet shows a capacitor on each supply pin (section 7.2) for boards where they are
separate rails; here they are one rail 1.6 mm apart and VDDIO only powers the interface,
so one capacitor at the loaded pin does both jobs.

Its pressure reading feeds the SCD43's pressure compensation (`set_ambient_pressure`,
SCD4x section 3.7.5). Nothing else depends on it: without U4 and C7 the CO2 reading is
compensated for a fixed pressure or altitude only.

### 5.7 MCU module: Ezurio 453-00223R (IC1)

| Module pin | nRF54L15 | Signal    | Use                                    |
| ---------- | -------- | --------- | -------------------------------------- |
| 5          | VDD      | VDD       | C3 10 µF, the one capacitor the module's datasheet requires |
| 18         | P1.14    | SDA       | I2C (firmware `i2c21`): SCD43, SHT4x, BME68x |
| 17         | P1.04    | SCL       |                                        |
| 45         | P2.04    | LED       | D2 through R4, active high             |
| 35         | P0.01    | BUTTON    | SW1 to ground, internal pull-up        |
| 21         | P1.10    | UART_TXD  | J1 A10                                 |
| 19         | P1.12    | UART_RXD  | J1 A11                                 |
| 25, 27     | SWD      | SWDCLK, SWDIO | J1 B3, B2 through D1               |
| 32         | nRESET   | nRESET    | J1 A2 through JP1                      |
| 42         | P2.07    | SWO       | J1 A3                                  |
| 12, 10     | P1.00, P1.01 | XL1, XL2 | X1, 32.768 kHz                      |

- **One I2C bus, no pull-up resistors.** All three sensors share the pins the hygrometer
  firmware uses for the SHT4x (R-11), with the nRF54L15's internal pull-ups (13 kΩ
  typical, Ezurio datasheet) at 100 kHz. With 30 pF on the bus the rise time is about
  0.33 µs, well inside the 1 µs 100 kHz allows. The sensors update every few seconds.
- The LED, button and UART pins were picked for routing: the button on port 0 and the
  UART on port 1, which have GPIO interrupts and UART instances, the LED on port 2. The
  firmware needs a new board definition.
- The module runs its regulator in DC/DC mode with the inductor inside; nothing external.
- X1 uses the nRF54L15's internal load capacitors (9 pF), as the firmware configures.
- All other pins are open.

### 5.8 LED, button and test points

- D2 with R4 (680 Ω) on P2.04 is the Matter status and pairing indicator: about 2 mA with
  a red, amber or yellow LED (about 2 V). A blue, white or true-green one (about 2.9 V)
  would get about 0.6 mA.
- SW1 on P0.01: factory reset and pairing, as on the hygrometer. It is at the rear edge
  left of the receptacle, D2 at the rear edge on the right, R4 beside the module. Both
  are inside the case: the button is reached with the shell off and the LED shows
  through the rear vents. There is no reset button; reset comes over the adapter or a
  power cycle.
- TP1–TP3 bring out VBUS, VDD and GND for section 7, TP4 and TP5 SCL and SDA. TP1 is
  beside R1, TP2–TP5 in a column on the right edge; TP6 (SWDIO) and TP7 (SWDCLK) sit on
  the debug lanes left of center.
- R5 (SDA) and R6 (SCL) are unfitted 0603 footprints for 4.7 kΩ I2C pull-ups, for 400 kHz
  or slow edges. They sit on the VDD trunk south of the regulator.

### 5.9 PCB layout

```
              rear: vents and USB
 +-----+  +----------------------------+
 | U3  |  |button [  USB-C  ] D2   C4  |
 | C6  |  |       [         ]+-------+ |
 |   ===  |       [         ]| SCD43 | |
 ===   |  |    o  D1 R2 R3   +-------+ |
 |   ===  |  TP1 R1 C1 LDO C2  BME68x  |
 ===   |  |             R5 R6   TP5    |
 |   ===  |            JP1      TP4    |
 ===   |  |     X1 C3           TP2    |
 |   ===  |  +--------+ R4      TP3    |
 |     '--'  | module |                |
 | o         |        |             o  |
 +-----------+--ant.--+----------------+
               front     o = M2 hole; === = notches
```

| Rule                         | Value                                   | Basis                                    |
| ---------------------------- | --------------------------------------- | ---------------------------------------- |
| Outline                      | 35 × 35 mm, 5 mm corner radius, less the SHT4x finger's cut and notches; the uncut outline is on User.1 | R-9; close to the smallest square that takes these parts with the receptacle centered on the rear edge |
| Mounting                     | three 2.2 mm unplated holes: one 12 mm in from the rear edge beside D1, two in the front corners 3 mm in from both edges | pegs on the case tray; no screws, so no metal near the antenna |
| Hole keep-out                | no tracks or vias within 2.2 mm of a hole center; nearest is a ground via at 2.77 mm | room for an M2 head if screws are ever used |
| Layers                       | 2, 1.6 mm, 1 oz                         | lowest-cost prototype stack              |
| Trace and space              | ≥ 0.1524 mm; signals 0.2 mm, 0.1524 mm at fine-pitch pads and on the SHT4x finger | the fab's 6 mil minimum; net class Default |
| Power traces                 | VBUS, VIN and VDD 0.4 mm; 0.3 mm at the receptacle's VBUS pads and into the module; 0.15 to 0.2 mm for VDD branches that carry no current | net class Power; 6 mV drop per 25 mm at 205 mA |
| Vias                         | 0.508/0.254 mm; 0.6/0.3 mm on VBUS and at the front of the VDD link under the SCD43 | the fab's 0.254 mm minimum drill |
| Copper to board edge         | 0.381 mm to the outline, the finger's cut and notches included (custom rule in `BL54L15μ_USB_CO2.kicad_dru`) | the fab's 15 mil keep-out for milled edges |
| Annular ring                 | ≥ 0.1 mm                                | the receptacle's 0.6/0.4 mm pins (section 8) |
| Ground pour                  | one zone on both layers, 0.1524 mm clearance and minimum width; surface-mount pads solid, through-hole pads with 0.2 mm spokes and gap | the fab's 6 mil minimum; hot-plate reflow needs no reliefs on surface-mount pads |
| Ground stitching             | 72 ground vias, to recheck after routing; 2026v1 had 81, with no point of pour more than 4.9 mm from one (the worst under the SCD43's center pad) | λ/8 at 2.4 GHz in FR-4 is 7.5 mm between vias, every point within 5.3 mm of one on a square grid; well under λ/2, so the two pours cannot resonate as a plate pair |

**Floor plan.** Placement and routing are by hand; the scripted layouts before them are in
the repository's history. Width and directness follow what each pin does, not the net
name: D1 in series with its lines (5.2), bulk and filter capacitors at the SCD43's pulsed
and I/O pads (5.4), the LDO input short and wide, its enable pin thin.

- **Power path:** the receptacle, D1 and R1 run down the center line, and the regulator row
  turns east from R1 (C1, U1, C2), each input facing the part before it, so VBUS and VIN
  are a few millimeters each. VDD leaves C2 for the SCD43 and the BME68x, and a 0.4 mm
  trunk runs south past R5 and R6 and back west to C3 and the module. R1, C1 and the LDO
  input are joined by 0.4 mm trace about 2 mm each; the enable pin is tied to the input
  under the body.
- **Module** on the front edge, 2 mm left of center, antenna end 0.5 mm from the edge. Its
  datasheet asks for an edge, "preferably in the edge center" (section 5.3.1), and figure
  12 draws the antenna end on the edge itself. The end ground pads sit 0.2 mm inside the
  module, so the edge keep-out would have allowed about 0.18 mm (section 8).
- **Right side:** the SCD43 in the rear corner with D2 and C4 behind it, the BME68x and C7
  at the east end of the regulator row, TP2 to TP5 down the edge: the warm parts and the
  pulsed current.
- **Left side:** the SHT4x finger along the edge, then the button beside the receptacle,
  the debug lanes and the SHT4x's I2C.
- **Three holes,** not four: one beside D1, which also takes the force of plugging in, and
  two in the front corners, freeing both rear corners for the sensors.

**Ground.** The aim is ground under, or over, every signal.

- SWDIO, SWDCLK, TXD and RXD leave the receptacle's west half and run on top to the
  module's west pads; the UART and I2C pairs hop under the other lanes just west of it.
- The SCD43's ground pads are in the pour, which has vias into the bottom ground around
  the sensor.

**Other points.**

- **SHT4x finger.** A 2.0 mm cut milled in from the rear edge frees the left 4.25 mm of
  the board, which joins the rest only at its front end, 2 mm behind H3. Seven 1.8 mm
  notches, alternately from the board edge and from the cut, leave 1.5 mm strips: room for
  two 6 mil traces per layer inside the 0.381 mm edge keep-out, along a path of about
  45 mm from the root to the sensor against 26 mm straight. The square tip, with 1 mm
  corners, stops 1.7 mm short of the rear edge to clear the case's rounded rear corner.
  OSH Park mills the cut and notches with its 1.73 mm bit; drilled slots may not touch the
  board edge, and short ones with webs at both ends would not lengthen the path. A rule
  area keeps the pour off the finger; U3 and C6 sit on the tip. The SHT4x footprint
  forbids tracks under the sensor. 2026v1 instead had an island cut off by two drilled
  slots, SL1 and SL2.
- **Module fan-out.** The crystal, button, SWO and nRESET leave inner pads through tented
  vias under the module. Pad 4, the ground pad boxed in by signal pads, has its own trace
  and via.
- **J1** sits where GCT's drawing and the "PCB Edge" line on its footprint's fab layer put
  the board edge: the front shell stakes are 1.55 mm in from the rear edge, so the
  receptacle's lip reaches the case wall. Its 16 through-hole pins and stakes have no
  paste openings: paste them by hand before the one reflow (R-10), as on the DevKit.
- Everything is on the top side (R-10) except JP1, which is only copper. The title,
  revision and name are on the bottom silkscreen. The tallest part is the SCD43 at 6.5 mm.

**Heat.** Estimates from textbook numbers, not measurements.
- The two pours spread heat sideways: for 2 × 35 µm of copper losing heat from both faces
  at about 10 W/m²K, the spreading length √(k·t/h) is about 37 mm, the size of the board.
  The poured part sits at nearly one temperature.
- About 24 cm² of surface gives roughly 41 K/W to free air: 3.9 °C above ambient at 95 mW
  (SCD43 in its 5 s mode) and 1.5 °C at 37 mW (30 s mode). At 38 mm it would be 3.3 °C
  and 1.3 °C. An enclosure adds to both.
- A 3D conduction model of the board in its case gives the SHT4x's rise. Its inputs:
  copper and vias from the layout, two 6 mil traces per layer along the finger,
  conduction-only air inside (Rayleigh number about 10³, below the onset of convection),
  and 10 W/m²K outside. On the finger the SHT4x sits 0.65 °C above ambient with the SCD43
  in its 30 s mode and 1.7 °C in its 5 s mode, against 1.16 and 3.1 °C on 2026v1's island;
  counting radiation across the cavity, 0.61 against 0.88 °C in the 30 s mode. The
  regulator causes about a third of each.
- 2026v1's island held the sensor at 70 % of the poured board's rise through its strips
  and traces. The finger brings it close to the air in its chamber, about 0.5 °C, so more
  isolation gains little. The zigzag gains 0.07 °C over a plain finger of the same size,
  and the chamber walls (8) cost 0.04 °C, since plastic conducts better than still air.
- Vents cannot carry the heat away. Buoyancy across the 6 mm between rows of rear vents
  moves 0.4 to 5 mW of the 95 mW, and a floor vent about 0.01 mW, as the board seals the
  floor off. Even with the air above the board held at room temperature, 2026v1's SHT4x
  would read 1.8 °C high in the 5 s mode.
- The rise is steady because the board is always on, but it scales with how well the room
  cools the box: for 2026v1 in the 5 s mode it is 2.1, 3.1 and 5.0 °C at 20, 10 and
  5 W/m²K outside. A fixed firmware correction holds only where it was calibrated (8).

## 6. Bill of materials

| Ref     | Value              | Part                     | Footprint       | Description                              |
| ------- | ------------------ | ------------------------ | --------------- | ---------------------------------------- |
| IC1     | BL54L15μ           | Ezurio 453-00223R        | module          | nRF54L15 module with antenna (5.7)       |
| U1      | 3.3 V LDO          | AP2112K-3.3TRG1          | SOT-25          | 600 mA LDO with enable (5.3)             |
| U2      | SCD43              | Sensirion SCD43-D-R2     | 10.1 mm LGA     | CO2 sensor (5.4)                         |
| U3      | SHT4x              | SHT45-AD1F-R2            | DFN-4 1.5 mm    | Temperature and humidity (5.5)           |
| U4      | BME680 or BME688   | Bosch                    | LGA-8 3 mm      | Pressure and gas (5.6)                   |
| J1      | USB-C receptacle   | GCT USB4056-03-A         | 24-contact      | Power and debug (5.1)                    |
| D1      | USBLC6-2SC6        | STMicroelectronics       | SOT-23-6        | ESD clamp: VBUS, SWDCLK, SWDIO (5.2)     |
| D2      | LED, red, amber or yellow (about 2 V) | any   | 0603            | Status (5.8)                             |
| X1      | 32.768 kHz, 9 pF   | CM7V-T1A-LOW-ESR         | 3.2 × 1.5 mm    | Low-frequency crystal (5.7)              |
| SW1     | Tactile switch     | Alps SKRK                | SMD             | Pairing and factory reset (5.8)          |
| R1      | 1 Ω, 1 %, 0.1 W    | RC0603FR-071RL           | 0603            | VBUS damping (5.2); bridged on the first build (8) |
| R2, R3  | 5.1 kΩ, 1 %        | RC0603FR-075K1L          | 0603            | CC pull-downs (5.1)                      |
| R4      | 680 Ω              | any                      | 0603            | LED current limit (5.8)                  |
| C1      | 4.7 µF, 10 V, X5R  | CL10A475KP8NNNC          | 0603            | LDO input (5.2)                          |
| C2      | 1 µF, X5R          | any                      | 0603            | LDO output (5.3)                         |
| C3, C4  | 10 µF, X5R         | CL10A106KP8NNNC          | 0603            | Module supply; SCD43 reservoir           |
| C5–C7   | 100 nF             | GRM155R61A104KA01J       | 0402            | Decoupling: SCD43, SHT4x, BME68x         |
| JP1     | Solder jumper      | –                        | bridged, bottom | nRESET to J1 (8)                         |
| R5, R6  | 4.7 kΩ 1 %         | any                      | 0603            | I2C pull-ups, not fitted (5.8)           |
| TP1–TP7 | Test point         | –                        | 1.0 mm pad      | VBUS, VDD, GND, SCL, SDA, SWDIO, SWDCLK  |
| H1, H3, H4 | Mounting hole   | –                        | 2.2 mm, M2      | Unplated; three holes, H2 is not used    |

Part numbers follow the other boards in this repository where one exists. The SCD4x,
AP2112K, BME680, SHT4x and USBLC6-2SC6 symbols and footprints are KiCad's stock ones; the
SCD43 uses the SCD41 symbol, which has the same pins. The receptacle's symbol, in
`Components/USB4056_03_A`, is KiCad's stock one with the shield pin renumbered for the GCT
footprint. The vendor 3D models for the two Sensirion parts are in
`Components/SCD43_D_R2` and `Components/SHT45_AD1F_R2` (with the download's license file),
and 2026v1's slot footprints in `Components/Slot.pretty`.

## 7. Verification

Not yet run. 2026v1 boards were ordered on 2026-11-21, from commit `d46e373`. There KiCad
reports no DRC violations, unconnected items or parity issues; three warnings for J1's
silkscreen at the board edge are excluded, since the fab trims silkscreen there. ERC's
three warnings are expected: SBU2 tied to VDD, SBU1 and the BME68x's SDO tied to ground.
In 2026v2 so far, DRC reports only the unrouted SHT4x: seven unconnected pads and four
dangling ends of its old route.

| Test                                                                 | Checks    | Pass                                         |
| -------------------------------------------------------------------- | --------- | -------------------------------------------- |
| Resistance CC1 and CC2 to ground, unpowered                          | R-4       | 5.1 kΩ ±1 % each                             |
| Power from a USB-C charger with a USB-C cable, both orientations     | R-4       | VDD at 3.25–3.35 V                           |
| Power from a USB-A port                                              | R-4       | same                                         |
| Power from a computer's USB port, with the SCD43 measuring, 1 h      | 5.1       | the port does not shut off                   |
| Scope VIN at C1 while hot-plugging a live 2 m cable, 10 times        | 5.2       | peak ≤ 6.0 V                                 |
| Scope VDD at TP2, AC coupled, sensor measuring                       | R-7       | ≤ 30 mV outside the sensor's own pulses; note the dip during them |
| Scope VDD with the SCD43 idle, radio transmitting, BME68x heating    | R-7       | no change above 30 mV                        |
| Scope VDD at C3, AC coupled, SCD43 measuring and radio transmitting  | R-12      | ≤ 10 mV peak to peak                         |
| Supply current at 5 V, averaged over 1 min and peak                  | R-4       | under 60 mA average, under 300 mA peak       |
| Flash and attach a debugger through the adapter, plugged in flipped  | R-6       | works; reset line resets                     |
| Console through the adapter at 115200 baud                           | R-6       | both directions                              |
| Read all sensors for 10 min at 100 kHz; scope SCL rise time          | R-1, R-2  | CO2 every 5 s; no I2C errors; rise < 1 µs    |
| SHT4x against a reference thermometer after 1 h in the enclosure     | R-2       | within 0.5 °C                                |
| CO2 against a calibrated reference, or outdoors, after 5 days        | R-1       | within specification                         |
| Thread: join as a router and carry a child's traffic for 24 h        | R-5       | no resets, child stays attached              |
| Range: RSSI at a fixed distance, board in its enclosure, against a DevKit in the same place | 8 | record the difference from the DevKit |
| Plug into a USB 3 host port with a full-featured cable, both ways up | 8         | record whether the board stays in reset      |

## 8. Known limitations and open questions

**Design**

- **Reset held by a USB 3 host.** nRESET is on a SuperSpeed contact. A full-featured cable
  to a USB 3 host connects it to the host's receiver, terminated to ground with a few tens
  of ohms, which in one plug orientation is expected to hold the board in reset. Chargers
  and USB 2.0 cables leave it open; the DevKit has the same exposure. Cutting JP1
  disconnects nRESET from the receptacle, and SWD still works. A series resistor cannot do
  both jobs: against the module's 13 kΩ pull-up it would need about 30 kΩ to hold reset
  high against the host and at most 5.6 kΩ for a probe to pull it low. The same receivers
  load SWDIO and SWDCLK in the other orientation, which is harmless.
- **R1 is bridged on the first build**, as no 1 Ω part was in stock. The hot-plug ring in
  5.2 is then undamped: an estimated 8 V against the regulator's 6.5 V maximum whenever an
  already live cable is plugged in. A USB-C source on a USB-C cable applies VBUS only after
  it detects the board; a USB-A to USB-C cable does not wait. Fit R1 before relying on such
  cables. D1 conducts from 6 V but clamps above the regulator's limit at these currents.
- **Regulator input rating.** The AP2112's 6.5 V maximum is why R1 and the larger C1 exist.
  A later revision could use a regulator rated for at least 10 V in, which needs no
  damping, if it still supplies the SCD43's 205 mA peaks and meets R-7.
- **Radio supply.** One regulator feeds everything, and the module allows only 10 mV of
  ripple or noise (R-12). The estimate in 4.3 says the SCD43's pulses stay under that;
  unmeasured. If not, the radio may lose packets while the sensor measures.
- **USB current.** The board peaks at about 240 mA against the 100 mA USB 2.0 allows an
  unconfigured device (5.1).
- SBU2 carries VDD to the receptacle; a short there is limited by U1's 50 mA foldback.
- D1 clamps SWDCLK and SWDIO to its 6 V breakdown plus a diode drop (12 V at 1 A, 17 V at
  5 A), which takes most of a discharge but still exceeds the pins' rating briefly; the
  module's own protection absorbs the rest. nRESET, SWO and the UART have no ESD
  protection, like the DevKit's. D1's paired pins are taken to be joined inside, as its
  pin diagram labels them, with negligible resistance; its text does not say.
- The SCD43's VDDH is fed through the 18 mΩ link under the part (5.4); the dip there
  during a pulse has not been measured.
- The module's average current as a Thread router is assumed (5.3), and the BME68x
  heater's effect on the SCD43 and SHT4x readings is not characterized.

**Board and fab**

- The SHT4x finger's 1.5 mm strips make a springy 27 mm finger: handle the bare board by
  its body. OSH Park gives no minimum width between milled cutouts; the notches (1.8 mm)
  and cut (2.0 mm) are wider than its 1.73 mm bit.
- The receptacle's through-hole pins have a 0.10 mm annular ring, under OSH Park's 0.127 mm
  minimum, and GCT recommends a 1.00 to 1.20 mm board: on 1.6 mm the pin tails (1.05 mm)
  and shell stakes (1.15 mm) stop short of the bottom. Both come from GCT's recommended
  layout; a bigger ring would break the 6 mil spacing on the 0.8 mm pitch. The DevKit uses
  the same footprint on 1.6 mm and came out fine.
- CC2 runs on the top layer under the receptacle's metal shell, insulated only by mask.

**Antenna**

- The antenna's performance here is not measured. The module's datasheet (section 5.3.2)
  gives 30 mm to the sides and 40 mm above or below as the safe distance for metal,
  impossible on a 35 mm board, and says metal closer than 20 mm "will begin to
  significantly degrade performance". With plastic pegs instead of screws, the nearest
  metal is the SCD43's can and the BME68x at about 22 mm and the receptacle at 25 mm. The
  antenna is tuned on a 113 × 63.5 mm board; the datasheet asks for a range test with the
  real board and enclosure (section 7). Departures from its figure 12:
  - The module is 2 mm off the center of its edge.
  - The figure wants at least 15 mm of board edge on each side. This board has 12.35 mm
    on the left and 16.35 mm on the right; 35 mm cannot give more than 14.35 mm on both.
  - The antenna end is 0.5 mm in from the edge (5.9). The edge keep-out allows about
    0.18 mm, and the DevKit sits at 0.23 mm, but moving the module and its fan-out was too
    much work this late. Do it in the next revision.

**Sensors, firmware and enclosure**

- The SCD43's self-calibration needs weekly exposure to fresh air; in a room that never
  drops to 400 ppm the reading drifts, so firmware should allow a forced recalibration.
- Whether Zephyr's SCD4x driver accepts the SCD43 is unchecked; the command set is the
  SCD41's.
- The SCD43 runs in its 30 s low power mode (3.2 mA rather than 15 mA), which cuts the
  SHT4x's offset to about a third (5.9). The datasheet states CO2 accuracy for the 5 s mode
  only.
- The heat figures in 5.9 are model estimates. Air reaches the sensors through the rear
  vents by diffusion, enough for CO2 with about 1 cm² of vent. Expect the SHT4x to read
  about 0.6 °C high until calibrated in the enclosure, and the offset to move with how the
  room cools the box.
- **Calibrating in place, an idea to try.** Switching the SCD43 from its 30 s to its 5 s
  mode raises the SHT4x by a step that the model puts at a fixed multiple of the 30 s
  offset, whatever the room's cooling: offset = 0.6 × step, the step about 1 °C on 2026v2.
  Measuring the step could calibrate each box where it stands, and CO2 keeps reporting
  meanwhile. The box takes about 20 minutes to settle, so each half-cycle needs an hour or
  more, averaged over many cycles against room drift. The ratio depends on the SCD43's
  actual current and needs checking against a reference thermometer. Compensating
  self-heating from known power changes is close to thermostat patents: check freedom to
  operate before using it.
- The 2026v2 case, `Case/USB_CO2_2026v2.FCStd` (parametric FreeCAD), is unprinted. The
  tray has pegs through the three holes and a rest under the right edge; the shell's
  ledges hold the board down, and nothing touches the finger. A 0.8 mm tray wall stands in
  the finger's cut, 0.6 mm clear of the board on each side, a shell wall comes down to
  0.3 mm above it, and cross walls close the chamber at the finger's root. The model says
  these walls cost 0.04 °C (5.9), so whether to keep them is open. `USB_CO2_2026v1.FCStd`
  is 2026v1's case. The button can only be pressed with the shell off and the LED is seen
  only through the rear vents, placeholders for a side-actuated switch and a rear-facing
  indicator.

## 9. References

Datasheets, with the revision that was read. The links are the manufacturers' own and
were checked on 2026-11-19.

- [Sensirion SCD4x datasheet](https://sensirion.com/resource/datasheet/scd4x), version
  1.7, April 2025: tables 1, 4 and 5 and sections 2.3, 3.8, 4.2 and 4.5. Sections 4.1,
  4.3 and 5.4; R-1, R-7 and R-10.
- [Sensirion STCC4 datasheet](https://sensirion.com/resource/datasheet/STCC4), version 1,
  June 2025: tables 1 and 3, sections 1.1.2 to 1.1.4 and figure 3. Section 4.1.
- [Sensirion SHT4x datasheet](https://sensirion.com/resource/datasheet/sht4x), version
  7.3, June 2026: tables 1 and 2 (SHT40: ±1.8 %RH and ±0.2 °C typical) and the supply
  range. R-2 and sections 4.3 and 5.5.
- [Diodes Incorporated AP2112 datasheet](https://www.diodes.com/assets/Datasheets/AP2112.pdf),
  DS39724 Rev. 2-2: the electrical characteristics tables and the load-transient figure.
  Sections 4.3, 5.2 and 5.3.
- GCT USB4056, the receptacle used:
  [product specification](https://gct.co/files/specs/usb4056-spec.pdf), revision A2, and
  [drawing](https://gct.co/files/drawings/usb4056.pdf). Sections 4.2, 5.1 and 8.
- [STMicroelectronics USBLC6-2 datasheet](https://www.st.com/resource/en/datasheet/usblc6-2.pdf),
  DS4260 Rev 7, December 2021: table 2, sections 2.2 and 2.3 and figure 6. Section 5.2.
- Bosch Sensortec
  [BME680 datasheet](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme680-ds001.pdf),
  BST-BME680-DS001-09, revision 1.9, and
  [BME688 datasheet](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme688-ds000.pdf),
  BST-BME688-DS000-03, revision 1.3: the pin-out sections and section 7.2. Sections 4.3
  and 5.6.
- [Ezurio BL54L15µ datasheet](https://www.ezurio.com/documentation/datasheet-bl54l15u),
  version 1.1, August 2025: the pin table, table 3 (supply range and the 10 mV ripple
  limit), the I2C pull-up note, sections 5.2 to 5.3.2 and figure 12 (land pattern and
  antenna keep-out). R-12 and sections 4.3, 5.7, 5.9 and 8.

Standards and other sources:

- [USB Type-C Cable and Connector Specification](https://www.usb.org/document-library/usb-type-cr-cable-and-connector-specification-release-24),
  release 2.x: sink Rd termination and the 5.5 V VBUS maximum (5.1, 5.2).
- [USB 2.0 Specification](https://www.usb.org/document-library/usb-20-specification),
  the June 2025 bundle: section 7.2.1, the 100 mA unit load before configuration (5.1).
- [Universal Serial Bus 3.2 Specification](https://www.usb.org/document-library/usb-32-revision-11-june-2022),
  revision 1.1: receiver termination (section 8).
- `HW/BL54L15μ_DevKit` and `HW/SWD_USBC_InlineAdapter` in this repository: the debug
  pinout (5.1).
- OSH Park's [two-layer service rules](https://docs.oshpark.com/services/two-layer/),
  [slots](https://docs.oshpark.com/submitting-orders/slots/) and
  [board outline](https://docs.oshpark.com/submitting-orders/board-outline/) pages, read on
  2026-11-20 and 21: trace, drill, annular ring and edge limits, drilled slots from
  0.508 mm and only inside the board, notches drawn on the outline, and the 1.73 mm cutout
  bit (5.9, 8).
- Sensirion, SHTxx and STSxx design guide, version 1.1: milled slits, etched-away copper
  and thin traces around the sensor, and a flex print as an alternative (5.5, 5.9).
- [TI SNOAA01](https://www.ti.com/lit/pdf/snoaa01), *Layout Considerations for Accurately
  Measuring Ambient Temperature*, July 2018: wider cutouts and small isolated islands
  read closer to ambient (5.9).
