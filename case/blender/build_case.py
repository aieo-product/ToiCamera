#!/usr/bin/env python3
"""Build the two-piece ToiCamera enclosure and export printable STL files.

Headless usage:
  /Applications/Blender.app/Contents/MacOS/Blender -b \
    --python case/blender/build_case.py -- \
    --out case/blender/out/toicamera_case.stl [--part shell|lid|all]

Unit contract: 1 Blender Unit = 1 mm.  STL export deliberately uses
``use_scene_unit=False`` and ``global_scale=1.0`` so the numeric mesh values are
written as millimetres without an implicit metre conversion.
"""

import argparse
import math
from pathlib import Path
import sys

import bmesh
import bpy


# All design dimensions live here.  Change PARAMS, then regenerate; never edit
# the generated STL.  TOL is the per-side assembly clearance (0.2 mm gives the
# specified +0.4 mm cavity dimensions).
#
# The exact StopWatch port/button angles and the CamS3 lens/microSD positions
# were not available in the source measurements.  The values explicitly marked
# ADJUST AFTER FIT TEST are therefore first-print defaults, not asserted facts.
PARAMS = {
    "TOL": 0.2,
    "BBOX_TOL": 0.3,
    "BOOLEAN_EPS": 0.25,
    "WALL": 2.0,
    "FILLET": 2.0,
    "FILLET_SEGMENTS": 8,
    "LID_THICKNESS": 1.2,  # GPS antenna-facing skin; must stay <= 1.2 mm.
    "CAM_GPS_SEPARATOR": 2.0,
    "POD_WATCH_SEPARATOR": 2.5,  # Matches the 2.5 mm side step for a 45-degree shoulder.
    "OPEN_CUTTER_OVERTRAVEL": 2.0,
    "WATCH_CAVITY_FILLET": 0.8,
    "POD_CAVITY_FILLET": 0.6,

    # Measured devices.
    "WATCH_W": 52.0,
    "WATCH_H": 52.0,
    "WATCH_D": 15.5,
    "CAM_W": 40.0,
    "CAM_H": 24.0,
    "CAM_D": 11.0,
    "GPS_W": 48.0,
    "GPS_H": 24.0,
    "GPS_D": 8.0,

    # Required finished cavities.
    "WATCH_INNER_W": 52.4,
    "WATCH_INNER_H": 52.4,
    "WATCH_INNER_D": 16.0,
    "CAM_INNER_W": 40.4,
    "CAM_INNER_H": 24.4,
    "CAM_INNER_D": 11.4,
    "GPS_INNER_W": 48.4,
    "GPS_INNER_H": 24.4,
    "GPS_INNER_D": 8.4,
    "WIRE_BAY_W": 15.0,
    "WIRE_BAY_H": 24.0,
    "WIRE_BAY_D": 8.0,
    "WIRE_DIVIDER": 2.0,

    # Front and access openings.
    "DISPLAY_OPENING_D": 48.0,
    "LENS_OPENING_D": 10.0,
    "MICROSD_SLOT_W": 12.0,
    "MICROSD_SLOT_D": 4.0,
    "DUCT_W": 8.0,
    "DUCT_D": 6.0,
    "BUTTON_WINDOW_W": 22.0,
    "BUTTON_WINDOW_H": 8.0,
    "USB_WINDOW_W": 10.0,
    "USB_WINDOW_H": 5.0,
    "GROVE_WINDOW_W": 8.0,
    "GROVE_WINDOW_H": 6.0,

    # ADJUST AFTER FIT TEST: angle is in the front X/Z plane, with 0 degrees
    # at device-right, +90 at the top, 180 at device-left, and -90 at bottom.
    # DEPTH_OFFSET shifts the window along the front/back Y axis.
    "BUTTON_ANGLE_DEG": 0.0,
    "BUTTON_DEPTH_OFFSET": -0.5,
    "USB_ANGLE_DEG": 180.0,
    "USB_DEPTH_OFFSET": -2.0,
    "GROVE_ANGLE_DEG": -90.0,
    "GROVE_DEPTH_OFFSET": 0.0,
    "PORT_RADIAL_EXTRA": 1.0,

    # ADJUST AFTER FIT TEST: offsets are from the CamS3 bay centre.
    "CAM_LENS_X_OFFSET": -12.0,
    "CAM_LENS_Z_OFFSET": 0.0,
    "MICROSD_X_OFFSET": 0.0,
    "MICROSD_Y_OFFSET": -4.0,

    # Four rear-driven M2 self-tapping screws.
    "SCREW_BOSS_D": 5.6,
    "SCREW_PILOT_D": 1.7,
    "SCREW_CLEARANCE_D": 2.4,
    "SCREW_BOSS_FRONT_OVERLAP": 0.2,
    "SCREW_PILOT_DEPTH": 4.8,
    "SCREW_X_INSET": 1.4,
    "SCREW_Z_INSET": 3.2,
}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Build the ToiCamera enclosure")
    parser.add_argument("--out", required=True, help="output STL path")
    parser.add_argument(
        "--part",
        choices=("shell", "lid", "all"),
        default="all",
        help="part to export; all adds _shell/_lid before the extension",
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
    pod_inner_w = p["CAM_INNER_W"] + p["WIRE_DIVIDER"] + p["WIRE_BAY_W"]
    pod_outer_w = pod_inner_w + 2.0 * p["WALL"]
    watch_outer_w = p["WATCH_INNER_W"] + 2.0 * p["WALL"]
    pod_outer_h = p["WALL"] + p["CAM_INNER_H"] + p["POD_WATCH_SEPARATOR"]
    total_h = (
        p["WALL"]
        + p["CAM_INNER_H"]
        + p["POD_WATCH_SEPARATOR"]
        + p["WATCH_INNER_H"]
        + p["WALL"]
    )
    total_d = (
        p["WALL"]
        + p["CAM_INNER_D"]
        + p["CAM_GPS_SEPARATOR"]
        + p["GPS_INNER_D"]
        + p["LID_THICKNESS"]
    )
    shell_d = total_d - p["LID_THICKNESS"]
    front_y = -total_d / 2.0
    shell_back_y = total_d / 2.0 - p["LID_THICKNESS"]
    inner_front_y = front_y + p["WALL"]
    cam_back_y = inner_front_y + p["CAM_INNER_D"]
    gps_front_y = cam_back_y + p["CAM_GPS_SEPARATOR"]
    watch_z0 = p["WALL"] + p["CAM_INNER_H"] + p["POD_WATCH_SEPARATOR"]
    watch_z1 = watch_z0 + p["WATCH_INNER_H"]
    pod_inner_z0 = p["WALL"]
    pod_inner_z1 = pod_inner_z0 + p["CAM_INNER_H"]
    cam_x = -pod_inner_w / 2.0 + p["CAM_INNER_W"] / 2.0
    wire_x = pod_inner_w / 2.0 - p["WIRE_BAY_W"] / 2.0
    return {
        "pod_inner_w": pod_inner_w,
        "pod_outer_w": pod_outer_w,
        "watch_outer_w": watch_outer_w,
        "pod_outer_h": pod_outer_h,
        "total_h": total_h,
        "total_d": total_d,
        "shell_d": shell_d,
        "front_y": front_y,
        "shell_back_y": shell_back_y,
        "inner_front_y": inner_front_y,
        "cam_back_y": cam_back_y,
        "gps_front_y": gps_front_y,
        "watch_z0": watch_z0,
        "watch_z1": watch_z1,
        "pod_inner_z0": pod_inner_z0,
        "pod_inner_z1": pod_inner_z1,
        "cam_x": cam_x,
        "wire_x": wire_x,
        "watch_center_z": (watch_z0 + watch_z1) / 2.0,
        "pod_center_z": (pod_inner_z0 + pod_inner_z1) / 2.0,
    }


D = derived()


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    units = bpy.context.scene.unit_settings
    units.system = "METRIC"
    units.scale_length = 0.001
    units.length_unit = "MILLIMETERS"


def validate_param_contract():
    p = PARAMS
    clearance_pairs = (
        ("WATCH_W", "WATCH_INNER_W"),
        ("WATCH_H", "WATCH_INNER_H"),
        ("CAM_W", "CAM_INNER_W"),
        ("CAM_H", "CAM_INNER_H"),
        ("CAM_D", "CAM_INNER_D"),
        ("GPS_W", "GPS_INNER_W"),
        ("GPS_H", "GPS_INNER_H"),
        ("GPS_D", "GPS_INNER_D"),
    )
    for device_key, cavity_key in clearance_pairs:
        expected = p[device_key] + 2.0 * p["TOL"]
        if not math.isclose(p[cavity_key], expected, abs_tol=1.0e-9):
            raise ValueError(f"{cavity_key} must equal {device_key} + 2*TOL")
    if p["LID_THICKNESS"] > 1.2:
        raise ValueError("LID_THICKNESS exceeds the GPS antenna skin limit")
    shoulder_run = (D["pod_outer_w"] - D["watch_outer_w"]) / 2.0
    shoulder_rise = p["POD_WATCH_SEPARATOR"]
    shoulder_angle = math.degrees(math.atan2(shoulder_rise, shoulder_run))
    if shoulder_angle < 45.0 - 1.0e-6:
        raise ValueError("pod shoulder is shallower than 45 degrees")
    print("PARAM_CONTRACT: PASS")
    print(f"POD_SHOULDER_ANGLE: {shoulder_angle:.3f} degrees from build plate")


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
    modifier = obj.modifiers.new("inside_corner_radius", "BEVEL")
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


def append_arc(points, cx, cz, radius, angle0, angle1, segments, include_first=False):
    start = 0 if include_first else 1
    for index in range(start, segments + 1):
        angle = math.radians(angle0 + (angle1 - angle0) * index / segments)
        points.append((cx + radius * math.cos(angle), cz + radius * math.sin(angle)))


def enclosure_profile():
    """XZ outline with 2 mm top/bottom fillets and a <=45 degree pod shoulder."""
    radius = PARAMS["FILLET"]
    segments = PARAMS["FILLET_SEGMENTS"]
    pod_half = D["pod_outer_w"] / 2.0
    watch_half = D["watch_outer_w"] / 2.0
    shoulder_z0 = D["pod_inner_z1"]
    shoulder_z1 = D["watch_z0"]
    top = D["total_h"]

    points = [(-pod_half + radius, 0.0), (pod_half - radius, 0.0)]
    append_arc(points, pod_half - radius, radius, radius, -90.0, 0.0, segments)
    points.extend([(pod_half, shoulder_z0), (watch_half, shoulder_z1), (watch_half, top - radius)])
    append_arc(points, watch_half - radius, top - radius, radius, 0.0, 90.0, segments)
    points.append((-watch_half + radius, top))
    append_arc(points, -watch_half + radius, top - radius, radius, 90.0, 180.0, segments)
    points.extend([(-watch_half, shoulder_z1), (-pod_half, shoulder_z0), (-pod_half, radius)])
    append_arc(points, -pod_half + radius, radius, radius, 180.0, 270.0, segments)
    return points


def extrude_xz_profile(name, points, y0, y1):
    count = len(points)
    vertices = [(x, y0, z) for x, z in points] + [(x, y1, z) for x, z in points]
    faces = [list(range(count)), list(range(2 * count - 1, count - 1, -1))]
    for index in range(count):
        nxt = (index + 1) % count
        faces.append([index, count + index, count + nxt, nxt])
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.validate(verbose=True)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def radial_watch_cutout(shell, name, angle_deg, width_y, height_tangent, depth_offset):
    angle = math.radians(angle_deg)
    radius = PARAMS["WATCH_INNER_W"] / 2.0 + PARAMS["PORT_RADIAL_EXTRA"]
    centre = (
        radius * math.cos(angle),
        depth_offset,
        D["watch_center_z"] + radius * math.sin(angle),
    )
    cutter = box(
        name,
        PARAMS["WALL"] * 4.0,
        width_y,
        height_tangent,
        centre,
    )
    cutter.rotation_euler = (0.0, -angle, 0.0)
    apply_transform(cutter)
    boolean(shell, cutter, "DIFFERENCE")


def add_screw_bosses(shell):
    p = PARAMS
    watch_back_y = D["inner_front_y"] + p["WATCH_INNER_D"]
    boss_front_y = watch_back_y - p["SCREW_BOSS_FRONT_OVERLAP"]
    boss_depth = D["shell_back_y"] - boss_front_y
    boss_y = (boss_front_y + D["shell_back_y"]) / 2.0
    screw_x = p["WATCH_INNER_W"] / 2.0 - p["SCREW_X_INSET"]
    screw_zs = (
        D["watch_z0"] + p["SCREW_Z_INSET"],
        D["watch_z1"] - p["SCREW_Z_INSET"],
    )
    for x in (-screw_x, screw_x):
        for z in screw_zs:
            boss = cylinder_y("m2_boss", p["SCREW_BOSS_D"], boss_depth, (x, boss_y, z))
            boolean(shell, boss, "UNION")
            pilot_end = D["shell_back_y"] + p["BOOLEAN_EPS"]
            pilot_start = pilot_end - p["SCREW_PILOT_DEPTH"]
            pilot = cylinder_y(
                "m2_pilot",
                p["SCREW_PILOT_D"],
                pilot_end - pilot_start,
                (x, (pilot_start + pilot_end) / 2.0, z),
            )
            boolean(shell, pilot, "DIFFERENCE")


def build_shell():
    p = PARAMS
    eps = p["BOOLEAN_EPS"]
    shell = extrude_xz_profile("toicamera_shell", enclosure_profile(), D["front_y"], D["shell_back_y"])

    # Rear-open StopWatch cradle, while retaining an exact 2 mm front skin.
    watch_depth = D["shell_back_y"] + p["OPEN_CUTTER_OVERTRAVEL"] - D["inner_front_y"]
    watch = rounded_box(
        "watch_cradle",
        p["WATCH_INNER_W"],
        watch_depth,
        p["WATCH_INNER_H"],
        p["WATCH_CAVITY_FILLET"],
        (0.0, D["inner_front_y"] + watch_depth / 2.0, D["watch_center_z"]),
    )
    boolean(shell, watch, "DIFFERENCE")

    # Front CamS3 bay (left) and an independent 15 x 24 x 8 mm wiring bay (right).
    cam_y = (D["inner_front_y"] + D["cam_back_y"]) / 2.0
    cam = rounded_box(
        "cams3_bay",
        p["CAM_INNER_W"],
        p["CAM_INNER_D"],
        p["CAM_INNER_H"],
        p["POD_CAVITY_FILLET"],
        (D["cam_x"], cam_y, D["pod_center_z"]),
    )
    boolean(shell, cam, "DIFFERENCE")

    wire_back = D["cam_back_y"]
    wire_front = wire_back - p["WIRE_BAY_D"]
    wire = rounded_box(
        "grove_y_bay",
        p["WIRE_BAY_W"],
        p["WIRE_BAY_D"],
        p["WIRE_BAY_H"],
        p["POD_CAVITY_FILLET"],
        (D["wire_x"], (wire_front + wire_back) / 2.0, D["pod_center_z"]),
    )
    boolean(shell, wire, "DIFFERENCE")

    # GPS is flat behind the camera; its antenna points toward the 1.2 mm lid.
    gps_depth = D["shell_back_y"] + p["OPEN_CUTTER_OVERTRAVEL"] - D["gps_front_y"]
    gps = rounded_box(
        "gps_bay",
        p["GPS_INNER_W"],
        gps_depth,
        p["GPS_INNER_H"],
        p["POD_CAVITY_FILLET"],
        (0.0, D["gps_front_y"] + gps_depth / 2.0, D["pod_center_z"]),
    )
    boolean(shell, gps, "DIFFERENCE")

    # Internal watch-to-pod duct (8 x 6) and a matching pass-through in the
    # Cam/GPS separator.  Both terminate inside the protected wiring bay.
    vertical_duct = box(
        "watch_grove_duct",
        p["DUCT_W"],
        p["DUCT_D"],
        p["POD_WATCH_SEPARATOR"] + 2.0 * eps,
        (
            D["wire_x"],
            (wire_front + wire_back) / 2.0,
            D["watch_z0"] - p["POD_WATCH_SEPARATOR"] / 2.0,
        ),
    )
    boolean(shell, vertical_duct, "DIFFERENCE")
    separator_duct = box(
        "gps_grove_duct",
        p["DUCT_W"],
        p["CAM_GPS_SEPARATOR"] + 2.0 * eps,
        p["DUCT_D"],
        (D["wire_x"], (D["cam_back_y"] + D["gps_front_y"]) / 2.0, D["pod_center_z"]),
    )
    boolean(shell, separator_duct, "DIFFERENCE")

    # Front display and camera apertures.
    front_hole_depth = p["WALL"] + 2.0 * eps
    display = cylinder_y(
        "display_opening",
        p["DISPLAY_OPENING_D"],
        front_hole_depth,
        (0.0, D["front_y"] + p["WALL"] / 2.0, D["watch_center_z"]),
        vertices=128,
    )
    boolean(shell, display, "DIFFERENCE")
    lens = cylinder_y(
        "lens_opening",
        p["LENS_OPENING_D"],
        front_hole_depth,
        (
            D["cam_x"] + p["CAM_LENS_X_OFFSET"],
            D["front_y"] + p["WALL"] / 2.0,
            D["pod_center_z"] + p["CAM_LENS_Z_OFFSET"],
        ),
        vertices=64,
    )
    boolean(shell, lens, "DIFFERENCE")

    # microSD access through the pod floor (position is intentionally adjustable).
    microsd = box(
        "microsd_access",
        p["MICROSD_SLOT_W"],
        p["MICROSD_SLOT_D"],
        p["WALL"] + 2.0 * eps,
        (
            D["cam_x"] + p["MICROSD_X_OFFSET"],
            cam_y + p["MICROSD_Y_OFFSET"],
            p["WALL"] / 2.0,
        ),
    )
    boolean(shell, microsd, "DIFFERENCE")

    # Parameterised StopWatch side windows (unknown production-unit angles).
    radial_watch_cutout(
        shell,
        "keya_keyb_window",
        p["BUTTON_ANGLE_DEG"],
        p["BUTTON_WINDOW_W"],
        p["BUTTON_WINDOW_H"],
        p["BUTTON_DEPTH_OFFSET"],
    )
    radial_watch_cutout(
        shell,
        "usb_c_window",
        p["USB_ANGLE_DEG"],
        p["USB_WINDOW_W"],
        p["USB_WINDOW_H"],
        p["USB_DEPTH_OFFSET"],
    )
    radial_watch_cutout(
        shell,
        "grove_lower_window",
        p["GROVE_ANGLE_DEG"],
        p["GROVE_WINDOW_W"],
        p["GROVE_WINDOW_H"],
        p["GROVE_DEPTH_OFFSET"],
    )

    add_screw_bosses(shell)
    shell.name = "toicamera_case_shell"
    return shell


def screw_positions():
    x = PARAMS["WATCH_INNER_W"] / 2.0 - PARAMS["SCREW_X_INSET"]
    zs = (
        D["watch_z0"] + PARAMS["SCREW_Z_INSET"],
        D["watch_z1"] - PARAMS["SCREW_Z_INSET"],
    )
    return [(sx, z) for sx in (-x, x) for z in zs]


def build_lid():
    p = PARAMS
    lid = extrude_xz_profile(
        "toicamera_case_lid",
        enclosure_profile(),
        D["shell_back_y"],
        D["shell_back_y"] + p["LID_THICKNESS"],
    )
    hole_depth = p["LID_THICKNESS"] + 2.0 * p["BOOLEAN_EPS"]
    for x, z in screw_positions():
        hole = cylinder_y(
            "m2_lid_clearance",
            p["SCREW_CLEARANCE_D"],
            hole_depth,
            (x, D["shell_back_y"] + p["LID_THICKNESS"] / 2.0, z),
        )
        boolean(lid, hole, "DIFFERENCE")
    return lid


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
        "shell": out.with_name(stem + "_shell" + suffix),
        "lid": out.with_name(stem + "_lid" + suffix),
    }


def main():
    args = parse_args()
    reset_scene()
    validate_param_contract()
    paths = output_paths(args.out, args.part)
    expected = {
        "shell": (D["pod_outer_w"], D["shell_d"], D["total_h"]),
        "lid": (D["pod_outer_w"], PARAMS["LID_THICKNESS"], D["total_h"]),
    }
    builders = {"shell": build_shell, "lid": build_lid}
    overall_ok = True

    print("UNIT_CONTRACT: 1 Blender Unit = 1 mm")
    print(f"GPS_ANTENNA_SKIN: {PARAMS['LID_THICKNESS']:.3f} mm (limit <= 1.200 mm)")
    print(
        "LAYOUT: front wall {:.1f} + camera {:.1f} + separator {:.1f} + GPS {:.1f} + lid {:.1f} = {:.1f} mm".format(
            PARAMS["WALL"],
            PARAMS["CAM_INNER_D"],
            PARAMS["CAM_GPS_SEPARATOR"],
            PARAMS["GPS_INNER_D"],
            PARAMS["LID_THICKNESS"],
            D["total_d"],
        )
    )

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
