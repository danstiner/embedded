#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "matplotlib",
#     "numpy",
# ]
# ///
"""
Collect and plot capacitance results from Elmer simulation sweeps.

Run after ElmerSolver has completed for each case. Reads capacitance.dat
files and params.json from each simulation directory, then generates
comparison plots.

Usage:
  python plot_results.py ./sim_output/sweep_epsilon
  python plot_results.py ./sim_output/sweep_gap
  python plot_results.py ./sim_output/sweep_geometry
"""

import json
import sys
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

try:
    import matplotlib
    matplotlib.use("Agg")  # headless
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("WARNING: matplotlib not found. Install with: pip install matplotlib")
    print("         Text-only output will be used.\n")


@dataclass
class SimResult:
    """Results from one simulation run."""
    label: str
    trace_width: float
    trace_gap: float
    soil_permittivity: float
    solder_mask_thickness: float
    finger_length: float
    sensing_depth: float
    capacitance_matrix: Optional[list] = None
    mutual_capacitance: Optional[float] = None  # pF


def parse_capacitance_file(cap_path: Path) -> Optional[list]:
    """
    Parse Elmer's capacitance.dat output.

    Handles two formats:
    1. Raw space-separated float matrix (default Elmer output):
         1.202368989E-15  1.345801501E-10
         1.345801501E-10 -6.314776575E-15
    2. Labeled format (some Elmer configs):
         C(1,1) = ...
         C(1,2) = ...
    """
    if not cap_path.exists():
        return None

    text = cap_path.read_text().strip()
    if not text:
        return None

    # Try labeled format first: C(i,j) = value
    labeled_values = []
    for line in text.splitlines():
        match = re.search(r'[Cc]\(\d+,\d+\)\s*=\s*([-+]?[\d.eE+-]+)', line)
        if match:
            labeled_values.append(float(match.group(1)))
    if labeled_values:
        return labeled_values

    # Raw space-separated float matrix
    values = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for tok in line.split():
            try:
                values.append(float(tok))
            except ValueError:
                continue

    return values if values else None


def collect_results(sweep_dir: Path) -> list:
    """Collect results from all simulation directories in a sweep.

    Reads from results.csv if available, otherwise scans individual dirs.
    """
    results = []

    if not sweep_dir.exists():
        print(f"Directory not found: {sweep_dir}")
        return results

    # Try CSV first
    csv_path = sweep_dir / "results.csv"
    if csv_path.exists():
        import csv
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                result = SimResult(
                    label=f"W{row['W_mm']}_G{row['G_mm']}_eps{row['soil_eps']}",
                    trace_width=float(row["W_mm"]),
                    trace_gap=float(row["G_mm"]),
                    soil_permittivity=float(row["soil_eps"]),
                    solder_mask_thickness=0,
                    finger_length=0,
                    sensing_depth=float(row["sensing_depth_mm"]),
                )
                c12 = row.get("C12_pF", "")
                if c12:
                    result.mutual_capacitance = float(c12)
                results.append(result)
        return results

    # Fallback: scan individual directories
    for sim_dir in sorted(sweep_dir.iterdir()):
        if not sim_dir.is_dir():
            continue

        params_path = sim_dir / "params.json"
        if not params_path.exists():
            continue

        with open(params_path) as f:
            params = json.load(f)

        result = SimResult(
            label=sim_dir.name,
            trace_width=params["trace_width"],
            trace_gap=params["trace_gap"],
            soil_permittivity=params["soil_permittivity"],
            solder_mask_thickness=params.get("solder_mask_thickness", 0),
            finger_length=params.get("finger_length", 0),
            sensing_depth=params["trace_width"] + params["trace_gap"],
        )

        # Try to read capacitance results
        cap_path = sim_dir / "capacitance.dat"
        cap_matrix = parse_capacitance_file(cap_path)
        if cap_matrix:
            result.capacitance_matrix = cap_matrix
            # For a 2-body system:
            # C(1,1) = self-capacitance of electrode 1
            # C(1,2) = mutual capacitance (negative of coupling)
            # The sensor capacitance is |C(1,2)| or equivalently C(1,1)
            if len(cap_matrix) >= 2:
                # Mutual capacitance magnitude, convert to pF
                result.mutual_capacitance = abs(cap_matrix[1]) * 1e12

        results.append(result)

    return results


def print_results_table(results: list, title: str):
    """Print results as a text table."""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")
    print(f"{'Label':<30} {'W(mm)':>6} {'G(mm)':>6} {'εr':>6} {'Depth(mm)':>9} {'C(pF)':>10}")
    print(f"{'-'*80}")

    for r in results:
        c_str = f"{r.mutual_capacitance:.3f}" if r.mutual_capacitance else "pending"
        print(f"{r.label:<30} {r.trace_width:>6.2f} {r.trace_gap:>6.2f} "
              f"{r.soil_permittivity:>6.1f} {r.sensing_depth:>9.2f} {c_str:>10}")

    print()


def plot_epsilon_sweep(results: list, output_path: Path):
    """Plot capacitance vs soil permittivity."""
    if not HAS_MATPLOTLIB:
        return

    eps_vals = [r.soil_permittivity for r in results]
    cap_vals = [r.mutual_capacitance for r in results if r.mutual_capacitance]

    if not cap_vals:
        print("  No capacitance data to plot (run ElmerSolver first).")
        return

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(eps_vals[:len(cap_vals)], cap_vals, 'o-', linewidth=2, markersize=8)
    ax.set_xlabel("Soil Relative Permittivity (εr)", fontsize=12)
    ax.set_ylabel("Capacitance per unit cell (pF)", fontsize=12)
    ax.set_title(f"IDC Sensor Response: W={results[0].trace_width}mm, G={results[0].trace_gap}mm",
                 fontsize=13)
    ax.grid(True, alpha=0.3)

    # Add VWC annotations on secondary x-axis (approximate Topp organic)
    # εr ≈ 2 + 50*θ for organic soils (very rough)
    ax2 = ax.twiny()
    ax2.set_xlim(ax.get_xlim())
    vwc_ticks = [0, 0.1, 0.2, 0.3, 0.4, 0.6, 0.8]
    eps_for_vwc = [2.0 + 50*v for v in vwc_ticks]
    ax2.set_xticks(eps_for_vwc)
    ax2.set_xticklabels([f"{v:.0%}" for v in vwc_ticks])
    ax2.set_xlabel("Approximate VWC (organic soil)", fontsize=10)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150)
    print(f"  Plot saved to: {output_path}")


def plot_gap_sweep(results: list, output_path: Path):
    """Plot capacitance and sensing depth vs gap width."""
    if not HAS_MATPLOTLIB:
        return

    gap_vals = [r.trace_gap for r in results]
    depth_vals = [r.sensing_depth for r in results]
    cap_vals = [r.mutual_capacitance for r in results if r.mutual_capacitance]

    if not cap_vals:
        print("  No capacitance data to plot (run ElmerSolver first).")
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    ax1.plot(gap_vals[:len(cap_vals)], cap_vals, 'o-', linewidth=2, markersize=8,
             color='tab:blue')
    ax1.set_xlabel("Gap Width G (mm)", fontsize=12)
    ax1.set_ylabel("Capacitance per unit cell (pF)", fontsize=12)
    ax1.set_title("Capacitance vs Gap Width", fontsize=13)
    ax1.grid(True, alpha=0.3)

    ax2.plot(gap_vals, depth_vals, 's-', linewidth=2, markersize=8,
             color='tab:orange')
    ax2.set_xlabel("Gap Width G (mm)", fontsize=12)
    ax2.set_ylabel("Sensing Depth ≈ W+G (mm)", fontsize=12)
    ax2.set_title("Sensing Depth vs Gap Width", fontsize=13)
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(str(output_path), dpi=150)
    print(f"  Plot saved to: {output_path}")


def plot_width_gap_sweep(results: list, output_dir: Path):
    """Plot capacitance vs penetration depth for W×G sweep.

    Generates:
      1. C12 vs penetration depth (W+G), colored by W
      2. Heatmap of C12 as a function of W and G
    """
    if not HAS_MATPLOTLIB:
        return
    import numpy as np

    has_cap = [r for r in results if r.mutual_capacitance]
    if not has_cap:
        print("  No capacitance data to plot (run ElmerSolver first).")
        return

    # --- Plot 1: C12 vs penetration depth, lines per W ---
    w_vals = sorted(set(r.trace_width for r in has_cap))

    fig, ax = plt.subplots(figsize=(9, 6))
    for w in w_vals:
        subset = sorted([r for r in has_cap if r.trace_width == w],
                        key=lambda r: r.sensing_depth)
        depths = [r.sensing_depth for r in subset]
        caps = [r.mutual_capacitance for r in subset]
        ax.plot(depths, caps, 'o-', linewidth=2, markersize=7, label=f"W={w}mm")

    ax.set_xlabel("Penetration Depth W+G (mm)", fontsize=12)
    ax.set_ylabel("C12 (pF/m)", fontsize=12)
    ax.set_title("Capacitance vs Penetration Depth", fontsize=13)
    ax.legend(title="Trace Width")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    path1 = output_dir / "capacitance_vs_penetration_depth.png"
    fig.savefig(str(path1), dpi=150)
    print(f"  Plot saved to: {path1}")
    plt.close(fig)

    # --- Plot 2: Heatmap of C12(W, G) ---
    g_vals = sorted(set(r.trace_gap for r in has_cap))

    # Build matrix
    cap_grid = np.full((len(w_vals), len(g_vals)), np.nan)
    for r in has_cap:
        wi = w_vals.index(r.trace_width)
        gi = g_vals.index(r.trace_gap)
        cap_grid[wi, gi] = r.mutual_capacitance

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(cap_grid, origin='lower', aspect='auto',
                   extent=[g_vals[0], g_vals[-1], w_vals[0], w_vals[-1]],
                   interpolation='nearest')
    cb = fig.colorbar(im, ax=ax)
    cb.set_label("C12 (pF/m)", fontsize=11)

    # Add text annotations
    for wi, w in enumerate(w_vals):
        for gi, g in enumerate(g_vals):
            val = cap_grid[wi, gi]
            if not np.isnan(val):
                ax.text(g, w, f"{val:.0f}", ha='center', va='center',
                        fontsize=8, color='white' if val > np.nanmedian(cap_grid) else 'black')

    ax.set_xlabel("Gap G (mm)", fontsize=12)
    ax.set_ylabel("Trace Width W (mm)", fontsize=12)
    ax.set_title("C12 (pF/m) — Width × Gap", fontsize=13)
    ax.set_xticks(g_vals)
    ax.set_yticks(w_vals)
    fig.tight_layout()
    path2 = output_dir / "capacitance_heatmap_W_G.png"
    fig.savefig(str(path2), dpi=150)
    print(f"  Plot saved to: {path2}")
    plt.close(fig)


def main():
    if len(sys.argv) < 2:
        print("Usage: python plot_results.py <sweep_directory>")
        print("  e.g.: python plot_results.py ./sim_output/sweep_epsilon")
        sys.exit(1)

    sweep_dir = Path(sys.argv[1])
    results = collect_results(sweep_dir)

    if not results:
        print(f"No results found in {sweep_dir}")
        sys.exit(1)

    # Determine sweep type from directory name
    sweep_name = sweep_dir.name

    print_results_table(results, f"Results: {sweep_name}")

    if HAS_MATPLOTLIB:
        plot_dir = sweep_dir / "plots"
        plot_dir.mkdir(exist_ok=True)

        if "epsilon" in sweep_name:
            plot_epsilon_sweep(results, plot_dir / "capacitance_vs_epsilon.png")
        elif sweep_name == "sweep_width_gap":
            plot_width_gap_sweep(results, plot_dir)
        elif "gap" in sweep_name:
            plot_gap_sweep(results, plot_dir / "capacitance_vs_gap.png")
        else:
            # Generic: just print table
            pass


if __name__ == "__main__":
    main()
