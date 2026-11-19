# USB CO2 sensor

## 1. Scope

A USB-powered indoor air sensor built on the Ezurio BL54L15μ (nRF54L15) module. It measures
CO2 with a Sensirion SCD43, temperature and humidity with an SHT4x, and pressure and gas
resistance with a BME68x. It joins a Thread network as an always-on router.

## 2. Background

The earlier CO2 boards in this repository are battery powered and use the STCC4, a
thermal-conductivity sensor. It is small and draws little, but its accuracy is ±(100 ppm +
10 %), it needs a long warm-up after power is applied, and it depends on recalibration.
To make a coin cell last, those boards also report only every few minutes and sleep
between reports, so they cannot route Thread traffic for their neighbors.

This board trades the battery for a USB cable and gets three things in return:

- A photoacoustic CO2 sensor with ±(30 ppm + 3 %) accuracy that keeps itself calibrated.
- Readings every 5 seconds from the sensor, so reports every 30 seconds or faster cost
  nothing.
- A radio that is always on, so the device is a Thread router rather than a sleepy end
  device.

Programming and the serial console use the same USB-C receptacle that powers the board,
with the pinout of `HW/BL54L15μ_DevKit`, so `HW/SWD_USBC_InlineAdapter` works unchanged.

## 3. Requirements

| ID   | Requirement                                                                              |
| ---- | ---------------------------------------------------------------------------------------- |
| R-1  | Report CO2 every 30 s, accuracy at least ±(50 ppm + 3) over 400 to 5000 ppm              |
| R-2  | Measure ambient temperature and humidity every 30 s |
| R-4  | Run from any 5 V USB-C source, 4.4 V to 5.5 V at the receptacle, drawing under 500 mA peak |
| R-5  | Keep the radio powered continuously (Thread router); no battery                           |
| R-6  | SWD, reset, SWO and a UART on the USB-C receptacle, pin-compatible with the DevKit        |
| R-7  | CO2 sensor supply: holds 205 mA peaks, moves less than 30 mV because of other loads       |
| R-9  | Fit a small square enclosure with rounded corners; USB and vents on the rear face         |
| R-10 | Single-sided surface-mount assembly, one reflow pass on a hot plate, no board wash        |
| R-11 | Keep the sensor bus the hygrometer firmware already uses: same pins, MCU pull-ups        |

Notes
- R-1 is the SCD43's specified accuracy and range. The 30 s interval is the reporting
  goal; the sensor itself updates every 5 s.
- R-4: 4.4 V is 4.75 V at a USB source less the voltage drop a cable may have at 500 mA;
  5.5 V is the USB Type-C maximum for VBUS at 5 V.
- R-7 and the single reflow pass in R-10 come from the SCD4x datasheet (sections 2.3 and 4.5).

## 4. Design trades

### 4.1 CO2 sensor

|                          | STCC4                | SCD41                  | **SCD43**            |
| ------------------------ | -------------------- | ---------------------- | -------------------- |
| Principle                | thermal conductivity | photoacoustic          | photoacoustic        |
| Accuracy                 | ±(100 ppm + 10 %)    | ±(50 ppm + 2.5 %) ¹    | ±(30 ppm + 3 %)      |
| Specified range          | –                    | 400–5000 ppm           | 400–5000 ppm         |
| Average current at 3.3 V | low, battery-suited  | 15 mA                  | 15 mA                |
| Peak current at 3.3 V    | –                    | 205 mA max             | 205 mA max           |
| Size                     | much smaller         | 10.1 × 10.1 × 6.5 mm   | 10.1 × 10.1 × 6.5 mm |
| Field calibration        | needed               | automatic              | automatic            |

¹ In its 400–1000 ppm band; ±(50 ppm + 3 %) from 1001 to 2000 ppm and ±(40 ppm + 5 %) above.

**Chosen: SCD43.** It is the most accurate of the family over the whole range, and with
USB power its 15 mA average and 205 mA peaks are free. The SCD40, SCD41 and SCD43 share one
package, land pattern and command set, so the footprint also takes an SCD41. The STCC4
column is from the battery boards' notes, not its datasheet, and is here for comparison
only. Whether a
future SCD5x part fits the same land pattern is not known; nothing in this design depends
on it.

### 4.2 USB receptacle

|                       | USB4105-GF-A       | USB4085-GF-A       | **USB4056-03-A**             |
| --------------------- | ------------------ | ------------------ | ---------------------------- |
| Contacts              | 16 (USB 2.0)       | 16 (USB 2.0)       | 24 (full)                    |
| SuperSpeed pins       | no                 | no                 | yes                          |
| Mounting              | SMT, top mount     | through-hole       | SMT front row, THT back row  |
| DevKit debug pinout   | not possible       | not possible       | same part as the DevKit      |

**Chosen: USB4056-03-A.** The DevKit puts SWD on the TX pairs and the UART on an RX pair
(section 5.1). A 16-contact receptacle has no contacts in those positions, so only the
24-contact part can carry the same pinout. Its footprint and 3D model are already in the
repository.

### 4.3 Regulation

|                               | **One LDO** | Two LDOs            | Buck              | SCD43 on VBUS       |
| ----------------------------- | ----------- | ------------------- | ----------------- | ------------------- |
| SCD43 rail moved by other loads | under 1 mV | no                  | plus ripple       | USB source noise    |
| MCU rail sees 205 mA pulses   | yes         | no                  | yes               | no                  |
| Parts                         | 3           | 6                   | 5 or more         | 3                   |
| Heat at 48 mA average         | 94 mW       | 94 mW               | about 25 mW       | 60 mW               |
| I2C levels                    | fine        | fine                | fine              | VIH 3.25 V at 5 V   |

**Chosen: one AP2112K-3.3 for the whole board.** The SCD4x datasheet asks that the supply
not move by more than 30 mV because of other loads, and recommends a separate LDO. That
advice is aimed at boards where a radio or motor shares the rail. Here the other loads
are an nRF54L15 and two small sensors, with steps of 10 to 30 mA; at the regulator's
worst-case 1 %/A load regulation that is under 1 mV. The SCD43's own 205 mA pulses do dip
the shared rail, but the MCU and the other sensors run anywhere from 1.7 to 3.6 V. A
second regulator would cost three parts and buy nothing measurable. A buck saves heat
that does not matter on USB power and adds ripple that does. Feeding the sensor straight
from VBUS would put the source's noise on it and raise its I2C input threshold to
0.65 × 5 V = 3.25 V, which a 3.3 V bus only just meets.

## 5. Circuit

```
 J1 USB-C
  VBUS o--[R1 1Ω]--+------+---- VIN ----[U1 AP2112K-3.3]---- VDD --+-- IC1 module
                   |      |                                       +-- U2 SCD43
               [D1 clamp] [C1]                                    +-- U3 SHT4x
                   |      |                                       +-- U4 BME68x
  GND  o-----------+------+---- GND                               +-- SBU1 (VTref)
  CC1  o--[R2 5.1k]-- GND
  CC2  o--[R3 5.1k]-- GND                    IC1 P1.14, P1.04 ---- I2C ---- U2, U3, U4
  TX1+/- o---- SWDIO, SWDCLK ---- IC1        IC1 P2.04 --[R4]--[D2 LED]
  TX2+/- o---- nRESET (JP1), SWO -- IC1      IC1 P0.01 ---- SW1 ---- GND
  RX1-/+ o---- UART TXD, RXD ---- IC1
```

### 5.1 USB-C receptacle and debug pinout (J1)

| Contact          | USB-C name | Signal    | Goes to                          |
| ---------------- | ---------- | --------- | -------------------------------- |
| A4, A9, B4, B9   | VBUS       | VBUS      | R1                               |
| A1, A12, B1, B12 | GND        | GND       | ground, with the shell           |
| A5               | CC1        | CC1       | R2, 5.1 kΩ to ground             |
| B5               | CC2        | CC2       | R3, 5.1 kΩ to ground             |
| A2               | TX1+       | SWDIO     | module pin 27                    |
| A3               | TX1−       | SWDCLK    | module pin 25                    |
| B2               | TX2+       | nRESET    | JP1, then module pin 32          |
| B3               | TX2−       | SWO       | module pin 42 (P2.07)            |
| B10              | RX1−       | UART_TXD  | module pin 21 (P1.10), MCU out   |
| B11              | RX1+       | UART_RXD  | module pin 19 (P1.12), MCU in    |
| A8               | SBU1       | VDD       | 3.3 V reference for the probe    |
| B8               | SBU2       | GND       | ground                           |
| A6, A7, B6, B7   | D+, D−     | –         | not connected                    |
| A10, A11         | RX2−, RX2+ | –         | not connected                    |

- This is the DevKit's J2 pinout contact for contact. The one difference is CC: the DevKit
  hands CC1 and CC2 to its PMIC, and this board has none, so each gets the 5.1 kΩ
  pull-down (Rd) that the USB Type-C specification requires of a sink. Two separate
  resistors are needed; sharing one breaks detection with electronically marked cables.
- The nRF54L15 has no USB interface, so D+ and D− are left open. The board draws well
  under the 500 mA a default USB source provides and does not need to read the source's
  current advertisement.
- The debug signals only line up in one plug orientation of the adapter. Flipped, they
  land on other contacts and nothing happens.
- UART direction is named from the MCU. Both pins are ordinary port 1 GPIOs, so firmware
  can swap them if the adapter's cable is wired the other way.
- JP1 is a solder jumper on the bottom of the board that is bridged in copper. See
  section 9 for why it exists.

### 5.2 VBUS input: R1, D1 and C1

| Requirement          | Limit                                   | Source               |
| -------------------- | --------------------------------------- | -------------------- |
| LDO input, operating | 6.0 V                                   | AP2112 line regulation and EN ranges |
| LDO input, absolute  | 6.5 V                                   | AP2112 absolute maximum ratings      |
| VBUS, normal         | 5.5 V max                               | USB Type-C                           |

Plugging a live cable into a ceramic input capacitor makes a series RLC circuit that can
ring to nearly twice the source voltage. C1 is 4.7 µF nominal, but a 0603 10 V X5R part
keeps perhaps 2 µF with 5 V across it (a typical figure, not checked against this part's
curve). With roughly 1 µH of cable inductance the characteristic impedance is
√(L/C) ≈ 0.7 Ω. A cable's own 0.2 Ω gives a damping ratio near 0.15 and an overshoot of
about 60 %, or 8 V. That is above the regulator's absolute maximum.

- **R1, 1 Ω** in series raises the damping ratio to about 0.85, where the overshoot is
  under 1 %. At the 240 mA worst-case peak it drops 0.24 V, which leaves the LDO more
  than 0.6 V of headroom at the 4.4 V minimum input (R-4). It dissipates about 2 mW on
  average. Anything from about 0.7 to 2.2 Ω does the job. The first boards are built
  with R1 bridged (section 9).
- **C1 is 4.7 µF in 0603**, not the regulator's 1 µF minimum, because the damping depends
  on the capacitance that is left under bias. If C1 kept only 30 % of its value the
  overshoot with R1 would still be under 5 %, about 5.5 V from a 5.25 V source. A
  2.2 µF 0402 part, at perhaps 0.9 µF under bias, would leave about 10 %.
- **D1, USBLC6-2SC6**, clamps ESD on VIN after R1. It sits at the regulator's input
  capacitor, about 20 mm of trace after R1, because the button took the space
  behind the receptacle. Only its supply clamp is used; its two data channels are left
  open, because the debug lines run on the bottom layer and bringing two of them up to
  the part would cost more vias than the protection is worth.
- Total capacitance on VBUS is 4.7 µF, under the 10 µF a USB device may present.

### 5.3 Regulator: AP2112K-3.3 (U1)

| Datasheet value        |                                   | Requirement                    |
| ---------------------- | --------------------------------- | ------------------------------ |
| Output                 | 3.3 V ±1.5 %, 600 mA min          | 240 mA peak                    |
| Dropout at 300 mA      | 125 mV typ, 200 mV max            | 0.6 V available                |
| Load regulation        | 0.2 %/A typ, 1 %/A max            | 30 mV (R-7)                    |
| PSRR                   | 65 dB at 100 Hz and 1 kHz         | –                              |
| Output noise           | 50 µV RMS, 10 Hz to 100 kHz       | –                              |
| Thermal resistance     | 184 °C/W junction to ambient      | see below                      |
| Enable                 | high above 1.5 V, 3 MΩ pull-down  | tied to VIN                    |
| Capacitors             | 1 µF ceramic, X5R or X7R, in and out | C1 4.7 µF, C2 1 µF          |

- Heat: 1.95 V of drop at the 5.25 V a source may hold, times an average of 48 mA (18 mA
  maximum for the SCD43 plus an assumed 30 mA for everything else), is 94 mW and a 17 °C
  junction rise. During a 205 mA pulse it dissipates about 0.46 W, but only for the
  length of the pulse.
- R-7: a 30 mA step from the MCU or the BME68x moves the output by 0.2 mV typical, 1 mV
  worst case. The SCD43's own 205 mA step moves it 1.4 mV typical, 7 mV worst case, in
  steady state; the dip at the edge of the pulse is larger and is on the test list.
- The enable pin has a pull-down and must be driven; it is tied to VIN, so the rail comes
  up with the cable. On the board the tie runs under the regulator's body.
- The output discharges through 60 Ω when the input goes away.

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

- VDD and VDDH sit on opposite sides of the package, and the datasheet says they "must be
  connected to each other close to the sensor". A 0.4 mm trace on the bottom layer joins
  them straight across under the part, with a via just outside each pad.
- The sensor is turned so that VDD and the I2C pads face the regulator and the module.
  C5 (100 nF) is at the VDD pad, between the sensor and the regulator; C4 (10 µF) is
  5 mm away beside the regulator's output. VDDH, the supply of the infrared source and
  so the pad that draws the pulses, is at the rear and is fed through the link: 11.5 mm
  of 0.4 mm trace, about 14 mΩ, or 3 mV at 205 mA.
- Turning it this way keeps the I2C lines out of the 1.5 mm gap between the receptacle
  and the sensor, which the button and LED traces need (5.9).
- The DNC pads are soldered to pads that connect to nothing, as the datasheet requires.
- It sits at the rear right, behind mounting hole H2 and beside the receptacle, a few
  millimeters from the vents. At about 50 mW in its 5 s mode it is the largest steady
  heat source on the board. It, the regulator and the BME68x are on the right side; the
  SHT4x has the left side to itself.
- Automatic self-calibration assumes the sensor sees fresh air (400 ppm) at least once a
  week. That is a firmware and placement matter, noted in section 9.
- The sensor may be reflowed once, must not be washed, and reads slightly off for up to
  five days after soldering.

### 5.5 Temperature and humidity: SHT4x (U3)

The SCD43 reports temperature and humidity too, but only to ±0.8 °C and ±6 %RH typical,
and it heats itself: the datasheet says those readings depend on the design-in and need a
temperature offset. The SHT4x is the reference for R-2. It sits on the rear edge
between mounting hole H1 and the receptacle, behind the vents, on its own island of
board: an L-shaped slot cuts it off on the east and south, the ground pour stops short of
it on both layers, and only thin traces cross the neck of bare board that is left beside
H1 (5.9). It is 23 mm from the SCD43, 34 mm from the BME68x and 25 mm from the regulator.
Address 0x44, with a 100 nF capacitor (C6).

### 5.6 Pressure and gas: BME680 or BME688 (U4)

Both parts share the 3 × 3 mm LGA-8 package. Wired for I2C: CSB to VDDIO, SDO to ground
for address 0x76, the address the hygrometer firmware uses. It sits at the front right.
It heats itself when it measures gas, so it is on the warm side of the board with the
SCD43 and the regulator, 34 mm from the SHT4x and on the other side of the case's
divider (5.9).

It is normally fitted. Its pressure reading feeds the SCD43's pressure compensation: the
SCD4x datasheet recommends sending the ambient pressure (`set_ambient_pressure`, section
3.7.5), which can be done while the sensor is measuring. Nothing else depends on the part,
so a board without U4 and C7 still works, with the CO2 reading compensated for a fixed
pressure or altitude only.

### 5.7 MCU module: Ezurio 453-00223R (IC1)

| Module pin | nRF54L15 | Signal    | Use                                    |
| ---------- | -------- | --------- | -------------------------------------- |
| 5          | VDD      | VDD       | C3 10 µF, the one capacitor the module's datasheet requires |
| 18         | P1.14    | SDA       | I2C (firmware `i2c21`): SCD43, SHT4x, BME68x |
| 17         | P1.04    | SCL       |                                        |
| 45         | P2.04    | LED       | D2 through R4, active high             |
| 35         | P0.01    | BUTTON    | SW1 to ground, internal pull-up        |
| 21         | P1.10    | UART_TXD  | J1 B10                                 |
| 19         | P1.12    | UART_RXD  | J1 B11                                 |
| 25, 27     | SWD      | SWDCLK, SWDIO | J1 A3, A2                          |
| 32         | nRESET   | nRESET    | J1 B2 through JP1                      |
| 42         | P2.07    | SWO       | J1 B3                                  |
| 12, 10     | P1.00, P1.01 | XL1, XL2 | X1, 32.768 kHz                      |

- **One I2C bus, no pull-up resistors.** All three sensors share the pins the hygrometer
  firmware already uses for the SHT4x (R-11). That firmware enables the nRF54L15's
  internal pull-ups, about 13 kΩ, and runs the bus at 100 kHz. With 30 pF of bus
  capacitance the rise time is about 0.33 µs: well inside the 1 µs that 100 kHz allows,
  just outside the 0.3 µs that 400 kHz allows. The sensors update every few seconds, so
  100 kHz is plenty.
- The LED, button and UART pins were chosen for the layout: each leaves the module on a
  pad that can be reached without crossing another signal. The button is on port 0 and
  the UART on port 1, where the nRF54L15 has GPIO interrupts and UART instances; the LED
  is on port 2, which is output-capable. The firmware needs a new board definition.
- The module's regulator runs in DC/DC mode with the inductor inside the module, as on
  the other BL54L15μ boards here; no external inductor is needed.
- X1 uses the nRF54L15's internal load capacitors (9 pF), as the firmware already
  configures.
- All other pins are left open.

### 5.8 LED, button and test points

- D2 with R4 (680 Ω) on P2.04: about 2 mA. It is the Matter status and pairing indicator.
- SW1 on P0.01: factory reset and pairing, as on the hygrometer. It is at the rear right,
  between the receptacle and mounting hole H2, with D2 beside it. Both are inside the
  case: the button is reached with the shell off, and the LED shows through the rear
  vent slots. A side-actuated switch at the rear edge is the plan for a later revision.
- There is no reset button; reset comes over the USB-C adapter or a power cycle.
- TP1–TP3 bring out VIN, VDD and GND for the supply measurements in section 8.

### 5.9 PCB layout

```
             rear: vents and USB
 +-------------------------------------+
 | o  SHT4x ¦ [   USB-C   ]R3 button o |
 |  .......¦  [           ]D2+-------+ |
 |              R1 R2        | SCD43 | |
 |        debug              +-------+ |
 |        bundle              C5       |
 |       (bottom)            LDO C2 C4 |
 |         /       X1 C3     C1 D1 TP1 |
 |  +-----/------+--------+  R4 C7 TP2 |
 | o     /       | module |  BME68x  o |
 +---------------+--ant.--+------------+
               front             o = M2 hole
```

| Rule                         | Value                                   | Basis                                    |
| ---------------------------- | --------------------------------------- | ---------------------------------------- |
| Outline                      | 35 × 35 mm, 5 mm corner radius          | R-9; see "Size" below                    |
| Mounting                     | four 2.2 mm unplated holes, 3 mm in from both edges: a 29 mm square | M2 screws |
| Screw head keep-out          | no tracks or vias within 2.2 mm of a hole center | 4 mm M2 head                    |
| Layers                       | 2, 1.6 mm, 1 oz                         | lowest-cost prototype stack              |
| Trace and space              | ≥ 0.1524 mm; signals 0.2 mm             | 6 mil prototype fab limit                |
| Power traces                 | VIN and VDD 0.4 mm                      | 6 mV drop per 25 mm at 205 mA            |
| Vias                         | 0.6/0.3 mm; 0.508/0.254 mm at the module and for ground | fab minimum is 0.254 mm drill  |
| Copper to board edge         | 0.4 mm                                  | 15 mil fab recommendation                |
| Annular ring                 | ≥ 0.1 mm                                | the receptacle's 0.6/0.4 mm pins         |
| Ground pour                  | both layers, 0.1524 mm clearance, 0.16 mm minimum width | above the 0.1524 mm minimum connection width |
| Ground stitching             | every pour piece tied to the other layer, then a 5 mm grid: 47 ground vias | 5 mm is about a twelfth of a wavelength at 2.4 GHz in FR-4 |

**Floor plan.** The module's signal pads all leave on its west side and the receptacle
is at the rear, so the six debug signals have to run from the front left to the rear
center. That bundle divides the board. The parts are placed around it, and so that a
wall in the case can separate the two halves:

- **Module** on the front edge, 2 mm left of center, antenna end 0.5 mm from the edge.
  The module's datasheet asks for an edge, "preferably in the edge center" (section
  5.3.1); the 2 mm gives the right side room.
- **Right half:** the SCD43 at the rear, the regulator and its parts in front of it, and
  the BME68x at the front. These are the warm parts and the ones with pulsed current.
- **Rear right pocket,** between the receptacle and mounting hole H2: the button, the
  LED and the CC2 resistor.
- **Left half:** only the SHT4x, on its island in the rear corner. Its SDA, SCL and VDD
  are the only traces that cross the whole bundle, in one place beside the module.
- **Right behind the receptacle:** R1 and R2, between its power pins.

**Ground.** The aim is unbroken ground under, or over, every signal.

- The bottom layer carries the debug bundle, the 11.5 mm VDD link under the SCD43 and
  about 65 mm of jumpers, the longest of them 13 mm of SDA, 11 mm of SCL and 10 mm of
  the button's trace. The rest is ground: 761 mm² in one piece and a 77 mm² strip
  between the lanes that is tied to the top pour by vias, of the board's 1204 mm².
- The four lines that leave the receptacle on its east side (SWD and the UART) turn west
  under R1 and then run forward and left toward the module. That path is fixed in pin
  order, not left to the router. It keeps every debug line west of the center line, so
  nothing on the right side has to cross one.
- Nothing else is routed on the top layer over the bundle, so each debug line has ground
  directly above it. The two exceptions are fixed windows: beside the module, where the
  SHT4x's three traces cross, and under R1, where VIN and the probe's VDD reference
  cross the four east lines at right angles.
- **SWO** leaves the module on the bottom layer south of the SWD pads instead of north
  of them as on the leak sensor board. It is crossed four times in 40 mm: by SWDIO once
  at the module pad, which the pad order forces, and by the SHT4x's SDA, SCL and VDD.
- Trace crossings in total: 48. Of those, 31 are over debug lines: 25 where the SHT4x's
  three traces, VIN and the VDD reference cross at the two windows, and 6 between debug
  lines at their own pads. The other 17 are among the supply, I2C, button and LED
  traces on the right side, where the button and LED signals run the length of the
  board from the module to the rear pocket.
- **SCD43 supply and return.** The regulator's output, C2, C5 and the SCD43's VDD pad
  are within 5 mm of each other. The pulses reach VDDH through the link under the
  sensor; the ground pads next to both supply pads have vias into the bottom ground,
  which is unbroken from there to the regulator apart from that link.
- No via touches a surface-mount pad; routed vias keep their copper off pad edges.
- The top pour is cut into pieces by the top traces. A script ties every piece to the
  bottom ground with at least one via and then adds vias on a 5 mm grid wherever both
  layers have ground and no part is in the way. It places none over the bundle.

**Other points.**

- **SHT4x island.** One 1 mm slot, an L along the island's east and south sides. Its
  south arm ends 3.5 mm from mounting hole H1 and its east arm 1.6 mm from the rear
  edge; those two strips of bare board hold the island. A rule area keeps the ground
  pour off the island and the neck beside H1 on both layers, so the only copper onto the
  island is the SDA, SCL and VDD traces on top and one ground trace on the bottom, 0.2
  to 0.4 mm wide, through that neck.
  Nothing is routed along the rear edge behind the receptacle, which would be a second
  way onto the island.
- **Module fan-out.** Crystal, button pin and ground vias are copied from the fabricated
  leak sensor board. SWO and nRESET take new paths under the module, both outside the
  antenna keep-out. Pad 4, the one ground pad boxed in by signal pads, has its own trace
  and via instead of relying on a 0.17 mm neck of pour.
- **Debug lane order,** west to east on the bottom layer: nRESET, SWO, SWDCLK, SWDIO,
  TXD, RXD. SWDIO crosses SWO and SWDCLK once each at the module and TXD once at the
  receptacle; nothing else in the bundle crosses.
- **SHT4x footprint.** It forbids tracks under the sensor, so each pad is entered from
  its outer edge.
- Everything is on the top side (R-10) except JP1, which is only copper, on the bottom
  at the front, left of the module. The title, revision and name are on the bottom silkscreen.
- The tallest part is the SCD43 at 6.5 mm.

**Size.** 35 mm is close to the smallest square that takes these parts with a hole in
each corner and the receptacle in the middle of the rear edge: the receptacle, the
SCD43 beside it and the SHT4x island on the other side fill the rear edge, and the
receptacle, button, LED, crystal and module fill the center line. An earlier layout was
38 mm; the difference is about a fifth of the area to lose heat from, and about $2 an
order at a prototype price of $5 per square inch for three boards.

**Heat.** These are estimates from textbook numbers, not measurements.
- The two ground pours spread heat sideways. For 2 × 35 µm of copper losing heat to still
  air from both faces at about 10 W/m²K each, the spreading length √(k·t/h) is about
  37 mm, the size of the board. So the poured part of the board sits at nearly one
  temperature, and moving a part a few millimeters across the pour changes little.
- That temperature depends on power over area. The board has about 24 cm² of surface,
  roughly 41 K/W to free air: about 3.9 °C above ambient at 95 mW (SCD43 in its 5 s mode)
  and 1.5 °C at 37 mW (30 s low power mode). At 38 mm it would be 3.3 °C and 1.3 °C.
  An enclosure adds to both.
- What protects the SHT4x is the island. Its traces and the two strips of FR-4 add up to
  roughly 300 K/W between the island and the board, against something like 300 to
  1000 K/W from the island to the air, so the sensor should see between half and three
  quarters of the board's rise. With pour running onto the island it would follow the
  board almost exactly.
- The rise is steady because the board is always on, so firmware can subtract it; the
  30 s mode of the SCD43 cuts it by more than half (section 9).

## 6. Bill of materials

| Ref     | Value              | Part                     | Footprint       | Description                              |
| ------- | ------------------ | ------------------------ | --------------- | ---------------------------------------- |
| IC1     | BL54L15μ           | Ezurio 453-00223R        | module          | nRF54L15 module with antenna (5.7)       |
| U1      | 3.3 V LDO          | AP2112K-3.3TRG1          | SOT-25          | 600 mA LDO with enable (5.3)             |
| U2      | SCD43              | Sensirion SCD43-D-R2     | 10.1 mm LGA     | CO2 sensor (5.4)                         |
| U3      | SHT4x              | SHT45-AD1F-R2            | DFN-4 1.5 mm    | Temperature and humidity (5.5)           |
| U4      | BME680 or BME688   | Bosch                    | LGA-8 3 mm      | Pressure and gas (5.6)                   |
| J1      | USB-C receptacle   | GCT USB4056-03-A         | 24-contact      | Power and debug (5.1)                    |
| D1      | USBLC6-2SC6        | STMicroelectronics       | SOT-23-6        | VIN clamp (5.2)                          |
| D2      | LED                | any                      | 0603            | Status (5.8)                             |
| X1      | 32.768 kHz, 9 pF   | CM7V-T1A-LOW-ESR         | 3.2 × 1.5 mm    | Low-frequency crystal (5.7)              |
| SW1     | Tactile switch     | Alps SKRK                | SMD             | Pairing and factory reset (5.8)          |
| R1      | 1 Ω, 1 %, 0.1 W    | RC0603FR-071RL           | 0603            | VBUS damping (5.2); bridged on the first build (9) |
| R2, R3  | 5.1 kΩ, 1 %        | RC0603FR-075K1L          | 0603            | CC pull-downs (5.1)                      |
| R4      | 680 Ω              | any                      | 0603            | LED current limit (5.8)                  |
| C1      | 4.7 µF, 10 V, X5R  | CL10A475KP8NNNC          | 0603            | LDO input (5.2)                          |
| C2      | 1 µF, X5R          | any                      | 0402            | LDO output (5.3)                         |
| C3, C4  | 10 µF, X5R         | CL10A106KP8NNNC          | 0603            | Module supply; SCD43 reservoir           |
| C5–C7   | 100 nF             | GRM155R61A104KA01J       | 0402            | Decoupling: SCD43, SHT4x, BME68x         |
| JP1     | Solder jumper      | –                        | bridged, bottom | nRESET to J1 (9)                         |
| TP1–TP3 | Test point         | –                        | 1.0 mm pad      | VIN, VDD, GND                            |
| H1–H4   | Mounting hole      | –                        | 2.2 mm, M2      | Unplated                                 |

The part numbers are the ones already used on the other boards in this repository, where
one exists. The SCD4x, AP2112K, BME680, SHT4x and USBLC6-2SC6 symbols and footprints are
KiCad's stock ones; the SCD43 uses the SCD41 symbol, which has the same pins. The
receptacle's symbol is KiCad's stock one with the shield pin renumbered to match the GCT
footprint; it lives in `Components/USB4056_03_A`.

## 7. Connections

J1 is the only connector. Its contacts are listed in section 5.1.

| Use           | Cable or adapter                                  | What works                    |
| ------------- | ------------------------------------------------- | ----------------------------- |
| Normal        | USB-C charger, or USB-A to USB-C cable            | power                         |
| Development   | `SWD_USBC_InlineAdapter` between cable and board  | power, SWD, reset, SWO, UART  |

## 8. Verification

Not yet run. Nothing has been built.

| Test                                                                 | Checks    | Pass                                         |
| -------------------------------------------------------------------- | --------- | -------------------------------------------- |
| Resistance CC1 and CC2 to ground, unpowered                          | R-4       | 5.1 kΩ ±1 % each                             |
| Power from a USB-C charger with a USB-C cable, both orientations     | R-4       | VDD at 3.25–3.35 V                           |
| Power from a USB-A port                                              | R-4       | same                                         |
| Scope VIN at TP1 while hot-plugging a live 2 m cable, 10 times       | 5.2       | peak ≤ 6.0 V                                 |
| Scope VDD at TP2, AC coupled, sensor measuring                       | R-7       | ≤ 30 mV outside the sensor's own pulses; note the dip during them |
| Scope VDD with the SCD43 idle, radio transmitting, BME68x heating    | R-7       | no change above 30 mV                        |
| Supply current at 5 V, averaged over 1 min and peak                  | R-4       | under 60 mA average, under 300 mA peak       |
| Flash and attach a debugger through the adapter                      | R-6       | works; reset line resets                     |
| Console through the adapter at 115200 baud                           | R-6       | both directions                              |
| Read all sensors for 10 min at 100 kHz; scope SCL rise time          | R-1, R-2  | CO2 every 5 s; no I2C errors; rise < 1 µs    |
| SHT4x against a reference thermometer after 1 h in the enclosure     | R-2       | within 0.5 °C                                |
| CO2 against a calibrated reference, or outdoors, after 5 days        | R-1       | within specification                         |
| Thread: join as a router and carry a child's traffic for 24 h        | R-5       | no resets, child stays attached              |
| Plug into a USB 3 host port with a full-featured cable, both ways up | 9         | record whether the board stays in reset      |

## 9. Known limitations and open questions

- **The layout has not been reviewed by a person.** The schematic and board were
  generated by script. Placement was chosen by hand; most traces were placed by a simple
  grid router, so they are correct to the design rules but not tidy. Open the board in
  KiCad and look it over before ordering. KiCad's checks report no DRC violations, no
  unconnected nets and no schematic parity issues.
- ERC reports three warnings, all expected: SBU1 tied to VDD, and SBU2 and the BME68x's
  SDO pin tied to ground. KiCad flags a bidirectional pin wired to a power rail.
- **Reset held by a USB 3 host.** nRESET is on a SuperSpeed contact. A full-featured cable
  to a USB 3 host connects that contact to the host's receiver, which is terminated to
  ground with a few tens of ohms. In one plug orientation this is expected to hold the
  board in reset. Chargers and USB 2.0 cables leave the contact open. The DevKit has the
  same pinout and the same exposure. JP1 can be cut to disconnect nRESET from the
  receptacle; SWD still works without it. Not yet observed on a bench.
- The same host receivers load SWDIO and SWDCLK in the other orientation. That is
  harmless: nothing drives them hard when no probe is attached.
- **R1 is bridged on the first build**, because no 1 Ω resistor was in stock. Without it
  the hot-plug ring in section 5.2 is undamped: an estimated 8 V peak against the
  regulator's 6.5 V absolute maximum whenever a cable that is already live is plugged
  in. A USB-C source on a USB-C cable applies VBUS only after it detects the board, so
  it does not produce that step; a USB-A to USB-C cable does. Fit R1 before relying on
  such cables, and run the hot-plug test in section 8 both ways.
- **Regulator input rating.** The AP2112's 6.5 V absolute maximum leaves little room
  above VBUS, which is why R1 and the larger C1 exist (5.2). For a later revision,
  consider a regulator rated for at least 10 V at its input, twice VBUS: the hot-plug
  ring then needs no damping, and R1 and its 0.24 V drop can go. It must still supply
  the SCD43's 205 mA peaks and meet R-7. None has been selected.
- SBU1 carries VDD to the receptacle. A short there is limited by U1's 50 mA foldback.
- The debug lines have no ESD protection, like the DevKit's.
- **SCD43 land pattern.** The datasheet asks for a keep-free area around the sensor's
  thermal relief hole (section 4.2, figure 4). The board uses KiCad's stock SCD4x
  footprint and keeps traces out from under the sensor, but the ground pour does reach
  the center pad. Check the footprint and the pour against the figure. The footprint has
  no 3D model.
- The SCD43's automatic self-calibration needs weekly exposure to fresh air. In a room
  that never drops to 400 ppm the reading drifts; firmware should allow a forced
  recalibration.
- Whether Zephyr's SCD4x driver accepts the SCD43 has not been checked. The command set is
  shared with the SCD41.
- I2C at 400 kHz would need external pull-ups; the board has no pads for them.
- The MCU's average current as a Thread router is assumed, not measured (5.3).
- One regulator feeds everything, so the SCD43's 205 mA pulses dip the rail the MCU and
  the other sensors share. Nothing here should mind, but it has not been measured.
- The BME68x heater current and its effect on the SCD43 and SHT4x readings are not
  characterized.
- The slot is 1 mm wide with square inside corners. Confirm the fab's minimum slot
  width; its router will round the corners.
- The SHT4x island is held by a 3.5 mm neck of board beside mounting hole H1 and a
  1.6 mm strip at the rear edge. Handle the bare board with care.
- The heat figures in 5.9 are estimates. Measure the SHT4x against a reference in the
  enclosure, in both SCD43 modes, before trusting or correcting its reading.
- Whether to run the SCD43 in its 5 s mode (15 mA) or its 30 s low power mode (3.2 mA) is
  a firmware choice. The datasheet states the CO2 accuracy for the 5 s mode only.
- With vents only at the rear, air reaches the sensors by diffusion. That is fast enough
  for CO2 if the open vent area is about 1 cm² or more. It does not remove heat: expect
  the SHT4x to read a couple of degrees above the room until that is calibrated out or
  the enclosure gets a second opening for through-flow.
- The antenna's performance in this placement is not measured. The module's datasheet
  says metal closer than 20 mm starts to degrade it (section 5.3.2). The BME68x and the
  front left screw are about 12 mm from the antenna, the front right screw 17 mm, the
  SCD43's can 18 mm and the receptacle 24 mm. Nylon screws at the front would remove two
  of those. The module is also 2 mm off the center of its edge.
- SWO and nRESET leave the module by paths that differ from the fabricated leak sensor
  board. They pass the design rules, and nRESET's edge is 0.22 mm outside the antenna
  keep-out, but this part of the fan-out is new.
- A short VDD jumper runs on the bottom layer under the crystal. It carries DC only.
- To confirm against the manufacturers' datasheets: USBLC6-2SC6 breakdown and clamping
  voltages, BME688 pin compatibility with the BME680, the nRF54L15's pull-up value and
  its GPIO limits on port 2, and the module's antenna keep-out dimensions.
- The I2C lines each run more than 11 mm on the bottom layer, and the button's trace
  10 mm, because the right side is crowded and those traces have to hop under the
  supply. They are the longest cuts in the bottom ground that are not debug lines; hand
  routing would shorten them.
- Only some routing orders of the generator reach a clean result with this placement.
  The board passes its checks, but the right side is close to full.
- The button can only be pressed with the case's shell off, and the LED is seen only
  through the rear vent slots, next to the SCD43's air path. Both are placeholders for a
  side-actuated switch and a rear-facing indicator in a later revision.
- With the SCD43 turned (5.4), its pulsed supply pad is fed through the 14 mΩ link under
  the part, not straight from the reservoir capacitor. The numbers say that is fine;
  the dip at VDDH during a pulse has not been measured.
- D1 is about 20 mm of trace after R1 (5.2), so a discharge at the plug sees R1 and that
  trace before the clamp.
- The enclosure does not exist yet. Vent position, the light pipe for D2 and access to SW1
  depend on it.

## 10. References

- [Sensirion SCD4x datasheet](https://sensirion.com/resource/datasheet/scd4x), version
  1.7, April 2025: tables 1, 4 and 5 and sections 2.3, 4.2 and 4.5, the source for
  sections 4.1 and 5.4 and for R-7 and R-10.
- [Diodes Incorporated AP2112 datasheet](https://www.diodes.com/assets/Datasheets/AP2112.pdf),
  DS39724 Rev. 2-2, the source for sections 5.2 and 5.3.
- USB Type-C Cable and Connector Specification, release 2.x: sink Rd termination and the
  5.5 V VBUS maximum (sections 5.1 and 5.2).
- Universal Serial Bus 3.2 Specification: receiver termination (section 9).
- `HW/BL54L15μ_DevKit` and `HW/SWD_USBC_InlineAdapter` in this repository, the source for
  the debug pinout in section 5.1.
- GCT USB4056 product specification for the receptacle; its footprint and model are in
  `HW/BL54L15μ_DevKit/Components/USB4056_03_A`.
- STMicroelectronics USBLC6-2 datasheet for D1.
- Bosch Sensortec BME680 and BME688 datasheets for section 5.6.
- Ezurio BL54L15μ (453-00223R) datasheet and hardware integration guide for section 5.7.
