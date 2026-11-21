# USB CO2 sensor

## 1. Scope

A USB-powered indoor air sensor built on the Ezurio BL54L15μ (nRF54L15) module. It measures
CO2 with a Sensirion SCD43, temperature and humidity with an SHT4x, and pressure and gas
resistance with a BME68x. It joins a Thread network as an always-on router.

## 2. Background

This board aims to be an accurate, set and forget CO2 sensor. No battery that needs replacement.

Programming and the serial console use the same USB-C receptacle that powers the board,
with the pinout of `HW/BL54L15μ_DevKit` mirrored, so `HW/SWD_USBC_InlineAdapter` works
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

Sources (section 10): STCC4 datasheet, tables 1 and 3, sections 1.1.2 to 1.1.4 and figure
3; SCD4x datasheet, tables 1 and 4 and section 3.8.

**Chosen: SCD43.** It is the most accurate of the family over the whole range, and with
USB power its 15 mA average and 205 mA peaks are free. The SCD40, SCD41 and SCD43 share one
package, land pattern and command set, so the footprint also takes an SCD41. The unreleased SCD5x
part may be a better choice once released, but its specs are currently not known.

### 4.2 USB receptacle

|                       | USB4105-GF-A       | USB4085-GF-A       | **USB4056-03-A**             |
| --------------------- | ------------------ | ------------------ | ---------------------------- |
| Contacts              | 16 (USB 2.0)       | 16 (USB 2.0)       | 24 (full)                    |
| SuperSpeed pins       | no                 | no                 | yes                          |
| Mounting              | SMT, top mount     | through-hole       | SMT front row, THT back row  |
| DevKit debug pinout   | not possible       | not possible       | same part as the DevKit      |

Source (section 10): the GCT product specification and drawing of each part. Their titles
give the type: USB4105 "for USB2.0, SMT Type, PCB Top Mount" (16 pads on the drawing),
USB4085 "Through-hole, PCB Top Mount" (16 pins) and USB4056 "USB3.2 Gen 2 ..., Hybrid
type, PCB Top Mount" (12 surface-mount and 12 through-hole contacts).

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

The part counts and heat figures are calculated: an LDO from 5.25 V to 3.3 V at 48 mA
dissipates 94 mW. The rest comes from the datasheets cited below (section 10).

**Chosen: one AP2112K-3.3 for the whole board.** The SCD4x datasheet (section 2.3) asks
that the supply "must not vary by more than 30 mV" because of other loads, and says a
separate LDO "is recommended". That advice is aimed at boards where a radio or motor
shares the rail. Here the other loads are an nRF54L15 and two small sensors, with steps of
10 to 30 mA; at the AP2112's worst-case load regulation of 1 %/A (0.2 %/A typical, from
its electrical characteristics table) that is 1 mV at most. The SCD43's own 205 mA pulses
(SCD4x table 4) do dip the shared rail, but the parts that share it have wide supply
ranges: the module 1.7 to 3.5 V (Ezurio datasheet), the SHT4x 1.08 to 3.6 V and the
BME680 1.71 to 3.6 V (their datasheets).

The module is the one that could mind. Its datasheet (table 3) allows only 10 mV of
ripple or noise on its supply, at any frequency, as the level that does not disturb the
radio (R-12). In steady state the 205 mA step moves the regulator's output by 1.4 mV
typical and 6.8 mV worst case. The AP2112's load-transient figure shows about 10 mV for a
0 to 600 mA step with 1 µF on the output; here the step is a third of that and the rail
carries 21 µF, so the dip should be smaller. That is an estimate, not a measurement
(section 8). If it fails, the fixes are a separate regulator for the SCD43, as Sensirion
recommends, or a small resistor ahead of C3 so the module sits behind its own filter.

A second regulator would cost three parts for a problem that may not exist. A buck would
reduce losses and heat, but those are not significant at this power. Feeding the sensor straight from VBUS would put the source's noise on it and
raise its I2C input threshold to 0.65 × VDD (SCD4x table 4), 3.25 V at 5 V, which a 3.3 V
bus only just meets.

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
  in the other row (A2 with B2, A10 with B10 and so on), the contact a plug turned over
  would reach. The inline adapter works unchanged, plugged in the other way up from the
  DevKit. The mirror puts SWD and the UART on the receptacle's west half and nRESET and
  SWO on its east half, the sides of the module their pads are on, which takes out the
  twist the DevKit's order needed between the receptacle and the module.
- The other difference is CC: the DevKit hands CC1 and CC2 to its PMIC, and this board
  has none, so each gets the 5.1 kΩ pull-down (Rd) that the USB Type-C specification
  requires of a sink. Two separate resistors are needed; sharing one breaks detection
  with electronically marked cables.
- The nRF54L15 has no USB interface, so D+ and D− are left open and no host ever
  configures the board. USB 2.0 (section 7.2.1) holds such a device to one unit load,
  100 mA, as "an absolute maximum, not an average over time". The board averages well
  under that, but the SCD43's pulses take it to about 240 mA. Chargers do not enforce
  the limit; whether a computer's port does is untested (section 9).
- Plugged in the wrong way up, the debug signals land on other contacts and do nothing,
  and the adapter's LED lights.
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
  than 0.6 V of headroom at a 4.4 V input: 4.75 V at a USB source less the cable drop
  allowed at 500 mA (R-4). It dissipates about 2 mW on average. Anything from about 0.7 to 2.2 Ω does the job. The first boards are built
  with R1 bridged (section 9).
- **C1 is 4.7 µF in 0603**, not the regulator's 1 µF minimum, because the damping depends
  on the capacitance that is left under bias. If C1 kept only 30 % of its value the
  overshoot with R1 would still be under 5 %, about 5.5 V from a 5.25 V source. A
  2.2 µF 0402 part, at perhaps 0.9 µF under bias, would leave about 10 %.
- **D1, USBLC6-2SC6**, clamps ESD on VBUS and on the two SWD lines. It sits right behind
  the receptacle, its near pads 2 mm from the pin row, because its datasheet asks for the
  tracks to its I/O, supply and ground pins to be "as short as possible" and for the part
  to be "as close as possible to the disturbance source (generally the connector)"
  (section 2.3): it reckons 6 nH for 10 mm of track, which adds about 144 V to the
  clamping voltage on an 8 kV contact discharge.
  - **The part is in series with the lines.** It has two pins for each line (1 and 6, 3
    and 4), joined inside the package. SWDIO and SWDCLK each come in from the receptacle
    at one pin and leave for the module from the other, and no copper on the board joins
    the two pins. A discharge on the line has to pass the clamp's own node to get any
    further; a trace that bridged the pins would be a second path around the clamp, and
    the voltage across its inductance would add to what the module sees. The datasheet's
    figure 6 shows the same thing for a single pin: the line crosses the pin, it does not
    pass by with a spur.
  - The schematic enforces this with separate nets: SWDCLK_USB and SWDIO_USB between the
    receptacle and pins 1 and 3, SWDCLK and SWDIO from pins 6 and 4 on. The design rule
    check then reports any copper that joins a pair.
  - The consequence: SWD only works with D1 fitted. On a board built without it, bridge
    pads 1 to 6 and 3 to 4.
  - VBUS comes from the receptacle's two through-hole VBUS pins on the bottom layer to a
    via under the body, passes through pin 5 and goes on to R1: 7 mm from the nearer
    receptacle pin to the pad, and nothing reaches R1 without passing the pad.
  - Its ground pin faces the receptacle and runs 3.4 mm on a 0.3 mm trace to the
    receptacle's A8 contact, which this board ties to ground as the probe's ground
    reference. The pad also sits solidly in the top pour.
  - It adds at most 3.5 pF to each SWD line and leaks at most 150 nA at 5 V. Its
    breakdown is 6 V minimum, so it does not conduct at the 5.5 V VBUS maximum.
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
  them under the part, from a via beside C4 at the rear to a via on the VDD trace in
  front of the sensor.
- The sensor is turned so that VDD and the I2C pads face the regulator and the module.
- **Each supply pad has the capacitor that suits what the pad does.** VDDH supplies the
  infrared source and draws the 205 mA pulses: C4 (10 µF) is beside it, 3 mm of trace
  away, so the pulse current comes from the capacitor and not through the link. VDD
  supplies the logic and the I2C interface and is the noise-sensitive pad: C5 (100 nF)
  is at it, and the trace from the regulator passes C5's pad on the way in. The link
  under the sensor is 14.5 mm of 0.4 mm trace, about 18 mΩ.
- The DNC pads are soldered to pads that connect to nothing, as the datasheet requires.
- The datasheet asks for a 0.6 mm circle under the sensor's thermal relief hole to stay
  "free from solder and flux" (section 4.2, figure 4). It sits just off a corner of the
  center pad, and nothing is there on this board: no pad, paste, mask opening, via or
  trace within 0.3 mm. The pour under it is covered by solder mask.
- It sits in the rear right corner beside the receptacle, its center 7.4 mm from the
  rear edge. At about 50 mW in its 5 s mode it is the largest steady
  heat source on the board. It, the regulator and the BME68x are on the right side; the
  SHT4x has the left side to itself.
- Automatic self-calibration assumes the sensor sees fresh air (400 ppm) at least once a
  week. That is a firmware and placement matter, noted in section 9.
- The sensor may be reflowed once, must not be washed, and reads slightly off for up to
  five days after soldering.

### 5.5 Temperature and humidity: SHT4x (U3)

The SCD43 reports temperature and humidity too, but only to ±0.8 °C and ±6 %RH typical,
and it heats itself: the datasheet says those readings depend on the design-in and need a
temperature offset. The SHT4x is the reference for R-2. It sits in the rear left
corner, behind the vents, on its own island of board: two slots cut it off on the east
and south, the ground pour stops short of it on both layers, and only thin traces cross
the two necks of board that are left (5.9). It is 26 mm from the SCD43, 31 mm from the
BME68x and 24 mm from the regulator.
Address 0x44, with a 100 nF capacitor (C6).

### 5.6 Pressure and gas: BME680 or BME688 (U4)

Both parts share the 3 × 3 mm LGA-8 package and the same pinout, numbered clockwise in top
view (each datasheet's pin-out section). Wired for I2C: CSB to VDDIO, SDO to ground
for address 0x76, the address the hygrometer firmware uses. It sits on the right edge,
in front of the SCD43 at the east end of the regulator row. It heats itself when it
measures gas, so it is on the warm side of the board with the SCD43 and the regulator,
31 mm from the SHT4x and on the other side of the case's divider (5.9).

C7 (100 nF) sits at VDD (pin 8) and the ground pin beside it; VDDIO (pin 6) joins VDD
under the package. CSB (pin 2) is on the far side, behind SDA and SCL, and reaches that
link through two vias and a short hop on the bottom layer. The datasheet's connection diagram has a 100 nF capacitor on each
(section 7.2), for boards where the two are separate rails. Here they are one rail, the
pins are 1.6 mm apart, and VDDIO only powers the interface, so one capacitor at the pin
that carries the load does both jobs.

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
| 21         | P1.10    | UART_TXD  | J1 A10                                 |
| 19         | P1.12    | UART_RXD  | J1 A11                                 |
| 25, 27     | SWD      | SWDCLK, SWDIO | J1 B3, B2 through D1               |
| 32         | nRESET   | nRESET    | J1 A2 through JP1                      |
| 42         | P2.07    | SWO       | J1 A3                                  |
| 12, 10     | P1.00, P1.01 | XL1, XL2 | X1, 32.768 kHz                      |

- **One I2C bus, no pull-up resistors.** All three sensors share the pins the hygrometer
  firmware already uses for the SHT4x (R-11). That firmware enables the nRF54L15's
  internal pull-ups, 13 kΩ typical (Ezurio datasheet), and runs the bus at 100 kHz. With 30 pF of bus
  capacitance the rise time is about 0.33 µs: well inside the 1 µs that 100 kHz allows,
  just outside the 0.3 µs that 400 kHz allows. The sensors update every few seconds, so
  100 kHz is plenty.
- The LED, button and UART pins were chosen for routing. The button is on port 0 and
  the UART on port 1, where the nRF54L15 has GPIO interrupts and UART instances; the LED
  is on port 2, which is output-capable. The firmware needs a new board definition.
- The module's regulator runs in DC/DC mode with the inductor inside the module, as on
  the other BL54L15μ boards here; no external inductor is needed.
- X1 uses the nRF54L15's internal load capacitors (9 pF), as the firmware already
  configures.
- All other pins are left open.

### 5.8 LED, button and test points

- D2 with R4 (680 Ω) on P2.04: about 2 mA with a red, amber or yellow LED, which drop
  about 2 V. A blue, white or true-green LED drops about 2.9 V and would get about
  0.6 mA. It is the Matter status and pairing indicator.
- SW1 on P0.01: factory reset and pairing, as on the hygrometer. It is at the rear edge,
  left of the receptacle; D2 is at the rear edge on the right, with R4 beside the
  module. Both are inside the case: the button is reached with the shell off, and the
  LED shows through the rear vent slots. A side-actuated switch at the rear edge is the
  plan for a later revision.
- There is no reset button; reset comes over the USB-C adapter or a power cycle.
- TP1–TP3 bring out VBUS, VDD and GND for the supply measurements in section 8, and TP4
  and TP5 bring out SCL and SDA for a logic analyzer. TP1 is beside R1; TP2 to TP5 are
  in a column on the right edge. TP6 (SWDIO) and TP7 (SWDCLK) sit on the debug lanes left
  of center, for probing SWD.
- R5 (SDA) and R6 (SCL) are 0603 footprints for I2C pull-ups to VDD, not fitted. The bus
  runs on the MCU's internal pull-ups as on the hygrometer (R-11); 4.7 kΩ here would be
  for 400 kHz or if the edges turn out slow. They sit on the VDD trunk south of the
  regulator.

### 5.9 PCB layout

```
             rear: vents and USB
 +-------------------------------------+
 | SHT4x¦ button [  USB-C  ]  D2   C4  |
 | -----'        [         ] +-------+ |
 |  |            [         ] | SCD43 | |
 |  |        \ o   D1 R2 R3  +-------+ |
 |  |      \  TP1 R1 C1 LDO C2 BME68x  |
 |  |     |               R5 R6   TP5  |
 |  |     |              JP1      TP4  |
 |  |     |    X1 C3              TP2  |
 |  '-----|  +--------+ R4        TP3  |
 | o      '--| module |              o |
 +-----------+--ant.--+----------------+
               front     o = M2 hole, ¦ and - = slots
```

| Rule                         | Value                                   | Basis                                    |
| ---------------------------- | --------------------------------------- | ---------------------------------------- |
| Outline                      | 35 × 35 mm, 5 mm corner radius          | R-9; see "Size" below                    |
| Mounting                     | three 2.2 mm unplated holes: one 12 mm in from the rear edge beside the ESD clamp, two in the front corners 3 mm in from both edges | pegs on the case tray; no screws, which keeps metal away from the antenna (section 9) |
| Hole keep-out                | no tracks or vias within 2.2 mm of a hole center | room for a 4 mm M2 head if screws are ever used; the bottom rests on the tray's plastic pad. The nearest copper is a ground via, 2.77 mm from the rear hole |
| Layers                       | 2, 1.6 mm, 1 oz                         | lowest-cost prototype stack              |
| Trace and space              | ≥ 0.1524 mm; signals 0.2 mm, 0.1524 mm at fine-pitch pads and onto the SHT4x island | the fab's 6 mil minimum; net class Default |
| Power traces                 | VBUS, VIN and VDD 0.4 mm; 0.3 mm at the receptacle's VBUS pads and into the module; 0.15 to 0.2 mm for VDD branches that carry no current | net class Power; 6 mV drop per 25 mm of 0.4 mm at 205 mA |
| Vias                         | 0.508/0.254 mm; 0.6/0.3 mm on VBUS and at the front of the VDD link under the SCD43 | the fab's 0.254 mm minimum drill; the net class presets |
| Copper to board edge         | 0.381 mm to the outline (custom rule in `BL54L15μ_USB_CO2.kicad_dru`), 0.3 mm to the slots; 0.40 mm as laid out | the fab's 15 mil (0.381 mm) keep-out is for the milled edge; the slots are drilled |
| Annular ring                 | ≥ 0.1 mm                                | the receptacle's 0.6/0.4 mm pins, under the fab's 0.127 mm minimum (section 9) |
| Ground pour                  | one zone on both layers, 0.1524 mm clearance and minimum width; surface-mount pads solid, through-hole pads with 0.2 mm spokes and gap | the fab's 6 mil minimum; reflow on a hot plate needs no reliefs on surface-mount pads; spokes the width of a signal trace |
| Ground stitching             | 81 ground vias. No point of pour is more than 4.9 mm from one (the worst is under the SCD43's center pad), so no gap between vias exceeds λ/8; every piece of pour has at least one | λ/8 at 2.4 GHz in FR-4 (wavelength about 60 mm) is 7.5 mm between vias, which on a square grid leaves every point within 5.3 mm of a via. Spacing well under λ/2 keeps the two pours from resonating as a plate pair |

**Floor plan.** Placement and routing are by hand; the scripted layouts before them are
in the repository's history.

- **Power path:** the receptacle, ESD clamp D1 and R1 run down the center line. The
  regulator row turns east from R1: C1, U1 and C2, each part's input facing the one
  before it, so VBUS and VIN are a few millimeters each. VDD leaves C2 for the SCD43 and
  the BME68x, and a 0.4 mm trunk runs south past R5 and R6 and back west to C3 and the
  module.
- **Module** on the front edge, 2 mm left of center, antenna end 0.5 mm from the edge.
  The module's datasheet asks for an edge, "preferably in the edge center" (section
  5.3.1), and its figure 12 draws the antenna end on the edge itself. The end ground pads
  sit 0.2 mm inside the module, so the fab's 0.381 mm edge keep-out would have allowed
  the module to come within about 0.18 mm. This build keeps 0.5 mm (section 9).
- **Right side:** the SCD43 in the rear corner with D2 and C4 behind it, the BME68x and C7
  at the east end of the regulator row, and TP2 to TP5 down the edge. These are the warm
  parts and the ones with pulsed current.
- **Left side:** the SHT4x on its island in the rear corner and the button beside the
  receptacle. The rest of the left side carries the debug lanes and the SHT4x's I2C.
- **Three holes,** not four: one beside D1, 12 mm in from the rear edge, where it also
  takes the force of plugging in, and two in the front corners. That frees both rear
  corners for the sensors.

**Routing by what each pin does.** Width and directness follow the current and the
purpose of the pin, not the net name:

- **ESD clamp:** it is in series with the lines it protects, with no path around it, and
  its VBUS and ground connections are the shortest on the board (5.2).
- **Regulator:** R1, C1 and the input pin are joined by 0.4 mm trace, about 2 mm each.
  The enable pin carries no current and is tied to the input pin under the body. The
  ground pin joins the top pour directly. The output goes to C2 and on to
  the loads at 0.4 mm.
- **SCD43:** bulk capacitor at the pad that draws the pulses, filter capacitor at the pad
  that does the I/O (5.4).
- **BME68x:** C7 at the VDD and ground pins; VDDIO joins VDD under the package (5.6).
- **Test points and the VDD reference for the debug probe** carry no current: 0.2 mm.

**Ground.** The aim is ground under, or over, every signal.

- 422 mm of trace on top and 162 mm on the bottom. The bottom pour is one 944 mm² piece
  of the board's 1204 mm²; the top pour is one 706 mm² piece and three small ones, each
  with at least one via.
- The longest bottom-layer runs, and so the longest cuts in the bottom pour: nRESET and
  SWO side by side from the receptacle's east pins to the module, about 25 mm each
  (nRESET through JP1), the VDD link under the SCD43 (15 mm) and the LED line (15 mm).
- SWDIO, SWDCLK, TXD and RXD leave the receptacle's west half and run on top to the
  module's west pads. The UART and I2C pairs hop under the other lanes on the bottom,
  just west of the module.
- **SCD43 supply and return.** The pulses are drawn at VDDH from C4. The ground pads
  next to both supply pads are in the pour, which has vias into the bottom ground around
  the sensor.

**Other points.**

- **SHT4x island.** Two drilled slots, SL1 and SL2, 0.508 mm wide, along the island's
  east and south sides. SL1 ends 1.37 mm from the rear edge and SL2 1.50 mm from the
  left edge; those two strips of bare board hold the island, with a 0.5 mm web at the
  corner where the slots stop short of each other. They are non-plated oval holes in
  board-only footprints (`Components/Slot.pretty`), so they reach the fab in the drill
  file: OSH Park drills slots from 0.508 mm but mills Edge.Cuts cutouts with a 1.73 mm
  bit, and its rules do not allow one slot to cut through another, hence the web. A rule
  area keeps the ground pour off the island on both layers. The copper onto it is four
  0.15 mm traces on top: SDA and SCL through the left neck, VDD and ground through the
  rear neck to vias beside the button.
- **Module fan-out.** The crystal, button, SWO and nRESET each leave an inner pad through
  a tented via under the module. Pad 4, the one ground pad boxed in by signal pads, has
  its own trace and via instead of relying on a neck of pour.
- **CC2** runs on the top layer under the receptacle's shell, between the shell's front
  legs and the through-hole row, to R3.
- **SHT4x footprint.** It forbids tracks under the sensor, so each pad is entered from
  its outer edge.
- Everything is on the top side (R-10) except JP1, which is only copper, on the bottom
  between the regulator and the module. The title, revision and name are on the bottom
  silkscreen.
- **J1** sits where GCT's drawing, and the "PCB Edge" line on its footprint's fab layer,
  put the board edge: the front shell stakes are 1.55 mm in from the rear edge, so the
  receptacle's lip reaches the case wall. Its 16 through-hole pins and stakes have no
  paste openings, so a stencil does not cover them: paste them by hand before the one
  reflow pass (R-10), as on the DevKit.
- The tallest part is the SCD43 at 6.5 mm.

**Size.** 35 mm is close to the smallest square that takes these parts with the
receptacle in the middle of the rear edge: the receptacle, the
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
- What protects the SHT4x is the island. Its traces, the two strips of FR-4 and the web
  between the slots add up to roughly 250 K/W between the island and the board, against
  something like 300 to 1000 K/W from the island to the air, so the sensor should see
  between half and four fifths of the board's rise. With pour running onto the island it would follow the
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
| D1      | USBLC6-2SC6        | STMicroelectronics       | SOT-23-6        | ESD clamp: VBUS, SWDCLK, SWDIO (5.2)     |
| D2      | LED, red, amber or yellow (about 2 V) | any   | 0603            | Status (5.8)                             |
| X1      | 32.768 kHz, 9 pF   | CM7V-T1A-LOW-ESR         | 3.2 × 1.5 mm    | Low-frequency crystal (5.7)              |
| SW1     | Tactile switch     | Alps SKRK                | SMD             | Pairing and factory reset (5.8)          |
| R1      | 1 Ω, 1 %, 0.1 W    | RC0603FR-071RL           | 0603            | VBUS damping (5.2); bridged on the first build (9) |
| R2, R3  | 5.1 kΩ, 1 %        | RC0603FR-075K1L          | 0603            | CC pull-downs (5.1)                      |
| R4      | 680 Ω              | any                      | 0603            | LED current limit (5.8)                  |
| C1      | 4.7 µF, 10 V, X5R  | CL10A475KP8NNNC          | 0603            | LDO input (5.2)                          |
| C2      | 1 µF, X5R          | any                      | 0603            | LDO output (5.3)                         |
| C3, C4  | 10 µF, X5R         | CL10A106KP8NNNC          | 0603            | Module supply; SCD43 reservoir           |
| C5–C7   | 100 nF             | GRM155R61A104KA01J       | 0402            | Decoupling: SCD43, SHT4x, BME68x         |
| JP1     | Solder jumper      | –                        | bridged, bottom | nRESET to J1 (9)                         |
| R5, R6  | 4.7 kΩ 1 %         | any                      | 0603            | I2C pull-ups, not fitted (5.8)           |
| TP1–TP7 | Test point         | –                        | 1.0 mm pad      | VBUS, VDD, GND, SCL, SDA, SWDIO, SWDCLK  |
| H1, H3, H4 | Mounting hole   | –                        | 2.2 mm, M2      | Unplated; three holes, H2 is not used    |
| SL1, SL2 | Slot              | –                        | drilled, 0.508 mm | SHT4x island (5.9); board only, not in the schematic |

The part numbers are the ones already used on the other boards in this repository, where
one exists. The SCD4x, AP2112K, BME680, SHT4x and USBLC6-2SC6 symbols and footprints are
KiCad's stock ones; the SCD43 uses the SCD41 symbol, which has the same pins. The
receptacle's symbol is KiCad's stock one with the shield pin renumbered to match the GCT
footprint; it lives in `Components/USB4056_03_A`. KiCad ships no 3D models for the two
Sensirion footprints, so the board points them at the vendor models in
`Components/SCD43_D_R2` and `Components/SHT45_AD1F_R2`; the latter folder keeps the
download's license file. The two slot footprints are in `Components/Slot.pretty`.

## 7. Connections

J1 is the only connector. Its contacts are listed in section 5.1.

| Use           | Cable or adapter                                  | What works                    |
| ------------- | ------------------------------------------------- | ----------------------------- |
| Normal        | USB-C charger, or USB-A to USB-C cable            | power                         |
| Development   | `SWD_USBC_InlineAdapter` between cable and board, turned over (5.1) | power, SWD, reset, SWO, UART |

## 8. Verification

Not yet run. Boards were ordered on 2026-11-21, from commit `d46e373`.

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
| Range: RSSI at a fixed distance, board in its enclosure, against a DevKit in the same place | 9 | record the difference from the DevKit |
| Plug into a USB 3 host port with a full-featured cable, both ways up | 9         | record whether the board stays in reset      |

## 9. Known limitations and open questions

- The layout was placed and routed by hand. KiCad's checks report no DRC violations, no
  unconnected items and no schematic parity issues. Three warnings for J1's silkscreen
  outline running to the board edge are excluded; the fab trims silkscreen there.
- ERC reports three warnings, all expected: SBU2 tied to VDD, and SBU1 and the BME68x's
  SDO pin tied to ground. KiCad flags a bidirectional pin wired to a power rail.
- **Reset held by a USB 3 host.** nRESET is on a SuperSpeed contact. A full-featured cable
  to a USB 3 host connects that contact to the host's receiver, which is terminated to
  ground with a few tens of ohms. In one plug orientation this is expected to hold the
  board in reset. Chargers and USB 2.0 cables leave the contact open. The DevKit has the
  same exposure. JP1 can be cut to disconnect nRESET from the receptacle; SWD still works
  without it. Not yet observed on a bench. A series resistor cannot do both jobs: against
  the module's 13 kΩ pull-up it would need about 30 kΩ to keep reset high against the
  host, and no more than about 5.6 kΩ for a probe to pull reset low through it.
- The same host receivers load SWDIO and SWDCLK in the other orientation. That is
  harmless: nothing drives them hard when no probe is attached.
- **R1 is bridged on the first build**, because no 1 Ω resistor was in stock. Without it
  the hot-plug ring in section 5.2 is undamped: an estimated 8 V peak against the
  regulator's 6.5 V absolute maximum whenever a cable that is already live is plugged
  in. A USB-C source on a USB-C cable applies VBUS only after it detects the board, so
  it does not produce that step; a USB-A to USB-C cable does. Fit R1 before relying on
  such cables, and run the hot-plug test in section 8 both ways. D1 starts to conduct at
  6 V and will clip some of the ring, but at the amps involved its clamping voltage is
  above the regulator's limit.
- **Regulator input rating.** The AP2112's 6.5 V absolute maximum leaves little room
  above VBUS, which is why R1 and the larger C1 exist (5.2). For a later revision,
  consider a regulator rated for at least 10 V at its input, twice VBUS: the hot-plug
  ring then needs no damping, and R1 and its 0.24 V drop can go. It must still supply
  the SCD43's 205 mA peaks and meet R-7. None has been selected.
- SBU2 carries VDD to the receptacle. A short there is limited by U1's 50 mA foldback.
- **USB current.** USB 2.0 holds a device that has not been configured to 100 mA (5.1),
  and the SCD43's pulses take this board to about 240 mA. Chargers do not police it; a
  computer's port that limits current could shut off. The test in section 8 checks one.
- SWDCLK and SWDIO are clamped by D1. nRESET, SWO and the two UART lines have no ESD
  protection, like the DevKit's.
- The SCD43's automatic self-calibration needs weekly exposure to fresh air. In a room
  that never drops to 400 ppm the reading drifts; firmware should allow a forced
  recalibration.
- Whether Zephyr's SCD4x driver accepts the SCD43 has not been checked. The command set is
  shared with the SCD41.
- I2C at 400 kHz would need external pull-ups: fit R5 and R6 (5.8).
- The MCU's average current as a Thread router is assumed, not measured (5.3).
- **Radio supply.** One regulator feeds everything, so the SCD43's 205 mA pulses dip the
  rail the module shares, and the module allows only 10 mV of ripple or noise (R-12).
  The estimate in 4.3 says the dip stays under that; it has not been measured. If it
  does not, the radio may lose packets while the sensor measures.
- The BME68x heater current and its effect on the SCD43 and SHT4x readings are not
  characterized.
- The island's slots are at OSH Park's 0.508 mm minimum for drilled slots. Its slots page
  lists slots that join as untested, so these two stop 0.5 mm apart. The leak sensor
  board's slots were drawn as joined 0.508 mm lines on Edge.Cuts and came back fine,
  which the fab's documentation does not promise.
- The SHT4x island is held by a 1.5 mm strip at the left edge, a 1.37 mm strip at the
  rear edge and the 0.5 mm web between the slots. Handle the bare board with care.
- Three holes hold the board in a flat triangle, 29 mm wide and 20 mm deep. The rear
  corners rest on the case's ledges only. The case model in `Case/` still has four
  posts and has to be updated before it is printed.
- The receptacle's through-hole pins have a 0.10 mm annular ring, under OSH Park's
  0.127 mm minimum, and GCT recommends a board 1.00 to 1.20 mm thick: on 1.6 mm its pin
  tails (1.05 mm) and shell stakes (1.15 mm) stop short of the bottom. Both come from
  GCT's recommended layout (drawing sheet 2); the ring cannot grow without breaking the
  6 mil spacing on the 0.8 mm pin pitch. The DevKit uses the same receptacle and
  footprint on a 1.6 mm board, and its receptacle came out fine.
- CC2 runs on the top layer under the receptacle's metal shell, insulated from it only
  by solder mask.
- The SWD lines pass through D1's package. The datasheet gives the capacitance this adds
  (3.5 pF) but no resistance for the path between the two pins of a pair; it is a bond
  or lead-frame connection and is assumed negligible for SWD.
- The heat figures in 5.9 are estimates. Measure the SHT4x against a reference in the
  enclosure, in both SCD43 modes, before trusting or correcting its reading.
- Whether to run the SCD43 in its 5 s mode (15 mA) or its 30 s low power mode (3.2 mA) is
  a firmware choice. The datasheet states the CO2 accuracy for the 5 s mode only.
- With vents only at the rear, air reaches the sensors by diffusion. That is fast enough
  for CO2 if the open vent area is about 1 cm² or more. It does not remove heat: expect
  the SHT4x to read a couple of degrees above the room until that is calibrated out or
  the enclosure gets a second opening for through-flow.
- The antenna's performance in this placement is not measured. The module's datasheet
  (section 5.3.2) gives 30 mm to the sides and 40 mm above or below as the safe distance
  for metal, which nothing on a 35 mm board can meet, and says metal closer than 20 mm
  "will begin to significantly degrade performance". The holes take the case's plastic
  pegs, not screws, so the nearest metal is the SCD43's can and the BME68x, about 22 mm
  from the antenna, and the receptacle at 25 mm. The datasheet also says the antenna is
  tuned on a 113 × 63.5 mm board and asks for a range test with the real board and
  enclosure (section 8). Three more departures from its figure 12:
  - The module is 2 mm off the center of its edge.
  - The figure wants at least 15 mm of board edge on each side of the module. This board
    has 12.35 mm on the left and 16.35 mm on the right; a 35 mm board cannot give more
    than 14.35 mm on both sides.
  - The antenna end is 0.5 mm in from the edge instead of on it (5.9). The fab's edge
    keep-out would have allowed about 0.18 mm, as on the DevKit's 0.23 mm, but moving the
    module and its fan-out was too much work at the end of this layout. Do it in the next
    revision.
- SWO and nRESET leave the module by paths that differ from the fabricated leak sensor
  board. They pass the design rules. nRESET's bottom trace runs 0.05 mm outside the
  antenna keep-out, no closer than the ground pour, which on both layers runs right up to
  the keep-out's edge.
- The button can only be pressed with the case's shell off, and the LED is seen only
  through the rear vent slots, next to the SCD43's air path. Both are placeholders for a
  side-actuated switch and a rear-facing indicator in a later revision.
- With the SCD43 turned (5.4), its pulsed supply pad is fed through the 18 mΩ link under
  the part, not straight from the reservoir capacitor. The numbers say that is fine;
  the dip at VDDH during a pulse has not been measured.
- D1 clamps to its own 6 V breakdown plus a diode drop, not to 3.3 V: the datasheet
  gives 12 V at 1 A and 17 V at 5 A. That takes most of a discharge away from the SWD
  pins but still exceeds their rating briefly; the module's own protection has to
  absorb the rest. D1's two pins per line are taken to be joined inside the part, as
  the datasheet's pin diagram labels them; that is not stated in its text.
- The enclosure does not exist yet. Vent position, the light pipe for D2 and access to SW1
  depend on it.

## 10. References

Datasheets, with the revision that was read. The links are the manufacturers' own and
were checked on 2026-11-19.

- [Sensirion SCD4x datasheet](https://sensirion.com/resource/datasheet/scd4x), version
  1.7, April 2025: tables 1, 4 and 5 and sections 2.3, 3.8, 4.2 and 4.5. Source for
  sections 4.1, 4.3 and 5.4 and for R-1, R-7 and R-10.
- [Sensirion STCC4 datasheet](https://sensirion.com/resource/datasheet/STCC4), version 1,
  June 2025: tables 1 and 3, sections 1.1.2 to 1.1.4 and figure 3. Source for the STCC4
  column in section 4.1.
- [Sensirion SHT4x datasheet](https://sensirion.com/resource/datasheet/sht4x), version
  7.3, June 2026: tables 1 and 2 (SHT40: ±1.8 %RH and ±0.2 °C typical) and the supply
  range. Source for R-2 and sections 4.3 and 5.5.
- [Diodes Incorporated AP2112 datasheet](https://www.diodes.com/assets/Datasheets/AP2112.pdf),
  DS39724 Rev. 2-2: the electrical characteristics tables and the load-transient figure.
  Source for sections 4.3, 5.2 and 5.3.
- GCT USB4056, the receptacle used:
  [product specification](https://gct.co/files/specs/usb4056-spec.pdf), revision A2, and
  [drawing](https://gct.co/files/drawings/usb4056.pdf). Its footprint and model are in
  `HW/BL54L15μ_DevKit/Components/USB4056_03_A`. Source for sections 4.2 and 5.1.
- GCT USB4105 [product specification](https://gct.co/files/specs/usb4105-spec.pdf),
  revision A3, and [drawing](https://gct.co/files/drawings/usb4105.pdf); GCT USB4085
  [product specification](https://gct.co/files/specs/usb4085-spec.pdf), revision B, and
  [drawing](https://gct.co/files/drawings/usb4085.pdf). The alternatives in section 4.2.
- [STMicroelectronics USBLC6-2 datasheet](https://www.st.com/resource/en/datasheet/usblc6-2.pdf),
  DS4260 Rev 7, December 2021: table 2, sections 2.2 and 2.3 and figure 6. Source for D1
  in section 5.2.
- Bosch Sensortec
  [BME680 datasheet](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme680-ds001.pdf),
  BST-BME680-DS001-09, revision 1.9, and
  [BME688 datasheet](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme688-ds000.pdf),
  BST-BME688-DS000-03, revision 1.3: the pin-out sections (both numbered clockwise in top
  view) and section 7.2. Source for sections 4.3 and 5.6.
- [Ezurio BL54L15µ datasheet](https://www.ezurio.com/documentation/datasheet-bl54l15u),
  version 1.1, August 2025: the pin table, table 3 (supply range and the 10 mV ripple
  limit), the I2C pull-up note, sections 5.2 to 5.3.2 and figure 12 (land pattern and
  antenna keep-out). Source for R-12 and sections 4.3, 5.7, 5.9 and 9.

Standards and other sources:

- [USB Type-C Cable and Connector Specification](https://www.usb.org/document-library/usb-type-cr-cable-and-connector-specification-release-24),
  release 2.x: sink Rd termination and the 5.5 V VBUS maximum (sections 5.1 and 5.2).
- [USB 2.0 Specification](https://www.usb.org/document-library/usb-20-specification),
  the June 2025 bundle: section 7.2.1, the 100 mA unit load and the limit before a
  device is configured (sections 5.1 and 9).
- [Universal Serial Bus 3.2 Specification](https://www.usb.org/document-library/usb-32-revision-11-june-2022),
  revision 1.1: receiver termination (section 9).
- `HW/BL54L15μ_DevKit` and `HW/SWD_USBC_InlineAdapter` in this repository, the source for
  the debug pinout in section 5.1.
- OSH Park's [two-layer service rules](https://docs.oshpark.com/services/two-layer/),
  [slots](https://docs.oshpark.com/submitting-orders/slots/) and
  [board outline](https://docs.oshpark.com/submitting-orders/board-outline/) pages, read on
  2026-11-20: trace, drill, annular ring and board edge limits, drilled slots from
  0.508 mm and the 1.73 mm cutout bit (sections 5.9 and 9).
