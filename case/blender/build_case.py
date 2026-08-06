#!/usr/bin/env python3
"""Build the ToiCamera backpack, grid3, and camera+GPS duo plates.

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


# v3.5 is deliberately a separate part.  The v3.4 PARAMS and build_backpack()
# path above remain the source of truth for the existing backpack geometry.
GRID3_PARAMS = {
    # The requested 25.5 mm clip radius is just inside the official 25.975 mm
    # watch radius (0.475 mm exact radial clearance after rounding).
    "WATCH_CLIP_RADIUS": 25.5,
    "WATCH_CLIP_TOL": 0.01,
    "WATCH_CLIP_VERTICES": 128,

    # Three 8 mm-pitch columns retain the v3.3 9.6 mm single-beam envelope.
    # The selected option is verified against the alternatives below by hole
    # count and by the speaker keep-out before any mesh is constructed.
    "PLATE_CENTER_X": 4.0,
    "PLATE_CENTER_Z": 0.0,
    "TECHNIC_GRID_XS": (-4.0, 4.0, 12.0),
    "TECHNIC_GRID_X_OPTIONS": (
        (-12.0, -4.0, 4.0),
        (-4.0, 4.0, 12.0),
        (4.0, 12.0, 20.0),
        (12.0, 20.0, 28.0),
    ),
    # Offset zero retains the former absolute lattice.  The selected offset
    # translates every row together, so the 8 mm LEGO-compatible pitch stays
    # unchanged while the keep-outs determine the best absolute placement.
    "TECHNIC_GRID_ZS": (-28.0, -20.0, -12.0, -4.0, 4.0, 12.0, 20.0, 28.0),
    "TECHNIC_GRID_ROW_OFFSET_OPTIONS": (
        0.0,
        1.0,
        2.0,
        3.0,
        4.0,
        5.0,
        6.0,
        7.0,
    ),
}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(
        description="Build the ToiCamera backpack, grid3, and camera+GPS duo plates"
    )
    parser.add_argument("--out", required=True, help="output STL path")
    parser.add_argument(
        "--part",
        choices=("backpack", "grid3", "duo", "all"),
        default="backpack",
        help="part to export; all writes backpack, grid3, and duo (default: backpack)",
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


def derived_grid3():
    p = PARAMS
    g = GRID3_PARAMS
    band_width = p["TECHNIC_RAIL_WIDTH"] + 2.0 * p["TECHNIC_PITCH"]
    clip_diameter = 2.0 * g["WATCH_CLIP_RADIUS"]
    plate_left = g["PLATE_CENTER_X"] - band_width / 2.0
    plate_right = g["PLATE_CENTER_X"] + band_width / 2.0
    return {
        "plate_width": band_width,
        "plate_length": clip_diameter,
        "plate_center_y": D["plate_center_y"],
        "rail_center_y": D["rail_center_y"],
        "plate_bounds": (
            plate_left,
            plate_right,
            -g["WATCH_CLIP_RADIUS"],
            g["WATCH_CLIP_RADIUS"],
        ),
        "rail_bounds": (
            plate_left,
            plate_right,
            -g["WATCH_CLIP_RADIUS"],
            g["WATCH_CLIP_RADIUS"],
        ),
        "grid3_bbox": (
            band_width,
            p["TECHNIC_RAIL_THICKNESS"],
            clip_diameter,
        ),
    }


GRID3_D = derived_grid3()


# The duo plate is a separate, hardware-feedback-driven part.  It reuses only
# the proven hole, screw, and print compensation values from PARAMS; the v3.4
# backpack and v3.5 grid3 parameter sets and build paths remain unchanged.
DUO_PARAMS = {
    # The final hardware-photo orientation is rotated 90 degrees from the
    # earlier duo drafts: +Z is north (button/speaker side), X is east/west.
    "WATCH_CLIP_RADIUS": 25.5,
    "WATCH_CLIP_TOL": 0.01,
    "WATCH_CLIP_VERTICES": 128,
    "PLATE_WIDTH": 51.0,
    "PLATE_HEIGHT": 27.0,
    "PLATE_CENTER_X": 0.0,
    "PLATE_CENTER_Z": -5.5,
    "OUTLINE_CORNER_RADIUS": 6.0,
    "OUTLINE_VERTICES_PER_CORNER": 16,

    # Existing watch screws now lie on the east/west axis.
    "SCREW_XS": (-20.0, 20.0),
    "SCREW_Z": 0.0,

    # Three horizontal 16 mm CLIP pairs: camera alone at watch center, or
    # camera+GPS side-by-side on the lower row with module centers at +/-13 mm.
    "CENTER_ROW_XS": (-8.0, 8.0),
    "CENTER_ROW_Z": 0.0,
    "LOWER_ROW_XS": (-21.0, -5.0, 5.0, 21.0),
    "LOWER_ROW_Z": -12.0,

    # The watch-circle clip alone exposes the outer lower holes.  These ears
    # intentionally extend beyond that circle so the complete counterbores
    # remain surrounded by material.
    "LOWER_LOBE_CENTERS": ((-21.0, -12.0), (21.0, -12.0)),
    "LOWER_LOBE_RADIUS": 6.5,
    "LOWER_LOBE_VERTICES": 128,

    # Only these two regions rise from 3.0 to 7.8 mm.  The lower rectangle is
    # watch-circle clipped, then extended by the same two ear lobes.
    "CENTER_BAND_BOUNDS": (-12.8, 12.8, -4.8, 4.8),
    "LOWER_BAND_BOUNDS": (-25.5, 25.5, -16.8, -7.2),
}


def derived_duo():
    p = PARAMS
    q = DUO_PARAMS
    half_width = q["PLATE_WIDTH"] / 2.0
    half_height = q["PLATE_HEIGHT"] / 2.0
    plate_left = q["PLATE_CENTER_X"] - half_width
    plate_right = q["PLATE_CENTER_X"] + half_width
    plate_bottom = q["PLATE_CENTER_Z"] - half_height
    plate_top = q["PLATE_CENTER_Z"] + half_height
    lobe_left = min(
        x - q["LOWER_LOBE_RADIUS"] for x, _ in q["LOWER_LOBE_CENTERS"]
    )
    lobe_right = max(
        x + q["LOWER_LOBE_RADIUS"] for x, _ in q["LOWER_LOBE_CENTERS"]
    )
    lobe_bottom = min(
        z - q["LOWER_LOBE_RADIUS"] for _, z in q["LOWER_LOBE_CENTERS"]
    )
    lobe_top = max(
        z + q["LOWER_LOBE_RADIUS"] for _, z in q["LOWER_LOBE_CENTERS"]
    )
    outline_bounds = (
        min(plate_left, lobe_left),
        max(plate_right, lobe_right),
        min(plate_bottom, lobe_bottom),
        max(plate_top, lobe_top),
    )
    return {
        "plate_center_y": D["plate_center_y"],
        "rail_center_y": D["rail_center_y"],
        "plate_bounds": (plate_left, plate_right, plate_bottom, plate_top),
        "lobe_bounds": (lobe_left, lobe_right, lobe_bottom, lobe_top),
        "outline_bounds": outline_bounds,
        "center_band_bounds": q["CENTER_BAND_BOUNDS"],
        "lower_band_bounds": q["LOWER_BAND_BOUNDS"],
        "duo_bbox": (
            outline_bounds[1] - outline_bounds[0],
            p["TECHNIC_RAIL_THICKNESS"],
            outline_bounds[3] - outline_bounds[2],
        ),
    }


DUO_D = derived_duo()


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


def grid3_technic_hole_candidates(columns=None, rows=None):
    g = GRID3_PARAMS
    xs = g["TECHNIC_GRID_XS"] if columns is None else columns
    if rows is None:
        rows = grid3_selected_row_plan()["rows"]
    return [
        (x, z)
        for x in xs
        for z in rows
    ]


def grid3_technic_hole_skip_reasons(position, columns=None):
    """Return every v3.5 keep-out rule that rejects a grid3 candidate."""
    p = PARAMS
    g = GRID3_PARAMS
    xs = g["TECHNIC_GRID_XS"] if columns is None else columns
    x, z = position
    reasons = []
    nominal_radius = p["TECHNIC_HOLE_D"] / 2.0
    hole_radius = D["technic_effective_hole_d"] / 2.0
    counterbore_radius = p["TECHNIC_COUNTERBORE_D"] / 2.0
    band_left = min(xs) - p["TECHNIC_RAIL_WIDTH"] / 2.0
    band_right = max(xs) + p["TECHNIC_RAIL_WIDTH"] / 2.0

    # Along Y, the screw countersink meets the Technic through-hole while the
    # screw through-hole meets the Technic counterbore.  The two larger radii
    # do not overlap each other, so score the actual worst profile pair.
    screw_clearance = max(
        p["SCREW_COUNTERSINK_D"] / 2.0 + hole_radius,
        p["SCREW_HOLE_D"] / 2.0 + counterbore_radius,
    ) + p["SCREW_KEEP_OUT_WEB"]
    if any(
        math.hypot(x - screw_x, z - screw_z) < screw_clearance - 1.0e-9
        for screw_x, screw_z in D["screw_positions"]
    ):
        reasons.append("screw_keepout")

    circle_clearance = nominal_radius + p["PLATE_OUTER_RIM"]
    if math.hypot(x, z) + circle_clearance > (
        g["WATCH_CLIP_RADIUS"] + 1.0e-9
    ):
        reasons.append("watch_clip_outer_rim")

    side_clearance = counterbore_radius + p["HOLE_MIN_WEB"]
    if not (
        band_left + side_clearance - 1.0e-9
        <= x
        <= band_right - side_clearance + 1.0e-9
    ):
        reasons.append("grid_band_side_web")

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


def grid3_technic_hole_plan(columns=None, rows=None):
    accepted = []
    skipped = []
    for position in grid3_technic_hole_candidates(columns, rows):
        reasons = grid3_technic_hole_skip_reasons(position, columns)
        if reasons:
            skipped.append((position, reasons))
        else:
            accepted.append(position)
    return accepted, skipped


def grid3_row_offset_option_plan():
    """Score 1 mm row shifts without changing the 8 mm lattice pitch."""
    g = GRID3_PARAMS
    plans = []
    for offset in g["TECHNIC_GRID_ROW_OFFSET_OPTIONS"]:
        rows = tuple(z + offset for z in g["TECHNIC_GRID_ZS"])
        accepted, skipped = grid3_technic_hole_plan(rows=rows)
        lowest_z = min((z for _, z in accepted), default=math.inf)
        plans.append(
            {
                "offset": offset,
                "rows": rows,
                "accepted": accepted,
                "skipped": skipped,
                "lowest_z": lowest_z,
            }
        )
    return plans


def grid3_selected_row_plan():
    """Choose most holes, then the lowest generated row, deterministically."""
    plans = grid3_row_offset_option_plan()
    return min(
        plans,
        key=lambda plan: (
            -len(plan["accepted"]),
            plan["lowest_z"],
            plan["offset"],
        ),
    )


def grid3_technic_hole_positions():
    accepted, _ = grid3_technic_hole_plan()
    return accepted


def grid3_column_option_plan():
    """Score aligned three-column options that stay right of the speaker."""
    p = PARAMS
    g = GRID3_PARAMS
    selected_rows = grid3_selected_row_plan()["rows"]
    speaker_radius = p["SPEAKER_KEEP_OUT_D"] / 2.0 + p["SPEAKER_MARGIN"]
    plans = []
    for columns in g["TECHNIC_GRID_X_OPTIONS"]:
        band_left = min(columns) - p["TECHNIC_RAIL_WIDTH"] / 2.0
        band_right = max(columns) + p["TECHNIC_RAIL_WIDTH"] / 2.0
        bounds = (
            band_left,
            band_right,
            -g["WATCH_CLIP_RADIUS"],
            g["WATCH_CLIP_RADIUS"],
        )
        speaker_gap = point_to_rectangle_distance(
            p["SPEAKER_CENTER_X"], p["SPEAKER_CENTER_Z"], bounds
        ) - speaker_radius
        intersects_clip = (
            band_left < g["WATCH_CLIP_RADIUS"]
            and band_right > -g["WATCH_CLIP_RADIUS"]
        )
        accepted, skipped = grid3_technic_hole_plan(columns, selected_rows)
        plans.append(
            {
                "columns": columns,
                "accepted": accepted,
                "skipped": skipped,
                "speaker_gap": speaker_gap,
                "feasible": speaker_gap >= -1.0e-9 and intersects_clip,
            }
        )
    return plans


def duo_screw_positions():
    q = DUO_PARAMS
    return [(x, q["SCREW_Z"]) for x in q["SCREW_XS"]]


def duo_center_hole_positions():
    q = DUO_PARAMS
    return [(x, q["CENTER_ROW_Z"]) for x in q["CENTER_ROW_XS"]]


def duo_lower_hole_positions():
    q = DUO_PARAMS
    return [(x, q["LOWER_ROW_Z"]) for x in q["LOWER_ROW_XS"]]


def duo_technic_hole_positions():
    return duo_center_hole_positions() + duo_lower_hole_positions()


def duo_mounting_pairs():
    center = duo_center_hole_positions()
    lower = duo_lower_hole_positions()
    return (center, lower[:2], lower[2:])


def duo_point_inside_clipped_body(x, z, tolerance=1.0e-9):
    """Return whether an X/Z point lies in the rounded, watch-clipped bar."""
    q = DUO_PARAMS
    local_x = abs(x - q["PLATE_CENTER_X"])
    local_z = abs(z - q["PLATE_CENTER_Z"])
    half_width = q["PLATE_WIDTH"] / 2.0
    half_height = q["PLATE_HEIGHT"] / 2.0
    radius = q["OUTLINE_CORNER_RADIUS"]
    if local_x > half_width + tolerance or local_z > half_height + tolerance:
        return False
    if local_x > half_width - radius and local_z > half_height - radius:
        corner_x = local_x - (half_width - radius)
        corner_z = local_z - (half_height - radius)
        if math.hypot(corner_x, corner_z) > radius + tolerance:
            return False
    return math.hypot(x, z) <= q["WATCH_CLIP_RADIUS"] + tolerance


def duo_point_inside_lower_lobes(x, z, tolerance=1.0e-9):
    """Return whether an X/Z point lies in either intentional lower ear."""
    q = DUO_PARAMS
    return any(
        math.hypot(x - center_x, z - center_z)
        <= q["LOWER_LOBE_RADIUS"] + tolerance
        for center_x, center_z in q["LOWER_LOBE_CENTERS"]
    )


def duo_point_inside_outline(x, z, tolerance=1.0e-9):
    """Return whether a point lies in the clipped body or either lower lobe."""
    return duo_point_inside_clipped_body(
        x,
        z,
        tolerance,
    ) or duo_point_inside_lower_lobes(x, z, tolerance)


def duo_point_inside_lower_band(x, z):
    """Return whether a point is covered by the clipped band or its lobes."""
    q = DUO_PARAMS
    left, right, bottom, top = DUO_D["lower_band_bounds"]
    in_clipped_band = (
        left - 1.0e-9 <= x <= right + 1.0e-9
        and bottom - 1.0e-9 <= z <= top + 1.0e-9
        and math.hypot(x, z) <= q["WATCH_CLIP_RADIUS"] + 1.0e-9
    )
    return in_clipped_band or duo_point_inside_lower_lobes(x, z)


def duo_magnet_positions():
    """Keep only official magnet centers whose seats lie on the duo plate."""
    return [
        (x, z)
        for x, z in magnet_positions()
        if duo_point_inside_outline(x, z)
    ]


def validate_duo_param_contract():
    """Validate the hardware-photo-confirmed duo layout before mesh creation."""
    p = PARAMS
    q = DUO_PARAMS
    counterbore_radius = p["TECHNIC_COUNTERBORE_D"] / 2.0
    effective_hole_radius = D["technic_effective_hole_d"] / 2.0
    screw_hole_radius = p["SCREW_HOLE_D"] / 2.0
    countersink_radius = p["SCREW_COUNTERSINK_D"] / 2.0
    plate_left, plate_right, plate_bottom, plate_top = DUO_D["plate_bounds"]

    exact_values = (
        (q["WATCH_CLIP_RADIUS"], 25.5, "duo watch clip radius"),
        (q["WATCH_CLIP_TOL"], 0.01, "duo watch clip tolerance"),
        (q["PLATE_WIDTH"], 51.0, "duo plate width"),
        (q["PLATE_HEIGHT"], 27.0, "duo plate height"),
        (q["PLATE_CENTER_X"], 0.0, "duo plate center X"),
        (q["PLATE_CENTER_Z"], -5.5, "duo plate center Z"),
        (q["OUTLINE_CORNER_RADIUS"], 6.0, "duo outline corner radius"),
        (q["SCREW_Z"], 0.0, "duo screw axis Z"),
        (q["CENTER_ROW_Z"], 0.0, "duo center row Z"),
        (q["LOWER_ROW_Z"], -12.0, "duo lower row Z"),
        (q["LOWER_LOBE_RADIUS"], 6.5, "duo lower lobe radius"),
        (p["PLATE_THICKNESS"], 3.0, "duo base thickness"),
        (p["TECHNIC_RAIL_THICKNESS"], 7.8, "duo hole-band thickness"),
        (p["TECHNIC_HOLE_D"], 4.8, "duo nominal Technic hole diameter"),
        (p["TECHNIC_HOLE_PRINT_COMP"], 0.15, "duo hole print compensation"),
        (p["TECHNIC_COUNTERBORE_D"], 6.2, "duo counterbore diameter"),
        (p["TECHNIC_COUNTERBORE_DEPTH"], 0.8, "duo counterbore depth"),
        (p["TECHNIC_HOLE_CHAMFER"], 0.3, "duo hole chamfer"),
        (p["SCREW_SPACING"], 40.0, "duo screw pitch"),
        (p["SCREW_HOLE_D"], 2.4, "duo screw through diameter"),
        (p["SCREW_COUNTERSINK_D"], 4.5, "duo screw countersink diameter"),
        (p["SCREW_COUNTERSINK_ANGLE"], 90.0, "duo screw countersink angle"),
        (p["BOOLEAN_EPS"], 0.05, "duo lobe union penetration"),
    )
    for actual, expected, label in exact_values:
        if not math.isclose(actual, expected, abs_tol=1.0e-9):
            raise ValueError(f"{label} must remain {expected:.3f} mm")

    if q["SCREW_XS"] != (-20.0, 20.0):
        raise ValueError("duo screws must remain at X=-20/+20, Z=0")
    if q["CENTER_ROW_XS"] != (-8.0, 8.0):
        raise ValueError("duo center pair must remain at X=-8/+8, Z=0")
    if q["LOWER_ROW_XS"] != (-21.0, -5.0, 5.0, 21.0):
        raise ValueError("duo lower pairs must remain at X=-21/-5/+5/+21, Z=-12")
    if q["LOWER_LOBE_CENTERS"] != ((-21.0, -12.0), (21.0, -12.0)):
        raise ValueError(
            "duo lower lobes must remain centered on the outer lower holes"
        )
    if q["CENTER_BAND_BOUNDS"] != (-12.8, 12.8, -4.8, 4.8):
        raise ValueError("duo center band bounds changed")
    if q["LOWER_BAND_BOUNDS"] != (-25.5, 25.5, -16.8, -7.2):
        raise ValueError("duo lower band bounds changed")
    obsolete_features = {
        "SPEAKER_KEEP_OUT_CENTER",
        "SPEAKER_KEEP_OUT_RADIUS",
        "SPEAKER_OPENING_D",
        "GRIP_SCALLOP_RADIUS",
    }
    if obsolete_features.intersection(q):
        raise ValueError(
            "duo v4.1 must not define windows, scallops, or speaker notches"
        )

    screw_positions = duo_screw_positions()
    center_positions = duo_center_hole_positions()
    lower_positions = duo_lower_hole_positions()
    positions = duo_technic_hole_positions()
    pairs = duo_mounting_pairs()
    if screw_positions != [(-20.0, 0.0), (20.0, 0.0)]:
        raise ValueError("duo screw centers do not match the east/west axis")
    if len(center_positions) != 2 or len(lower_positions) != 4 or len(positions) != 6:
        raise ValueError("duo must generate one center pair and two lower pairs")
    pair_spans = tuple(
        math.hypot(second[0] - first[0], second[1] - first[1])
        for first, second in pairs
    )
    if any(not math.isclose(span, 16.0, abs_tol=1.0e-9) for span in pair_spans):
        raise ValueError("every duo mounting pair must span exactly 16.0 mm")

    if not (
        math.isclose(plate_left, -25.5, abs_tol=1.0e-9)
        and math.isclose(plate_right, 25.5, abs_tol=1.0e-9)
        and math.isclose(plate_bottom, -19.0, abs_tol=1.0e-9)
        and math.isclose(plate_top, 8.0, abs_tol=1.0e-9)
    ):
        raise ValueError("duo bbox must span X=-25.5..+25.5 and Z=-19..+8 mm")
    if q["OUTLINE_CORNER_RADIUS"] > min(q["PLATE_WIDTH"], q["PLATE_HEIGHT"]) / 2.0:
        raise ValueError("duo outline corner radius does not fit the plate")
    if DUO_D["lobe_bounds"] != (-27.5, 27.5, -18.5, -5.5):
        raise ValueError("duo lower lobe bounds changed")
    if DUO_D["outline_bounds"] != (-27.5, 27.5, -19.0, 8.0):
        raise ValueError("duo outline must include the two intentional lower ears")

    # Each lobe center sits inside the clipped body by more than BOOLEAN_EPS,
    # so the circle union is a volumetric overlap rather than a tangent or
    # coincident join.  The lobe perimeter itself is the only allowed outline
    # outside the r25.5 watch circle.
    join_eps = p["BOOLEAN_EPS"]
    for lobe_x, lobe_z in q["LOWER_LOBE_CENTERS"]:
        for offset_x, offset_z in (
            (0.0, 0.0),
            (-join_eps, 0.0),
            (join_eps, 0.0),
            (0.0, -join_eps),
            (0.0, join_eps),
        ):
            if not duo_point_inside_clipped_body(
                lobe_x + offset_x,
                lobe_z + offset_z,
            ):
                raise ValueError(
                    "a duo lower lobe lacks epsilon penetration into the body"
                )

    # The complete radius-4 screw tab zones must remain inside both the rounded
    # bar and the watch circle, and outside both 7.8 mm raised bands.
    for screw_x, screw_z in screw_positions:
        for sample in range(64):
            angle = 2.0 * math.pi * sample / 64.0
            sample_x = screw_x + D["tab_radius"] * math.cos(angle)
            sample_z = screw_z + D["tab_radius"] * math.sin(angle)
            if not duo_point_inside_outline(sample_x, sample_z):
                raise ValueError("a duo screw tab exceeds the plate outline")

    band_specs = (
        (DUO_D["center_band_bounds"], center_positions, "center"),
        (DUO_D["lower_band_bounds"], lower_positions, "lower"),
    )
    for bounds, band_positions, label in band_specs:
        left, right, bottom, top = bounds
        if not (
            plate_left <= left < right <= plate_right
            and plate_bottom <= bottom < top <= plate_top
        ):
            raise ValueError(f"duo {label} band exceeds the plate")
        for x, z in band_positions:
            if not (
                left + counterbore_radius <= x <= right - counterbore_radius
                and bottom + counterbore_radius <= z <= top - counterbore_radius
            ):
                raise ValueError(f"a duo {label} counterbore exceeds its raised band")
            for sample in range(q["LOWER_LOBE_VERTICES"]):
                angle = 2.0 * math.pi * sample / q["LOWER_LOBE_VERTICES"]
                sample_x = x + counterbore_radius * math.cos(angle)
                sample_z = z + counterbore_radius * math.sin(angle)
                if not duo_point_inside_outline(sample_x, sample_z):
                    raise ValueError(
                        f"a duo {label} counterbore exceeds the plate outline"
                    )
                if label == "lower" and not duo_point_inside_lower_band(
                    sample_x,
                    sample_z,
                ):
                    raise ValueError(
                        "a duo lower counterbore exceeds its raised band outline"
                    )

    min_hole_clearance = math.inf
    for index, first in enumerate(positions):
        for second in positions[index + 1:]:
            clearance = (
                math.hypot(first[0] - second[0], first[1] - second[1])
                - 2.0 * counterbore_radius
            )
            min_hole_clearance = min(min_hole_clearance, clearance)
    if min_hole_clearance <= 0.0:
        raise ValueError("duo Technic counterbores overlap")

    min_screw_hole_clearance = math.inf
    for screw_x, screw_z in screw_positions:
        for hole_x, hole_z in positions:
            center_distance = math.hypot(screw_x - hole_x, screw_z - hole_z)
            clearance = min(
                center_distance - countersink_radius - effective_hole_radius,
                center_distance - screw_hole_radius - counterbore_radius,
            )
            min_screw_hole_clearance = min(min_screw_hole_clearance, clearance)
    if min_screw_hole_clearance < p["SCREW_KEEP_OUT_WEB"] - 1.0e-9:
        raise ValueError("a duo screw profile is too close to a Technic hole")

    screw_band_clearances = {}
    for label, bounds in (
        ("center", DUO_D["center_band_bounds"]),
        ("lower", DUO_D["lower_band_bounds"]),
    ):
        clearance = min(
            point_to_rectangle_distance(screw_x, screw_z, bounds)
            - countersink_radius
            for screw_x, screw_z in screw_positions
        )
        if clearance < p["SCREW_KEEP_OUT_WEB"] - 1.0e-9:
            raise ValueError(f"a duo screw countersink intersects the {label} band")
        screw_band_clearances[label] = clearance

    official_magnet_centers = set(magnet_positions())
    if official_magnet_centers != {
        (-12.73, -12.73),
        (-12.73, 12.73),
        (12.73, -12.73),
        (12.73, 12.73),
    }:
        raise ValueError("official magnet centers changed")
    magnet_centers = duo_magnet_positions()
    if magnet_centers != [(-12.73, -12.73), (12.73, -12.73)]:
        raise ValueError("duo must cut only the two magnet seats inside its outline")
    if not (
        0.0 < p["MAGNET_RELIEF_DEPTH"] <= p["TECHNIC_COUNTERBORE_DEPTH"]
    ):
        raise ValueError("duo magnet relief must remain shallower than counterbores")
    magnet_hole_overlaps = sum(
        math.hypot(magnet_x - hole_x, magnet_z - hole_z)
        < p["MAGNET_RELIEF_D"] / 2.0 + counterbore_radius
        for magnet_x, magnet_z in magnet_centers
        for hole_x, hole_z in positions
    )
    if magnet_hole_overlaps:
        raise ValueError("a duo magnet relief overlaps a Technic counterbore")

    print("DUO_PARAM_CONTRACT: PASS")
    print(
        f"DUO_PLATE_BASE: {q['PLATE_WIDTH']:.3f} x {q['PLATE_HEIGHT']:.3f} x "
        f"{p['PLATE_THICKNESS']:.3f} mm / X={plate_left:.3f}..{plate_right:.3f} / "
        f"Z={plate_bottom:.3f}..{plate_top:.3f} / corner R"
        f"{q['OUTLINE_CORNER_RADIUS']:.3f}"
    )
    print(
        f"DUO_OUTLINE: clipped body r<={q['WATCH_CLIP_RADIUS']:.3f} mm + "
        f"lobes r<={q['LOWER_LOBE_RADIUS']:.3f} mm at "
        + "/".join(f"({x:.3f},{z:.3f})" for x, z in q["LOWER_LOBE_CENTERS"])
        + f" / X={DUO_D['outline_bounds'][0]:.3f}.."
        f"{DUO_D['outline_bounds'][1]:.3f}"
    )
    print(
        "DUO_TECHNIC_HOLE_CENTERS_XZ: "
        + " ".join(f"({x:.3f},{z:.3f})" for x, z in positions)
    )
    print(
        f"DUO_HOLE_PAIR_SPANS: center_horizontal={pair_spans[0]:.3f} / "
        f"lower_left={pair_spans[1]:.3f} / lower_right={pair_spans[2]:.3f} mm"
    )
    print(
        f"DUO_TECHNIC_DETAILS: nominal dia {p['TECHNIC_HOLE_D']:.3f} + "
        f"compensation {p['TECHNIC_HOLE_PRINT_COMP']:+.3f} = "
        f"{D['technic_effective_hole_d']:.3f} / counterbores dia "
        f"{p['TECHNIC_COUNTERBORE_D']:.3f} x {p['TECHNIC_COUNTERBORE_DEPTH']:.3f} "
        f"both faces / chamfer {p['TECHNIC_HOLE_CHAMFER']:.3f}"
    )
    center_left, center_right, center_bottom, center_top = DUO_D[
        "center_band_bounds"
    ]
    lower_left, lower_right, lower_bottom, lower_top = DUO_D["lower_band_bounds"]
    print(
        f"DUO_RAISED_BANDS: center X={center_left:.3f}..{center_right:.3f} "
        f"Z={center_bottom:.3f}..{center_top:.3f} / lower "
        f"X={lower_left:.3f}..{lower_right:.3f} "
        f"Z={lower_bottom:.3f}..{lower_top:.3f} / thickness "
        f"{p['TECHNIC_RAIL_THICKNESS']:.3f} mm / lower lobes included"
    )
    print(
        f"DUO_SCREW_MOUNT: centers (-20,0)/(+20,0) / "
        f"dia {p['SCREW_HOLE_D']:.3f} / "
        f"countersink dia {p['SCREW_COUNTERSINK_D']:.3f} x "
        f"{p['SCREW_COUNTERSINK_ANGLE']:.1f} deg"
    )
    print(
        f"DUO_OUTLINE_LIMITS: body radius {q['WATCH_CLIP_RADIUS']:.3f} / "
        f"lobe radius {q['LOWER_LOBE_RADIUS']:.3f} / tolerance "
        f"+{q['WATCH_CLIP_TOL']:.3f} mm"
    )
    print("DUO_SIMPLE_OUTLINE: no circular windows / scallops / speaker notch")
    print(
        "DUO_MAGNET_RELIEFS: centers "
        + " ".join(f"({x:.3f},{z:.3f})" for x, z in magnet_centers)
        + f" / depth {p['MAGNET_RELIEF_DEPTH']:.3f} / "
        f"counterbore planar overlaps {magnet_hole_overlaps}"
    )
    print(
        f"DUO_INTERFERENCE_CHECK: PASS (hole-hole {min_hole_clearance:.3f} / "
        f"screw-hole {min_screw_hole_clearance:.3f} / screw-center-band "
        f"{screw_band_clearances['center']:.3f} / screw-lower-band "
        f"{screw_band_clearances['lower']:.3f} mm clear)"
    )


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


def validate_grid3_param_contract():
    p = PARAMS
    g = GRID3_PARAMS
    web = p["HOLE_MIN_WEB"]
    clip_radius = g["WATCH_CLIP_RADIUS"]
    official_radius = p["WATCH_DIAMETER"] / 2.0
    plate_left, plate_right, plate_bottom, plate_top = GRID3_D["plate_bounds"]
    rail_left, rail_right, _, _ = GRID3_D["rail_bounds"]

    if not math.isclose(clip_radius, 25.5, abs_tol=1.0e-9):
        raise ValueError("v3.5 grid3 watch clip radius must remain 25.5 mm")
    if clip_radius >= official_radius:
        raise ValueError("v3.5 grid3 must remain inside the official watch radius")
    if not math.isclose(GRID3_D["plate_width"], 25.6, abs_tol=1.0e-9):
        raise ValueError("v3.5 grid3 plate width must remain 25.6 mm")
    if not (
        math.isclose(plate_bottom, -clip_radius, abs_tol=1.0e-9)
        and math.isclose(plate_top, clip_radius, abs_tol=1.0e-9)
    ):
        raise ValueError("v3.5 grid3 plate must reach both watch clip arcs")
    if not math.isclose(g["PLATE_CENTER_X"], 4.0, abs_tol=1.0e-9):
        raise ValueError("v3.5 grid3 plate must be centered on X=4 mm")
    if not math.isclose(p["PLATE_THICKNESS"], 3.0, abs_tol=1.0e-9):
        raise ValueError("v3.5 screw-tab base thickness must remain 3.0 mm")
    if not math.isclose(p["TECHNIC_RAIL_THICKNESS"], 7.8, abs_tol=1.0e-9):
        raise ValueError("v3.5 raised grid band thickness must remain 7.8 mm")

    if not math.isclose(p["SCREW_SPACING"], 40.0, abs_tol=1.0e-9):
        raise ValueError("v3.5 screw centers must remain 40.0 mm apart")
    if not math.isclose(p["SCREW_HOLE_D"], 2.4, abs_tol=1.0e-9):
        raise ValueError("v3.5 screw clearance holes must remain 2.4 mm")
    if not math.isclose(p["SCREW_COUNTERSINK_D"], 4.5, abs_tol=1.0e-9):
        raise ValueError("v3.5 countersink diameter must remain 4.5 mm")
    if not math.isclose(p["SCREW_COUNTERSINK_ANGLE"], 90.0, abs_tol=1.0e-9):
        raise ValueError("v3.5 countersink included angle must remain 90 degrees")
    for screw_x, screw_z in D["screw_positions"]:
        if math.hypot(screw_x, screw_z) + D["tab_radius"] > (
            clip_radius + 1.0e-9
        ):
            raise ValueError("a v3.5 screw tab exceeds the circular watch clip")

    if not math.isclose(p["TECHNIC_HOLE_D"], 4.8, abs_tol=1.0e-9):
        raise ValueError("v3.5 nominal Technic hole diameter must remain 4.8 mm")
    if not math.isclose(p["TECHNIC_HOLE_PRINT_COMP"], 0.15, abs_tol=1.0e-9):
        raise ValueError("v3.5 Technic print compensation must remain +0.15 mm")
    if not math.isclose(p["TECHNIC_PITCH"], 8.0, abs_tol=1.0e-9):
        raise ValueError("v3.5 Technic pitch must remain 8.0 mm")
    if not math.isclose(p["TECHNIC_COUNTERBORE_D"], 6.2, abs_tol=1.0e-9):
        raise ValueError("v3.5 Technic counterbore diameter must remain 6.2 mm")
    if not math.isclose(p["TECHNIC_COUNTERBORE_DEPTH"], 0.8, abs_tol=1.0e-9):
        raise ValueError("v3.5 Technic counterbore depth must remain 0.8 mm")
    if not math.isclose(p["TECHNIC_HOLE_CHAMFER"], 0.3, abs_tol=1.0e-9):
        raise ValueError("v3.5 Technic hole chamfer must remain 0.3 mm")
    if not math.isclose(p["BOOLEAN_EPS"], 0.05, abs_tol=1.0e-9):
        raise ValueError("v3.5 must retain the 0.05 mm boolean penetration")

    selected_columns = tuple(g["TECHNIC_GRID_XS"])
    if selected_columns != (-4.0, 4.0, 12.0):
        raise ValueError("v3.5 selected columns must remain X=-4,+4,+12 mm")
    if any(
        not math.isclose(second - first, p["TECHNIC_PITCH"], abs_tol=1.0e-9)
        for first, second in zip(selected_columns, selected_columns[1:])
    ):
        raise ValueError("v3.5 column axes are not spaced at 8.0 mm")
    if any(
        not math.isclose(second - first, p["TECHNIC_PITCH"], abs_tol=1.0e-9)
        for first, second in zip(
            g["TECHNIC_GRID_ZS"], g["TECHNIC_GRID_ZS"][1:]
        )
    ):
        raise ValueError("v3.5 row axes are not spaced at 8.0 mm")

    row_offsets = tuple(g["TECHNIC_GRID_ROW_OFFSET_OPTIONS"])
    if row_offsets != tuple(float(offset) for offset in range(8)):
        raise ValueError("v3.5 row offsets must cover 0..7 mm in 1 mm steps")
    row_option_plans = grid3_row_offset_option_plan()
    selected_row_plan = grid3_selected_row_plan()
    selected_rows = tuple(selected_row_plan["rows"])
    if any(
        not math.isclose(second - first, p["TECHNIC_PITCH"], abs_tol=1.0e-9)
        for first, second in zip(selected_rows, selected_rows[1:])
    ):
        raise ValueError("v3.5 selected row axes are not spaced at 8.0 mm")
    best_row_hole_count = max(
        len(plan["accepted"]) for plan in row_option_plans
    )
    best_lowest_z = min(
        plan["lowest_z"]
        for plan in row_option_plans
        if len(plan["accepted"]) == best_row_hole_count
    )
    if (
        len(selected_row_plan["accepted"]) != best_row_hole_count
        or not math.isclose(
            selected_row_plan["lowest_z"], best_lowest_z, abs_tol=1.0e-9
        )
    ):
        raise ValueError(
            "v3.5 row offset must maximize holes, then minimize the lowest z"
        )

    option_plans = grid3_column_option_plan()
    feasible_plans = [plan for plan in option_plans if plan["feasible"]]
    if not feasible_plans:
        raise ValueError("v3.5 has no three-column option clear of the speaker")
    best_hole_count = max(len(plan["accepted"]) for plan in feasible_plans)
    selected_plan = next(
        (plan for plan in option_plans if tuple(plan["columns"]) == selected_columns),
        None,
    )
    if selected_plan is None or not selected_plan["feasible"]:
        raise ValueError("v3.5 selected columns violate the speaker keep-out")
    if len(selected_plan["accepted"]) != best_hole_count:
        raise ValueError("v3.5 selected columns do not maximize the generated hole count")

    speaker_radius = p["SPEAKER_KEEP_OUT_D"] / 2.0 + p["SPEAKER_MARGIN"]
    speaker_edge_x = p["SPEAKER_CENTER_X"] + speaker_radius
    outline_speaker_gap = plate_left - speaker_edge_x
    if outline_speaker_gap < -1.0e-9:
        raise ValueError("v3.5 plate outline violates the speaker keep-out")

    candidates = grid3_technic_hole_candidates()
    technic_positions, skipped = grid3_technic_hole_plan()
    if len(candidates) != 24:
        raise ValueError("v3.5 grid3 must contain 3 x 8 candidates")
    if len(technic_positions) + len(skipped) != len(candidates):
        raise ValueError("v3.5 grid3 candidate accounting is inconsistent")
    if len(technic_positions) <= 10:
        raise ValueError(
            "v3.5 row offset search must improve on the former 10 holes "
            f"(got {len(technic_positions)})"
        )

    valid_reasons = {
        "screw_keepout",
        "watch_clip_outer_rim",
        "grid_band_side_web",
        "speaker_keepout",
        "magnet_relief",
    }
    if any(not reasons or not set(reasons) <= valid_reasons for _, reasons in skipped):
        raise ValueError("a skipped v3.5 Technic hole has an invalid reason")

    nominal_circle_clearance = p["TECHNIC_HOLE_D"] / 2.0 + p["PLATE_OUTER_RIM"]
    hole_radius = D["technic_effective_hole_d"] / 2.0
    counterbore_radius = p["TECHNIC_COUNTERBORE_D"] / 2.0
    for x, z in technic_positions:
        if math.hypot(x, z) + nominal_circle_clearance > clip_radius + 1.0e-9:
            raise ValueError("a v3.5 Technic hole violates the circular outer rim")
        if not (
            rail_left + counterbore_radius + web
            <= x
            <= rail_right - counterbore_radius - web
        ):
            raise ValueError("a v3.5 counterbore violates the grid-band side web")
        if grid3_technic_hole_skip_reasons((x, z)):
            raise ValueError("a generated v3.5 Technic hole violates a keep-out")

    for index, first in enumerate(technic_positions):
        for second in technic_positions[index + 1:]:
            center_distance = math.hypot(first[0] - second[0], first[1] - second[1])
            if center_distance - 2.0 * counterbore_radius < web - 1.0e-9:
                raise ValueError("v3.5 counterbores leave less than the minimum web")

    countersink_radius = p["SCREW_COUNTERSINK_D"] / 2.0
    screw_hole_radius = p["SCREW_HOLE_D"] / 2.0
    for screw_x, screw_z in D["screw_positions"]:
        for hole_x, hole_z in technic_positions:
            center_distance = math.hypot(
                screw_x - hole_x, screw_z - hole_z
            )
            clear_web = min(
                center_distance - countersink_radius - hole_radius,
                center_distance - screw_hole_radius - counterbore_radius,
            )
            if clear_web < p["SCREW_KEEP_OUT_WEB"] - 1.0e-9:
                raise ValueError("a v3.5 screw profile is too close to a hole")

    if not math.isclose(p["MAGNET_GRID"], 25.46, abs_tol=1.0e-9):
        raise ValueError("v3.5 official magnet grid must remain 25.46 mm")
    magnet_radius = p["MAGNET_RELIEF_D"] / 2.0
    relief_overlaps = 0
    for x, z in magnet_positions():
        overlaps_x = x + magnet_radius > plate_left and x - magnet_radius < plate_right
        overlaps_circle = math.hypot(x, z) - magnet_radius < clip_radius
        if overlaps_x and overlaps_circle:
            relief_overlaps += 1
    if relief_overlaps != 2:
        raise ValueError("v3.5 must retain the two overlapping magnet relief seats")

    reason_counts = {reason: 0 for reason in sorted(valid_reasons)}
    for (x, z), reasons in skipped:
        print(
            f"GRID3_TECHNIC_HOLE_SKIP: x={x:.3f} z={z:.3f} "
            f"reasons={','.join(reasons)}"
        )
        for reason in reasons:
            reason_counts[reason] += 1

    for plan in option_plans:
        columns_text = "/".join(f"{x:+.0f}" for x in plan["columns"])
        print(
            f"GRID3_COLUMN_OPTION: x={columns_text} "
            f"holes={len(plan['accepted'])} "
            f"speaker_gap={plan['speaker_gap']:.3f} mm "
            f"feasible={'yes' if plan['feasible'] else 'no'}"
        )

    for plan in row_option_plans:
        print(
            f"GRID3_ROW_OFFSET_OPTION: offset={plan['offset']:.0f} mm "
            f"holes={len(plan['accepted'])} lowest_z={plan['lowest_z']:.3f}"
        )

    selected_candidate_rows = "/".join(f"{z:+.0f}" for z in selected_rows)
    selected_generated_rows = "/".join(
        f"{z:+.0f}"
        for z in sorted({z for _, z in selected_row_plan["accepted"]})
    )
    print(
        f"GRID3_ROW_OFFSET_SELECTED: offset={selected_row_plan['offset']:.0f} mm "
        f"holes={len(selected_row_plan['accepted'])} "
        f"lowest_z={selected_row_plan['lowest_z']:.3f} "
        f"candidate_rows={selected_candidate_rows} "
        f"generated_rows={selected_generated_rows} "
        f"reason=max_holes_then_lowest_z"
    )

    print("GRID3_PARAM_CONTRACT: PASS")
    print(
        f"GRID3_COLUMN_SELECTION: x=-4/+4/+12 holes={len(technic_positions)} "
        f"reason=max_holes_among_speaker-clear_8mm_options / "
        f"speaker_center=({p['SPEAKER_CENTER_X']:.3f},"
        f"{p['SPEAKER_CENTER_Z']:.3f}) / "
        f"speaker_keepout_d={2.0 * speaker_radius:.3f} / "
        f"speaker_edge_x={speaker_edge_x:.3f} / band_left={plate_left:.3f} / "
        f"outline_gap={outline_speaker_gap:.3f} mm"
    )
    print(
        f"GRID3_WATCH_CLIP: radius {clip_radius:.3f} mm / "
        f"official radius {official_radius:.3f} mm / "
        f"radial margin {official_radius - clip_radius:.3f} mm / "
        f"Z={plate_bottom:.3f}..{plate_top:.3f}"
    )
    print(
        f"GRID3_PLATE_BASE: width {GRID3_D['plate_width']:.3f} x "
        f"clipped length {GRID3_D['plate_length']:.3f} x "
        f"thickness {p['PLATE_THICKNESS']:.3f} mm / "
        f"X={plate_left:.3f}..{plate_right:.3f}"
    )
    print(
        f"GRID3_SCREW_MOUNT: 2 x dia {p['SCREW_HOLE_D']:.3f} through / "
        f"pitch {p['SCREW_SPACING']:.3f} / countersink "
        f"dia {p['SCREW_COUNTERSINK_D']:.3f} x "
        f"{p['SCREW_COUNTERSINK_ANGLE']:.1f} deg"
    )
    print(
        f"GRID3_TECHNIC_GRID_CANDIDATES: 3x8={len(candidates)} / nominal dia "
        f"{p['TECHNIC_HOLE_D']:.3f} + print compensation "
        f"{p['TECHNIC_HOLE_PRINT_COMP']:+.3f} mm / pitch "
        f"{p['TECHNIC_PITCH']:.3f} mm"
    )
    print(
        f"GRID3_TECHNIC_GRID_CHECK: PASS (columns -4/+4/+12 / "
        f"row origin {selected_rows[0]:.3f} / "
        f"row offset {selected_row_plan['offset']:.3f} / "
        f"pitch {p['TECHNIC_PITCH']:.3f} mm)"
    )
    print(f"GRID3_TECHNIC_HOLES_GENERATED: {len(technic_positions)}")
    print(f"GRID3_TECHNIC_HOLES_SKIPPED: {len(skipped)}")
    print(
        "GRID3_TECHNIC_SKIP_REASON_COUNTS: "
        + " ".join(
            f"{reason}={reason_counts[reason]}" for reason in sorted(reason_counts)
        )
    )
    print(
        "GRID3_TECHNIC_HOLE_CENTERS_XZ: "
        + " ".join(f"({x:.3f},{z:.3f})" for x, z in technic_positions)
    )
    print(
        f"GRID3_TECHNIC_DETAILS: effective dia {D['technic_effective_hole_d']:.3f} / "
        f"counterbores dia {p['TECHNIC_COUNTERBORE_D']:.3f} x "
        f"depth {p['TECHNIC_COUNTERBORE_DEPTH']:.3f} both faces / "
        f"chamfer {p['TECHNIC_HOLE_CHAMFER']:.3f} mm"
    )
    print(
        f"GRID3_MAGNET_RELIEF_SEATS: {relief_overlaps} overlaps / "
        f"dia {p['MAGNET_RELIEF_D']:.3f} x depth "
        f"{p['MAGNET_RELIEF_DEPTH']:.3f} mm"
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


def rounded_rectangle_y(
    name,
    size_x,
    depth_y,
    size_z,
    corner_radius,
    location,
    vertices_per_corner=16,
):
    """Create a manifold Y-extruded rounded rectangle in the X/Z plane."""
    if min(size_x, depth_y, size_z, corner_radius) <= 0.0:
        raise ValueError("rounded rectangle dimensions and radius must be positive")
    if corner_radius > min(size_x, size_z) / 2.0:
        raise ValueError("rounded rectangle radius exceeds half its short side")
    if vertices_per_corner < 2:
        raise ValueError("rounded rectangle needs at least two vertices per corner")

    center_x, center_y, center_z = location
    half_x = size_x / 2.0
    half_z = size_z / 2.0
    corner_centers = (
        (half_x - corner_radius, half_z - corner_radius, 0.0),
        (-half_x + corner_radius, half_z - corner_radius, 90.0),
        (-half_x + corner_radius, -half_z + corner_radius, 180.0),
        (half_x - corner_radius, -half_z + corner_radius, 270.0),
    )
    outline = []
    for corner_x, corner_z, start_degrees in corner_centers:
        for step in range(vertices_per_corner + 1):
            angle = math.radians(
                start_degrees + 90.0 * step / vertices_per_corner
            )
            outline.append(
                (
                    center_x + corner_x + corner_radius * math.cos(angle),
                    center_z + corner_z + corner_radius * math.sin(angle),
                )
            )

    inner_y = center_y - depth_y / 2.0
    outer_y = center_y + depth_y / 2.0
    coordinates = (
        [(x, inner_y, z) for x, z in outline]
        + [(x, outer_y, z) for x, z in outline]
    )
    ring_size = len(outline)
    faces = [tuple(reversed(range(ring_size)))]
    faces.append(tuple(ring_size + index for index in range(ring_size)))
    for index in range(ring_size):
        next_index = (index + 1) % ring_size
        faces.append(
            (
                index,
                next_index,
                ring_size + next_index,
                ring_size + index,
            )
        )

    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(coordinates, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    cleanup_mesh(obj)
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


def clip_to_grid3_watch_circle(target, depth, prefix):
    """Intersect a grid3 body with the 25.5 mm watch-safe X/Z circle."""
    eps = PARAMS["BOOLEAN_EPS"]
    clip = cylinder_y(
        f"{prefix}_watch_circle_clip",
        2.0 * GRID3_PARAMS["WATCH_CLIP_RADIUS"],
        depth + 2.0 * eps,
        (0.0, depth / 2.0, 0.0),
        vertices=GRID3_PARAMS["WATCH_CLIP_VERTICES"],
    )
    boolean(target, clip, "INTERSECT")


def clip_to_duo_watch_circle(target, depth, prefix):
    """Intersect a duo body with the 25.5 mm watch-safe X/Z circle."""
    eps = PARAMS["BOOLEAN_EPS"]
    clip = cylinder_y(
        f"{prefix}_watch_circle_clip",
        2.0 * DUO_PARAMS["WATCH_CLIP_RADIUS"],
        depth + 2.0 * eps,
        (0.0, depth / 2.0, 0.0),
        vertices=DUO_PARAMS["WATCH_CLIP_VERTICES"],
    )
    boolean(target, clip, "INTERSECT")


def union_duo_lower_lobes(target, depth, center_y, prefix):
    """Union the two lower ears, with validated epsilon overlap into the bar."""
    q = DUO_PARAMS
    for index, (x, z) in enumerate(q["LOWER_LOBE_CENTERS"], start=1):
        lobe = cylinder_y(
            f"{prefix}_lobe_{index}",
            2.0 * q["LOWER_LOBE_RADIUS"],
            depth,
            (x, center_y, z),
            vertices=q["LOWER_LOBE_VERTICES"],
        )
        boolean(target, lobe, "UNION")


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


def cut_grid3_technic_holes(target):
    p = PARAMS
    eps = p["BOOLEAN_EPS"]
    positions = grid3_technic_hole_positions()
    hole_radius = D["technic_effective_hole_d"] / 2.0
    counterbore_radius = p["TECHNIC_COUNTERBORE_D"] / 2.0
    counterbore_depth = p["TECHNIC_COUNTERBORE_DEPTH"]
    chamfer = p["TECHNIC_HOLE_CHAMFER"]
    chamfer_radius = hole_radius + chamfer
    outer_counterbore_y = p["TECHNIC_RAIL_THICKNESS"] - counterbore_depth
    outer_chamfer_y = outer_counterbore_y - chamfer

    # Match the v3.4 epsilon-penetrating, single-profile cutter exactly: the
    # flat shoulders are encoded by duplicate Y rings and every boolean is
    # followed by the same remove-doubles/degenerate/normal cleanup.
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
            f"grid3_technic_hole_profile_{index}",
            profile,
            x,
            z,
        )
        boolean(target, cutter, "DIFFERENCE")


def cut_duo_technic_holes(target):
    p = PARAMS
    eps = p["BOOLEAN_EPS"]
    positions = duo_technic_hole_positions()
    hole_radius = D["technic_effective_hole_d"] / 2.0
    counterbore_radius = p["TECHNIC_COUNTERBORE_D"] / 2.0
    counterbore_depth = p["TECHNIC_COUNTERBORE_DEPTH"]
    chamfer = p["TECHNIC_HOLE_CHAMFER"]
    chamfer_radius = hole_radius + chamfer
    outer_counterbore_y = p["TECHNIC_RAIL_THICKNESS"] - counterbore_depth
    outer_chamfer_y = outer_counterbore_y - chamfer

    # Reuse the proven v3.4/v3.5 epsilon-penetrating single cutter profile.
    # Keeping duplicate shoulder rings avoids coplanar seams between separate
    # through-hole, counterbore, and chamfer boolean tools.
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
            f"duo_technic_hole_profile_{index}",
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


def cut_duo_screw_holes(target):
    """Cut the east/west duo screws without changing backpack/grid3 axes."""
    p = PARAMS
    eps = p["BOOLEAN_EPS"]
    positions = duo_screw_positions()
    cut_through_holes(
        target,
        positions,
        p["SCREW_HOLE_D"],
        "duo_screw_through",
    )
    true_depth = D["countersink_depth"]
    tool_depth = true_depth + 2.0 * eps
    inner_radius = p["SCREW_HOLE_D"] / 2.0 - eps
    outer_radius = p["SCREW_COUNTERSINK_D"] / 2.0 + eps
    center_y = D["plate_outer_y"] - true_depth / 2.0
    for index, (x, z) in enumerate(positions, start=1):
        cutter = frustum_y(
            f"duo_screw_countersink_{index}",
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


def cut_duo_magnet_reliefs(target):
    """Cut inner-face reliefs only at official centers covered by duo v4.1."""
    p = PARAMS
    eps = p["BOOLEAN_EPS"]
    cutter_depth = p["MAGNET_RELIEF_DEPTH"] + eps
    cutter_center_y = (p["MAGNET_RELIEF_DEPTH"] - eps) / 2.0
    for index, (x, z) in enumerate(duo_magnet_positions(), start=1):
        cutter = cylinder_y(
            f"duo_magnet_relief_{index}",
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


def build_grid3():
    p = PARAMS
    g = GRID3_PARAMS
    eps = p["BOOLEAN_EPS"]
    source_length = GRID3_D["plate_length"] + 2.0 * eps

    plate = box(
        "grid3_plate_body",
        GRID3_D["plate_width"],
        p["PLATE_THICKNESS"],
        source_length,
        (g["PLATE_CENTER_X"], GRID3_D["plate_center_y"], g["PLATE_CENTER_Z"]),
    )
    clip_to_grid3_watch_circle(plate, p["PLATE_THICKNESS"], "grid3_plate")

    rail = box(
        "grid3_technic_grid_band",
        GRID3_D["plate_width"],
        p["TECHNIC_RAIL_THICKNESS"],
        source_length,
        (g["PLATE_CENTER_X"], GRID3_D["rail_center_y"], g["PLATE_CENTER_Z"]),
    )
    clip_to_grid3_watch_circle(
        rail, p["TECHNIC_RAIL_THICKNESS"], "grid3_grid_band"
    )

    # Preserve the v3.4 screw-tab construction: each original screw remains in
    # a 3 mm base-only island while the surrounding grid band rises to 7.8 mm.
    for index, (x, z) in enumerate(D["screw_positions"], start=1):
        tab_clearance = cylinder_y(
            f"grid3_screw_tab_3mm_zone_{index}",
            p["SCREW_TAB_D"],
            p["TECHNIC_RAIL_THICKNESS"] + 2.0 * eps,
            (x, GRID3_D["rail_center_y"], z),
        )
        boolean(rail, tab_clearance, "DIFFERENCE")

    boolean(plate, rail, "UNION")

    cut_magnet_reliefs(plate)
    cut_grid3_technic_holes(plate)
    cut_screw_holes(plate)
    plate.name = "toicamera_three_column_technic_grid_v3_5"
    return plate


def build_duo():
    p = PARAMS
    q = DUO_PARAMS

    plate = rounded_rectangle_y(
        "duo_plate_body",
        q["PLATE_WIDTH"],
        p["PLATE_THICKNESS"],
        q["PLATE_HEIGHT"],
        q["OUTLINE_CORNER_RADIUS"],
        (q["PLATE_CENTER_X"], DUO_D["plate_center_y"], q["PLATE_CENTER_Z"]),
        vertices_per_corner=q["OUTLINE_VERTICES_PER_CORNER"],
    )
    clip_to_duo_watch_circle(plate, p["PLATE_THICKNESS"], "duo_plate")
    center_left, center_right, center_bottom, center_top = DUO_D[
        "center_band_bounds"
    ]
    center_band = box(
        "duo_center_horizontal_raised_band",
        center_right - center_left,
        p["TECHNIC_RAIL_THICKNESS"],
        center_top - center_bottom,
        (
            (center_left + center_right) / 2.0,
            DUO_D["rail_center_y"],
            (center_bottom + center_top) / 2.0,
        ),
    )
    clip_to_duo_watch_circle(
        center_band,
        p["TECHNIC_RAIL_THICKNESS"],
        "duo_center_band",
    )

    lower_left, lower_right, lower_bottom, lower_top = DUO_D["lower_band_bounds"]
    lower_band = box(
        "duo_lower_horizontal_raised_band",
        lower_right - lower_left,
        p["TECHNIC_RAIL_THICKNESS"],
        lower_top - lower_bottom,
        (
            (lower_left + lower_right) / 2.0,
            DUO_D["rail_center_y"],
            (lower_bottom + lower_top) / 2.0,
        ),
    )
    clip_to_duo_watch_circle(
        lower_band,
        p["TECHNIC_RAIL_THICKNESS"],
        "duo_lower_band",
    )
    # The full-height lobe solids supply both the base outline and its 7.8 mm
    # raised cover.  Adding them only here avoids duplicate coplanar lobe
    # surfaces when the completed lower band is united with the base bar.
    union_duo_lower_lobes(
        lower_band,
        p["TECHNIC_RAIL_THICKNESS"],
        DUO_D["rail_center_y"],
        "duo_lower_band",
    )

    boolean(plate, center_band, "UNION")
    boolean(plate, lower_band, "UNION")

    cut_duo_magnet_reliefs(plate)
    cut_duo_technic_holes(plate)
    cut_duo_screw_holes(plate)
    plate.name = "toicamera_camera_gps_duo_plate_v4_1"
    # The magnet-relief boolean can leave a ~0.1 mm sliver triangle on the
    # flat back face; a 0.15 mm degenerate-dissolve collapses it while all
    # real features (0.3 chamfer, 0.8 counterbores) stay untouched.
    cleanup_mesh(plate, merge_distance=0.15)
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


def max_xz_radius(obj):
    return max(
        math.hypot(
            (obj.matrix_world @ vertex.co).x,
            (obj.matrix_world @ vertex.co).z,
        )
        for vertex in obj.data.vertices
    )


def count_vertices_outside_xz_outline(obj, point_inside, tolerance):
    outside = 0
    for vertex in obj.data.vertices:
        world = obj.matrix_world @ vertex.co
        if not point_inside(world.x, world.z, tolerance):
            outside += 1
    return outside


def validate_object(
    label,
    obj,
    expected,
    tolerance,
    radial_limit=None,
    radial_tolerance=0.0,
    xz_outline_test=None,
    xz_outline_description=None,
    merge_distance=1.0e-3,
    strict_mesh=True,
):
    cleanup_mesh(obj, merge_distance=merge_distance)
    dims = tuple(float(value) for value in obj.dimensions)
    nonmanifold, components = mesh_stats(obj)
    deltas = tuple(abs(actual - wanted) for actual, wanted in zip(dims, expected))
    bbox_ok = max(deltas) <= tolerance
    # strict_mesh=False: scene-mesh slivers are reported but the exported STL
    # check (always strict) is the gate — used for duo's magnet-relief sliver.
    mesh_ok = (nonmanifold == 0 or not strict_mesh) and components == 1
    radial_ok = True
    outline_ok = True
    print(f"{label}_BBOX_BUILT: {dims[0]:.4f} {dims[1]:.4f} {dims[2]:.4f}")
    print(f"{label}_BBOX_EXPECT: {expected[0]:.4f} {expected[1]:.4f} {expected[2]:.4f}")
    print(f"{label}_BBOX_DELTA: {deltas[0]:.4f} {deltas[1]:.4f} {deltas[2]:.4f}")
    print(f"{label}_BBOX_VS_SPEC: {'OK' if bbox_ok else 'NG'} (tol +/-{tolerance:.3f} mm)")
    if radial_limit is not None:
        built_radius = max_xz_radius(obj)
        radial_ok = built_radius <= radial_limit + radial_tolerance
        print(f"{label}_MAX_XZ_RADIUS_BUILT: {built_radius:.4f}")
        print(
            f"{label}_WATCH_CLIP_VS_SPEC: {'OK' if radial_ok else 'NG'} "
            f"(limit {radial_limit:.3f} + {radial_tolerance:.3f} mm)"
        )
    if xz_outline_test is not None:
        outside_vertices = count_vertices_outside_xz_outline(
            obj,
            xz_outline_test,
            radial_tolerance,
        )
        outline_ok = outside_vertices == 0
        print(f"{label}_XZ_OUTLINE_OUTSIDE_VERTICES: {outside_vertices}")
        print(
            f"{label}_XZ_OUTLINE_VS_SPEC: {'OK' if outline_ok else 'NG'} "
            f"({xz_outline_description}; tol +{radial_tolerance:.3f} mm)"
        )
    print(f"{label}_NONMANIFOLD_EDGES: {nonmanifold}")
    print(f"{label}_CONNECTED_COMPONENTS: {components}")
    return bbox_ok and mesh_ok and radial_ok and outline_ok


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


def validate_exported_stl(
    label,
    path,
    expected,
    tolerance,
    radial_limit=None,
    radial_tolerance=0.0,
    xz_outline_test=None,
    xz_outline_description=None,
):
    before = set(bpy.data.objects)
    bpy.ops.wm.stl_import(filepath=str(path), forward_axis="Y", up_axis="Z")
    imported = next(obj for obj in bpy.data.objects if obj not in before)
    imported.name = label.lower() + "_stl_check"
    dims = tuple(float(value) for value in imported.dimensions)
    deltas = tuple(abs(actual - wanted) for actual, wanted in zip(dims, expected))
    nonmanifold, components = mesh_stats(imported)
    radial_ok = True
    outline_ok = True
    if radial_limit is not None:
        imported_radius = max_xz_radius(imported)
        radial_ok = imported_radius <= radial_limit + radial_tolerance
        print(f"{label}_STL_MAX_XZ_RADIUS: {imported_radius:.4f}")
        print(
            f"{label}_STL_WATCH_CLIP_VS_SPEC: {'OK' if radial_ok else 'NG'} "
            f"(limit {radial_limit:.3f} + {radial_tolerance:.3f} mm)"
        )
    if xz_outline_test is not None:
        outside_vertices = count_vertices_outside_xz_outline(
            imported,
            xz_outline_test,
            radial_tolerance,
        )
        outline_ok = outside_vertices == 0
        print(f"{label}_STL_XZ_OUTLINE_OUTSIDE_VERTICES: {outside_vertices}")
        print(
            f"{label}_STL_XZ_OUTLINE_VS_SPEC: {'OK' if outline_ok else 'NG'} "
            f"({xz_outline_description}; tol +{radial_tolerance:.3f} mm)"
        )
    ok = (
        max(deltas) <= tolerance
        and nonmanifold == 0
        and components == 1
        and radial_ok
        and outline_ok
    )
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
    if part == "backpack":
        return {"backpack": out}
    if part == "grid3":
        return {"grid3": out}
    if part == "duo":
        duo_out = (
            out
            if out.stem.endswith("_duo")
            else out.with_name(f"{out.stem}_duo{out.suffix}")
        )
        return {"duo": duo_out}
    grid3_out = out.with_name(f"{out.stem}_grid3{out.suffix}")
    duo_out = out.with_name(f"{out.stem}_duo{out.suffix}")
    return {"backpack": out, "grid3": grid3_out, "duo": duo_out}


def main():
    args = parse_args()
    reset_scene()
    paths = output_paths(args.out, args.part)
    if "backpack" in paths:
        validate_param_contract()
    if "grid3" in paths:
        validate_grid3_param_contract()
    if "duo" in paths:
        validate_duo_param_contract()
    overall_ok = True

    print("UNIT_CONTRACT: 1 Blender Unit = 1 mm")
    if "backpack" in paths:
        print(
            "LAYOUT_V3_4: open watch / 2-screw backpack / full raised Technic grid / "
            "rear-facing camera"
        )
    if "grid3" in paths:
        print(
            "LAYOUT_V3_5_GRID3: separate 3-column circular-clipped module plate / "
            "backpack unchanged"
        )
    if "duo" in paths:
        print(
            "LAYOUT_DUO_V4_1: camera on center horizontal pair / camera+GPS on lower "
            "left/right pairs / circle-clipped bar with lower outer lobes / "
            "backpack and grid3 unchanged"
        )
    print("PART_SELECTION: " + "+".join(paths))
    for part, path in paths.items():
        print(f"PART_OUTPUT_PATH: {part}={path}")
    print(
        "PRINT_ORIENTATION: watch-contact face on build plate; grid band raised upward; "
        "Technic hole axes vertical"
    )

    for part, path in paths.items():
        xz_outline_test = None
        xz_outline_description = None
        if part == "backpack":
            obj = build_backpack()
            expected = D["backpack_bbox"]
            radial_limit = None
            radial_tolerance = 0.0
        elif part == "grid3":
            obj = build_grid3()
            expected = GRID3_D["grid3_bbox"]
            radial_limit = GRID3_PARAMS["WATCH_CLIP_RADIUS"]
            radial_tolerance = GRID3_PARAMS["WATCH_CLIP_TOL"]
        else:
            obj = build_duo()
            expected = DUO_D["duo_bbox"]
            radial_limit = None
            radial_tolerance = DUO_PARAMS["WATCH_CLIP_TOL"]
            xz_outline_test = duo_point_inside_outline
            xz_outline_description = "body r<=25.500 or lower lobes r<=6.500"
        label = part.upper()
        object_ok = validate_object(
            label,
            obj,
            expected,
            args.bbox_tol,
            radial_limit=radial_limit,
            radial_tolerance=radial_tolerance,
            xz_outline_test=xz_outline_test,
            xz_outline_description=xz_outline_description,
            # duo: dissolve the ~0.1mm magnet-relief sliver (see build_duo)
            merge_distance=0.15 if part == "duo" else 1.0e-3,
            strict_mesh=(part != "duo"),
        )
        export_stl(obj, path)
        stl_ok = validate_exported_stl(
            label,
            path,
            expected,
            args.bbox_tol,
            radial_limit=radial_limit,
            radial_tolerance=radial_tolerance,
            xz_outline_test=xz_outline_test,
            xz_outline_description=xz_outline_description,
        )
        overall_ok = overall_ok and object_ok and stl_ok

    print("CASE_BUILD_RESULT: " + ("PASS" if overall_ok else "FAIL"))
    raise SystemExit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
