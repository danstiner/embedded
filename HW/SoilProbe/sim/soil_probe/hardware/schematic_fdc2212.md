# FDC2212 probe head — schematic (text form)

```
   3.0 V ---+--- U1 FDC2212DNTR VDD (100 nF + 1 uF)
            |
            +--- U2 40 MHz oscillator (gated by its EN or a P-FET) ---> U1 CLKIN
   nRF I2C SDA/SCL --- U1 SDA/SCL (4.7 k pull-ups), U1 INTB -> nRF GPIO, U1 SD -> nRF GPIO (shutdown)
   U1 IN0A ---+--- L1 12 uH ---+--- IN0B
              |                |
              +--- C1 10 pF ---+
              |                |
           SENSE strip      GND strip (probe; GND strip also to circuit GND)
```

| ref | value | note |
|---|---|---|
| U1 | FDC2212DNTR | 2-ch 28-bit, sensor f ≤ 10 MHz |
| U2 | 40 MHz CMOS oscillator (e.g. ECS-2520MV-400) | external reference; gate it between readings |
| L1 | 12 µH, Q ≥ 20 at 10 MHz, shielded | with C1 + probe 11–30 pF → 7.3–10 MHz |
| C1 | 10 pF C0G | fixed tank C; keeps f ≤ 10 MHz when the probe is dry |
| C2 | 100 nF, C3 1 µF | decoupling |
| R1, R2 | 4.7 kΩ | I2C pull-ups (or use nRF internal) |

Notes:
- Tank is single-ended: the probe's ground strip is circuit ground, sense strip on IN0A side of L1.
  (FDC2x1x sensor topology: L and C in parallel between INxA and INxB; check the datasheet figure
  for the single-ended connection and whether INxB should be grounded through the sensor.)
- IDRIVE: run the datasheet's Rp/amplitude search; expect Rp 1.9–10 kΩ with the 0.3 mm coat.
- Use the second channel for an in-air / reference capacitor if you want to cancel reference drift.
- Compute C_probe = 1/(L(2πf)²) − C1 − C_par; correct with bulk EC (S_σ ≈ 0.4·θ at 8–10 MHz, bare geometry).
