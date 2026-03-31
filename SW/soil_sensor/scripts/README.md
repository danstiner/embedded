# IDC Capacitive Soil Moisture Sensor — FEM Simulation Toolkit

Parametric 2D electrostatic simulation of interdigitated capacitor (IDC)
geometries for soil moisture sensing, using **Gmsh** (meshing) and
**Elmer FEM** (solving).

## What this does

Models a 2D cross-section of one IDC unit cell with layered dielectrics:

```
    ┌───────────────────────────────────┐  ← far-field boundary
    │           SOIL (εr variable)      │
    │                                   │
    ├──┬──────┬───┬──────┬─────────────-┤  ← coating surface
    │  │ coat │   │ coat │   coating    │
    ├──┼──────┼───┼──────┼─────────────-┤  ← electrode surface
    │  │ Cu₁  │   │ Cu₂  │             │  ← 35µm copper
    ├──┴──────┴───┴──────┴─────────────-┤  ← substrate surface
    │         FR4 (εr ≈ 4.5)           │
    ├───────────────────────────────────┤  ← PCB bottom
    │         Air below                 │
    └───────────────────────────────────┘  ← ground
```

Elmer's `StatElecSolver` with `Calculate Capacitance Matrix = True`
extracts the capacitance matrix between electrodes. Sweeping soil εr
from 2 (dry) to 50+ (saturated) gives the sensor response curve.

## Prerequisites

### In a Distrobox/Toolbox on Bazzite:

```bash
# Create container
distrobox create --name fem-tools --image registry.fedoraproject.org/fedora-toolbox:41
distrobox enter fem-tools

# Install Gmsh
sudo dnf install -y gmsh python3-gmsh python3-pip python3-matplotlib

# Install Elmer (compile from source — no Fedora package)
sudo dnf install -y gcc gcc-gfortran gcc-c++ cmake make \
    openmpi-devel blas-devel lapack-devel \
    qt5-qtbase-devel qt5-qtscript-devel \
    paraview

# Clone and build Elmer
git clone https://github.com/ElmerCSC/elmerfem.git
cd elmerfem && mkdir build && cd build
cmake .. -DCMAKE_INSTALL_PREFIX=$HOME/.local \
         -DWITH_MPI=FALSE \
         -DWITH_ELMERGUI=FALSE \
         -DWITH_ElmerIce=FALSE
make -j$(nproc)
make install

# Add to PATH
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# Verify
ElmerSolver --version
ElmerGrid
```

### Alternative: just Gmsh (for mesh generation + visual inspection)

If you only want to generate and inspect the geometry/mesh without
solving, you only need:

```bash
pip install gmsh matplotlib
```

## Quick start

```bash
# Generate a single model with default parameters (W=1mm, G=1mm, εr=10)
python generate_idc_model.py

# Inspect the mesh in Gmsh GUI
gmsh sim_output/W1.00_G1.00_eps10.0/idc_unit_cell.msh

# If Elmer is installed, generate + solve in one step
python generate_idc_model.py --solve

# Custom geometry
python generate_idc_model.py -W 0.5 -G 2.0 --soil-epsilon 25
```

## Parameter sweeps

```bash
# Sweep soil permittivity (εr = 2 to 50)
python generate_idc_model.py --sweep-epsilon --solve

# Sweep electrode gap (G = 0.25 to 5mm)
python generate_idc_model.py --sweep-gap --solve

# Compare different W/G combinations
python generate_idc_model.py --sweep-geometry --solve

# Everything
python generate_idc_model.py --sweep-all --solve
```

## Collecting results

After solving, plot the results:

```bash
python plot_results.py ./sim_output/sweep_epsilon
python plot_results.py ./sim_output/sweep_gap
```

## Manual workflow (step by step)

If you prefer to run each step individually:

```bash
# 1. Generate mesh + SIF files
python generate_idc_model.py -W 1.0 -G 1.0 --soil-epsilon 15

# 2. Inspect mesh in Gmsh
gmsh sim_output/W1.00_G1.00_eps15.0/idc_unit_cell.msh

# 3. Convert mesh to Elmer format
cd sim_output/W1.00_G1.00_eps15.0
ElmerGrid 14 2 idc_unit_cell.msh -out mesh -autoclean

# 4. Run Elmer solver
ElmerSolver

# 5. Check capacitance output
cat capacitance.dat

# 6. Visualize fields in ParaView
paraview results/case0001.vtu
```

## Interpreting results

The Elmer capacitance matrix output gives C(i,j) in Farads per
**unit depth** (since this is a 2D simulation). To get total capacitance
for an IDC with N finger pairs and finger length L:

```
C_total ≈ (N - 1) × C_unit_cell × L
```

where:
- C_unit_cell = |C(1,2)| from the simulation (mutual capacitance)
- L = finger length (default 20mm = 0.02m)
- N = number of finger pairs in your design

For an FDC2212 LC tank targeting ~8 MHz resonance with 4.7 µH inductor:
- Target C range: ~10 pF (dry) to ~100 pF (saturated)
- Size your N and L to land in this range

## File structure

```
sim_output/
├── W1.00_G1.00_eps10.0/
│   ├── params.json              ← geometry parameters
│   ├── idc_unit_cell.msh        ← Gmsh mesh (open in Gmsh to inspect)
│   ├── idc_unit_cell.geo_unrolled  ← Gmsh geometry script
│   ├── case.sif                 ← Elmer solver input
│   ├── ELMERSOLVER_STARTINFO    ← tells Elmer which SIF to use
│   ├── mesh/                    ← Elmer mesh format (after ElmerGrid)
│   ├── results/                 ← VTU output (after solving)
│   └── capacitance.dat          ← capacitance matrix (after solving)
├── sweep_epsilon/
│   ├── W1.00_G1.00_eps2.0/
│   ├── W1.00_G1.00_eps5.0/
│   └── ...
└── sweep_gap/
    ├── W1.00_G0.25_eps15.0/
    ├── W1.00_G0.50_eps15.0/
    └── ...
```

## Notes for FDC2212 integration

- The 2D simulation gives capacitance per unit length. Scale by finger
  length and number of unit cells to get total sensor capacitance.
- Add ~2-5 pF for PCB parasitic and connector capacitance.
- The FDC2212 measures LC tank resonant frequency, not capacitance
  directly. Use f = 1/(2π√(LC)) to convert.
- For best salinity rejection in potting soil, target the highest
  practical resonant frequency (use smaller L inductor → higher f).

## References

- Igreja & Dias, "Analytical evaluation of the interdigital electrodes
  capacitance for a multi-layered structure," Sensors and Actuators A,
  2004, vol. 112, pp. 291–301.
- Elmer Models Manual, Chapter: StatElecSolver
- TI Application Note SNOA935A (liquid level sensing with FDC2x1x)
