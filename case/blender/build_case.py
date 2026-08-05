#!/usr/bin/env python3
"""Build the ToiCamera v3 open backpack plate and fit-check coupon.

The printed part never surrounds the StopWatch.  Two rear-facing U channels
slide over the outside of the upper and lower female-header housings; no FDM
pins enter the 2.54 mm sockets.  A commercial M5Stack CLIP-A/B connects the
CamS3 to the Technic-compatible holes in the plate.

Headless usage::

  /Applications/Blender.app/Contents/MacOS/Blender -b \
    --python case/blender/build_case.py -- \
    --part backpack --out case/blender/out/toicamera_backpack.stl

Unit contract: 1 Blender Unit = 1 mm.  Rear-view coordinates are X=left/right,
Y=outward from the watch back, and Z=up/down.  The plate's outer face is +Y.
"""

import argparse
import math
from pathlib import Path
import sys

import bmesh
import bpy


# All measurements and fit-test adjustments are centralized here.  Values for
# the photographed header housings are estimates until checked with calipers.
PARAMS = {
    "BBOX_TOL": 0.3,
    "BOOLEAN_EPS": 0.15,
    "FILLET_SEGMENTS": 6,

    # StopWatch rear geometry (rear-view X/Z plane).
    "WATCH_REAR_RADIUS": 25.7,
    "SPEAKER_CENTER_X": -17.5,
    "SPEAKER_CENTER_Z": 0.0,
    "SPEAKER_KEEP_OUT_D": 16.0,
    "SPEAKER_MARGIN": 0.3,
    "SCREW_CENTER_X": 0.0,
    "SCREW_CENTER_Z": 23.7,
    "SCREW_HEAD_D": 4.4,
    "SCREW_ACCESS_MARGIN": 1.0,

    # ADJUST AFTER COUPON: photographed black female-header housings.
    "HEADER_LENGTH": 18.0,
    "HEADER_WIDTH": 2.5,
    "HEADER_DEPTH": 8.5,
    "HEADER_FIT_TOL": 0.2,
    "HEADER_CENTER_X": 0.0,
    "HEADER_ROW_SPACING": 30.0,
    "CLAMP_WALL": 1.2,
    "CLAMP_END_WALL": 0.9,

    # One open plate, biased right so the rear-left speaker stays uncovered.
    "PLATE_WIDTH": 30.4,
    "PLATE_HEIGHT": 40.0,
    "PLATE_THICKNESS": 3.0,
    "PLATE_CENTER_X": 6.0,
    "PLATE_CENTER_Z": 0.0,

    # LEGO Technic-compatible through holes.  The main mount is 2 x 2; the
    # separate upper 1 x 2 row is reserved for a later GPS bracket.
    "TECHNIC_HOLE_D": 4.8,
    "TECHNIC_PITCH": 8.0,
    "TECHNIC_CENTER_X": 6.0,
    "TECHNIC_MAIN_CENTER_Z": -4.0,
    "GPS_HOLE_CENTER_Z": 9.3,
    "HOLE_MIN_WEB": 0.6,

    # Small first-print piece: one copy of the same U-channel fit geometry.
    "COUPON_WIDTH": 20.0,
    "COUPON_HEIGHT": 10.0,
    "COUPON_FILLET": 1.0,
}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Build the ToiCamera v3 open backpack plate")
    parser.add_argument("--out", required=True, help="output STL path")
    parser.add_argument(
        "--part",
        choices=("backpack", "coupon", "all"),
        default="backpack",
        help="part to export (default: backpack)",
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
    header_cavity_length = p["HEADER_LENGTH"] + p["HEADER_FIT_TOL"]
    header_cavity_width = p["HEADER_WIDTH"] + p["HEADER_FIT_TOL"]
    header_cavity_depth = p["HEADER_DEPTH"] + p["HEADER_FIT_TOL"]
    plate_front_y = header_cavity_depth
    plate_back_y = plate_front_y + p["PLATE_THICKNESS"]
    row_offset = p["HEADER_ROW_SPACING"] / 2.0
    clamp_half_height = header_cavity_width / 2.0 + p["CLAMP_WALL"]
    clamp_outer_length = header_cavity_length + 2.0 * p["CLAMP_END_WALL"]
    return {
        "header_cavity_length": header_cavity_length,
        "header_cavity_width": header_cavity_width,
        "header_cavity_depth": header_cavity_depth,
        "plate_front_y": plate_front_y,
        "plate_back_y": plate_back_y,
        "plate_center_y": (plate_front_y + plate_back_y) / 2.0,
        "header_rows": (-row_offset, row_offset),
        "clamp_half_height": clamp_half_height,
        "clamp_outer_length": clamp_outer_length,
        "backpack_bbox": (
            max(
                p["PLATE_CENTER_X"] + p["PLATE_WIDTH"] / 2.0,
                p["HEADER_CENTER_X"] + clamp_outer_length / 2.0,
            )
            - min(
                p["PLATE_CENTER_X"] - p["PLATE_WIDTH"] / 2.0,
                p["HEADER_CENTER_X"] - clamp_outer_length / 2.0,
            ),
            plate_back_y,
            p["PLATE_HEIGHT"],
        ),
        "coupon_bbox": (
            p["COUPON_WIDTH"],
            plate_back_y,
            p["COUPON_HEIGHT"],
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


def point_to_rectangle_distance(x, z, bounds):
    min_x, max_x, min_z, max_z = bounds
    dx = max(min_x - x, 0.0, x - max_x)
    dz = max(min_z - z, 0.0, z - max_z)
    return math.hypot(dx, dz)


def validate_param_contract():
    p = PARAMS
    tol = p["HEADER_FIT_TOL"]
    if tol <= 0.0:
        raise ValueError("HEADER_FIT_TOL must be positive")
    for source, cavity in (
        ("HEADER_LENGTH", "header_cavity_length"),
        ("HEADER_WIDTH", "header_cavity_width"),
        ("HEADER_DEPTH", "header_cavity_depth"),
    ):
        if not math.isclose(D[cavity], p[source] + tol, abs_tol=1.0e-9):
            raise ValueError(f"{cavity} must equal {source} + HEADER_FIT_TOL")

    if not math.isclose(p["PLATE_THICKNESS"], 3.0, abs_tol=1.0e-9):
        raise ValueError("v3 plate thickness must remain 3.0 mm")
    if p["CLAMP_WALL"] < 1.0:
        raise ValueError("CLAMP_WALL is too thin for a reusable FDM snap channel")
    if p["CLAMP_END_WALL"] < 0.8:
        raise ValueError("CLAMP_END_WALL is too thin for repeatable length fit")
    if D["clamp_outer_length"] > p["COUPON_WIDTH"]:
        raise ValueError("coupon is narrower than the header fit channel")

    plate_left = p["PLATE_CENTER_X"] - p["PLATE_WIDTH"] / 2.0
    plate_right = p["PLATE_CENTER_X"] + p["PLATE_WIDTH"] / 2.0
    plate_bottom = p["PLATE_CENTER_Z"] - p["PLATE_HEIGHT"] / 2.0
    plate_top = p["PLATE_CENTER_Z"] + p["PLATE_HEIGHT"] / 2.0
    plate_bounds = (plate_left, plate_right, plate_bottom, plate_top)
    speaker_keepout = p["SPEAKER_KEEP_OUT_D"] / 2.0 + p["SPEAKER_MARGIN"]
    if point_to_rectangle_distance(
        p["SPEAKER_CENTER_X"], p["SPEAKER_CENTER_Z"], plate_bounds
    ) < speaker_keepout - 1.0e-9:
        raise ValueError("plate intrudes into the rear-left speaker keep-out")

    clamp_half_x = D["clamp_outer_length"] / 2.0
    for row_z in D["header_rows"]:
        clamp_bounds = (
            p["HEADER_CENTER_X"] - clamp_half_x,
            p["HEADER_CENTER_X"] + clamp_half_x,
            row_z - D["clamp_half_height"],
            row_z + D["clamp_half_height"],
        )
        if point_to_rectangle_distance(
            p["SPEAKER_CENTER_X"], p["SPEAKER_CENTER_Z"], clamp_bounds
        ) < speaker_keepout - 1.0e-9:
            raise ValueError("a header clamp intrudes into the speaker keep-out")

    screw_keepout = p["SCREW_HEAD_D"] / 2.0 + p["SCREW_ACCESS_MARGIN"]
    for screw_z in (-p["SCREW_CENTER_Z"], p["SCREW_CENTER_Z"]):
        if point_to_rectangle_distance(
            p["SCREW_CENTER_X"], screw_z, plate_bounds
        ) < screw_keepout - 1.0e-9:
            raise ValueError("plate blocks a 12/6 o'clock screw access zone")

    speaker_right = (
        p["SPEAKER_CENTER_X"] + speaker_keepout
    )

    hole_radius = p["TECHNIC_HOLE_D"] / 2.0
    for x, z in main_hole_positions() + gps_hole_positions():
        web = p["HOLE_MIN_WEB"]
        if not (plate_left + hole_radius + web <= x <= plate_right - hole_radius - web):
            raise ValueError("a Technic hole violates the plate side web")
        if not (plate_bottom + hole_radius + web <= z <= plate_top - hole_radius - web):
            raise ValueError("a Technic hole violates the plate top/bottom web")
        if math.hypot(x, z) + hole_radius + web > p["WATCH_REAR_RADIUS"]:
            raise ValueError("a Technic hole violates the circular watch-back boundary")

    upper_clamp_bottom = D["header_rows"][1] - D["clamp_half_height"]
    gps_hole_top = p["GPS_HOLE_CENTER_Z"] + hole_radius
    if upper_clamp_bottom - gps_hole_top < p["HOLE_MIN_WEB"]:
        raise ValueError("GPS holes do not leave enough web below the upper clamp")

    main = main_hole_positions()
    if not math.isclose(main[1][0] - main[0][0], p["TECHNIC_PITCH"], abs_tol=1.0e-9):
        raise ValueError("main Technic column pitch is not 8 mm")
    if not math.isclose(main[2][1] - main[0][1], p["TECHNIC_PITCH"], abs_tol=1.0e-9):
        raise ValueError("main Technic row pitch is not 8 mm")

    print("PARAM_CONTRACT: PASS")
    print(
        "HEADER_CAVITY: "
        f"{D['header_cavity_length']:.3f} x "
        f"{D['header_cavity_width']:.3f} x "
        f"{D['header_cavity_depth']:.3f} mm "
        f"(housing + {tol:.3f} mm fit tolerance)"
    )
    print(f"HEADER_ROW_CENTER_DISTANCE: {p['HEADER_ROW_SPACING']:.3f} mm")
    print(
        "SCREW_ACCESS_12_6: CLEAR "
        f"(plate +/-{plate_top:.3f} mm; screw centers +/-{p['SCREW_CENTER_Z']:.3f} mm)"
    )
    print(
        "SPEAKER_KEEP_OUT: CLEAR "
        f"(plate left {plate_left:.3f} mm; protected boundary {speaker_right:.3f} mm)"
    )
    print(
        f"TECHNIC_HOLES: dia {p['TECHNIC_HOLE_D']:.3f} mm / "
        f"pitch {p['TECHNIC_PITCH']:.3f} mm / 2x2 + GPS 1x2"
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


def rounded_box(name, size_x, size_y, size_z, radius, location):
    obj = box(name, size_x, size_y, size_z, location)
    modifier = obj.modifiers.new("edge_radius", "BEVEL")
    modifier.width = radius
    modifier.segments = PARAMS["FILLET_SEGMENTS"]
    modifier.profile = 0.5
    modifier.limit_method = "NONE"
    activate(obj)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
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


def boolean(target, tool, operation):
    modifier = target.modifiers.new(operation.lower(), "BOOLEAN")
    modifier.operation = operation
    modifier.solver = "EXACT"
    modifier.object = tool
    activate(target)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.data.objects.remove(tool, do_unlink=True)


def add_u_channel(target, center_x, center_z):
    """Union one rear-open U channel sized to the outside of a header."""
    p = PARAMS
    overlap = p["BOOLEAN_EPS"]
    arm_depth = D["header_cavity_depth"] + overlap
    arm_y = arm_depth / 2.0
    arm_offset_z = D["header_cavity_width"] / 2.0 + p["CLAMP_WALL"] / 2.0
    for sign in (-1.0, 1.0):
        arm = box(
            "header_clamp_arm",
            D["clamp_outer_length"],
            arm_depth,
            p["CLAMP_WALL"],
            (center_x, arm_y, center_z + sign * arm_offset_z),
        )
        boolean(target, arm, "UNION")

    end_wall_height = D["header_cavity_width"] + 2.0 * p["CLAMP_WALL"]
    end_wall_offset_x = D["header_cavity_length"] / 2.0 + p["CLAMP_END_WALL"] / 2.0
    for sign in (-1.0, 1.0):
        end_wall = box(
            "header_clamp_end_wall",
            p["CLAMP_END_WALL"],
            arm_depth,
            end_wall_height,
            (center_x + sign * end_wall_offset_x, arm_y, center_z),
        )
        boolean(target, end_wall, "UNION")


def cut_technic_holes(target, positions):
    p = PARAMS
    cut_depth = p["PLATE_THICKNESS"] + 2.0 * p["BOOLEAN_EPS"]
    for index, (x, z) in enumerate(positions, start=1):
        cutter = cylinder_y(
            f"technic_hole_{index}",
            p["TECHNIC_HOLE_D"],
            cut_depth,
            (x, D["plate_center_y"], z),
            vertices=64,
        )
        boolean(target, cutter, "DIFFERENCE")


def build_backpack():
    p = PARAMS
    # Intersect a circular rear envelope with the right-biased plate band.  The
    # right edge follows the watch back instead of projecting past its outline.
    plate = cylinder_y(
        "watch_back_circular_envelope",
        p["WATCH_REAR_RADIUS"] * 2.0,
        p["PLATE_THICKNESS"],
        (0.0, D["plate_center_y"], p["PLATE_CENTER_Z"]),
        vertices=128,
    )
    band = box(
        "backpack_plate_band",
        p["PLATE_WIDTH"],
        p["PLATE_THICKNESS"] + 2.0 * p["BOOLEAN_EPS"],
        p["PLATE_HEIGHT"],
        (p["PLATE_CENTER_X"], D["plate_center_y"], p["PLATE_CENTER_Z"]),
    )
    boolean(plate, band, "INTERSECT")

    for row_z in D["header_rows"]:
        add_u_channel(
            plate,
            p["HEADER_CENTER_X"],
            row_z,
        )

    cut_technic_holes(plate, main_hole_positions() + gps_hole_positions())
    plate.name = "toicamera_open_backpack_plate_v3"
    return plate


def build_coupon():
    p = PARAMS
    coupon = rounded_box(
        "fit_coupon_back_wall",
        p["COUPON_WIDTH"],
        p["PLATE_THICKNESS"],
        p["COUPON_HEIGHT"],
        p["COUPON_FILLET"],
        (p["HEADER_CENTER_X"], D["plate_center_y"], 0.0),
    )
    add_u_channel(
        coupon,
        p["HEADER_CENTER_X"],
        0.0,
    )
    coupon.name = "toicamera_header_fit_coupon_v3"
    return coupon


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
    if part != "all":
        return {part: out}
    suffix = out.suffix or ".stl"
    stem = out.stem if out.suffix else out.name
    return {
        "backpack": out.with_name(stem + "_backpack" + suffix),
        "coupon": out.with_name(stem + "_coupon" + suffix),
    }


def main():
    args = parse_args()
    reset_scene()
    validate_param_contract()
    paths = output_paths(args.out, args.part)
    expected = {
        "backpack": D["backpack_bbox"],
        "coupon": D["coupon_bbox"],
    }
    builders = {"backpack": build_backpack, "coupon": build_coupon}
    overall_ok = True

    print("UNIT_CONTRACT: 1 Blender Unit = 1 mm")
    print("LAYOUT_V3: open watch / rear header backpack / commercial CLIP-A/B / rear-facing camera")
    print("PRINT_ORIENTATION: outer plate face on build plate; Technic hole axes vertical")

    for part, path in paths.items():
        obj = builders[part]()
        label = part.upper()
        object_ok = validate_object(label, obj, expected[part], args.bbox_tol)
        export_stl(obj, path)
        stl_ok = validate_exported_stl(label, path, expected[part], args.bbox_tol)
        overall_ok = overall_ok and object_ok and stl_ok

    print("CASE_BUILD_RESULT: " + ("PASS" if overall_ok else "FAIL"))
    raise SystemExit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
