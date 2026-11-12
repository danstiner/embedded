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

|                          | Relay    | **PhotoMOS** | Driver IC + FETs | TPSI8830    | TRIAC       |
| ------------------------ | -------- | ------------ | ---------------- | ----------- | ----------- |
| Hold current (R-8)       | 70–90 mA | 5–10 mA      | ~5 mA            | ~5 mA       | ~10 mA      |
| 1 mA load (R-3)          | marginal | ✓            | ✓                | ✓           | ✗           |
| Leakage (R-6)            | ✓        | ✓            | ✓                | ✓           | ✗ (snubber) |
| Parts per channel        | 4        | 3            | ~10              | 3–4         | 5+          |
| Available to buy         | ✓        | ✓            | ✓                | ✗ (preview) | ✓           |
| Short-circuit protection | rugged   | none         | possible         | built in    | none        |

**Chosen: PhotoMOS.** An LED inside the package lights a photovoltaic cell that turns on
two back-to-back MOSFETs. It meets every requirement with three parts per channel. It
does not have short-circuit protection inherently, but a fuse can be added.

TI's reference designs for 24 VAC thermostat switching (section 10) both use discrete
MOSFET pairs with a separate isolated gate drive. Their reasons are cost per channel in
volume and switching in microseconds, which a power-stealing thermostat needs. Neither
applies to a two-channel prototype with no power supply.

TI's TPSI8830 may be the better switch once it can be purchased: 30 mΩ and it shuts itself
off on a short.

## 5. Circuit

Two identical channels share one fused R input. Only one channel is shown.

```
 logic side (3.3 V, USB ground) :        furnace side (24 VAC, floating)
                                :
 HEAT_EN o--+--[R1 220R]---+    :    +------+--- [F1 3A]-- o R
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
- Heat: at 1.5 A and the maximum 65 mΩ the switch dissipates 0.15 W, a rise of about
  37 °C. Allowing 1.6× for hot resistance (my estimate) gives 0.23 W against 0.26 W
  allowed at 60 °C, so about 10 % margin on a pessimistic estimate. By the datasheet's own
  current derating, 1.5 A is 77 % of the 1.95 A allowed at 60 °C. The thermal resistance,
  about 250 °C/W, is derived from the datasheet's derating figure. Give pins 4 and 6
  generous copper on the PCB to carry heat away.
- 100 V was chosen over the 60 V parts common in HVAC for margin, not because 60 V is
  impossible. A 60 V switch works with a tighter clamp (43 V standoff, about 55 V at
  1 A), but that leaves under 10 % headroom, nothing for a surge, and a PhotoMOS has no
  avalanche rating to absorb an overshoot. Both TI reference designs use 100 V MOSFETs:
  TIDA-00751 allows for a 42 V peak and up to 84 V in a mis-wired two-transformer
  system; TIDA-010085 notes that the surge clamp can reach 65 V.

Parts considered (DigiKey, 2026-11-12, quantity 1):

| Part              | Rating       | At 60 °C | R_on max | Isolation | Price                | Outcome                                                |
| ----------------- | ------------ | -------- | -------- | --------- | -------------------- | ------------------------------------------------------ |
| **TLP3109A(TP,F** | 100 V, 3 A   | 1.95 A   | 65 mΩ    | 1500 V    | $4.14, in stock      | chosen                                                 |
| TLP3546A(TP1,F    | 100 V, 3.5 A | 2.3 A    | 80 mΩ    | 2500 V    | $4.11, none in stock | unavailable                                            |
| TLP241BF(D4TP4,F  | 100 V, 2 A   | 1.3 A    | 200 mΩ   | 5000 V    | $2.55                | fallback: enough for mA loads, short of 1.5 A when hot |
| TLP3556A(TP1,F    | 100 V, 2 A   | 1.3 A    | 200 mΩ   | 2500 V    | $3.62                | same as TLP241BF, dearer                               |
| AQV252GAX         | 60 V, 2.5 A  | –        | ~100 mΩ  | –         | $5.89                | 60 V and dearer                                        |
| TLP3122A          | 60 V, 1.4 A  | –        | 250 mΩ   | –         | $2.16                | 60 V, under 1.5 A                                      |

### 5.2 LED resistor: 220 Ω (R1, R3)

The datasheet recommends 5 to 25 mA. `I = (V_GPIO − V_LED) / R`:

| Case            | V_GPIO | V_LED  | I      |
| --------------- | ------ | ------ | ------ |
| Worst-case low  | 3.0 V  | 1.80 V | 5.4 mA |
| Nominal         | 3.3 V  | 1.65 V | 7.5 mA |
| Worst-case high | 3.47 V | 1.50 V | 9.0 mA |

The low case is still above the recommended minimum and 1.8× the trigger current. The
high case, plus 0.3 mA in the pull-down, stays under 10 mA (R-8). The GPIO drives the LED
directly; no transistor is needed. The 3.0 V low figure is my assumption for a sagging
3.3 V rail.

### 5.3 Pull-down: 10 kΩ (R2, R4)

Holds the input at 0 V when the GPIO is not driving it (R-2). Against the roughly 45 kΩ
internal pull-up some ESP32 pins apply during reset, the input sits at 0.6 V, too low to
light the LED. It cannot override a pin that actively drives high during boot, so pin
choice matters (section 7).

### 5.4 Optional indicator: 2.2 kΩ and a red LED (R5/D3, R6/D4)

One LED per channel, from the control input to ground, lit while the ESP32 commands the
channel closed. It shows the commanded state, not that current is flowing in the furnace
circuit; an indicator on the field side would leak through the load and break R-6.

At 2.2 kΩ it draws about 0.7 mA, which a modern high-brightness 0603 LED shows clearly
indoors. Fitted, a channel draws about 8.5 mA nominal and up to 10.2 mA worst case, just
over the R-8 limit, which is why R-8 is stated without them. Leave R5, D3, R6 and D4 off
the board to save the current in a battery-backed build.

### 5.5 Clamp: SMBJ48CA bidirectional TVS (D1, D2)

When the switch opens on a relay coil or gas valve, the coil forces its current to keep
flowing and the voltage across the switch rises until something conducts. The TVS is that
something, at a controlled voltage (R-5).

|                        | SMBJ48CA   | Needed                            |
| ---------------------- | ---------- | --------------------------------- |
| Does not conduct below | 48 V       | ≥ 45 V peak                       |
| Clamps at, for 2.1 A   | about 64 V | ≤ 80 V (switch's recommended max) |
| Leakage                | a few µA   | see 5.7                           |

The SMBJ48CA figures (breakdown 53.3 to 58.9 V, 77.4 V at 7.8 A) are the standard values
for the type, from memory; confirm them on the datasheet of the brand bought. 2.1 A is
the peak of 1.5 A RMS, the most the coil can carry at the instant the switch opens; the
64 V figure is interpolated between those two points. TI measured about ±46 V on a relay coil
with a 40 V TVS in TIDA-010085, which is the same behaviour one size down.

I have no inductance figures for furnace coils, but the load current bounds the energy. A
coil drawing 1.5 A at 24 VAC has at most 16 Ω of reactance, 42 mH at 60 Hz, so at the
current peak it stores no more than ½ × 42 mH × (2.1 A)² ≈ 0.1 J (in general, VA / ω). A
600 W TVS absorbs roughly 0.6 J in a 1 ms pulse. The test in section 8 measures it on a
real coil.

An RC snubber is ruled out by R-6: 100 nF passes about 1.2 mA at 60 Hz with the switch
open. A rectifier and capacitor across the switch, as power-stealing thermostats have,
would also absorb the kick but leaks through the load in the same way. The TVS goes
across the switch, not from W to C, so it works without a C wire.

### 5.6 Fuse: 3 A very-fast-acting, surface-mount (F1)

Protects the thermostat cable and transformer from a short (R-9); older furnaces may have
no fuse of their own. F1 carries both channels: 1.5 A on one (R-3) plus a fan relay on
the other, or all 1.7 A a 40 VA transformer can supply, is about 1.7 A continuous. A fuse
run continuously at 60 °C should be loaded to about two thirds of its rating (the usual
75 % rule and roughly 10 % more for temperature; rules of thumb, not from this fuse's
datasheet), which needs 3 A. Furnace control boards that have a fuse commonly use 3 A
too. The cost is that 3 A is above the switch's 1.95 A hot rating, so the fuse protects
against shorts, not sustained overloads. Proposed part: Littelfuse 0451003 (Nano2, 125 V). Its ratings,
including breaking capacity against a shorted transformer's 10 to 20 A (my estimate), are
still to be confirmed on the datasheet.

Fuse or resettable PTC:

|                                          | Fast fuse, 3 A (chosen)              | PTC, e.g. 2920L110/60 (1.1 A hold)                        |
| ---------------------------------------- | ------------------------------------ | --------------------------------------------------------- |
| Carries 1.5 A at 60 °C                   | yes                                  | no: hold current falls with temperature, to roughly 0.8 A |
| Clears a hard short in                   | milliseconds                         | about 0.5 s (listing figure)                              |
| Lets through, against the switch's 8 A²s | to be confirmed, expected well under | tens of A²s                                               |
| Maximum fault current                    | 50 A AC (listing)                    | 20 A (listing)                                            |
| After a fault                            | replace the part                     | resets itself                                             |

The PTC fails on two counts. To carry 1.5 A hot it would need a hold current over 2 A,
which trips even more slowly; and at any size it lets through several times the energy
the PhotoMOS survives (9 A for 0.1 s is about 8 A²s), so it would protect the wiring but
not the switch. A fast fuse might save the switch; that is not guaranteed, because a
shorted transformer can exceed 9 A outright. A fuse drawn as a thin PCB trace is not an
option: it has no defined rating and fails by burning the board.

### 5.7 Leakage when open (R-6)

At 30 VAC, 60 Hz: 1 µA (switch) + 5.2 µA (its 460 pF) + 5 µA (TVS) + about 11 µA (TVS
capacitance, assumed 1 nF) ≈ 23 µA, against a 100 µA limit.

### 5.8 Isolation (R-7)

Isolation is needed because the two sides have unrelated references. The furnace's 24 VAC
secondary is often bonded to chassis earth at C, and the ESP32's USB ground can reach earth
through a PC or charger; a shared connection would tie the two together, and R, W and G
swing up to ±42 V against it, far outside what a GPIO tolerates. A switch for AC also has
to float with the line it switches.

The only link between the two sides is the light path inside U1 and U2, rated 1500 V RMS.
That is far above anything a 24 VAC Class 2 circuit produces, but it is functional
isolation, not a safety rating. The datasheet does not
state the package's creepage distance. The field side is never connected to logic ground;
C is a parking terminal. For the PCB: keep logic and field copper as far apart as the
package allows and route no copper under U1 and U2.

## 6. Bill of materials

| Ref    | Value                     | Part                                  | Package                    |
| ------ | ------------------------- | ------------------------------------- | -------------------------- |
| U1, U2 | TLP3109A                  | Toshiba TLP3109A(TP,F                 | 2.54SOP6 (Toshiba 11-7C1S) |
| R1, R3 | 220 Ω 1 %                 | any                                   | 0603                       |
| R2, R4 | 10 kΩ                     | any                                   | 0603                       |
| D1, D2 | SMBJ48CA                  | Littelfuse, Vishay or equivalent      | SMB                        |
| R5, R6 | 2.2 kΩ                    | any; optional                         | 0603                       |
| D3, D4 | red LED                   | any high-brightness; optional         | 0603                       |
| F1     | 3 A very fast             | Littelfuse 0451003.MRL (to confirm)   | Nano2                      |
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


| Color         | Terminal | Function                    |
| ------------- | -------- | --------------------------- |
| Red           | R        | 24 VAC power supply         |
| Blue or Black | C        | Common return circuit       |
| White         | W        | Heat call                   |
| Yellow        | Y        | Cooling call                |
| Green         | G        | Fan or blower control       |
| Orange/Blue   | O/B      | Heat-pump reversing valve   |
| Brown or Gray | AUX/E    | Auxiliary or emergency heat |
| Extra (Y2/W2) | –        | Second stage cooling/heat   |

## 8. Verification

Not yet run. Bench first, on a spare 24 VAC transformer, then the furnace.

| Test                                                             | Checks        | Pass                                                |
| ---------------------------------------------------------------- | ------------- | --------------------------------------------------- |
| Inputs open: resistance R–W, R–G                                 | R-2           | open circuit                                        |
| Resistance from J1 GND to every J2 terminal                      | R-7           | open circuit                                        |
| Input driven to 3.3 V through an ammeter                         | R-8           | 6.5–9.5 mA; R–W below 0.5 Ω                         |
| Input tied to 3.3 V through 47 kΩ                                | R-2           | stays open                                          |
| Open channel, µA meter in series with a 1 kΩ load                | R-6           | < 100 µA                                            |
| Closed into 22 kΩ, scope the load                                | R-3           | clean sine                                          |
| Closed into 16 Ω, 50 W (1.5 A) for 30 min                        | R-3           | drop < 0.3 V, case rise < 50 °C                     |
| Switch a 24 VAC relay coil off 20 times, scope across the switch | R-5           | peak ≤ 80 V                                         |
| Reset and unplug the ESP32 while a channel is closed             | R-2           | load drops, no pulse at boot                        |
| Short R to C at the terminals (last: blows the fuse)             | R-9           | fuse opens, nothing else damaged                    |
| On the furnace: idle 10 min, then G, then W, then reset mid-call | R-1, R-2, R-6 | no phantom call; normal cycles; call drops on reset |

## 9. Known limitations and open questions

- A hard short on W or G while that channel is closed may destroy the PhotoMOS before the
  fuse clears.
- Both channels at 1.5 A together (3 A through F1) is not supported; the fuse is sized for
  about 2 A continuous in total.
- A sustained overload between 2 and 3 A can overheat a PhotoMOS without blowing the fuse.
- A firmware hang with an output high keeps that channel closed until the watchdog fires.
- This board is not a safety device; the furnace's own limit and flame safeties remain in
  charge.
- To confirm by test or datasheet: hot on-resistance, coil energy, TVS values and
  capacitance, transformer short-circuit current, the fuse's ratings and melting I²t,
  the TLP3109A's creepage distance.

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
