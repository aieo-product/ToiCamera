#!/usr/bin/env python3
"""Build the ToiCamera v3.4 screw-fastened full Technic-grid plate.

The plate replaces the StopWatch's two rear screws with longer screws and is
clamped directly to the existing plastic bosses.  It does not grip or enter the
flush 2.54 mm bus sockets.  A commercial M5Stack CLIP-A/B connects the CamS3
to the LEGO Technic-compatible rail raised from the plate.

Headless usage::

  /Applications/Blender.app/Contents/MacOS/Blender -b \
    --python case/blender/build_case.py -- \
    --part all --out case/blender/out/toicamera.stl

Unit contract: 1 Blender Unit = 1 mm.  Rear-view coordinates are X=left/right,
Y=outward from the watch back, and Z=up/down.  The plate's outer face is +Y.
"""

import argparse
import math
from pathlib import Path
import sys

import bmesh
import bpy


# Official StopWatch values are from C152-StopWatch-model-size.pdf.  All
# printable-part dimensions and clearance rules are centralized here.
PARAMS = {
    "BBOX_TOL": 0.3,
    "BOOLEAN_EPS": 0.05,

    # StopWatch rear geometry (rear-view X/Z plane).
    "WATCH_DIAMETER": 51.95,
    "WATCH_THICKNESS": 15.5,
    "SPEAKER_CENTER_X": -17.5,
    "SPEAKER_CENTER_Z": 0.0,
    "SPEAKER_KEEP_OUT_D": 16.0,
    "SPEAKER_MARGIN": 0.3,

    # Existing 12/6 o'clock self-tapping screws, used for the backpack.
    "SCREW_CENTER_X": 0.0,
    "SCREW_SPACING": 40.0,
    "SCREW_HOLE_D": 2.4,
    "SCREW_COUNTERSINK_D": 4.5,
    "SCREW_COUNTERSINK_ANGLE": 90.0,
    "SCREW_TAB_D": 8.0,

    # The plate is centered on the two-column grid (X=4), while the existing
    # screw bosses and their 3 mm-thick tab zones remain on X=0.
    "PLATE_WIDTH": 22.0,
    "PLATE_LENGTH": 64.0,
    "PLATE_BODY_HEIGHT": 64.0,
    "PLATE_THICKNESS": 3.0,
    "PLATE_CENTER_X": 4.0,
    "PLATE_CENTER_Z": 0.0,

    # Full LEGO Technic grid.  The 4.8 mm nominal through-hole diameter receives
    # a configurable FDM compensation; counterbores remain at their exact spec.
    "TECHNIC_HOLE_D": 4.8,
    "TECHNIC_HOLE_PRINT_COMP": 0.15,
    "TECHNIC_PITCH": 8.0,
    "TECHNIC_GRID_XS": (0.0, 8.0),
    "TECHNIC_GRID_ZS": (-28.0, -20.0, -12.0, -4.0, 4.0, 12.0, 20.0, 28.0),
    "TECHNIC_RAIL_WIDTH": 9.6,
    "TECHNIC_GRID_BAND_WIDTH": 17.6,
    "TECHNIC_RAIL_THICKNESS": 7.8,
    "TECHNIC_RAIL_LENGTH": 64.0,
    "TECHNIC_RAIL_CENTER_X": 4.0,
    "TECHNIC_RAIL_CENTER_Z": 0.0,
    "TECHNIC_COUNTERBORE_D": 6.2,
    "TECHNIC_COUNTERBORE_DEPTH": 0.8,
    "TECHNIC_HOLE_CHAMFER": 0.3,
    "HOLE_MIN_WEB": 0.6,
    "SCREW_KEEP_OUT_WEB": 0.8,
    "PLATE_OUTER_RIM": 1.6,

    # Four flush factory magnets.  Only the plate-overlap crescents are cut;
    # the official centers remain the source of truth for a future magnet mount.
    "MAGNET_D": 5.0,
    "MAGNET_GRID": 25.46,
    "MAGNET_RELIEF_D": 5.5,
    "MAGNET_RELIEF_DEPTH": 0.3,
}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(
        description="Build the ToiCamera v3.4 full Technic-grid backpack plate"
    )
    parser.add_argument("--out", required=True, help="output STL path")
    parser.add_argument(
        "--part",
        choices=("backpack", "all"),
        default="backpack",
        help="part to export; all is an alias for backpack (default: backpack)",
    )
    parser.add_argument(
        "--bbox-tol",
        type=float,
        default=PARAMS["BBOX_TOL"],
        help="exported STL bbox tolerance in mm (default: 0.3)",
    )
    return parser.parse_args(argv)


def derived():
    p = PARAMS
    screw_offset = p["SCREW_SPACING"] / 2.0
    tab_radius = p["SCREW_TAB_D"] / 2.0
    plate_inner_y = 0.0
    plate_outer_y = p["PLATE_THICKNESS"]
    rail_inner_y = plate_inner_y
    rail_outer_y = p["TECHNIC_RAIL_THICKNESS"]
    countersink_depth = (
        (p["SCREW_COUNTERSINK_D"] - p["SCREW_HOLE_D"])
        / 2.0
        / math.tan(math.radians(p["SCREW_COUNTERSINK_ANGLE"] / 2.0))
    )
    return {
        "watch_radius": p["WATCH_DIAMETER"] / 2.0,
        "speaker_relief_d": p["SPEAKER_KEEP_OUT_D"] + 2.0 * p["SPEAKER_MARGIN"],
        "screw_positions": (
            (p["SCREW_CENTER_X"], -screw_offset),
            (p["SCREW_CENTER_X"], screw_offset),
        ),
        "tab_radius": tab_radius,
        "plate_inner_y": plate_inner_y,
        "plate_outer_y": plate_outer_y,
        "plate_center_y": (plate_inner_y + plate_outer_y) / 2.0,
        "rail_inner_y": rail_inner_y,
        "rail_outer_y": rail_outer_y,
        "rail_center_y": (rail_inner_y + rail_outer_y) / 2.0,
        "technic_effective_hole_d": (
            p["TECHNIC_HOLE_D"] + p["TECHNIC_HOLE_PRINT_COMP"]
        ),
        "countersink_depth": countersink_depth,
        "plate_bounds": (
            p["PLATE_CENTER_X"] - p["PLATE_WIDTH"] / 2.0,
            p["PLATE_CENTER_X"] + p["PLATE_WIDTH"] / 2.0,
            p["PLATE_CENTER_Z"] - p["PLATE_LENGTH"] / 2.0,
            p["PLATE_CENTER_Z"] + p["PLATE_LENGTH"] / 2.0,
        ),
        "rail_bounds": (
            p["TECHNIC_RAIL_CENTER_X"] - p["TECHNIC_GRID_BAND_WIDTH"] / 2.0,
            p["TECHNIC_RAIL_CENTER_X"] + p["TECHNIC_GRID_BAND_WIDTH"] / 2.0,
            p["TECHNIC_RAIL_CENTER_Z"] - p["TECHNIC_RAIL_LENGTH"] / 2.0,
            p["TECHNIC_RAIL_CENTER_Z"] + p["TECHNIC_RAIL_LENGTH"] / 2.0,
        ),
        "backpack_bbox": (
            p["PLATE_WIDTH"],
            rail_outer_y - plate_inner_y,
            p["PLATE_LENGTH"],
        ),
    }


D = derived()


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    units = bpy.context.scene.unit_settings
    units.system = "METRIC"
    units.scale_length = 0.001
    units.length_unit = "MILLIMETERS"


def technic_hole_candidates():
    return [
        (x, z)
        for x in PARAMS["TECHNIC_GRID_XS"]
        for z in PARAMS["TECHNIC_GRID_ZS"]
    ]


def magnet_positions():
    half_grid = PARAMS["MAGNET_GRID"] / 2.0
    return [
        (x, z)
        for z in (-half_grid, half_grid)
        for x in (-half_grid, half_grid)
    ]


def point_to_rectangle_distance(x, z, bounds):
    min_x, max_x, min_z, max_z = bounds
    dx = max(min_x - x, 0.0, x - max_x)
    dz = max(min_z - z, 0.0, z - max_z)
    return math.hypot(dx, dz)


def technic_hole_skip_reasons(position):
    """Return every keep-out rule that rejects a candidate grid position."""
    p = PARAMS
    x, z = position
    reasons = []
    nominal_radius = p["TECHNIC_HOLE_D"] / 2.0
    counterbore_radius = p["TECHNIC_COUNTERBORE_D"] / 2.0
    plate_left, plate_right, plate_bottom, plate_top = D["plate_bounds"]

    screw_clearance = (
        p["SCREW_COUNTERSINK_D"] / 2.0
        + counterbore_radius
        + p["SCREW_KEEP_OUT_WEB"]
    )
    if any(
        math.hypot(x - screw_x, z - screw_z) < screw_clearance - 1.0e-9
        for screw_x, screw_z in D["screw_positions"]
    ):
        reasons.append("screw_keepout")

    rim_clearance = nominal_radius + p["PLATE_OUTER_RIM"]
    if not (
        plate_left + rim_clearance - 1.0e-9
        <= x
        <= plate_right - rim_clearance + 1.0e-9
        and plate_bottom + rim_clearance - 1.0e-9
        <= z
        <= plate_top - rim_clearance + 1.0e-9
    ):
        reasons.append("outer_rim")

    speaker_clearance = (
        p["SPEAKER_KEEP_OUT_D"] / 2.0
        + p["SPEAKER_MARGIN"]
        + counterbore_radius
    )
    if math.hypot(x - p["SPEAKER_CENTER_X"], z - p["SPEAKER_CENTER_Z"]) < (
        speaker_clearance - 1.0e-9
    ):
        reasons.append("speaker_keepout")

    magnet_clearance = p["MAGNET_RELIEF_D"] / 2.0 + counterbore_radius
    if any(
        math.hypot(x - magnet_x, z - magnet_z) < magnet_clearance - 1.0e-9
        for magnet_x, magnet_z in magnet_positions()
    ):
        reasons.append("magnet_relief")

    return tuple(reasons)


def technic_hole_plan():
    accepted = []
    skipped = []
    for position in technic_hole_candidates():
        reasons = technic_hole_skip_reasons(position)
        if reasons:
            skipped.append((position, reasons))
        else:
            accepted.append(position)
    return accepted, skipped


def technic_hole_positions():
    accepted, _ = technic_hole_plan()
    return accepted


def validate_param_contract():
    p = PARAMS
    web = p["HOLE_MIN_WEB"]
    plate_left, plate_right, plate_bottom, plate_top = D["plate_bounds"]
    rail_left, rail_right, rail_bottom, rail_top = D["rail_bounds"]

    if not math.isfinite(p["BOOLEAN_EPS"]) or p["BOOLEAN_EPS"] < 0.05:
        raise ValueError("boolean cutter overlap must be at least 0.05 mm")
    if not math.isclose(p["WATCH_DIAMETER"], 51.95, abs_tol=1.0e-9):
        raise ValueError("official StopWatch diameter must remain 51.95 mm")
    if not math.isclose(p["WATCH_THICKNESS"], 15.5, abs_tol=1.0e-9):
        raise ValueError("official StopWatch thickness must remain 15.5 mm")
    if not math.isclose(p["PLATE_WIDTH"], 22.0, abs_tol=1.0e-9):
        raise ValueError("v3.4 base plate width must remain 22.0 mm")
    if not math.isclose(p["PLATE_LENGTH"], 64.0, abs_tol=1.0e-9):
        raise ValueError("v3.4 base plate length must remain 64.0 mm")
    if not math.isclose(p["PLATE_BODY_HEIGHT"], 64.0, abs_tol=1.0e-9):
        raise ValueError("v3.4 base plate body must span the full 64.0 mm")
    if not math.isclose(p["PLATE_CENTER_X"], 4.0, abs_tol=1.0e-9):
        raise ValueError("v3.4 plate must be centered between X=0 and X=8")
    if not (
        math.isclose(plate_bottom, -32.0, abs_tol=1.0e-9)
        and math.isclose(plate_top, 32.0, abs_tol=1.0e-9)
    ):
        raise ValueError("v3.4 plate must span Z=-32 through Z=+32 mm")
    if not math.isclose(p["PLATE_THICKNESS"], 3.0, abs_tol=1.0e-9):
        raise ValueError("screw-tab base thickness must remain 3.0 mm")

    screw_pitch = D["screw_positions"][1][1] - D["screw_positions"][0][1]
    if not math.isclose(screw_pitch, 40.0, abs_tol=1.0e-9):
        raise ValueError("screw centers must remain 40.0 mm apart")
    if not math.isclose(p["SCREW_HOLE_D"], 2.4, abs_tol=1.0e-9):
        raise ValueError("M2 clearance holes must remain 2.4 mm")
    if not math.isclose(p["SCREW_COUNTERSINK_D"], 4.5, abs_tol=1.0e-9):
        raise ValueError("countersink diameter must remain 4.5 mm")
    if not math.isclose(p["SCREW_COUNTERSINK_ANGLE"], 90.0, abs_tol=1.0e-9):
        raise ValueError("countersink included angle must remain 90 degrees")
    screw_web = D["tab_radius"] - p["SCREW_COUNTERSINK_D"] / 2.0
    if screw_web < web:
        raise ValueError("screw countersinks leave less than the minimum tab web")
    if not math.isclose(p["SCREW_KEEP_OUT_WEB"], 0.8, abs_tol=1.0e-9):
        raise ValueError("screw-to-grid keep-out web must remain 0.8 mm")
    for x, z in D["screw_positions"]:
        if not (
            plate_left <= x - D["tab_radius"]
            and x + D["tab_radius"] <= plate_right
            and plate_bottom <= z - D["tab_radius"]
            and z + D["tab_radius"] <= plate_top
        ):
            raise ValueError("a 3 mm screw-tab zone exceeds the extended plate")

    speaker_keepout = p["SPEAKER_KEEP_OUT_D"] / 2.0 + p["SPEAKER_MARGIN"]
    if D["speaker_relief_d"] / 2.0 < speaker_keepout:
        raise ValueError("speaker relief does not preserve the configured keep-out")
    if point_to_rectangle_distance(
        p["SPEAKER_CENTER_X"], p["SPEAKER_CENTER_Z"], D["plate_bounds"]
    ) < speaker_keepout - 1.0e-9:
        raise ValueError("extended plate violates the speaker keep-out")

    if not math.isclose(p["TECHNIC_HOLE_D"], 4.8, abs_tol=1.0e-9):
        raise ValueError("nominal Technic through-hole diameter must remain 4.8 mm")
    if not math.isfinite(p["TECHNIC_HOLE_PRINT_COMP"]) or not (
        -0.5 <= p["TECHNIC_HOLE_PRINT_COMP"] <= 0.5
    ):
        raise ValueError("Technic print compensation must be finite and within +/-0.5 mm")
    if not math.isclose(p["TECHNIC_RAIL_WIDTH"], 9.6, abs_tol=1.0e-9):
        raise ValueError("single-column Technic beam envelope must remain 9.6 mm")
    expected_band_width = p["TECHNIC_PITCH"] + p["TECHNIC_RAIL_WIDTH"]
    if not math.isclose(
        p["TECHNIC_GRID_BAND_WIDTH"], expected_band_width, abs_tol=1.0e-9
    ):
        raise ValueError("two-column grid band must be pitch plus 9.6 mm beam width")
    if not math.isclose(p["TECHNIC_RAIL_THICKNESS"], 7.8, abs_tol=1.0e-9):
        raise ValueError("Technic rail hole-axis thickness must remain 7.8 mm")
    if not math.isclose(
        p["TECHNIC_RAIL_LENGTH"], p["PLATE_LENGTH"], abs_tol=1.0e-9
    ):
        raise ValueError("raised grid band must cover the full 64 mm plate length")
    if p["TECHNIC_RAIL_THICKNESS"] <= p["PLATE_THICKNESS"]:
        raise ValueError("Technic grid band must rise above the 3 mm screw tabs")
    if not math.isclose(p["TECHNIC_COUNTERBORE_D"], 6.2, abs_tol=1.0e-9):
        raise ValueError("Technic counterbore diameter must remain 6.2 mm")
    if not math.isclose(p["TECHNIC_COUNTERBORE_DEPTH"], 0.8, abs_tol=1.0e-9):
        raise ValueError("Technic counterbore depth must remain 0.8 mm per face")
    if not math.isclose(p["TECHNIC_HOLE_CHAMFER"], 0.3, abs_tol=1.0e-9):
        raise ValueError("Technic inner-edge chamfer must remain 0.3 mm")
    if (
        D["technic_effective_hole_d"] + 2.0 * p["TECHNIC_HOLE_CHAMFER"]
        >= p["TECHNIC_COUNTERBORE_D"]
    ):
        raise ValueError("compensated Technic hole and chamfer exceed the counterbore")
    if (
        2.0 * (p["TECHNIC_COUNTERBORE_DEPTH"] + p["TECHNIC_HOLE_CHAMFER"])
        >= p["TECHNIC_RAIL_THICKNESS"]
    ):
        raise ValueError("Technic face details overlap through the rail thickness")

    if not (
        plate_left <= rail_left
        and rail_right <= plate_right
        and plate_bottom <= rail_bottom
        and rail_top <= plate_top
    ):
        raise ValueError("Technic grid band exceeds the 3 mm base planform")

    counterbore_radius = p["TECHNIC_COUNTERBORE_D"] / 2.0
    candidates = technic_hole_candidates()
    if len(candidates) != 16:
        raise ValueError("v3.4 base grid must contain 2 x 8 candidates")
    grid_origin_x = p["TECHNIC_GRID_XS"][0]
    grid_origin_z = p["TECHNIC_GRID_ZS"][0]
    for x, z in candidates:
        x_index = (x - grid_origin_x) / p["TECHNIC_PITCH"]
        z_index = (z - grid_origin_z) / p["TECHNIC_PITCH"]
        if not (
            math.isclose(x_index, round(x_index), abs_tol=1.0e-9)
            and math.isclose(z_index, round(z_index), abs_tol=1.0e-9)
        ):
            raise ValueError("a Technic candidate is not on the 8.0 mm lattice")

    technic_positions, skipped = technic_hole_plan()
    if len(technic_positions) != 12 or len(skipped) != 4:
        raise ValueError("v3.4 keep-outs must yield 12 holes and 4 skipped candidates")
    valid_reasons = {
        "screw_keepout",
        "outer_rim",
        "speaker_keepout",
        "magnet_relief",
    }
    if any(not reasons or not set(reasons) <= valid_reasons for _, reasons in skipped):
        raise ValueError("a skipped Technic hole has an invalid reason")

    for x, z in technic_positions:
        if not (
            rail_left + counterbore_radius + web
            <= x
            <= rail_right - counterbore_radius - web
        ):
            raise ValueError("a Technic counterbore violates the rail side web")
        if not (
            rail_bottom + counterbore_radius + web
            <= z
            <= rail_top - counterbore_radius - web
        ):
            raise ValueError("a Technic counterbore violates the rail end web")
        if technic_hole_skip_reasons((x, z)):
            raise ValueError("a generated Technic hole violates a keep-out")

    for index, first in enumerate(technic_positions):
        for second in technic_positions[index + 1:]:
            center_distance = math.hypot(first[0] - second[0], first[1] - second[1])
            if center_distance - 2.0 * counterbore_radius < web - 1.0e-9:
                raise ValueError("Technic counterbores leave less than the minimum web")
    countersink_radius = p["SCREW_COUNTERSINK_D"] / 2.0
    for screw_x, screw_z in D["screw_positions"]:
        for hole_x, hole_z in technic_positions:
            clear_web = (
                math.hypot(screw_x - hole_x, screw_z - hole_z)
                - countersink_radius
                - counterbore_radius
            )
            if clear_web < p["SCREW_KEEP_OUT_WEB"] - 1.0e-9:
                raise ValueError("a screw countersink is too close to a Technic counterbore")

    x_pitch = p["TECHNIC_GRID_XS"][1] - p["TECHNIC_GRID_XS"][0]
    z_pitches = [
        second - first
        for first, second in zip(p["TECHNIC_GRID_ZS"], p["TECHNIC_GRID_ZS"][1:])
    ]
    if not math.isclose(x_pitch, p["TECHNIC_PITCH"], abs_tol=1.0e-9) or any(
        not math.isclose(delta, p["TECHNIC_PITCH"], abs_tol=1.0e-9)
        for delta in z_pitches
    ):
        raise ValueError("Technic candidate axes are not spaced at 8.0 mm")

    if not math.isclose(p["PLATE_OUTER_RIM"], 1.6, abs_tol=1.0e-9):
        raise ValueError("nominal through-hole outer rim must remain 1.6 mm")

    if not math.isclose(p["MAGNET_GRID"], 25.46, abs_tol=1.0e-9):
        raise ValueError("official magnet grid must remain 25.46 mm")
    if p["MAGNET_RELIEF_DEPTH"] >= p["PLATE_THICKNESS"]:
        raise ValueError("magnet relief must remain a shallow inner-face recess")
    magnet_radius = p["MAGNET_RELIEF_D"] / 2.0
    relief_overlaps = 0
    for x, z in magnet_positions():
        overlaps_x = x + magnet_radius > plate_left and x - magnet_radius < plate_right
        overlaps_z = z + magnet_radius > plate_bottom and z - magnet_radius < plate_top
        if overlaps_x and overlaps_z:
            relief_overlaps += 1
    if relief_overlaps != 2:
        raise ValueError("the right-side magnet relief seats must overlap the shifted plate")

    reason_counts = {reason: 0 for reason in sorted(valid_reasons)}
    for (x, z), reasons in skipped:
        print(f"TECHNIC_HOLE_SKIP: x={x:.3f} z={z:.3f} reasons={','.join(reasons)}")
        for reason in reasons:
            reason_counts[reason] += 1

    print("PARAM_CONTRACT: PASS")
    print(
        f"OFFICIAL_WATCH: dia {p['WATCH_DIAMETER']:.3f} x "
        f"thickness {p['WATCH_THICKNESS']:.3f} mm"
    )
    print(
        f"PLATE_BASE: {p['PLATE_WIDTH']:.3f} x "
        f"{p['PLATE_LENGTH']:.3f} x {p['PLATE_THICKNESS']:.3f} mm / "
        f"X={plate_left:.3f}..{plate_right:.3f} / "
        f"Z={plate_bottom:.3f}..{plate_top:.3f}"
    )
    print(
        f"SCREW_MOUNT: 2 x dia {p['SCREW_HOLE_D']:.3f} through / "
        f"pitch {p['SCREW_SPACING']:.3f} / countersink "
        f"dia {p['SCREW_COUNTERSINK_D']:.3f} x "
        f"{p['SCREW_COUNTERSINK_ANGLE']:.1f} deg / "
        f"tab thickness {p['PLATE_THICKNESS']:.3f} / tab web {screw_web:.3f} mm"
    )
    print(
        f"SPEAKER_KEEP_OUT: CLEAR (dia {D['speaker_relief_d']:.3f} mm)"
    )
    print(
        f"TECHNIC_GRID_BAND: width {p['TECHNIC_GRID_BAND_WIDTH']:.3f} "
        f"(9.6 beam + 8.0 pitch) x "
        f"thickness {p['TECHNIC_RAIL_THICKNESS']:.3f} x "
        f"length {p['TECHNIC_RAIL_LENGTH']:.3f} mm / "
        f"rise {p['TECHNIC_RAIL_THICKNESS'] - p['PLATE_THICKNESS']:.3f} mm"
    )
    print(
        f"TECHNIC_GRID_CANDIDATES: 2x8={len(candidates)} / nominal dia "
        f"{p['TECHNIC_HOLE_D']:.3f} + print compensation "
        f"{p['TECHNIC_HOLE_PRINT_COMP']:+.3f} mm / "
        f"pitch {p['TECHNIC_PITCH']:.3f} mm"
    )
    print(f"TECHNIC_HOLES_GENERATED: {len(technic_positions)}")
    print(f"TECHNIC_HOLES_SKIPPED: {len(skipped)}")
    print(
        "TECHNIC_SKIP_REASON_COUNTS: "
        + " ".join(f"{reason}={reason_counts[reason]}" for reason in sorted(reason_counts))
    )
    print(
        f"TECHNIC_EFFECTIVE_HOLE_D: {D['technic_effective_hole_d']:.3f} mm"
    )
    print(
        "TECHNIC_HOLE_CENTERS_XZ: "
        + " ".join(f"({x:.3f},{z:.3f})" for x, z in technic_positions)
    )
    print(
        f"TECHNIC_GRID_CHECK: PASS (origin {grid_origin_x:.3f},{grid_origin_z:.3f} / "
        f"pitch {p['TECHNIC_PITCH']:.3f} mm / all generated holes on lattice)"
    )
    print(
        f"TECHNIC_COUNTERBORES: dia {p['TECHNIC_COUNTERBORE_D']:.3f} x "
        f"depth {p['TECHNIC_COUNTERBORE_DEPTH']:.3f} mm / both faces / "
        f"minimum web {web:.3f} mm"
    )
    print(
        f"TECHNIC_OUTER_RIM: nominal {p['PLATE_OUTER_RIM']:.3f} mm / "
        f"effective after +{p['TECHNIC_HOLE_PRINT_COMP']:.3f} diameter compensation "
        f"{p['PLATE_OUTER_RIM'] - p['TECHNIC_HOLE_PRINT_COMP'] / 2.0:.3f} mm"
    )
    print(
        f"TECHNIC_HOLE_CHAMFER: {p['TECHNIC_HOLE_CHAMFER']:.3f} mm / "
        "both inner bore edges"
    )
    print(
        f"MAGNET_RELIEF_SEATS: 4 official positions on {p['MAGNET_GRID']:.3f} mm "
        f"grid / {relief_overlaps} plate overlaps / dia {p['MAGNET_RELIEF_D']:.3f} "
        f"x depth {p['MAGNET_RELIEF_DEPTH']:.3f} mm"
    )


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def apply_transform(obj):
    activate(obj)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def box(name, size_x, size_y, size_z, location):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (size_x, size_y, size_z)
    apply_transform(obj)
    return obj


def cylinder_y(name, diameter, depth, location, vertices=64):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices,
        radius=diameter / 2.0,
        depth=depth,
        location=location,
        rotation=(math.radians(90.0), 0.0, 0.0),
    )
    obj = bpy.context.active_object
    obj.name = name
    apply_transform(obj)
    return obj


def frustum_y(name, radius_inner, radius_outer, depth, location, vertices=64):
    bpy.ops.mesh.primitive_cone_add(
        vertices=vertices,
        radius1=radius_inner,
        radius2=radius_outer,
        depth=depth,
        location=location,
        rotation=(math.radians(-90.0), 0.0, 0.0),
    )
    obj = bpy.context.active_object
    obj.name = name
    apply_transform(obj)
    return obj


def revolved_profile_y(name, profile, center_x, center_z, vertices=64):
    """Create one closed Y-axis cutter from an ordered ``(y, radius)`` profile."""
    if len(profile) < 2 or vertices < 3:
        raise ValueError("a revolved profile needs at least two rings and three vertices")
    if any(radius <= 0.0 for _, radius in profile):
        raise ValueError("revolved profile radii must be positive")
    if any(
        next_y < current_y
        for (current_y, _), (next_y, _) in zip(profile, profile[1:])
    ):
        raise ValueError("revolved profile Y coordinates must be ordered")

    mesh = bpy.data.meshes.new(name + "_mesh")
    coordinates = []
    phase = math.pi / vertices
    for y, radius in profile:
        for segment in range(vertices):
            angle = 2.0 * math.pi * segment / vertices + phase
            coordinates.append(
                (
                    center_x + radius * math.cos(angle),
                    y,
                    center_z + radius * math.sin(angle),
                )
            )

    faces = []
    for ring in range(len(profile) - 1):
        lower = ring * vertices
        upper = (ring + 1) * vertices
        for segment in range(vertices):
            next_segment = (segment + 1) % vertices
            faces.append(
                (
                    lower + segment,
                    upper + segment,
                    upper + next_segment,
                    lower + next_segment,
                )
            )
    faces.append(tuple(range(vertices)))
    last_ring = (len(profile) - 1) * vertices
    faces.append(tuple(last_ring + segment for segment in reversed(range(vertices))))

    mesh.from_pydata(coordinates, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    cleanup_mesh(obj)
    return obj


def boolean(target, tool, operation):
    modifier = target.modifiers.new(operation.lower(), "BOOLEAN")
    modifier.operation = operation
    modifier.solver = "EXACT"
    modifier.object = tool
    activate(target)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.data.objects.remove(tool, do_unlink=True)
    cleanup_mesh(target)


def cut_through_holes(target, positions, diameter, prefix):
    p = PARAMS
    cut_depth = p["PLATE_THICKNESS"] + 2.0 * p["BOOLEAN_EPS"]
    for index, (x, z) in enumerate(positions, start=1):
        cutter = cylinder_y(
            f"{prefix}_{index}",
            diameter,
            cut_depth,
            (x, D["plate_center_y"], z),
        )
        boolean(target, cutter, "DIFFERENCE")


def cut_technic_holes(target):
    p = PARAMS
    eps = p["BOOLEAN_EPS"]
    positions = technic_hole_positions()
    hole_radius = D["technic_effective_hole_d"] / 2.0
    counterbore_radius = p["TECHNIC_COUNTERBORE_D"] / 2.0
    counterbore_depth = p["TECHNIC_COUNTERBORE_DEPTH"]
    chamfer = p["TECHNIC_HOLE_CHAMFER"]
    chamfer_radius = hole_radius + chamfer
    outer_counterbore_y = p["TECHNIC_RAIL_THICKNESS"] - counterbore_depth
    outer_chamfer_y = outer_counterbore_y - chamfer

    # A single closed cutter avoids coplanar seams between the former through,
    # counterbore, and chamfer cutters.  Duplicate Y values intentionally form
    # the flat counterbore shoulders in the revolved profile.
    profile = (
        (-eps, counterbore_radius),
        (counterbore_depth, counterbore_radius),
        (counterbore_depth, chamfer_radius),
        (counterbore_depth + chamfer, hole_radius),
        (outer_chamfer_y, hole_radius),
        (outer_counterbore_y, chamfer_radius),
        (outer_counterbore_y, counterbore_radius),
        (p["TECHNIC_RAIL_THICKNESS"] + eps, counterbore_radius),
    )

    for index, (x, z) in enumerate(positions, start=1):
        cutter = revolved_profile_y(
            f"technic_hole_profile_{index}",
            profile,
            x,
            z,
        )
        boolean(target, cutter, "DIFFERENCE")


def cut_screw_holes(target):
    p = PARAMS
    eps = p["BOOLEAN_EPS"]
    cut_through_holes(target, D["screw_positions"], p["SCREW_HOLE_D"], "screw_through")
    true_depth = D["countersink_depth"]
    tool_depth = true_depth + 2.0 * eps
    inner_radius = p["SCREW_HOLE_D"] / 2.0 - eps
    outer_radius = p["SCREW_COUNTERSINK_D"] / 2.0 + eps
    center_y = D["plate_outer_y"] - true_depth / 2.0
    for index, (x, z) in enumerate(D["screw_positions"], start=1):
        cutter = frustum_y(
            f"screw_countersink_{index}",
            inner_radius,
            outer_radius,
            tool_depth,
            (x, center_y, z),
        )
        boolean(target, cutter, "DIFFERENCE")


def cut_magnet_reliefs(target):
    p = PARAMS
    eps = p["BOOLEAN_EPS"]
    cutter_depth = p["MAGNET_RELIEF_DEPTH"] + eps
    cutter_center_y = (p["MAGNET_RELIEF_DEPTH"] - eps) / 2.0
    for index, (x, z) in enumerate(magnet_positions(), start=1):
        cutter = cylinder_y(
            f"magnet_relief_{index}",
            p["MAGNET_RELIEF_D"],
            cutter_depth,
            (x, cutter_center_y, z),
        )
        boolean(target, cutter, "DIFFERENCE")


def build_backpack():
    p = PARAMS
    eps = p["BOOLEAN_EPS"]
    plate = box(
        "backpack_plate_body",
        p["PLATE_WIDTH"],
        p["PLATE_THICKNESS"],
        p["PLATE_BODY_HEIGHT"],
        (p["PLATE_CENTER_X"], D["plate_center_y"], p["PLATE_CENTER_Z"]),
    )

    rail = box(
        "technic_grid_band",
        p["TECHNIC_GRID_BAND_WIDTH"],
        p["TECHNIC_RAIL_THICKNESS"],
        p["TECHNIC_RAIL_LENGTH"],
        (
            p["TECHNIC_RAIL_CENTER_X"],
            D["rail_center_y"],
            p["TECHNIC_RAIL_CENTER_Z"],
        ),
    )

    # Remove the raised portion over each original screw tab, then union the
    # band to the 3 mm base.  The base fills these circular zones back to exactly
    # 3 mm while the rest of the grid band reaches the 7.8 mm beam thickness.
    for index, (x, z) in enumerate(D["screw_positions"], start=1):
        tab_clearance = cylinder_y(
            f"screw_tab_3mm_zone_{index}",
            p["SCREW_TAB_D"],
            p["TECHNIC_RAIL_THICKNESS"] + 2.0 * eps,
            (x, D["rail_center_y"], z),
        )
        boolean(rail, tab_clearance, "DIFFERENCE")

    boolean(plate, rail, "UNION")

    cut_magnet_reliefs(plate)
    cut_technic_holes(plate)
    cut_screw_holes(plate)
    plate.name = "toicamera_screw_fastened_full_technic_grid_v3_4"
    return plate


def cleanup_mesh(obj, merge_distance=1.0e-4):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge_distance)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=merge_distance)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.validate(verbose=True)
    obj.data.update()


def mesh_stats(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    nonmanifold = sum(1 for edge in bm.edges if len(edge.link_faces) != 2)
    remaining = set(bm.verts)
    components = 0
    while remaining:
        components += 1
        stack = [remaining.pop()]
        while stack:
            vertex = stack.pop()
            for edge in vertex.link_edges:
                other = edge.other_vert(vertex)
                if other in remaining:
                    remaining.remove(other)
                    stack.append(other)
    bm.free()
    return nonmanifold, components


def validate_object(label, obj, expected, tolerance):
    cleanup_mesh(obj, merge_distance=1.0e-3)
    dims = tuple(float(value) for value in obj.dimensions)
    nonmanifold, components = mesh_stats(obj)
    deltas = tuple(abs(actual - wanted) for actual, wanted in zip(dims, expected))
    bbox_ok = max(deltas) <= tolerance
    mesh_ok = nonmanifold == 0 and components == 1
    print(f"{label}_BBOX_BUILT: {dims[0]:.4f} {dims[1]:.4f} {dims[2]:.4f}")
    print(f"{label}_BBOX_EXPECT: {expected[0]:.4f} {expected[1]:.4f} {expected[2]:.4f}")
    print(f"{label}_BBOX_DELTA: {deltas[0]:.4f} {deltas[1]:.4f} {deltas[2]:.4f}")
    print(f"{label}_BBOX_VS_SPEC: {'OK' if bbox_ok else 'NG'} (tol +/-{tolerance:.3f} mm)")
    print(f"{label}_NONMANIFOLD_EDGES: {nonmanifold}")
    print(f"{label}_CONNECTED_COMPONENTS: {components}")
    return bbox_ok and mesh_ok


def export_stl(obj, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    activate(obj)
    bpy.ops.wm.stl_export(
        filepath=str(path),
        export_selected_objects=True,
        global_scale=1.0,
        use_scene_unit=False,
        ascii_format=False,
        forward_axis="Y",
        up_axis="Z",
        apply_modifiers=True,
    )
    print(f"STL_EXPORTED: {path}")


def validate_exported_stl(label, path, expected, tolerance):
    before = set(bpy.data.objects)
    bpy.ops.wm.stl_import(filepath=str(path), forward_axis="Y", up_axis="Z")
    imported = next(obj for obj in bpy.data.objects if obj not in before)
    imported.name = label.lower() + "_stl_check"
    dims = tuple(float(value) for value in imported.dimensions)
    deltas = tuple(abs(actual - wanted) for actual, wanted in zip(dims, expected))
    nonmanifold, components = mesh_stats(imported)
    ok = max(deltas) <= tolerance and nonmanifold == 0 and components == 1
    print(f"{label}_STL_BBOX: {dims[0]:.4f} {dims[1]:.4f} {dims[2]:.4f}")
    print(f"{label}_STL_NONMANIFOLD_EDGES: {nonmanifold}")
    print(f"{label}_STL_CONNECTED_COMPONENTS: {components}")
    print(f"{label}_STL_SELF_CHECK: {'PASS' if ok else 'FAIL'}")
    bpy.data.objects.remove(imported, do_unlink=True)
    return ok


def output_paths(raw_out, part):
    out = Path(raw_out).expanduser().resolve()
    if not out.suffix:
        out = out.with_suffix(".stl")
    return {"backpack": out}


def main():
    args = parse_args()
    reset_scene()
    validate_param_contract()
    paths = output_paths(args.out, args.part)
    overall_ok = True

    print("UNIT_CONTRACT: 1 Blender Unit = 1 mm")
    print(
        "LAYOUT_V3_4: open watch / 2-screw backpack / full raised Technic grid / "
        "rear-facing camera"
    )
    print("PART_ALIAS: all -> backpack")
    print(
        "PRINT_ORIENTATION: watch-contact face on build plate; grid band raised upward; "
        "Technic hole axes vertical"
    )

    for part, path in paths.items():
        obj = build_backpack()
        label = part.upper()
        object_ok = validate_object(label, obj, D["backpack_bbox"], args.bbox_tol)
        export_stl(obj, path)
        stl_ok = validate_exported_stl(label, path, D["backpack_bbox"], args.bbox_tol)
        overall_ok = overall_ok and object_ok and stl_ok

    print("CASE_BUILD_RESULT: " + ("PASS" if overall_ok else "FAIL"))
    raise SystemExit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
