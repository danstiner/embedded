#!/usr/bin/env python3
"""Predicted readings in reference media, for bench validation (TEST_PLAN.md phase 1).
Liquids wet the faces completely, so this tests the field model, the line model and the
oscillator without any contact uncertainty.  Permittivities at 25 C; the alcohols relax
above 300 MHz, so their static values hold at the probe frequency to a few percent."""
import numpy as np
import soil_probe_sim as s, probe as p, system_sim as S

MEDIA = [('air', 1.0, 0.0), ('dry sand', 2.7, 0.0), ('mineral oil', 2.2, 0.0),
         ('isopropanol 99 %', 18.6, 0.0), ('acetone', 20.7, 0.0),
         ('water, deionised', s.water_er(25), 0.0005), ('water, tap 0.3 mS/cm', s.water_er(25), 0.03),
         ('NaCl 0.5 g/L (1.0 mS/cm)', s.water_er(25), 0.10), ('NaCl 1 g/L (2.0 mS/cm)', s.water_er(25), 0.20),
         ('NaCl 2 g/L (3.9 mS/cm)', s.water_er(25), 0.39)]

if __name__ == '__main__':
    S.OSC = S.Oscillator()
    print(f"{'medium':26s} {'er':>5s} {'f_osc MHz':>9s} {'FOUT kHz':>9s} {'REF-AMP mV':>10s} {'C pF':>6s} {'G mS':>6s}")
    for name, er, sig in MEDIA:
        f, det, C, G = S._settle(lambda fr: p.feed_Y((er, sig, 0.0), fr))
        if S.OSC.stalled(C, G):
            print(f'{name:26s} {er:5.1f}   oscillator stalls (probe loss {G*1e3:.0f} mS)'); continue
        print(f'{name:26s} {er:5.1f} {f/1e6:9.2f} {f/1024e3:9.2f} {-det*1e3:10.1f} {C*1e12:6.2f} {G*1e3:6.2f}')
    print('\nImmersion depth in tap water (strip length in water, rest in air):')
    for ex in (60, 40, 20, 0):
        f, det = S.measure((s.water_er(25), 0.03, 0.0), exposed_mm=ex)
        print(f'  {80-ex:2d} mm: {f/1e6:7.2f} MHz')
