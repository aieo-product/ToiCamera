#!/usr/bin/env python3
"""Build the ToiCamera v3.2 screw-fastened backpack plate.

The plate replaces the StopWatch's two rear screws with longer screws and is
clamped directly to the existing plastic bosses.  It does not grip or enter the
flush 2.54 mm bus sockets.  A commercial M5Stack CLIP-A/B connects the CamS3
to the Technic-compatible holes in the plate.

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
    "BOOLEAN_EPS": 0.15,

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

    # Narrow central plate.  The speaker relief makes the waist locally
    # center-to-right biased while the screw tabs remain on the official axis.
    "PLATE_WIDTH": 22.0,
    "PLATE_LENGTH": 48.0,
    "PLATE_BODY_HEIGHT": 40.0,
    "PLATE_THICKNESS": 3.0,
    "PLATE_CENTER_X": 0.0,
    "PLATE_CENTER_Z": 0.0,

    # LEGO Technic-compatible through holes.  The main mount is 2 x 2; the
    # separate upper 1 x 2 row is reserved for a later GPS bracket.
    "TECHNIC_HOLE_D": 4.8,
    "TECHNIC_PITCH": 8.0,
    "TECHNIC_CENTER_X": 4.0,
    "TECHNIC_MAIN_CENTER_Z": -4.0,
    "GPS_HOLE_CENTER_Z": 9.3,
    "HOLE_MIN_WEB": 0.6,

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
        description="Build the ToiCamera v3.2 screw-fastened backpack plate"
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
        "countersink_depth": countersink_depth,
        "backpack_bbox": (
            p["PLATE_WIDTH"],
            p["PLATE_THICKNESS"],
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


def main_hole_positions():
    p = PARAMS
    half_pitch = p["TECHNIC_PITCH"] / 2.0
    return [
        (p["TECHNIC_CENTER_X"] + dx, p["TECHNIC_MAIN_CENTER_Z"] + dz)
        for dz in (-half_pitch, half_pitch)
        for dx in (-half_pitch, half_pitch)
    ]


def gps_hole_positions():
    p = PARAMS
    half_pitch = p["TECHNIC_PITCH"] / 2.0
    return [
        (p["TECHNIC_CENTER_X"] - half_pitch, p["GPS_HOLE_CENTER_Z"]),
        (p["TECHNIC_CENTER_X"] + half_pitch, p["GPS_HOLE_CENTER_Z"]),
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


def validate_param_contract():
    p = PARAMS
    web = p["HOLE_MIN_WEB"]
    half_width = p["PLATE_WIDTH"] / 2.0
    half_body = p["PLATE_BODY_HEIGHT"] / 2.0
    plate_left = p["PLATE_CENTER_X"] - half_width
    plate_right = p["PLATE_CENTER_X"] + half_width
    plate_bottom = p["PLATE_CENTER_Z"] - half_body
    plate_top = p["PLATE_CENTER_Z"] + half_body
    body_bounds = (plate_left, plate_right, plate_bottom, plate_top)

    if not math.isclose(p["WATCH_DIAMETER"], 51.95, abs_tol=1.0e-9):
        raise ValueError("official StopWatch diameter must remain 51.95 mm")
    if not math.isclose(p["WATCH_THICKNESS"], 15.5, abs_tol=1.0e-9):
        raise ValueError("official StopWatch thickness must remain 15.5 mm")
    if not math.isclose(p["PLATE_WIDTH"], 22.0, abs_tol=1.0e-9):
        raise ValueError("v3.2 plate width must remain 22.0 mm")
    if not math.isclose(p["PLATE_LENGTH"], 48.0, abs_tol=1.0e-9):
        raise ValueError("v3.2 plate length must remain 48.0 mm")
    if not math.isclose(p["PLATE_THICKNESS"], 3.0, abs_tol=1.0e-9):
        raise ValueError("v3.2 plate thickness must remain 3.0 mm")
    expected_length = p["PLATE_BODY_HEIGHT"] + p["SCREW_TAB_D"]
    if not math.isclose(p["PLATE_LENGTH"], expected_length, abs_tol=1.0e-9):
        raise ValueError("body height plus two tab radii must equal plate length")

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

    for x, z in (
        (plate_left, plate_bottom),
        (plate_left, plate_top),
        (plate_right, plate_bottom),
        (plate_right, plate_top),
    ):
        if math.hypot(x, z) > D["watch_radius"] + 1.0e-9:
            raise ValueError("plate body corner exceeds the circular watch back")
    for x, z in D["screw_positions"]:
        if math.hypot(x, z) + D["tab_radius"] > D["watch_radius"] + 1.0e-9:
            raise ValueError("a rounded screw tab exceeds the circular watch back")

    speaker_keepout = p["SPEAKER_KEEP_OUT_D"] / 2.0 + p["SPEAKER_MARGIN"]
    if D["speaker_relief_d"] / 2.0 < speaker_keepout:
        raise ValueError("speaker relief does not preserve the configured keep-out")
    if point_to_rectangle_distance(
        p["SPEAKER_CENTER_X"], p["SPEAKER_CENTER_Z"], body_bounds
    ) >= speaker_keepout:
        raise ValueError("speaker relief no longer intersects the plate waist")

    hole_radius = p["TECHNIC_HOLE_D"] / 2.0
    technic_positions = main_hole_positions() + gps_hole_positions()
    for x, z in technic_positions:
        if not (plate_left + hole_radius + web <= x <= plate_right - hole_radius - web):
            raise ValueError("a Technic hole violates the plate side web")
        if not (plate_bottom + hole_radius + web <= z <= plate_top - hole_radius - web):
            raise ValueError("a Technic hole violates the plate body end web")
        if math.hypot(x, z) + hole_radius + web > D["watch_radius"]:
            raise ValueError("a Technic hole violates the circular watch boundary")

    for index, first in enumerate(technic_positions):
        for second in technic_positions[index + 1:]:
            center_distance = math.hypot(first[0] - second[0], first[1] - second[1])
            if center_distance - 2.0 * hole_radius < web - 1.0e-9:
                raise ValueError("Technic holes leave less than the minimum web")
    countersink_radius = p["SCREW_COUNTERSINK_D"] / 2.0
    for screw_x, screw_z in D["screw_positions"]:
        for hole_x, hole_z in technic_positions:
            clear_web = (
                math.hypot(screw_x - hole_x, screw_z - hole_z)
                - countersink_radius
                - hole_radius
            )
            if clear_web < web - 1.0e-9:
                raise ValueError("a screw countersink is too close to a Technic hole")

    main = main_hole_positions()
    if not math.isclose(main[1][0] - main[0][0], p["TECHNIC_PITCH"], abs_tol=1.0e-9):
        raise ValueError("main Technic column pitch is not 8 mm")
    if not math.isclose(main[2][1] - main[0][1], p["TECHNIC_PITCH"], abs_tol=1.0e-9):
        raise ValueError("main Technic row pitch is not 8 mm")

    if not math.isclose(p["MAGNET_GRID"], 25.46, abs_tol=1.0e-9):
        raise ValueError("official magnet grid must remain 25.46 mm")
    if p["MAGNET_RELIEF_DEPTH"] >= p["PLATE_THICKNESS"]:
        raise ValueError("magnet relief must remain a shallow inner-face recess")
    magnet_radius = p["MAGNET_RELIEF_D"] / 2.0
    for x, z in magnet_positions():
        overlaps_x = x + magnet_radius > plate_left and x - magnet_radius < plate_right
        overlaps_z = z + magnet_radius > plate_bottom and z - magnet_radius < plate_top
        if not (overlaps_x and overlaps_z):
            raise ValueError("an official magnet position no longer overlaps the plate")

    print("PARAM_CONTRACT: PASS")
    print(
        f"OFFICIAL_WATCH: dia {p['WATCH_DIAMETER']:.3f} x "
        f"thickness {p['WATCH_THICKNESS']:.3f} mm"
    )
    print(
        f"PLATE_ENVELOPE: {p['PLATE_WIDTH']:.3f} x "
        f"{p['PLATE_LENGTH']:.3f} x {p['PLATE_THICKNESS']:.3f} mm / "
        "inside watch circle"
    )
    print(
        f"SCREW_MOUNT: 2 x dia {p['SCREW_HOLE_D']:.3f} through / "
        f"pitch {p['SCREW_SPACING']:.3f} / countersink "
        f"dia {p['SCREW_COUNTERSINK_D']:.3f} x "
        f"{p['SCREW_COUNTERSINK_ANGLE']:.1f} deg / "
        f"tab web {screw_web:.3f} mm"
    )
    print(
        f"SPEAKER_KEEP_OUT: CLEAR (relief dia {D['speaker_relief_d']:.3f} mm)"
    )
    print(
        f"TECHNIC_HOLES: dia {p['TECHNIC_HOLE_D']:.3f} mm / "
        f"pitch {p['TECHNIC_PITCH']:.3f} mm / 2x2 + GPS 1x2 / "
        f"minimum web {web:.3f} mm"
    )
    print(
        f"MAGNET_RELIEF_SEATS: 4 positions on {p['MAGNET_GRID']:.3f} mm grid / "
        f"dia {p['MAGNET_RELIEF_D']:.3f} x depth {p['MAGNET_RELIEF_DEPTH']:.3f} mm"
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


def boolean(target, tool, operation):
    modifier = target.modifiers.new(operation.lower(), "BOOLEAN")
    modifier.operation = operation
    modifier.solver = "EXACT"
    modifier.object = tool
    activate(target)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.data.objects.remove(tool, do_unlink=True)


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

    for index, (x, z) in enumerate(D["screw_positions"], start=1):
        tab = cylinder_y(
            f"rounded_screw_tab_{index}",
            p["SCREW_TAB_D"],
            p["PLATE_THICKNESS"] + 2.0 * eps,
            (x, D["plate_center_y"], z),
        )
        boolean(plate, tab, "UNION")

    # The union tools overlap the front/back faces by BOOLEAN_EPS for robust
    # booleans.  Trim that overlap so the printable thickness stays exactly 3 mm.
    thickness_trim = box(
        "plate_thickness_trim",
        p["WATCH_DIAMETER"] + 2.0,
        p["PLATE_THICKNESS"],
        p["WATCH_DIAMETER"] + 2.0,
        (0.0, D["plate_center_y"], 0.0),
    )
    boolean(plate, thickness_trim, "INTERSECT")

    speaker_relief = cylinder_y(
        "speaker_keepout_relief",
        D["speaker_relief_d"],
        p["PLATE_THICKNESS"] + 2.0 * eps,
        (p["SPEAKER_CENTER_X"], D["plate_center_y"], p["SPEAKER_CENTER_Z"]),
        vertices=96,
    )
    boolean(plate, speaker_relief, "DIFFERENCE")

    cut_magnet_reliefs(plate)
    cut_through_holes(
        plate,
        main_hole_positions() + gps_hole_positions(),
        p["TECHNIC_HOLE_D"],
        "technic_hole",
    )
    cut_screw_holes(plate)
    plate.name = "toicamera_screw_fastened_backpack_plate_v3_2"
    return plate


def cleanup_mesh(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1.0e-5)
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
    cleanup_mesh(obj)
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
    print("LAYOUT_V3_2: open watch / 2-screw backpack / commercial CLIP-A/B / rear-facing camera")
    print("PART_ALIAS: all -> backpack")
    print("PRINT_ORIENTATION: inner watch-contact face on build plate; countersinks upward")

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
