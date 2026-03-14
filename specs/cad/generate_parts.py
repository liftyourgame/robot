#!/usr/bin/env python3
"""
specs/cad/generate_parts.py

Parametric STEP file generator for robot body parts using CadQuery.
All dimensions are at 50% print scale (850 mm assembled height).

Coordinate system used throughout:
    X  =  left / right   (+X = right)
    Y  =  up   / down    (+Y = up)
    Z  =  front/ back    (+Z = front)

Install:
    cd specs/cad
    python3 -m venv .venv && .venv/bin/pip install cadquery termcolor

Run:
    .venv/bin/python3 generate_parts.py            # all parts
    .venv/bin/python3 generate_parts.py --part h01 # single part

Output:
    specs/cad/step/<PartName>.step  → import into Onshape
"""

import argparse
import math
import os
import sys

try:
    import cadquery as cq
except ImportError:
    sys.exit(
        "cadquery not found.\n"
        "Install: cd specs/cad && python3 -m venv .venv && .venv/bin/pip install cadquery termcolor"
    )

from termcolor import cprint

# ── Output directory ──────────────────────────────────────────────────────────
OUT = os.path.join(os.path.dirname(__file__), "step")
os.makedirs(OUT, exist_ok=True)

# ── Global constants (mm) ─────────────────────────────────────────────────────
WALL     = 3.0   # shell wall thickness
INS_OD   = 4.6   # M3 heat-set insert outer diameter
INS_DEPTH = 5.0  # heat-set insert depth
M3_BOSS  = 7.0   # boss OD around insert

# ── Head ellipsoid semi-axes (outer surface, 50% robot scale) ─────────────────
HEAD_RX  = 65.0   # half-width  = 130 mm total
HEAD_RY  = 85.0   # half-height = 170 mm total
HEAD_RZ  = 57.5   # half-depth  = 115 mm total


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def save(name: str, part: cq.Workplane) -> None:
    """Export part as STEP file."""
    path = os.path.join(OUT, f"{name}.step")
    try:
        cq.exporters.export(part, path)
        cprint(f"  ✅  {name}.step", "green")
    except Exception as exc:
        cprint(f"  ❌  {name}.step — {exc}", "red")


def ellipsoid_solid(rx: float, ry: float, rz: float) -> cq.Shape:
    """
    Build a solid ellipsoid with given semi-axes by scaling a unit sphere.
    Returns a cadquery Shape (not a Workplane).
    """
    sph = cq.Workplane("XY").sphere(1.0).val()
    mat = cq.Matrix(
        [
            [rx, 0,  0,  0],
            [0,  ry, 0,  0],
            [0,  0,  rz, 0],
            [0,  0,  0,  1],
        ]
    )
    return sph.transformGeometry(mat)


def ellipsoid_shell(rx: float, ry: float, rz: float, wall: float = WALL) -> cq.Workplane:
    """
    Build a closed hollow ellipsoid shell (outer minus inner) centred at origin.
    Returns a Workplane containing one solid.
    """
    outer = ellipsoid_solid(rx, ry, rz)
    inner = ellipsoid_solid(rx - wall, ry - wall, rz - wall)
    return (
        cq.Workplane("XY")
        .add(outer)
        .cut(cq.Workplane("XY").add(inner))
    )


def cut_box_below_y(part: cq.Workplane, y_cut: float) -> cq.Workplane:
    """Remove everything at Y < y_cut from the part."""
    box = (
        cq.Workplane("XZ")
        .workplane(offset=y_cut)           # plane at y = y_cut
        .rect(1000, 1000)
        .extrude(-500)                     # extends downward (−Y)
    )
    return part.cut(box)


def cut_box_above_y(part: cq.Workplane, y_cut: float) -> cq.Workplane:
    """Remove everything at Y > y_cut from the part."""
    box = (
        cq.Workplane("XZ")
        .workplane(offset=y_cut)
        .rect(1000, 1000)
        .extrude(500)                      # extends upward (+Y)
    )
    return part.cut(box)


def cut_box_front(part: cq.Workplane, z_cut: float) -> cq.Workplane:
    """Remove everything at Z > z_cut (front of head)."""
    box = (
        cq.Workplane("XY")
        .workplane(offset=z_cut)
        .rect(1000, 1000)
        .extrude(500)
    )
    return part.cut(box)


def cut_box_rear(part: cq.Workplane, z_cut: float) -> cq.Workplane:
    """Remove everything at Z < z_cut (rear of head)."""
    box = (
        cq.Workplane("XY")
        .workplane(offset=z_cut)
        .rect(1000, 1000)
        .extrude(-500)
    )
    return part.cut(box)


def m3_inserts_on_bottom(
    part: cq.Workplane,
    pcd: float,
    count: int = 4,
    start_angle_deg: float = 45,
) -> cq.Workplane:
    """
    Add M3 heat-set insert bosses on the bottom face (<Y selector).
    pcd = pitch circle diameter for boss centres.
    """
    r = pcd / 2
    for i in range(count):
        angle = math.radians(start_angle_deg + 360 * i / count)
        bx = r * math.cos(angle)
        bz = r * math.sin(angle)
        # Boss stub protruding downward
        boss = (
            cq.Workplane("XZ")
            .transformed(offset=cq.Vector(bx, 0, bz))
            .circle(M3_BOSS / 2)
            .extrude(-3)                  # 3 mm boss below face
        )
        # Recess for insert (going upward into the boss)
        recess = (
            cq.Workplane("XZ")
            .transformed(offset=cq.Vector(bx, 0, bz))
            .circle(INS_OD / 2)
            .extrude(INS_DEPTH)
        )
        part = part.union(boss).cut(recess)
    return part


# ═════════════════════════════════════════════════════════════════════════════
#  HEAD
# ═════════════════════════════════════════════════════════════════════════════

def make_H01_rear_dome() -> None:
    """
    H-01 — Head shell, rear dome (Z ≤ 0 half of the cranium).

    • Hollow ellipsoid: 130W × 170H × 115D, 3 mm wall
    • Split at Z = 0 plane (face-to-rear separation)
    • Open neck at bottom: everything below Y = −45 removed
    • 2 × Ø12 mm mic holes on left/right sides at ear height (Y = +5, Z = −25)
    """
    HEAD_OPEN_Y = -45.0
    MIC_D       = 12.0
    MIC_Y       = 5.0     # above equator
    MIC_Z       = -25.0   # rear side

    shell = ellipsoid_shell(HEAD_RX, HEAD_RY, HEAD_RZ)
    shell = cut_box_below_y(shell, HEAD_OPEN_Y)   # open bottom
    shell = cut_box_front(shell, 0)                # keep only rear half

    # 2 × mic holes through both side walls at ear level
    mic = (
        cq.Workplane("YZ")
        .transformed(offset=cq.Vector(0, MIC_Y, MIC_Z))
        .circle(MIC_D / 2)
        .extrude(HEAD_RX + 10, both=True)
    )
    shell = shell.cut(mic)

    save("H01_RearDome", shell)


def make_H02_front_face() -> None:
    """
    H-02 — Head shell, front face plate (Z ≥ 0 half).

    • Same ellipsoid shell as H-01
    • Eye visor cutouts : 2 × 30 × 18 mm slots centred at Y = +22, Z = ±16
    • Mouth slit        : 50 × 8 mm slot centred at Y = −20
    """
    HEAD_OPEN_Y = -45.0

    EYE_W   = 28.0   # slot width (horizontal, ±Z)
    EYE_H   = 16.0   # slot height (vertical, Y)
    EYE_Y   = 22.0   # Y position of eye centre
    EYE_Z   = 17.0   # ±Z offset (inter-eye distance / 2)

    MOUTH_W = 48.0
    MOUTH_H = 8.0
    MOUTH_Y = -20.0

    shell = ellipsoid_shell(HEAD_RX, HEAD_RY, HEAD_RZ)
    shell = cut_box_below_y(shell, HEAD_OPEN_Y)
    shell = cut_box_rear(shell, 0)                 # keep only front half

    # Eye cutouts (slots cut in from the front face, depth = full X width)
    for z_side in [EYE_Z, -EYE_Z]:
        eye = (
            cq.Workplane("YZ")
            .transformed(offset=cq.Vector(0, EYE_Y, z_side))
            .rect(EYE_H, EYE_W)
            .extrude(HEAD_RX + 10)            # cut from centre outward in +X
        )
        # Mirror: also cut the –X side
        eye_both = eye.union(
            cq.Workplane("YZ")
            .transformed(offset=cq.Vector(0, EYE_Y, z_side))
            .rect(EYE_H, EYE_W)
            .extrude(-(HEAD_RX + 10))
        )
        shell = shell.cut(eye_both)

    # Mouth slit
    mouth = (
        cq.Workplane("YZ")
        .transformed(offset=cq.Vector(0, MOUTH_Y, 0))
        .rect(MOUTH_H, MOUTH_W)
        .extrude(HEAD_RX + 10, both=True)
    )
    shell = shell.cut(mouth)

    save("H02_FrontFace", shell)


def make_H03_top_cap() -> None:
    """
    H-03 — Head top cap (closes the crown, attaches to H-01 + H-02).

    Slices the top 25 mm of the ellipsoid shell (Y ≥ 60 mm).
    """
    CAP_BASE_Y = 60.0   # lower edge of cap

    shell = ellipsoid_shell(HEAD_RX, HEAD_RY, HEAD_RZ)
    shell = cut_box_below_y(shell, CAP_BASE_Y)

    save("H03_TopCap", shell)


def make_H04_neck_collar() -> None:
    """
    H-04 — Neck collar.

    • Hollow cylinder  : OD 68 mm, ID 62 mm, height 40 mm
    • Top flange ring  : OD 88 mm, 3 mm thick — mates with dome base
    • Bottom face      : 4 × M3 heat-set insert bosses on PCD 52 mm
                         for head-pan servo attachment
    """
    OD       = 68.0
    ID       = 62.0
    HEIGHT   = 40.0
    FL_OD    = 88.0    # flange outer diameter
    FL_T     = 3.0     # flange thickness
    PCD      = 52.0    # insert bolt-circle diameter

    collar = (
        cq.Workplane("XY")
        .circle(OD / 2).circle(ID / 2)
        .extrude(HEIGHT)
    )

    # Top flange ring
    flange = (
        cq.Workplane("XY")
        .workplane(offset=HEIGHT)
        .circle(FL_OD / 2).circle(OD / 2)
        .extrude(FL_T)
    )
    collar = collar.union(flange)

    # Bottom insert bosses
    collar = m3_inserts_on_bottom(collar, PCD, count=4, start_angle_deg=45)

    save("H04_NeckCollar", collar)


# ═════════════════════════════════════════════════════════════════════════════
#  TORSO
# ═════════════════════════════════════════════════════════════════════════════

def make_T01_upper_chest_front() -> None:
    """
    T-01 — Upper chest, front shell half.

    • Rounded box    : 130W × 170H × 55D (front half of 110 mm torso)
    • 10 mm fillet on vertical edges
    • 3 mm wall hollow shell (close the back in Onshape if desired)
    • Speaker boss ring : 42 mm ID, 2 mm tall on inner front face
    • 4 × M3 inserts around speaker ring
    """
    W       = 130.0
    H       = 170.0
    D       = 55.0
    FILLET  = 10.0
    SPK_ID  = 42.0
    SPK_RW  = 2.5
    SPK_H   = 2.0
    SPK_PCD = SPK_ID + 12.0

    # Hollow shell: outer box minus inner box (more reliable than .shell())
    outer = (
        cq.Workplane("XY")
        .box(W, H, D, centered=(True, True, False))
        .edges("|Z")
        .fillet(FILLET)
    )
    inner_w = W - WALL * 2
    inner_h = H - WALL * 2
    inner = (
        cq.Workplane("XY")
        .box(inner_w, inner_h, D - WALL, centered=(True, True, False))
        .translate((0, 0, WALL))
        .edges("|Z")
        .fillet(max(FILLET - WALL, 1.0))
    )
    front = outer.cut(inner)

    # Speaker ring boss on the interior front face (at z = WALL)
    spk_ring = (
        cq.Workplane("XY")
        .workplane(offset=WALL)
        .circle((SPK_ID / 2) + SPK_RW)
        .circle(SPK_ID / 2)
        .extrude(SPK_H)
    )
    front = front.union(spk_ring)

    # 4 × M3 insert bosses + recesses at speaker PCD
    r_pcd = SPK_PCD / 2
    for i in range(4):
        angle  = math.radians(45 + 90 * i)
        bx     = r_pcd * math.cos(angle)
        by_xz  = r_pcd * math.sin(angle)   # in XZ plane this becomes bz
        # Boss protrudes inward from front face (+Z direction from Z=WALL)
        boss = (
            cq.Workplane("XZ")
            .workplane(offset=WALL)
            .transformed(offset=cq.Vector(bx, 0, by_xz))
            .circle(M3_BOSS / 2)
            .extrude(3)
        )
        # Recess drills back into the boss from its tip (at Z=WALL+3)
        recess = (
            cq.Workplane("XZ")
            .workplane(offset=WALL + 3)
            .transformed(offset=cq.Vector(bx, 0, by_xz))
            .circle(INS_OD / 2)
            .extrude(-INS_DEPTH)
        )
        front = front.union(boss).cut(recess)

    save("T01_UpperChestFront", front)


def make_T05_hip_pelvis() -> None:
    """
    T-05 — Hip pelvis shell (central structural hub, mounts all leg servos).

    • Rounded box  : 190W × 80H × 110D
    • 8 mm edge fillet
    • 3 mm wall shell
    • 4 × Ø28 mm leg-servo pass-throughs on bottom face, PCD 130 mm
    """
    W       = 190.0
    H       = 80.0
    D       = 110.0
    FILLET  = 8.0
    SRV_D   = 28.0
    SRV_PCD = 130.0

    hips = (
        cq.Workplane("XY")
        .box(W, H, D, centered=(True, True, False))
        .edges("|Z")
        .fillet(FILLET)
        .shell(-WALL)
    )

    # Leg servo holes on the bottom face
    for sx, sz in [(1, 1), (1, -1), (-1, 1), (-1, -1)]:
        cx = sx * SRV_PCD / 2
        cz = sz * SRV_PCD / 2
        hole = (
            cq.Workplane("XZ")
            .transformed(offset=cq.Vector(cx, 0, cz))
            .circle(SRV_D / 2)
            .extrude(WALL * 2, both=True)
        )
        hips = hips.cut(hole)

    save("T05_HipPelvis", hips)


# ═════════════════════════════════════════════════════════════════════════════
#  ARMS  (left side; mirror in Onshape for right)
# ═════════════════════════════════════════════════════════════════════════════

def _tapered_tube(od_bot: float, od_top: float, height: float) -> cq.Workplane:
    """
    Build a hollow tapered cylinder (frustum shell) via a revolved closed profile.
    od_bot / od_top are the outer diameters at the bottom and top.
    Wall thickness is always WALL mm.
    """
    id_bot = od_bot - WALL * 2
    id_top = od_top - WALL * 2
    return (
        cq.Workplane("XY")
        .moveTo(od_bot / 2, 0)
        .lineTo(od_top / 2, height)
        .lineTo(id_top / 2, height)
        .lineTo(id_bot / 2, 0)
        .close()
        .revolve(360, (0, 0, 0), (0, 1, 0))
    )


def _add_insert_boss(
    part: cq.Workplane,
    face_y: float,
    direction: float,
    bx: float,
    bz: float,
) -> cq.Workplane:
    """
    Add one M3 heat-set insert boss at (bx, face_y, bz).
    direction = +1 → boss protrudes upward (top face)
                -1 → boss protrudes downward (bottom face)
    """
    boss_h = 3.0
    boss = (
        cq.Workplane("XZ")
        .workplane(offset=face_y)
        .transformed(offset=cq.Vector(bx, 0, bz))
        .circle(M3_BOSS / 2)
        .extrude(boss_h * direction)
    )
    # Recess starts at boss tip and drills back into the boss/part
    recess = (
        cq.Workplane("XZ")
        .workplane(offset=face_y + boss_h * direction)
        .transformed(offset=cq.Vector(bx, 0, bz))
        .circle(INS_OD / 2)
        .extrude(-INS_DEPTH * direction)
    )
    return part.union(boss).cut(recess)


def make_LA02_upper_arm() -> None:
    """
    LA-02 — Left upper arm shell.

    • Tapered hollow cylinder: OD bottom 38 mm → OD top 44 mm, height 110 mm
    • 2 × M3 insert bosses on top face for shoulder bracket (PCD 30 mm)
    """
    OD_BOT = 38.0
    OD_TOP = 44.0
    HEIGHT = 110.0
    PCD    = 30.0

    arm = _tapered_tube(OD_BOT, OD_TOP, HEIGHT)

    r = PCD / 2
    for angle_deg in [0, 180]:
        a  = math.radians(angle_deg)
        bx = r * math.cos(a)
        bz = r * math.sin(a)
        arm = _add_insert_boss(arm, HEIGHT, +1, bx, bz)

    save("LA02_UpperArm", arm)


def make_LA03_forearm() -> None:
    """
    LA-03 — Left forearm shell.

    • Uniform hollow cylinder: OD 38 mm, height 90 mm
    • 2 × M3 insert bosses on top face (elbow) and bottom face (wrist)
    """
    OD     = 38.0
    HEIGHT = 90.0
    PCD    = 26.0

    forearm = (
        cq.Workplane("XY")
        .circle(OD / 2).circle((OD - WALL * 2) / 2)
        .extrude(HEIGHT)
    )

    r = PCD / 2
    for angle_deg in [0, 180]:
        a  = math.radians(angle_deg)
        bx = r * math.cos(a)
        bz = r * math.sin(a)
        forearm = _add_insert_boss(forearm, HEIGHT, +1, bx, bz)   # top
        forearm = _add_insert_boss(forearm, 0,      -1, bx, bz)   # bottom

    save("LA03_Forearm", forearm)


# ═════════════════════════════════════════════════════════════════════════════
#  LEGS  (left side; mirror in Onshape for right)
# ═════════════════════════════════════════════════════════════════════════════

def make_LL01_thigh() -> None:
    """
    LL-01 — Left thigh shell.

    • Tapered hollow cylinder: OD bottom 44 mm → OD top 52 mm, height 170 mm
    • 4 × M3 insert bosses on top face for hip bracket (PCD 38 mm)
    """
    OD_BOT = 44.0
    OD_TOP = 52.0
    HEIGHT = 170.0
    PCD    = 38.0

    thigh = _tapered_tube(OD_BOT, OD_TOP, HEIGHT)

    r = PCD / 2
    for angle_deg in [45, 135, 225, 315]:
        a  = math.radians(angle_deg)
        bx = r * math.cos(a)
        bz = r * math.sin(a)
        thigh = _add_insert_boss(thigh, HEIGHT, +1, bx, bz)

    save("LL01_Thigh", thigh)


def make_LL02_shin() -> None:
    """
    LL-02 — Left shin shell.

    • Uniform hollow cylinder: OD 44 mm, height 150 mm
    • 2 × M3 inserts on top face (knee) and bottom face (ankle)
    """
    OD     = 44.0
    HEIGHT = 150.0
    PCD    = 30.0

    shin = (
        cq.Workplane("XY")
        .circle(OD / 2).circle((OD - WALL * 2) / 2)
        .extrude(HEIGHT)
    )

    r = PCD / 2
    for angle_deg in [0, 180]:
        a  = math.radians(angle_deg)
        bx = r * math.cos(a)
        bz = r * math.sin(a)
        shin = _add_insert_boss(shin, HEIGHT, +1, bx, bz)   # top (knee)
        shin = _add_insert_boss(shin, 0,      -1, bx, bz)   # bottom (ankle)

    save("LL02_Shin", shin)


def make_LL04_foot_sole() -> None:
    """
    LL-04 — Left foot sole (base plate).

    • Flat rounded rectangle: 80W × 10H × 120D
    • 4 × M3 insert bosses on top face for ankle housing
    """
    W      = 80.0
    H      = 10.0
    D      = 120.0
    FILLET = 6.0
    PCD_X  = 50.0
    PCD_Z  = 80.0

    foot = (
        cq.Workplane("XY")
        .box(W, H, D, centered=(True, False, True))
        .edges("|Y")
        .fillet(FILLET)
    )

    # 4 × M3 inserts on top face (Y = H)
    for ix, iz in [
        (PCD_X / 2, PCD_Z / 2),
        (PCD_X / 2, -PCD_Z / 2),
        (-PCD_X / 2, PCD_Z / 2),
        (-PCD_X / 2, -PCD_Z / 2),
    ]:
        foot = _add_insert_boss(foot, H, +1, ix, iz)

    save("LL04_FootSole", foot)


# ═════════════════════════════════════════════════════════════════════════════
#  STRUCTURAL CONNECTORS
# ═════════════════════════════════════════════════════════════════════════════

def make_S01_servo_bracket() -> None:
    """
    S-01 — Standard servo bracket (×18 needed).

    Fits MG996R / MG995 servo (40 × 20 × 43 mm body).
    • U-channel back plate : (CH_W + flanges) × CH_H × 3 mm
    • Two side flanges forming a U  (servo drops in from the front)
    • 4 × Ø3.4 mm servo mounting holes through back plate
    • 2 × M3 insert bosses on rear face for attaching to robot shell
    """
    CH_W  = 50.0   # interior channel width
    CH_H  = 50.0   # bracket height
    FL_W  = 12.0   # flange depth (front-to-back)
    T     = 3.0    # wall thickness
    SRV_X = 40.0   # servo mounting hole spacing (X)
    SRV_Y = 43.0   # servo mounting hole spacing (Y)

    # Back plate (XY plane, extends in +Z)
    back = (
        cq.Workplane("XY")
        .box(CH_W + T * 2, CH_H, T, centered=(True, True, False))
    )

    # Left and right side flanges
    for sign in [1, -1]:
        flange = (
            cq.Workplane("XY")
            .box(T, CH_H, FL_W, centered=(False, True, False))
            .translate((sign * CH_W / 2, 0, T))
        )
        back = back.union(flange)

    # 4 × servo mounting holes through the back plate
    for hx, hy in [
        (SRV_X / 2, SRV_Y / 2), (SRV_X / 2, -SRV_Y / 2),
        (-SRV_X / 2, SRV_Y / 2), (-SRV_X / 2, -SRV_Y / 2),
    ]:
        hole = (
            cq.Workplane("XY")
            .transformed(offset=cq.Vector(hx, hy, 0))
            .circle(3.4 / 2)
            .extrude(T + 1, both=True)
        )
        back = back.cut(hole)

    # 2 × M3 insert bosses on rear face (Z = 0, protruding in -Z direction)
    for ix in [CH_W / 2 - 6, -(CH_W / 2 - 6)]:
        boss = (
            cq.Workplane("XY")           # XY plane normal = +Z; extrude(-3) → -Z
            .transformed(offset=cq.Vector(ix, 0, 0))
            .circle(M3_BOSS / 2)
            .extrude(-3)
        )
        recess = (
            cq.Workplane("XY")
            .transformed(offset=cq.Vector(ix, 0, -3))
            .circle(INS_OD / 2)
            .extrude(INS_DEPTH)           # drills back into the boss in +Z
        )
        back = back.union(boss).cut(recess)

    save("S01_ServoBracket", back)


# ═════════════════════════════════════════════════════════════════════════════
#  DISPATCH TABLE
# ═════════════════════════════════════════════════════════════════════════════

PARTS: dict = {
    # Head
    "h01":  ("H-01  Rear Dome",         make_H01_rear_dome),
    "h02":  ("H-02  Front Face",        make_H02_front_face),
    "h03":  ("H-03  Top Cap",           make_H03_top_cap),
    "h04":  ("H-04  Neck Collar",       make_H04_neck_collar),
    # Torso
    "t01":  ("T-01  Upper Chest Front", make_T01_upper_chest_front),
    "t05":  ("T-05  Hip Pelvis",        make_T05_hip_pelvis),
    # Arms (left; mirror right in Onshape)
    "la02": ("LA-02 Upper Arm",         make_LA02_upper_arm),
    "la03": ("LA-03 Forearm",           make_LA03_forearm),
    # Legs (left; mirror right in Onshape)
    "ll01": ("LL-01 Thigh",             make_LL01_thigh),
    "ll02": ("LL-02 Shin",              make_LL02_shin),
    "ll04": ("LL-04 Foot Sole",         make_LL04_foot_sole),
    # Structural
    "s01":  ("S-01  Servo Bracket",     make_S01_servo_bracket),
}


# ═════════════════════════════════════════════════════════════════════════════
#  ASSEMBLY  — positions all parts in world space and exports one STEP file
# ═════════════════════════════════════════════════════════════════════════════

def make_assembly() -> None:
    """
    Build full robot assembly (50% scale, 753 mm tall, Y-up).

    Part stack from ground (Y=0) up:
        Foot sole → Shin → Thigh → Hip → Chest → Neck → Head

    Left/right pairs share the same part geometry; right-side parts are
    mirrored across the YZ plane (180° rotation around the world Y axis).

    Output: specs/cad/step/RobotAssembly.step
    """

    def load(name: str) -> cq.Workplane:
        """Import a previously generated STEP file."""
        path = os.path.join(OUT, f"{name}.step")
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"{name}.step not found — run without --part first to generate all parts"
            )
        return cq.importers.importStep(path)

    # ── World Y positions (bottom of each part, mm) ───────────────────────────
    FOOT_H    = 10
    SHIN_H    = 150
    THIGH_H   = 170
    HIP_H     = 80
    CHEST_H   = 170
    NECK_H    = 43    # collar 40 + top flange 3

    # Head: local Y runs from -45 (open neck bottom) to +85 (crown).
    # We want the neck opening (local Y = -45) to sit at the neck top.
    HEAD_LOCAL_BOTTOM = 45   # abs(HEAD_OPEN_Y) from make_H01_rear_dome

    y_foot   = 0
    y_shin   = y_foot  + FOOT_H
    y_thigh  = y_shin  + SHIN_H
    y_hip    = y_thigh + THIGH_H
    y_chest  = y_hip   + HIP_H
    y_neck   = y_chest + CHEST_H
    # Head local origin placed so its bottom cut (local Y = -45) aligns with y_neck + NECK_H
    y_head   = y_neck  + NECK_H + HEAD_LOCAL_BOTTOM   # = world Y of head ellipsoid centre

    # ── Horizontal offsets (mm from spine centre-line) ───────────────────────
    LEG_X      = 60.0   # leg cylinder centre-line
    ARM_X      = 95.0   # arm cylinder centre-line (≈ shoulder width / 2)
    SHOULDER_Y = y_neck - 10   # world Y of shoulder attachment (near chest top)

    # Upper arm: Y=0 = narrow (elbow), Y=110 = wide (shoulder).
    # Position so the wide end (Y=110) is at SHOULDER_Y.
    ARM_TOP_H  = 110    # LA02 height
    ARM_BOT_H  = 90     # LA03 height

    # ── Colour scheme ─────────────────────────────────────────────────────────
    CLR_HEAD  = cq.Color(0.9, 0.85, 0.78, 1)   # warm off-white
    CLR_TORSO = cq.Color(0.3, 0.35, 0.42, 1)   # slate blue-grey
    CLR_LIMB  = cq.Color(0.22, 0.25, 0.30, 1)  # dark grey

    def loc(x: float, y: float, z: float = 0) -> cq.Location:
        """Simple translation Location."""
        return cq.Location(cq.Vector(x, y, z))

    def loc_mirror_x(x: float, y: float, z: float = 0) -> cq.Location:
        """Mirror across YZ plane: translate to (+x,y,z) then rotate 180° around Y."""
        return cq.Location(cq.Vector(x, y, z), cq.Vector(0, 1, 0), 180)

    cprint("  Loading parts...", "cyan")
    assy = cq.Assembly(name="RobotBody_50pct")

    # ── Head (three shells share same origin) ─────────────────────────────────
    head_loc = loc(0, y_head)
    assy.add(load("H01_RearDome"),  name="H01", color=CLR_HEAD,  loc=head_loc)
    assy.add(load("H02_FrontFace"), name="H02", color=CLR_HEAD,  loc=head_loc)
    assy.add(load("H03_TopCap"),    name="H03", color=CLR_HEAD,  loc=head_loc)
    cprint("    head ✓", "white")

    # ── Neck + torso ──────────────────────────────────────────────────────────
    assy.add(load("H04_NeckCollar"),      name="H04", color=CLR_TORSO, loc=loc(0, y_neck))
    assy.add(load("T01_UpperChestFront"), name="T01", color=CLR_TORSO, loc=loc(0, y_chest))
    assy.add(load("T05_HipPelvis"),       name="T05", color=CLR_TORSO, loc=loc(0, y_hip))
    cprint("    torso ✓", "white")

    # ── Left leg ──────────────────────────────────────────────────────────────
    assy.add(load("LL01_Thigh"),    name="LL01_L", color=CLR_LIMB, loc=loc(-LEG_X, y_thigh))
    assy.add(load("LL02_Shin"),     name="LL02_L", color=CLR_LIMB, loc=loc(-LEG_X, y_shin))
    assy.add(load("LL04_FootSole"), name="LL04_L", color=CLR_LIMB, loc=loc(-LEG_X, y_foot))
    cprint("    left leg ✓", "white")

    # ── Right leg (mirrored) ──────────────────────────────────────────────────
    assy.add(load("LL01_Thigh"),    name="LL01_R", color=CLR_LIMB, loc=loc_mirror_x(LEG_X, y_thigh))
    assy.add(load("LL02_Shin"),     name="LL02_R", color=CLR_LIMB, loc=loc_mirror_x(LEG_X, y_shin))
    assy.add(load("LL04_FootSole"), name="LL04_R", color=CLR_LIMB, loc=loc_mirror_x(LEG_X, y_foot))
    cprint("    right leg ✓", "white")

    # ── Left arm (hanging: wide shoulder end at top) ──────────────────────────
    # Translate so local Y=ARM_TOP_H (shoulder) aligns with SHOULDER_Y in world
    assy.add(load("LA02_UpperArm"), name="LA02_L", color=CLR_LIMB,
             loc=loc(-ARM_X, SHOULDER_Y - ARM_TOP_H))
    assy.add(load("LA03_Forearm"),  name="LA03_L", color=CLR_LIMB,
             loc=loc(-ARM_X, SHOULDER_Y - ARM_TOP_H - ARM_BOT_H))
    cprint("    left arm ✓", "white")

    # ── Right arm (mirrored) ──────────────────────────────────────────────────
    assy.add(load("LA02_UpperArm"), name="LA02_R", color=CLR_LIMB,
             loc=loc_mirror_x(ARM_X, SHOULDER_Y - ARM_TOP_H))
    assy.add(load("LA03_Forearm"),  name="LA03_R", color=CLR_LIMB,
             loc=loc_mirror_x(ARM_X, SHOULDER_Y - ARM_TOP_H - ARM_BOT_H))
    cprint("    right arm ✓", "white")

    # ── Export ────────────────────────────────────────────────────────────────
    out_path = os.path.join(OUT, "RobotAssembly.step")
    cprint("  Exporting assembly STEP (may take a moment)...", "cyan")
    cq.exporters.export(assy.toCompound(), out_path)
    cprint(f"  ✅  RobotAssembly.step  →  {out_path}", "green")
    cprint(
        f"  Total height: ~{y_head + 85} mm  "
        f"(foot Y=0 → head crown Y≈{y_head + 85})",
        "yellow",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate robot STEP files with CadQuery."
    )
    parser.add_argument(
        "--part",
        metavar="KEY",
        help=(
            "Generate a single part by key. "
            f"Available: {', '.join(PARTS)}, asm. "
            "Omit to generate all parts + assembly."
        ),
    )
    args = parser.parse_args()

    if args.part:
        key = args.part.lower()
        if key == "asm":
            cprint("\nBuilding assembly...", "cyan")
            make_assembly()
        elif key not in PARTS:
            cprint(f"Unknown part '{key}'. Valid keys: {', '.join(PARTS)}, asm", "red")
            sys.exit(1)
        else:
            label, fn = PARTS[key]
            cprint(f"\nGenerating {label}...", "cyan")
            fn()
    else:
        cprint(f"\nGenerating {len(PARTS)} robot parts...\n", "cyan")
        for key, (label, fn) in PARTS.items():
            cprint(f"  {label}", "cyan")
            try:
                fn()
            except Exception as exc:
                cprint(f"  ❌  {label}: {exc}", "red")

        cprint("\nBuilding assembly...", "cyan")
        try:
            make_assembly()
        except Exception as exc:
            cprint(f"  ❌  Assembly failed: {exc}", "red")

    cprint(f"\nSTEP files → {OUT}", "green")
    cprint("Onshape: New Document → Import → RobotAssembly.step", "yellow")


if __name__ == "__main__":
    main()
