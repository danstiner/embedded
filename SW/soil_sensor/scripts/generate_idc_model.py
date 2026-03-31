#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "gmsh",
# ]
# ///
"""
PCB Capacitive Soil Moisture Sensor — Gmsh + Elmer Simulation Generator
========================================================================

Generates a 2D cross-section model of a two-layer PCB probe (e.g. OSH Park
stackup) inserted vertically into soil. Two electrode strips sit on the top
copper layer; the model includes FR4 core, solder mask, optional conformal
sealant, optional ground plane, and a surrounding soil domain.

The 2D cross-section is perpendicular to the electrode fingers. Elmer's
coordinate scaling converts mm geometry to meters for SI capacitance output.

Workflow:
  1. Run this script to generate mesh + Elmer input files
  2. Open the .msh file in Gmsh GUI to visually inspect geometry
  3. Run ElmerGrid to convert mesh format
  4. Run ElmerSolver to compute capacitance

Usage:
  uv run scripts/generate_idc_model.py                     # default geometry
  uv run scripts/generate_idc_model.py -W 1.0 -G 0.5      # custom W/G
  uv run scripts/generate_idc_model.py --sweep-epsilon      # sweep soil εr
  uv run scripts/generate_idc_model.py --sweep-gap          # sweep gap
  uv run scripts/generate_idc_model.py --sweep-geometry     # compare combos
  uv run scripts/generate_idc_model.py --solve              # also run Elmer

Requirements:
  gmsh (pip/uv)
  ElmerGrid and ElmerSolver in PATH (for --solve)
"""

import argparse
import csv
import json
import math
import os
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import gmsh
except ImportError:
    print("ERROR: gmsh python package not found. Install with: pip install gmsh")
    sys.exit(1)


# ============================================================================
# Topp equation: relate soil dielectric constant Ka to volumetric water content
# ============================================================================

def topp_vwc(ka: float) -> float:
    """
    Topp equation (Topp et al., 1980): apparent dielectric constant → VWC.

    θv = -5.3e-2 + 2.92e-2·Ka - 5.5e-4·Ka² + 4.3e-6·Ka³

    Returns volumetric water content as a fraction (e.g. 0.20 = 20%).
    """
    return -5.3e-2 + 2.92e-2 * ka - 5.5e-4 * ka**2 + 4.3e-6 * ka**3


# ============================================================================
# Geometry parameters (all dimensions in mm)
# ============================================================================

@dataclass
class PCBGeometry:
    """
    Parameters defining a 2-layer PCB probe cross-section in soil.

    Default stackup: OSH Park After Dark 2-layer
    https://docs.oshpark.com/services/afterdark/
      - Substrate: Ventec VT-447b, black 180Tg FR4, εr=4.35 @1GHz
      - Copper: 1 oz (1.4 mil / 0.0356 mm)
      - Core: 60 mil (1.524 mm) ±6 mil
      - Solder resist: clear SMOBC, 0.6 mil (0.0152 mm) ±0.2 mil
      - Finish: ENIG
      - Total board thickness: 63 mil (1.6 mm) nominal

    The PCB stackup (top to bottom):
      - Sealant (optional, wraps entire PCB)
      - Top solder mask
      - Top copper: two electrode strips (E1, E2) with gap
      - FR4 core
      - Bottom copper (optional ground plane)
      - Bottom solder mask
      - Sealant (optional)

    Soil fills the surrounding domain.
    """

    # Electrode geometry
    trace_width: float = 1.0        # mm — electrode strip width (W)
    trace_gap: float = 1.0          # mm — gap between electrodes (G)
    edge_gap: float = 0.5           # mm — margin from electrode to PCB edge

    # PCB stackup thicknesses (OSH Park After Dark)
    copper_thickness: float = 0.0356    # mm — 1.4 mil (1 oz copper)
    substrate_thickness: float = 1.524  # mm — 60 mil FR4 core
    solder_mask_thickness: float = 0.0152  # mm — 0.6 mil; 0 = no solder mask
    sealant_thickness: float = 0.0      # mm — 0 = none; e.g. 0.1 for conformal coat

    # Bottom copper
    has_ground_plane: bool = False

    # Material permittivities
    substrate_permittivity: float = 4.35  # Ventec VT-447b FR4 @1GHz (After Dark)
    solder_mask_permittivity: float = 4   # clear soldermask at ~1 MHz
    sealant_permittivity: float = 2.8     # silicone conformal coat
    soil_permittivity: float = 11.0       # swept; ~20% VWC via Topp

    # Domain
    soil_domain_size: float = 20.0  # mm — extent of soil around PCB
    finger_length: float = 20.0     # mm — electrode length for 2D→3D scaling

    # Mesh
    mesh_size_electrode: float = 0.005  # mm — fine mesh near electrodes
    mesh_size_global: float = 2.0       # mm — coarse mesh in far-field soil
    element_order: int = 2              # quadratic elements

    @property
    def pcb_width(self) -> float:
        """Total PCB width: edge_gap + W + G + W + edge_gap."""
        return 2 * self.edge_gap + 2 * self.trace_width + self.trace_gap

    @property
    def pcb_total_thickness(self) -> float:
        """Total PCB thickness including solder mask and copper."""
        t = self.substrate_thickness
        # Top: copper + solder mask
        t += self.copper_thickness
        if self.solder_mask_thickness > 0:
            t += self.solder_mask_thickness
        # Bottom: ground plane + solder mask
        if self.has_ground_plane:
            t += self.copper_thickness
        if self.solder_mask_thickness > 0:
            t += self.solder_mask_thickness
        return t

    @property
    def sensing_depth(self) -> float:
        """Approximate sensing depth ≈ W + G."""
        return self.trace_width + self.trace_gap


# ============================================================================
# STEP export helpers
# ============================================================================

def _rename_step_products(step_path: Path, surfaces: list, tag_to_name: dict):
    """Post-process STEP file to rename PRODUCT entries with material names.

    Gmsh/OCC writes products named like:
      'Open CASCADE STEP translator 7.8 1'     (assembly)
      'Open CASCADE STEP translator 7.8 1.1'   (first surface)
      'Open CASCADE STEP translator 7.8 1.2'   (second surface)
    The sub-part numbering matches the order of getEntities(2).
    """
    import re

    text = step_path.read_text()

    # Build ordered name list matching surface order
    surface_names = []
    for dim, tag in surfaces:
        surface_names.append(tag_to_name.get(tag, f"surface_{tag}"))

    surface_idx = 0

    def replace_product(match):
        nonlocal surface_idx
        prefix = match.group(1)
        name1 = match.group(2)

        # Sub-parts have names like "... 1.1", "... 1.2"
        # Assembly root is "... 1" (no dot suffix)
        if re.search(r'\d+\.\d+$', name1):
            if surface_idx < len(surface_names):
                new_name = surface_names[surface_idx]
                surface_idx += 1
            else:
                new_name = name1
            return f"{prefix}'{new_name}','{new_name}'"
        else:
            return f"{prefix}'pcb_sensor_assembly','pcb_sensor_assembly'"

    product_pattern = re.compile(
        r"(PRODUCT\()'([^']*?)'\s*,\s*'([^']*?)'",
    )
    text = product_pattern.sub(replace_product, text)
    step_path.write_text(text)


# ============================================================================
# Geometry and mesh generation
# ============================================================================

def generate_mesh(geom: PCBGeometry, output_dir: Path) -> Path:
    """
    Generate a 2D Gmsh mesh of a PCB probe cross-section in soil.

    Cross-section layout (not to scale, PCB centered in soil domain):

        ┌──────────────────────────────────────────┐
        │                   SOIL                   │
        │   ┌──────────────────────────────────┐   │
        │   │  sealant (if sealant_thickness>0)│   │
        │   │  ┌────────────────────────────┐  │   │
        │   │  │  solder mask (top)         │  │   │
        │   │  │  ┌────┐  gap  ┌────┐      │  │   │
        │   │  │  │ E1 │       │ E2 │      │  │   │  ← top copper
        │   │  │  └────┘       └────┘      │  │   │
        │   │  ├────────────────────────────┤  │   │
        │   │  │       FR4 core             │  │   │
        │   │  ├────────────────────────────┤  │   │
        │   │  │  bottom copper (optional)  │  │   │
        │   │  ├────────────────────────────┤  │   │
        │   │  │  solder mask (bottom)      │  │   │
        │   │  └────────────────────────────┘  │   │
        │   │  sealant                         │   │
        │   └──────────────────────────────────┘   │
        │                   SOIL                   │
        └──────────────────────────────────────────┘

    The origin is at the center of the soil domain.
    """

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 1)
    gmsh.model.add("pcb_soil_sensor")

    occ = gmsh.model.occ

    W = geom.trace_width
    G = geom.trace_gap
    eg = geom.edge_gap
    t_cu = geom.copper_thickness
    t_sub = geom.substrate_thickness
    t_sm = geom.solder_mask_thickness
    t_seal = geom.sealant_thickness
    D = geom.soil_domain_size
    pcb_w = geom.pcb_width

    # --- Y coordinates (build from center of FR4 outward) ---
    # FR4 core centered at y=0
    y_sub_bot = -t_sub / 2.0
    y_sub_top = t_sub / 2.0

    # Top side (above FR4)
    y_cu_top_bot = y_sub_top                    # top copper bottom
    y_cu_top_top = y_cu_top_bot + t_cu          # top copper top
    y_sm_top_top = y_cu_top_top + t_sm          # top solder mask top (0 if no SM)

    # Bottom side (below FR4)
    if geom.has_ground_plane:
        y_cu_bot_top = y_sub_bot                # bottom copper top
        y_cu_bot_bot = y_cu_bot_top - t_cu      # bottom copper bottom
    else:
        y_cu_bot_top = y_sub_bot
        y_cu_bot_bot = y_sub_bot

    y_sm_bot_bot = (y_cu_bot_bot if geom.has_ground_plane else y_sub_bot) - t_sm

    # Sealant wraps the whole PCB
    y_pcb_top = y_sm_top_top if t_sm > 0 else y_cu_top_top
    y_pcb_bot = y_sm_bot_bot if t_sm > 0 else (y_cu_bot_bot if geom.has_ground_plane else y_sub_bot)
    y_seal_top = y_pcb_top + t_seal
    y_seal_bot = y_pcb_bot - t_seal

    # Soil domain
    y_domain_top = y_seal_top + D
    y_domain_bot = y_seal_bot - D

    # --- X coordinates ---
    # PCB centered at x=0
    x_pcb_left = -pcb_w / 2.0
    x_pcb_right = pcb_w / 2.0

    # Electrodes on top copper
    # E1: from x_pcb_left + edge_gap to x_pcb_left + edge_gap + W
    x_e1_left = x_pcb_left + eg
    x_e1_right = x_e1_left + W
    # E2: from x_e1_right + G to x_e1_right + G + W
    x_e2_left = x_e1_right + G
    x_e2_right = x_e2_left + W

    # Sealant extends around PCB sides too
    x_seal_left = x_pcb_left - t_seal
    x_seal_right = x_pcb_right + t_seal

    # Soil domain
    x_domain_left = x_seal_left - D
    x_domain_right = x_seal_right + D

    # --- Create all rectangular bodies ---
    # We'll create each distinct region, then fragment them all.

    rects = {}  # name -> tag

    # 1. Soil domain (will be cut by other bodies)
    rects["soil"] = occ.addRectangle(
        x_domain_left, y_domain_bot, 0,
        x_domain_right - x_domain_left, y_domain_top - y_domain_bot
    )

    # 2. FR4 core
    rects["fr4"] = occ.addRectangle(
        x_pcb_left, y_sub_bot, 0, pcb_w, t_sub
    )

    # 3. Electrode 1
    rects["e1"] = occ.addRectangle(
        x_e1_left, y_cu_top_bot, 0, W, t_cu
    )

    # 4. Electrode 2
    rects["e2"] = occ.addRectangle(
        x_e2_left, y_cu_top_bot, 0, W, t_cu
    )

    # 5. Top solder mask — covers full PCB width at top copper level + SM thickness
    # This is a single rectangle from PCB left to right, from copper bottom to SM top.
    # The electrodes will be cut out of it by fragmentation.
    if t_sm > 0:
        rects["sm_top"] = occ.addRectangle(
            x_pcb_left, y_cu_top_bot, 0, pcb_w, t_cu + t_sm
        )

    # 6. Bottom solder mask
    if t_sm > 0:
        if geom.has_ground_plane:
            rects["sm_bot"] = occ.addRectangle(
                x_pcb_left, y_sm_bot_bot, 0, pcb_w, t_cu + t_sm
            )
        else:
            rects["sm_bot"] = occ.addRectangle(
                x_pcb_left, y_sm_bot_bot, 0, pcb_w, t_sm
            )

    # 7. Ground plane (optional)
    if geom.has_ground_plane:
        rects["gnd"] = occ.addRectangle(
            x_pcb_left, y_cu_bot_bot, 0, pcb_w, t_cu
        )

    # 8. Sealant (wraps entire PCB exterior)
    if t_seal > 0:
        rects["sealant"] = occ.addRectangle(
            x_seal_left, y_seal_bot, 0,
            x_seal_right - x_seal_left, y_seal_top - y_seal_bot
        )

    occ.synchronize()

    # --- Fragment all bodies to create conforming mesh interfaces ---
    all_dimtags = [(2, tag) for tag in rects.values()]

    # Fragment: first arg is "object", rest is "tool". All get fragmented together.
    occ.fragment([all_dimtags[0]], all_dimtags[1:])
    occ.synchronize()

    # --- Classify surfaces by centroid position ---
    surfaces = gmsh.model.occ.getEntities(2)

    body_soil = []
    body_fr4 = []
    body_e1 = []
    body_e2 = []
    body_sm_top = []
    body_sm_bot = []
    body_gnd = []
    body_sealant = []

    tol = 1e-6

    # Bottom solder mask y-range
    y_sm_bot_top = y_cu_bot_bot if geom.has_ground_plane else y_sub_bot

    for dim, tag in surfaces:
        com = gmsh.model.occ.getCenterOfMass(dim, tag)
        cx, cy = com[0], com[1]
        bb = gmsh.model.occ.getBoundingBox(dim, tag)
        xmin, ymin, _, xmax, ymax, _ = bb

        in_pcb_x = xmin >= x_pcb_left - tol and xmax <= x_pcb_right + tol
        in_seal_x = xmin >= x_seal_left - tol and xmax <= x_seal_right + tol

        # --- Electrodes: exact copper rectangle bounds ---
        if (ymin >= y_cu_top_bot - tol and ymax <= y_cu_top_top + tol
                and in_pcb_x):
            if (xmin >= x_e1_left - tol and xmax <= x_e1_right + tol):
                body_e1.append(tag)
                continue
            if (xmin >= x_e2_left - tol and xmax <= x_e2_right + tol):
                body_e2.append(tag)
                continue

        # --- Ground plane ---
        if (geom.has_ground_plane
                and ymin >= y_cu_bot_bot - tol and ymax <= y_cu_bot_top + tol
                and in_pcb_x):
            body_gnd.append(tag)
            continue

        # --- FR4 core ---
        if (ymin >= y_sub_bot - tol and ymax <= y_sub_top + tol
                and in_pcb_x):
            body_fr4.append(tag)
            continue

        # --- Top solder mask: spans y_cu_top_bot to y_sm_top_top ---
        # After fragmentation with electrodes, this is an L-shaped region:
        # gap fills at copper height + full-width strip above copper.
        if (t_sm > 0
                and ymin >= y_cu_top_bot - tol and ymax <= y_sm_top_top + tol
                and in_pcb_x):
            body_sm_top.append(tag)
            continue

        # --- Bottom solder mask ---
        if (t_sm > 0
                and ymin >= y_sm_bot_bot - tol and ymax <= y_sm_bot_top + tol
                and in_pcb_x):
            body_sm_bot.append(tag)
            continue

        # --- Sealant: inside sealant envelope but outside PCB proper ---
        if (t_seal > 0 and in_seal_x
                and ymin >= y_seal_bot - tol and ymax <= y_seal_top + tol):
            is_in_pcb = (in_pcb_x
                         and ymin >= y_pcb_bot - tol and ymax <= y_pcb_top + tol)
            if not is_in_pcb:
                body_sealant.append(tag)
                continue

        # Everything else is soil
        body_soil.append(tag)

    # --- Create physical groups ---
    # Body numbering matches the plan

    pg_soil = gmsh.model.addPhysicalGroup(2, body_soil, 1)
    gmsh.model.setPhysicalName(2, pg_soil, "soil")

    pg_fr4 = gmsh.model.addPhysicalGroup(2, body_fr4, 2)
    gmsh.model.setPhysicalName(2, pg_fr4, "fr4")

    pg_e1 = gmsh.model.addPhysicalGroup(2, body_e1, 3)
    gmsh.model.setPhysicalName(2, pg_e1, "electrode1")

    pg_e2 = gmsh.model.addPhysicalGroup(2, body_e2, 4)
    gmsh.model.setPhysicalName(2, pg_e2, "electrode2")

    body_id = 5
    if t_sm > 0 and body_sm_top:
        pg = gmsh.model.addPhysicalGroup(2, body_sm_top, body_id)
        gmsh.model.setPhysicalName(2, pg, "solder_mask_top")
        sm_top_id = body_id
        body_id += 1
    else:
        sm_top_id = None

    if t_sm > 0 and body_sm_bot:
        pg = gmsh.model.addPhysicalGroup(2, body_sm_bot, body_id)
        gmsh.model.setPhysicalName(2, pg, "solder_mask_bot")
        sm_bot_id = body_id
        body_id += 1
    else:
        sm_bot_id = None

    if geom.has_ground_plane and body_gnd:
        pg = gmsh.model.addPhysicalGroup(2, body_gnd, body_id)
        gmsh.model.setPhysicalName(2, pg, "ground_plane")
        gnd_id = body_id
        body_id += 1
    else:
        gnd_id = None

    if t_seal > 0 and body_sealant:
        pg = gmsh.model.addPhysicalGroup(2, body_sealant, body_id)
        gmsh.model.setPhysicalName(2, pg, "sealant")
        seal_id = body_id
        body_id += 1
    else:
        seal_id = None

    # --- Boundary physical groups ---
    edges = gmsh.model.occ.getEntities(1)

    bc_outer = []
    bc_id = 1

    for dim, tag in edges:
        bb = gmsh.model.occ.getBoundingBox(dim, tag)
        xmin, ymin, _, xmax, ymax, _ = bb

        on_left = abs(xmin - x_domain_left) < tol and abs(xmax - x_domain_left) < tol
        on_right = abs(xmin - x_domain_right) < tol and abs(xmax - x_domain_right) < tol
        on_bottom = abs(ymin - y_domain_bot) < tol and abs(ymax - y_domain_bot) < tol
        on_top = abs(ymin - y_domain_top) < tol and abs(ymax - y_domain_top) < tol

        if on_left or on_right or on_bottom or on_top:
            bc_outer.append(tag)

    if bc_outer:
        pg = gmsh.model.addPhysicalGroup(1, bc_outer, bc_id)
        gmsh.model.setPhysicalName(1, pg, "outer_boundary")
        outer_bc_id = bc_id
        bc_id += 1

    # Electrode boundary groups (for Capacitance Body BCs)
    e1_all_edges = []
    for tag in body_e1:
        bnd = gmsh.model.getBoundary([(2, tag)], oriented=False)
        e1_all_edges.extend([b[1] for b in bnd])
    e1_all_edges = list(set(e1_all_edges))

    e2_all_edges = []
    for tag in body_e2:
        bnd = gmsh.model.getBoundary([(2, tag)], oriented=False)
        e2_all_edges.extend([b[1] for b in bnd])
    e2_all_edges = list(set(e2_all_edges))

    if e1_all_edges:
        pg = gmsh.model.addPhysicalGroup(1, e1_all_edges, bc_id)
        gmsh.model.setPhysicalName(1, pg, "electrode1_boundary")
        e1_bc_id = bc_id
        bc_id += 1
    else:
        e1_bc_id = None

    if e2_all_edges:
        pg = gmsh.model.addPhysicalGroup(1, e2_all_edges, bc_id)
        gmsh.model.setPhysicalName(1, pg, "electrode2_boundary")
        e2_bc_id = bc_id
        bc_id += 1
    else:
        e2_bc_id = None

    # --- Mesh size fields ---
    # Fine mesh near electrode surfaces, coarse in far-field

    all_electrode_edges = list(set(e1_all_edges + e2_all_edges))

    gmsh.model.mesh.field.add("Distance", 1)
    gmsh.model.mesh.field.setNumbers(1, "CurvesList", all_electrode_edges)
    gmsh.model.mesh.field.setNumber(1, "Sampling", 100)

    # Threshold: fine near electrodes, coarse far away
    gmsh.model.mesh.field.add("Threshold", 2)
    gmsh.model.mesh.field.setNumber(2, "InField", 1)
    gmsh.model.mesh.field.setNumber(2, "SizeMin", geom.mesh_size_electrode)
    gmsh.model.mesh.field.setNumber(2, "SizeMax", geom.mesh_size_global)
    gmsh.model.mesh.field.setNumber(2, "DistMin", t_cu * 2)
    gmsh.model.mesh.field.setNumber(2, "DistMax", G * 5)

    gmsh.model.mesh.field.setAsBackgroundMesh(2)

    # Disable default mesh sizing
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)

    gmsh.option.setNumber("Mesh.ElementOrder", geom.element_order)

    # --- Generate mesh ---
    gmsh.model.mesh.generate(2)

    # --- Name entities for STEP export ---
    # Build tag→name mapping from classified surfaces
    tag_to_name = {}
    for tag in body_soil:
        tag_to_name[tag] = "soil"
    for tag in body_fr4:
        tag_to_name[tag] = "FR4"
    for tag in body_e1:
        tag_to_name[tag] = "electrode1"
    for tag in body_e2:
        tag_to_name[tag] = "electrode2"
    for tag in body_sm_top:
        tag_to_name[tag] = "solder_mask_top"
    for tag in body_sm_bot:
        tag_to_name[tag] = "solder_mask_bot"
    for tag in body_gnd:
        tag_to_name[tag] = "ground_plane"
    for tag in body_sealant:
        tag_to_name[tag] = "sealant"

    # --- Write outputs ---
    msh_path = output_dir / "pcb_sensor.msh"
    gmsh.write(str(msh_path))

    step_path = output_dir / "pcb_sensor.step"
    gmsh.write(str(step_path))

    gmsh.finalize()

    # Post-process STEP to rename PRODUCT entries with material names
    _rename_step_products(step_path, surfaces, tag_to_name)

    print(f"  Mesh written to: {msh_path}")
    print(f"  STEP written to: {step_path}")

    # Return body ID mapping for SIF generation
    body_ids = {
        "soil": 1, "fr4": 2, "electrode1": 3, "electrode2": 4,
        "solder_mask_top": sm_top_id, "solder_mask_bot": sm_bot_id,
        "ground_plane": gnd_id, "sealant": seal_id,
    }
    bc_ids = {
        "outer": outer_bc_id,
        "electrode1": e1_bc_id,
        "electrode2": e2_bc_id,
    }
    return msh_path, body_ids, bc_ids


# ============================================================================
# Elmer SIF generation
# ============================================================================

def write_elmer_sif(geom: PCBGeometry, body_ids: dict, bc_ids: dict, output_dir: Path) -> Path:
    """Write the Elmer solver input file for capacitance matrix extraction."""

    t_sm = geom.solder_mask_thickness
    t_seal = geom.sealant_thickness

    # Build body/material sections dynamically based on what's present
    bodies = []
    materials = []
    mat_id = 1

    # --- Materials ---
    # Soil
    soil_mat = mat_id
    materials.append(f"""\
Material {mat_id}
  Name = "Soil"
  Relative Permittivity = {geom.soil_permittivity}
End
""")
    mat_id += 1

    # FR4
    fr4_mat = mat_id
    materials.append(f"""\
Material {mat_id}
  Name = "FR4"
  Relative Permittivity = {geom.substrate_permittivity}
End
""")
    mat_id += 1

    # Copper (high εr to approximate conductor)
    cu_mat = mat_id
    materials.append(f"""\
Material {mat_id}
  Name = "Copper"
  Relative Permittivity = 1.0e6
End
""")
    mat_id += 1

    # Solder mask (if present)
    if t_sm > 0:
        sm_mat = mat_id
        materials.append(f"""\
Material {mat_id}
  Name = "Solder Mask"
  Relative Permittivity = {geom.solder_mask_permittivity}
End
""")
        mat_id += 1
    else:
        sm_mat = None

    # Sealant (if present)
    if t_seal > 0:
        seal_mat = mat_id
        materials.append(f"""\
Material {mat_id}
  Name = "Sealant"
  Relative Permittivity = {geom.sealant_permittivity}
End
""")
        mat_id += 1
    else:
        seal_mat = None

    # --- Bodies ---
    # Body 1: Soil
    bodies.append(f"""\
Body 1
  Target Bodies(1) = {body_ids['soil']}
  Name = "Soil"
  Equation = 1
  Material = {soil_mat}
End
""")

    # Body 2: FR4
    bodies.append(f"""\
Body 2
  Target Bodies(1) = {body_ids['fr4']}
  Name = "FR4"
  Equation = 1
  Material = {fr4_mat}
End
""")

    # Body 3: Electrode 1
    bodies.append(f"""\
Body 3
  Target Bodies(1) = {body_ids['electrode1']}
  Name = "Electrode 1"
  Equation = 1
  Material = {cu_mat}
  Body Force = 1
End
""")

    # Body 4: Electrode 2
    bodies.append(f"""\
Body 4
  Target Bodies(1) = {body_ids['electrode2']}
  Name = "Electrode 2"
  Equation = 1
  Material = {cu_mat}
  Body Force = 2
End
""")

    body_n = 5

    # Top solder mask
    if body_ids.get("solder_mask_top"):
        bodies.append(f"""\
Body {body_n}
  Target Bodies(1) = {body_ids['solder_mask_top']}
  Name = "Solder Mask Top"
  Equation = 1
  Material = {sm_mat}
End
""")
        body_n += 1

    # Bottom solder mask
    if body_ids.get("solder_mask_bot"):
        bodies.append(f"""\
Body {body_n}
  Target Bodies(1) = {body_ids['solder_mask_bot']}
  Name = "Solder Mask Bottom"
  Equation = 1
  Material = {sm_mat}
End
""")
        body_n += 1

    # Ground plane
    if body_ids.get("ground_plane"):
        bodies.append(f"""\
Body {body_n}
  Target Bodies(1) = {body_ids['ground_plane']}
  Name = "Ground Plane"
  Equation = 1
  Material = {cu_mat}
End
""")
        body_n += 1

    # Sealant
    if body_ids.get("sealant"):
        bodies.append(f"""\
Body {body_n}
  Target Bodies(1) = {body_ids['sealant']}
  Name = "Sealant"
  Equation = 1
  Material = {seal_mat}
End
""")
        body_n += 1

    # --- Boundary conditions ---
    bcs = []

    # Outer boundary: Neumann (natural BC)
    bcs.append(f"""\
Boundary Condition 1
  Target Boundaries(1) = {bc_ids['outer']}
  Name = "Outer Boundary"
  ! Neumann BC (natural) — domain large enough that this doesn't matter
End
""")

    # Electrode 1: Capacitance Body 1
    if bc_ids.get('electrode1'):
        bcs.append(f"""\
Boundary Condition 2
  Target Boundaries(1) = {bc_ids['electrode1']}
  Name = "Electrode 1"
  Capacitance Body = 1
End
""")

    # Electrode 2: Capacitance Body 2
    if bc_ids.get('electrode2'):
        bcs.append(f"""\
Boundary Condition 3
  Target Boundaries(1) = {bc_ids['electrode2']}
  Name = "Electrode 2"
  Capacitance Body = 2
End
""")

    vwc = topp_vwc(geom.soil_permittivity)

    sif_content = f"""\
! =============================================================
! PCB Capacitive Soil Moisture Sensor — Electrostatic Simulation
! Generated by generate_idc_model.py
!
! Geometry: W={geom.trace_width}mm, G={geom.trace_gap}mm, edge_gap={geom.edge_gap}mm
!           PCB width={geom.pcb_width:.2f}mm
!           substrate={geom.substrate_thickness}mm FR4 (εr={geom.substrate_permittivity})
!           copper={geom.copper_thickness}mm
!           solder mask={geom.solder_mask_thickness}mm (εr={geom.solder_mask_permittivity})
!           sealant={geom.sealant_thickness}mm (εr={geom.sealant_permittivity})
!           ground plane={'yes' if geom.has_ground_plane else 'no'}
!           soil εr={geom.soil_permittivity} (≈{vwc*100:.0f}% VWC via Topp)
! Sensing depth ≈ {geom.sensing_depth}mm
! =============================================================

Check Keywords Warn

Header
  Mesh DB "." "mesh"
  Include Path ""
  Results Directory "results"
End

Simulation
  Max Output Level = 5
  Coordinate System = Cartesian
  Coordinate Mapping(3) = 1 2 3
  Coordinate Scaling = 1.0e-3       ! mm → meters

  Simulation Type = Steady state
  Steady State Max Iterations = 1
  Output Intervals = 1
  Post File = case.vtu
End

Constants
  Permittivity of Vacuum = 8.8542e-12
End

! ------ Bodies ------
{"".join(bodies)}
! ------ Solver ------
Solver 1
  Equation = Electrostatics
  Variable = Potential
  Procedure = "StatElecSolve" "StatElecSolver"

  Calculate Capacitance Matrix = True
  Capacitance Matrix Filename = "capacitance.dat"

  Calculate Electric Field = True
  Calculate Electric Energy = True

  Linear System Solver = Iterative
  Linear System Iterative Method = BiCGStab
  Linear System Max Iterations = 5000
  Linear System Convergence Tolerance = 1.0e-10
  Linear System Preconditioning = ILU1
  Linear System Abort Not Converged = False
  Linear System Residual Output = 20

  Nonlinear System Max Iterations = 1
  Nonlinear System Convergence Tolerance = 1.0e-7

  Steady State Convergence Tolerance = 1.0e-5
  Optimize Bandwidth = True
End

! VTU output for ParaView visualization
Solver 2
  Equation = Result Output
  Procedure = "ResultOutputSolve" "ResultOutputSolver"
  Output File Name = "case"
  Output Format = vtu
  Scalar Field 1 = Potential
  Exec Solver = After Simulation
End

! ------ Equation ------
Equation 1
  Name = "Electrostatics"
  Active Solvers(2) = 1 2
End

! ------ Materials ------
{"".join(materials)}
! ------ Body Forces (Capacitance Bodies) ------
Body Force 1
  Name = "Electrode 1 Capacitance"
  Charge Density = 0.0
End

Body Force 2
  Name = "Electrode 2 Capacitance"
  Charge Density = 0.0
End

! ------ Boundary Conditions ------
{"".join(bcs)}
! Capacitance bodies are defined on electrode boundary conditions above.
! Elmer iterates over all Capacitance Bodies, setting each to 1V in turn.
"""

    sif_path = output_dir / "case.sif"
    sif_path.write_text(sif_content)
    print(f"  Elmer SIF written to: {sif_path}")
    return sif_path


def write_elmersolver_startinfo(output_dir: Path):
    """Write ELMERSOLVER_STARTINFO."""
    (output_dir / "ELMERSOLVER_STARTINFO").write_text("case.sif\n")


# ============================================================================
# Result parsing
# ============================================================================

def parse_capacitance_matrix(cap_path: Path) -> Optional[Dict[str, float]]:
    """
    Parse Elmer's capacitance.dat output (raw space-separated float matrix).

    Example 2×2 output:
      1.202368989E-15  1.345801501E-10
      1.345801501E-10 -6.314776575E-15

    Returns dict with C11, C12, C21, C22 in Farads, or None if parsing fails.
    """
    if not cap_path.exists():
        return None

    text = cap_path.read_text().strip()
    if not text:
        return None

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

    if len(values) >= 4:
        return {"C11": values[0], "C12": values[1], "C21": values[2], "C22": values[3]}
    elif len(values) >= 1:
        return {"C11": values[0]}

    return None


# ============================================================================
# ElmerGrid / ElmerSolver
# ============================================================================

def convert_mesh(msh_path: Path, output_dir: Path) -> bool:
    """Convert Gmsh .msh to Elmer mesh format using ElmerGrid."""
    mesh_dir = output_dir / "mesh"
    mesh_dir.mkdir(exist_ok=True)

    cmd = [
        "ElmerGrid", "14", "2",
        str(msh_path),
        "-out", str(mesh_dir),
        "-autoclean"
    ]

    print(f"\n  Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            print("  ElmerGrid conversion successful.")
            return True
        else:
            print(f"  ElmerGrid failed (return code {result.returncode}):")
            print(f"  {result.stderr}")
            return False
    except FileNotFoundError:
        print("  WARNING: ElmerGrid not found in PATH.")
        print(f"  Convert manually: ElmerGrid 14 2 {msh_path} -out {mesh_dir} -autoclean")
        return False
    except subprocess.TimeoutExpired:
        print("  ERROR: ElmerGrid timed out.")
        return False


def run_solver(output_dir: Path) -> Optional[Dict[str, float]]:
    """Run ElmerSolver in the output directory. Returns parsed capacitance or None."""
    cmd = ["ElmerSolver"]
    print(f"\n  Running: {' '.join(cmd)} in {output_dir}")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=300, cwd=str(output_dir)
        )
        if result.returncode == 0:
            print("  ElmerSolver completed successfully.")
            cap_file = output_dir / "capacitance.dat"
            cap = parse_capacitance_matrix(cap_file)
            if cap:
                c12_pf = abs(cap.get("C12", 0)) * 1e12
                print(f"  C12 = {c12_pf:.4f} pF")
            else:
                print("  WARNING: Could not parse capacitance.dat")
            return cap
        else:
            print(f"  ElmerSolver failed (return code {result.returncode}):")
            lines = result.stdout.split('\n')
            for line in lines[-20:]:
                print(f"    {line}")
            return None
    except FileNotFoundError:
        print("  WARNING: ElmerSolver not found in PATH.")
        print(f"  Run manually: cd {output_dir} && ElmerSolver")
        return None
    except subprocess.TimeoutExpired:
        print("  ERROR: ElmerSolver timed out (>300s).")
        return None


# ============================================================================
# Single run and sweeps
# ============================================================================

def run_single(geom: PCBGeometry, base_dir: Path, solve: bool = False) -> Optional[Dict]:
    """Run a single simulation: generate mesh + SIF, optionally solve.

    Returns a result dict with geometry params and capacitance values, or None if
    meshing/solving failed.
    """

    label = f"W{geom.trace_width:.2f}_G{geom.trace_gap:.2f}_eps{geom.soil_permittivity:.1f}"
    output_dir = base_dir / label
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results").mkdir(exist_ok=True)

    vwc = topp_vwc(geom.soil_permittivity)

    print(f"\n{'='*60}")
    print(f"  Generating: {label}")
    print(f"  W={geom.trace_width}mm  G={geom.trace_gap}mm  εr_soil={geom.soil_permittivity}")
    print(f"  VWC ≈ {vwc*100:.1f}% (Topp equation)")
    print(f"  Sensing depth ≈ {geom.sensing_depth}mm")
    print(f"  PCB width = {geom.pcb_width:.2f}mm")
    print(f"{'='*60}")

    # Save parameters
    params = asdict(geom)
    params["_derived"] = {
        "pcb_width": geom.pcb_width,
        "sensing_depth": geom.sensing_depth,
        "vwc_topp": vwc,
    }
    (output_dir / "params.json").write_text(json.dumps(params, indent=2))

    # Generate mesh
    msh_path, body_ids, bc_ids = generate_mesh(geom, output_dir)

    # Write Elmer files
    write_elmer_sif(geom, body_ids, bc_ids, output_dir)
    write_elmersolver_startinfo(output_dir)

    # Convert and optionally solve
    mesh_ok = convert_mesh(msh_path, output_dir)

    cap = None
    if solve and mesh_ok:
        cap = run_solver(output_dir)

    # Build result dict
    result = {
        "W_mm": geom.trace_width,
        "G_mm": geom.trace_gap,
        "edge_gap_mm": geom.edge_gap,
        "soil_eps": geom.soil_permittivity,
        "VWC_pct": round(vwc * 100, 1),
        "pcb_width_mm": round(geom.pcb_width, 2),
        "sensing_depth_mm": round(geom.sensing_depth, 2),
        "output_dir": str(output_dir),
    }
    if cap:
        result["C12_pF"] = abs(cap.get("C12", 0)) * 1e12
        result["C11_pF"] = abs(cap.get("C11", 0)) * 1e12

    return result


CSV_COLUMNS = [
    "W_mm", "G_mm", "edge_gap_mm", "soil_eps", "VWC_pct",
    "pcb_width_mm", "sensing_depth_mm", "C12_pF", "C11_pF",
]


def write_results_csv(results: List[Dict], sweep_dir: Path):
    """Write sweep results to a CSV file and print a summary table."""
    csv_path = sweep_dir / "results.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow(r)
    print(f"\n  Results CSV written to: {csv_path}")

    # Print summary table
    print(f"\n  {'W':>5} {'G':>5} {'εr':>5} {'VWC%':>5} {'C12(pF)':>10} {'C11(pF)':>10}")
    print(f"  {'-'*45}")
    for r in results:
        c12 = f"{r['C12_pF']:.4f}" if "C12_pF" in r else "—"
        c11 = f"{r['C11_pF']:.4f}" if "C11_pF" in r else "—"
        print(f"  {r['W_mm']:>5.2f} {r['G_mm']:>5.2f} {r['soil_eps']:>5.1f} "
              f"{r['VWC_pct']:>5.1f} {c12:>10} {c11:>10}")


def sweep_permittivity(base_dir: Path, solve: bool = False):
    """Sweep soil permittivity from dry to saturated using Topp values."""
    # Ka values spanning dry → saturated soil
    ka_values = [3, 5, 8, 11, 15, 20, 30, 40]

    print(f"\n{'#'*60}")
    print(f"  PERMITTIVITY SWEEP (Topp equation)")
    print(f"  Ka = {ka_values}")
    for ka in ka_values:
        print(f"    Ka={ka:3d} → VWC ≈ {topp_vwc(ka)*100:.1f}%")
    print(f"{'#'*60}")

    sweep_dir = base_dir / "sweep_epsilon"
    results = []
    for ka in ka_values:
        geom = PCBGeometry(soil_permittivity=ka)
        result = run_single(geom, sweep_dir, solve=solve)
        if result:
            results.append(result)

    if results:
        write_results_csv(results, sweep_dir)


def sweep_gap(base_dir: Path, solve: bool = False):
    """Sweep electrode gap width."""
    gap_values = [0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0]

    print(f"\n{'#'*60}")
    print(f"  GAP SWEEP: G = {gap_values} mm")
    print(f"{'#'*60}")

    sweep_dir = base_dir / "sweep_gap"
    results = []
    for gap in gap_values:
        geom = PCBGeometry(
            trace_gap=gap,
            soil_permittivity=11.0,  # ~20% VWC
            soil_domain_size=max(20.0, gap * 10),
        )
        result = run_single(geom, sweep_dir, solve=solve)
        if result:
            results.append(result)

    if results:
        write_results_csv(results, sweep_dir)


def sweep_geometry_comparison(base_dir: Path, solve: bool = False):
    """Compare different W/G/edge_gap combinations."""

    configs = [
        # (name, W, G, edge_gap)
        ("narrow_dense",  0.3, 0.3, 0.3),
        ("medium",        1.0, 1.0, 0.5),
        ("wide_sparse",   2.0, 2.0, 1.0),
        ("wide_trace",    2.0, 0.5, 0.5),
        ("narrow_trace",  0.5, 2.0, 0.5),
    ]

    print(f"\n{'#'*60}")
    print(f"  GEOMETRY COMPARISON SWEEP")
    print(f"{'#'*60}")

    sweep_dir = base_dir / "sweep_geometry"
    results = []
    for name, w, g, eg in configs:
        geom = PCBGeometry(
            trace_width=w,
            trace_gap=g,
            edge_gap=eg,
            soil_permittivity=11.0,
            soil_domain_size=max(20.0, (w + g) * 5),
        )
        result = run_single(geom, sweep_dir, solve=solve)
        if result:
            results.append(result)

    if results:
        write_results_csv(results, sweep_dir)


def sweep_width_gap(base_dir: Path, solve: bool = False):
    """Sweep electrode width and gap on a grid.

    Penetration depth ≈ W + G, so this sweep maps out how geometry
    affects both capacitance and sensing depth.
    """
    w_values = [0.3, 0.5, 1.0, 1.5, 2.0, 3.0]
    g_values = [0.3, 0.5, 1.0, 1.5, 2.0, 3.0]

    print(f"\n{'#'*60}")
    print(f"  WIDTH × GAP SWEEP")
    print(f"  W = {w_values} mm")
    print(f"  G = {g_values} mm")
    print(f"  {len(w_values) * len(g_values)} combinations")
    print(f"{'#'*60}")

    sweep_dir = base_dir / "sweep_width_gap"
    results = []
    for w in w_values:
        for g in g_values:
            geom = PCBGeometry(
                trace_width=w,
                trace_gap=g,
                soil_permittivity=11.0,  # ~20% VWC
                soil_domain_size=max(20.0, (w + g) * 5),
            )
            result = run_single(geom, sweep_dir, solve=solve)
            if result:
                results.append(result)

    if results:
        write_results_csv(results, sweep_dir)


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Generate PCB capacitive soil moisture sensor models for Elmer FEM simulation"
    )
    parser.add_argument("--output-dir", "-o", type=Path, default=Path("./sim_output"),
                        help="Base output directory (default: ./sim_output)")
    parser.add_argument("--solve", action="store_true",
                        help="Also run ElmerGrid + ElmerSolver (requires both in PATH)")

    # Sweep modes
    parser.add_argument("--sweep-epsilon", action="store_true",
                        help="Sweep soil permittivity from dry to saturated")
    parser.add_argument("--sweep-gap", action="store_true",
                        help="Sweep electrode gap width")
    parser.add_argument("--sweep-geometry", action="store_true",
                        help="Compare different W/G combinations")
    parser.add_argument("--sweep-width-gap", action="store_true",
                        help="Sweep electrode width × gap grid (penetration depth study)")
    parser.add_argument("--sweep-all", action="store_true",
                        help="Run all sweeps")

    # Single-run geometry overrides
    parser.add_argument("--trace-width", "-W", type=float, default=1.0,
                        help="Electrode strip width in mm (default: 1.0)")
    parser.add_argument("--trace-gap", "-G", type=float, default=1.0,
                        help="Gap between electrodes in mm (default: 1.0)")
    parser.add_argument("--edge-gap", type=float, default=0.5,
                        help="Margin from electrode to PCB edge in mm (default: 0.5)")
    parser.add_argument("--soil-epsilon", type=float, default=11.0,
                        help="Soil relative permittivity (default: 11.0, ~20%% VWC)")
    parser.add_argument("--copper-thickness", type=float, default=0.0356,
                        help="Copper thickness in mm (default: 0.0356 = 1.4 mil)")
    parser.add_argument("--substrate-thickness", type=float, default=1.524,
                        help="FR4 core thickness in mm (default: 1.524 = 60 mil)")
    parser.add_argument("--solder-mask-thickness", type=float, default=0.0152,
                        help="Solder mask thickness in mm (default: 0.0152 = 0.6 mil, 0=none)")
    parser.add_argument("--sealant-thickness", type=float, default=0.0,
                        help="Conformal sealant thickness in mm (default: 0 = none)")
    parser.add_argument("--ground-plane", action="store_true",
                        help="Include bottom copper ground plane")
    parser.add_argument("--finger-length", type=float, default=20.0,
                        help="Electrode length in mm for 2D→3D scaling (default: 20.0)")
    parser.add_argument("--domain-size", type=float, default=20.0,
                        help="Soil domain extent around PCB in mm (default: 20.0)")

    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.sweep_all:
        sweep_permittivity(args.output_dir, solve=args.solve)
        sweep_gap(args.output_dir, solve=args.solve)
        sweep_geometry_comparison(args.output_dir, solve=args.solve)
        sweep_width_gap(args.output_dir, solve=args.solve)
    elif args.sweep_epsilon:
        sweep_permittivity(args.output_dir, solve=args.solve)
    elif args.sweep_gap:
        sweep_gap(args.output_dir, solve=args.solve)
    elif args.sweep_geometry:
        sweep_geometry_comparison(args.output_dir, solve=args.solve)
    elif args.sweep_width_gap:
        sweep_width_gap(args.output_dir, solve=args.solve)
    else:
        geom = PCBGeometry(
            trace_width=args.trace_width,
            trace_gap=args.trace_gap,
            edge_gap=args.edge_gap,
            soil_permittivity=args.soil_epsilon,
            copper_thickness=args.copper_thickness,
            substrate_thickness=args.substrate_thickness,
            solder_mask_thickness=args.solder_mask_thickness,
            sealant_thickness=args.sealant_thickness,
            has_ground_plane=args.ground_plane,
            finger_length=args.finger_length,
            soil_domain_size=args.domain_size,
        )
        run_single(geom, args.output_dir, solve=args.solve)

    print(f"\n{'='*60}")
    print(f"  Done! Output in: {args.output_dir}")
    print(f"{'='*60}")
    print(f"\nNext steps:")
    print(f"  1. Inspect mesh:  gmsh {args.output_dir}/*/pcb_sensor.msh")
    print(f"  2. Convert mesh:  ElmerGrid 14 2 pcb_sensor.msh -out mesh -autoclean")
    print(f"  3. Solve:         cd <sim_dir> && ElmerSolver")
    print(f"  4. Visualize:     paraview results/case0001.vtu")
    print(f"\n  Or re-run with --solve to do steps 2-3 automatically.")


if __name__ == "__main__":
    main()
