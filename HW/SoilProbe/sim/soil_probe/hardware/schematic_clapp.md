# Clapp oscillator probe head — schematic (text form for KiCad entry)

Verified in ngspice: `spice/clapp_osc.cir`, numbers in `results/clapp_spice_results.txt`.
Rail: 3.0 V regulated (TPS7A02 output or equivalent), switched by Q2 from an nRF GPIO (OSC_EN).

```
                 VOSC (3.0 V, gated)
                   |
        +----------+----------+-------------------+
        |          |          |                   |
       R1 22k     C5 100n     |                  R5 100k (peak-det bleed, see below)
        |          |          |
        +----------|--------- C  Q1 MMBT3904
        |  base    |          B ----+
        |          |          E     |
   B ---+---||-----+---- L1 ---+--R--+--> SENSE electrode (probe strip, top+bottom)
        |  C4 10n        470nH  (RL ~4 ohm, inductor loss)
       R2 22k                        GND electrode ---> GND (probe strip, top+bottom)
        |
       GND

   Feedback divider:          B --||-- E      C1 22 pF C0G
                              E --||-- GND    C2 22 pF C0G
   Emitter bias:              E --[R3 390]-- GND        (Ie ~ 2.5 mA)

   Output pick-off:           E --||-- SQ_IN   C3 10 pF
   Squarer:                   U1 74LVC1G04, input SQ_IN, 1 M feedback R4 (out->in), output SQ_OUT
   Prescaler:                 U2 74LVC161 (SN74LVC161APWR): CLK=SQ_OUT, ENP=ENT=VOSC, CLR=VOSC,
                              LOAD=VOSC, A..D=GND, QD -> nRF GPIOTE input (f/16, 4.5-5.3 MHz)
   Peak detector (optional):  E --|>|-- PK    D1 BAT54;  PK --||-- GND C6 100 pF;  PK --[R5 100k]-- GND;
                              PK -> nRF SAADC (Vpk ~ 1.7-2.7 V, falls with soil EC)
   Power switch:              Q2 DMG2305UX P-FET, S=3.0 V, D=VOSC, G pulled to 3.0 V by 100k, driven low by OSC_EN
   Decoupling:                100 nF at Q1 collector, U1, U2 (C5, C7, C8)
```

Netlist (node names as in the SPICE):

| ref | value | from | to | note |
|---|---|---|---|---|
| Q1 | MMBT3904 | C=VOSC, B=b, E=e | | fT 300 MHz is enough at 85 MHz; BFR93A if you want margin |
| R1 | 22 kΩ | VOSC | b | bias |
| R2 | 22 kΩ | b | GND | bias (11 k Thevenin across the tank node; negligible vs 1/ωC_div ≈ 150 Ω) |
| R3 | 390 Ω | e | GND | Ie ≈ 2.5 mA; ≥2 mA needed for start-up at D ≈ 0.26 |
| C1 | 22 pF C0G | b | e | divider; sets negative resistance and loss pulling |
| C2 | 22 pF C0G | e | GND | divider |
| C4 | 10 nF | b | n0 | DC block; also isolates the probe's DC leakage from the bias |
| L1 | 470 nH ±2 % wirewound 0603 | n0 | n1 | Q ≥ 30 at 80 MHz, SRF ≥ 400 MHz |
| — | probe | n1 (sense) | GND (ground strip) | Cp 14–31 pF, Gp 0.2–2.7 mS coated |
| C3 | 10 pF C0G | e | SQ_IN | pick-off |
| U1 | 74LVC1G04 | SQ_IN | SQ_OUT | R4 1 MΩ output→input self-bias |
| U2 | 74LVC161 | CLK=SQ_OUT | QD → nRF | ÷16; check f_max ≥ 90 MHz at 3.0 V, else 74LVC1G74 ×4 |
| D1 | BAT54 | e | PK | peak detector (optional) |
| C6 / R5 | 100 pF / 100 kΩ | PK | GND | τ = 10 µs; sample after ~50 µs |
| Q2 | DMG2305UX | 3.0 V | VOSC | high-side switch; 100 k gate pull-up |
| C5, C7, C8 | 100 nF | VOSC | GND | at Q1, U1, U2 |

Layout rules:
- Q1, C1, C2, L1, C4 within 10 mm of the sense strip; the sense trace n1 is part of the tank —
  keep it short and off the ground pour (every pF of stray is in the calibration, every 0.1 pF of
  drift is 0.5 % of C_eff).
- Ground pour only under the electronics; none under the strips. Stitch top/bottom strips with vias.
- Keep the LVC161 and its clock trace away from the tank (85 MHz squarewave next to a 76 MHz tank
  will injection-lock at harmonics if coupled).
- Route QD to the nRF as a short trace with a 33 Ω series resistor.

nRF54L15 firmware sketch:
1. OSC_EN low (power on), wait 100 µs.
2. TIMER_gate in timer mode, 2.000 ms compare; TIMER_cnt in counter mode, COUNT task via PPI from
   GPIOTE IN (rising edge on QD). Start both from one PPI event, stop TIMER_cnt on TIMER_gate compare.
3. Read count N: f_osc = 16·N / 2 ms. SAADC sample PK once at ~1 ms.
4. OSC_EN high. Compute θ from (f_osc, Vpk) via the calibration table.
