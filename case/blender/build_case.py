#!/usr/bin/env python3
"""Build the v2 two-piece ToiCamera enclosure and export printable STL files.

The v2 enclosure turns the StopWatch into a compact-camera style body: the
display faces the photographer (-Y) and the CamS3 lens faces the subject (+Y).
The first exported part is the front watch ring; the second is the rear pod,
which also acts as the cover.

Headless usage:
  /Applications/Blender.app/Contents/MacOS/Blender -b \
    --python case/blender/build_case.py -- \
    --out case/blender/out/toicamera_case.stl [--part shell|lid|all]

For compatibility with the v1 filenames, ``shell`` means the watch ring and
``lid`` means the rear pod.  Unit contract: 1 Blender Unit = 1 mm.  STL export
uses ``use_scene_unit=False`` and ``global_scale=1.0`` so numeric mesh values
are written as millimetres without an implicit metre conversion.
"""

import argparse
import math
from pathlib import Path
import sys

import bmesh
import bpy


# All design dimensions and fit-test offsets live here. Change PARAMS, then
# regenerate; never edit the generated STL. X/Z locations use rear-view
# coordinates: +X is right, +Z is up, while -Y is the display side and +Y is
# the subject/lens side.
PARAMS = {
    "TOL_XY": 0.2,
    "TOL_DEPTH": 0.1,
    "WATCH_DEPTH_CLEARANCE": 0.2,
    "BBOX_TOL": 0.3,
    "BOOLEAN_EPS": 0.25,
    "OPEN_CUTTER_OVERTRAVEL": 2.0,
    "WALL": 2.0,
    "FRONT_BEZEL_DEPTH": 2.0,
    "REAR_SKIN": 1.2,  # GPS antenna-facing skin; must stay <= 1.2 mm.
    "POD_AIR_GAP": 2.0,
    "POD_SHOULDER": 2.0,  # 2 mm run over 2 mm rise = 45 degrees.
    "FILLET_SEGMENTS": 8,
    "RING_OUTER_FILLET": 2.0,
    "WATCH_CAVITY_FILLET": 0.8,
    "POD_OUTER_FILLET": 16.0,
    "POD_CAVITY_FILLET": 0.6,

    # Measured devices.
    "WATCH_W": 52.0,
    "WATCH_H": 52.0,
    "WATCH_D": 15.5,
    "WATCH_HEADER_PROTRUSION": 2.0,
    "CAM_W": 40.0,
    "CAM_H": 24.0,
    "CAM_D": 11.0,
    "GPS_W": 48.0,
    "GPS_H": 24.0,
    "GPS_D": 8.0,

    # Finished XY cavities. Depth receives one-sided clearance because each
    # board is registered against the 1.2 mm rear skin.
    "WATCH_INNER_W": 52.4,
    "WATCH_INNER_H": 52.4,
    "WATCH_INNER_D": 15.7,
    "CAM_INNER_W": 40.4,
    "CAM_INNER_H": 24.4,
    "CAM_INNER_D": 11.1,
    "GPS_INNER_W": 48.4,
    "GPS_INNER_H": 24.4,
    "GPS_INNER_D": 8.1,

    # Rear pod envelope and rear-view component locations. The pod is a small
    # vertical oval: GPS at the top, camera at centre-right, wiring below.
    "POD_OUTER_W": 74.0,
    "POD_OUTER_H": 96.0,
    "POD_CENTER_Z": 9.5,
    "CAM_CENTER_X": 12.0,
    "CAM_CENTER_Z": -0.3,
    "GPS_CENTER_X": 0.0,
    "GPS_CENTER_Z": 38.5,
    "WIRE_BAY_W": 15.0,
    "WIRE_BAY_H": 24.0,
    "WIRE_BAY_D": 8.0,
    "WIRE_CENTER_X": -16.0,
    "WIRE_CENTER_Z": -22.0,

    # Front/rear openings.
    "DISPLAY_OPENING_D": 48.0,
    "SPEAKER_CENTER_X": -17.5,
    "SPEAKER_CENTER_Z": 0.0,
    "SPEAKER_OPENING_D": 16.5,
    "LENS_OPENING_D": 10.0,
    "MICROSD_SLOT_W": 12.0,
    "MICROSD_SLOT_H": 4.0,

    # ADJUST AFTER FIT TEST: offsets are from the CamS3 bay centre in rear view.
    "CAM_LENS_X_OFFSET": -11.0,
    "CAM_LENS_Z_OFFSET": 0.0,
    "MICROSD_X_OFFSET": 5.0,
    "MICROSD_Z_OFFSET": -8.0,

    # Parameterised StopWatch side windows. Angles are rear-view polar angles:
    # 0 degrees=right, +90=top, 180=left, -90=bottom.
    "PORT_RADIAL_EXTRA": 1.0,
    "BUTTON_ANGLE_DEG": 180.0,
    "BUTTON_WINDOW_DEPTH": 8.0,
    "BUTTON_WINDOW_TANGENT": 22.0,
    "BUTTON_DEPTH_OFFSET": 0.0,
    "USB_ANGLE_DEG": 0.0,
    "USB_WINDOW_DEPTH": 10.0,
    "USB_WINDOW_TANGENT": 5.0,
    "USB_DEPTH_OFFSET": 0.0,
    "POWER_ANGLE_DEG": 20.0,
    "POWER_WINDOW_DEPTH": 8.0,
    "POWER_WINDOW_TANGENT": 5.0,
    "POWER_DEPTH_OFFSET": 0.0,
    "GROVE_ANGLE_DEG": -45.0,
    "GROVE_WINDOW_DEPTH": 10.0,
    "GROVE_WINDOW_TANGENT": 8.0,
    "GROVE_RING_RADIAL_CENTER": 38.0,
    "GROVE_RING_RADIAL_LENGTH": 14.0,
    "GROVE_POD_NOTCH_DEPTH": 3.0,
    "GROVE_POD_RADIAL_CENTER": 39.0,
    "GROVE_POD_RADIAL_LENGTH": 22.0,

    # Four rear-driven M2 self-tapping screws. The bosses are part of the ring
    # and extend into clearance tunnels in the rear pod.
    "SCREW_BOSS_D": 5.6,
    "SCREW_PILOT_D": 1.7,
    "SCREW_CLEARANCE_D": 2.4,
    "SCREW_BOSS_FRONT_OVERLAP": 0.8,
    "SCREW_PILOT_DEPTH": 8.0,
    "SCREW_CENTER_X": 29.0,
    "SCREW_CENTER_Z": 22.0,
}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Build the ToiCamera v2 enclosure")
    parser.add_argument("--out", required=True, help="output STL path")
    parser.add_argument(
        "--part",
        choices=("shell", "lid", "all"),
        default="all",
        help="part to export: shell=watch ring, lid=rear pod",
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
    ring_outer_w = p["WATCH_INNER_W"] + 2.0 * p["WALL"]
    ring_outer_h = p["WATCH_INNER_H"] + 2.0 * p["WALL"]
    ring_depth = p["FRONT_BEZEL_DEPTH"] + p["WATCH_INNER_D"]
    pod_inner_depth = p["POD_AIR_GAP"] + p["CAM_INNER_D"]
    pod_depth = pod_inner_depth + p["REAR_SKIN"]
    total_depth = ring_depth + pod_depth
    front_y = -total_depth / 2.0
    ring_back_y = front_y + ring_depth
    rear_inner_y = ring_back_y + pod_inner_depth
    pod_back_y = rear_inner_y + p["REAR_SKIN"]
    watch_inner_front_y = front_y + p["FRONT_BEZEL_DEPTH"]
    watch_actual_back_y = watch_inner_front_y + p["WATCH_D"]
    camera_actual_front_y = rear_inner_y - p["CAM_D"]
    gps_actual_front_y = rear_inner_y - p["GPS_D"]
    shoulder_angle = math.degrees(math.atan2(p["POD_SHOULDER"], p["POD_SHOULDER"]))
    boss_end_y = rear_inner_y
    shell_bbox_w = max(ring_outer_w, 2.0 * (p["SCREW_CENTER_X"] + p["SCREW_BOSS_D"] / 2.0))
    shell_bbox_h = max(ring_outer_h, 2.0 * (p["SCREW_CENTER_Z"] + p["SCREW_BOSS_D"] / 2.0))
    return {
        "ring_outer_w": ring_outer_w,
        "ring_outer_h": ring_outer_h,
        "ring_depth": ring_depth,
        "pod_inner_depth": pod_inner_depth,
        "pod_depth": pod_depth,
        "total_depth": total_depth,
        "front_y": front_y,
        "ring_back_y": ring_back_y,
        "rear_inner_y": rear_inner_y,
        "pod_back_y": pod_back_y,
        "watch_inner_front_y": watch_inner_front_y,
        "watch_center_y": watch_inner_front_y + p["WATCH_INNER_D"] / 2.0,
        "watch_actual_back_y": watch_actual_back_y,
        "camera_actual_front_y": camera_actual_front_y,
        "gps_actual_front_y": gps_actual_front_y,
        "camera_air_gap": camera_actual_front_y - watch_actual_back_y,
        "gps_air_gap": gps_actual_front_y - watch_actual_back_y,
        "shoulder_angle": shoulder_angle,
        "boss_end_y": boss_end_y,
        "shell_bbox_w": shell_bbox_w,
        "shell_bbox_h": shell_bbox_h,
        "shell_bbox_d": boss_end_y - front_y,
    }


D = derived()


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    units = bpy.context.scene.unit_settings
    units.system = "METRIC"
    units.scale_length = 0.001
    units.length_unit = "MILLIMETERS"


def rect_bounds(cx, cz, width, height):
    return (cx - width / 2.0, cx + width / 2.0, cz - height / 2.0, cz + height / 2.0)


def rectangles_overlap(first, second):
    return first[0] < second[1] and first[1] > second[0] and first[2] < second[3] and first[3] > second[2]


def point_inside_rounded_rect(x, z, width, height, radius, center_x=0.0, center_z=0.0):
    half_w = width / 2.0
    half_h = height / 2.0
    dx = abs(x - center_x)
    dz = abs(z - center_z)
    if dx > half_w or dz > half_h:
        return False
    corner_dx = max(dx - (half_w - radius), 0.0)
    corner_dz = max(dz - (half_h - radius), 0.0)
    return corner_dx * corner_dx + corner_dz * corner_dz <= radius * radius + 1.0e-9


def rectangle_inside_rounded_rect_with_wall(inner, width, height, radius, wall, center_z):
    inset_width = width - 2.0 * wall
    inset_height = height - 2.0 * wall
    inset_radius = radius - wall
    corners = (
        (inner[0], inner[2]),
        (inner[0], inner[3]),
        (inner[1], inner[2]),
        (inner[1], inner[3]),
    )
    return all(
        point_inside_rounded_rect(x, z, inset_width, inset_height, inset_radius, center_z=center_z)
        for x, z in corners
    )


def validate_param_contract():
    p = PARAMS
    xy_clearance_pairs = (
        ("WATCH_W", "WATCH_INNER_W"),
        ("WATCH_H", "WATCH_INNER_H"),
        ("CAM_W", "CAM_INNER_W"),
        ("CAM_H", "CAM_INNER_H"),
        ("GPS_W", "GPS_INNER_W"),
        ("GPS_H", "GPS_INNER_H"),
    )
    for device_key, cavity_key in xy_clearance_pairs:
        expected = p[device_key] + 2.0 * p["TOL_XY"]
        if not math.isclose(p[cavity_key], expected, abs_tol=1.0e-9):
            raise ValueError(f"{cavity_key} must equal {device_key} + 2*TOL_XY")

    depth_clearance_pairs = (
        ("WATCH_D", "WATCH_INNER_D", p["WATCH_DEPTH_CLEARANCE"]),
        ("CAM_D", "CAM_INNER_D", p["TOL_DEPTH"]),
        ("GPS_D", "GPS_INNER_D", p["TOL_DEPTH"]),
    )
    for device_key, cavity_key, clearance in depth_clearance_pairs:
        expected = p[device_key] + clearance
        if not math.isclose(p[cavity_key], expected, abs_tol=1.0e-9):
            raise ValueError(f"{cavity_key} depth clearance is inconsistent")

    if not math.isclose(p["WALL"], 2.0, abs_tol=1.0e-9):
        raise ValueError("v2 nominal wall must remain 2.0 mm")
    if not math.isclose(p["REAR_SKIN"], 1.2, abs_tol=1.0e-9):
        raise ValueError("v2 GPS antenna-facing skin must remain 1.2 mm")
    if p["SPEAKER_OPENING_D"] < 16.0:
        raise ValueError("speaker opening must be at least 16 mm")
    if D["camera_air_gap"] < p["POD_AIR_GAP"]:
        raise ValueError("camera violates the 2 mm watch-rear air gap")
    if D["camera_air_gap"] < p["WATCH_HEADER_PROTRUSION"]:
        raise ValueError("camera does not clear the rear header protrusion")
    if D["total_depth"] > 32.0 + 1.0e-9:
        raise ValueError("assembled depth exceeds the 32 mm v2 target")
    if D["shoulder_angle"] < 45.0 - 1.0e-6:
        raise ValueError("pod shoulder is shallower than 45 degrees")

    cam = rect_bounds(p["CAM_CENTER_X"], p["CAM_CENTER_Z"], p["CAM_INNER_W"], p["CAM_INNER_H"])
    gps = rect_bounds(p["GPS_CENTER_X"], p["GPS_CENTER_Z"], p["GPS_INNER_W"], p["GPS_INNER_H"])
    wire = rect_bounds(p["WIRE_CENTER_X"], p["WIRE_CENTER_Z"], p["WIRE_BAY_W"], p["WIRE_BAY_H"])
    pod_front_w = p["POD_OUTER_W"] - 2.0 * p["POD_SHOULDER"]
    pod_front_h = p["POD_OUTER_H"] - 2.0 * p["POD_SHOULDER"]
    pod_front_radius = p["POD_OUTER_FILLET"] - p["POD_SHOULDER"]
    if not all(
        rectangle_inside_rounded_rect_with_wall(
            item,
            pod_front_w,
            pod_front_h,
            pod_front_radius,
            p["WALL"],
            p["POD_CENTER_Z"],
        )
        for item in (cam, gps, wire)
    ):
        raise ValueError("a rear pod bay violates the 2 mm wall at the 45-degree front shoulder")
    if rectangles_overlap(cam, gps) or rectangles_overlap(cam, wire) or rectangles_overlap(gps, wire):
        raise ValueError("rear pod component bays overlap in the rear-view plane")
    if gps[2] <= p["WATCH_INNER_H"] / 2.0:
        raise ValueError("GPS bay must sit outside the upper watch/header edge")

    for name, bay in (("CamS3", cam), ("GPS", gps), ("wire", wire)):
        speaker_dx = max(bay[0] - p["SPEAKER_CENTER_X"], 0.0, p["SPEAKER_CENTER_X"] - bay[1])
        speaker_dz = max(bay[2] - p["SPEAKER_CENTER_Z"], 0.0, p["SPEAKER_CENTER_Z"] - bay[3])
        if math.hypot(speaker_dx, speaker_dz) <= p["SPEAKER_OPENING_D"] / 2.0:
            raise ValueError(f"{name} bay intrudes into the speaker opening")

    boss_radius = p["SCREW_BOSS_D"] / 2.0
    for screw_x, screw_z in screw_positions():
        for name, bay in (("CamS3", cam), ("GPS", gps), ("wire", wire)):
            boss_dx = max(bay[0] - screw_x, 0.0, screw_x - bay[1])
            boss_dz = max(bay[2] - screw_z, 0.0, screw_z - bay[3])
            if math.hypot(boss_dx, boss_dz) <= boss_radius:
                raise ValueError(f"M2 boss intrudes into the {name} bay")

    print("PARAM_CONTRACT: PASS")
    print(f"ASSEMBLED_DEPTH: {D['total_depth']:.3f} mm (target <= 32.000 mm)")
    print(f"CAMERA_WATCH_REAR_AIR_GAP: {D['camera_air_gap']:.3f} mm (minimum 2.000 mm)")
    print(f"GPS_WATCH_REAR_AIR_GAP: {D['gps_air_gap']:.3f} mm")
    print(f"SPEAKER_OPENING: {p['SPEAKER_OPENING_D']:.3f} mm (minimum 16.000 mm)")
    print(f"POD_SHOULDER_ANGLE: {D['shoulder_angle']:.3f} degrees from build plate")


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


def rounded_rect_profile(width, height, radius, center_x=0.0, center_z=0.0):
    """Return a counter-clockwise XZ rounded-rectangle profile."""
    half_w = width / 2.0
    half_h = height / 2.0
    radius = min(radius, half_w, half_h)
    segments = PARAMS["FILLET_SEGMENTS"]
    points = [(center_x - half_w + radius, center_z - half_h)]
    points.append((center_x + half_w - radius, center_z - half_h))
    append_arc(points, center_x + half_w - radius, center_z - half_h + radius, radius, -90.0, 0.0, segments)
    points.append((center_x + half_w, center_z + half_h - radius))
    append_arc(points, center_x + half_w - radius, center_z + half_h - radius, radius, 0.0, 90.0, segments)
    points.append((center_x - half_w + radius, center_z + half_h))
    append_arc(points, center_x - half_w + radius, center_z + half_h - radius, radius, 90.0, 180.0, segments)
    points.append((center_x - half_w, center_z - half_h + radius))
    append_arc(points, center_x - half_w + radius, center_z - half_h + radius, radius, 180.0, 270.0, segments)
    # The final arc endpoint equals the initial point. Polygon loops close
    # implicitly, so remove that duplicate to avoid a zero-length mesh edge.
    points.pop()
    return points


def loft_mesh_data(profile_layers):
    """Return vertices/faces for a capped loft of equal-length XZ profiles."""
    count = len(profile_layers[0][1])
    if any(len(points) != count for _, points in profile_layers):
        raise ValueError("loft profiles must have equal vertex counts")
    vertices = []
    for y, points in profile_layers:
        vertices.extend((x, y, z) for x, z in points)

    layer_count = len(profile_layers)
    # XZ profiles are counter-clockwise when viewed from -Y, so the front cap
    # keeps profile order and the rear cap reverses it (matching the proven v1
    # extrusion winding). Side quads follow the same outward orientation.
    faces = [list(range(count))]
    for layer in range(layer_count - 1):
        base = layer * count
        nxt_base = (layer + 1) * count
        for index in range(count):
            nxt = (index + 1) % count
            faces.append([base + index, nxt_base + index, nxt_base + nxt, base + nxt])
    last = (layer_count - 1) * count
    faces.append([last + index for index in range(count - 1, -1, -1)])
    return vertices, faces


def loft_xz_profiles(name, profile_layers):
    """Create a Blender solid from XZ profile layers along Y."""
    vertices, faces = loft_mesh_data(profile_layers)

    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.validate(verbose=True)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def extrude_xz_profile(name, points, y0, y1):
    return loft_xz_profiles(name, ((y0, points), (y1, points)))


def radial_cutout(target, name, angle_deg, radial_center, radial_length, depth_y, tangent_height, center_y):
    angle = math.radians(angle_deg)
    centre = (
        radial_center * math.cos(angle),
        center_y,
        radial_center * math.sin(angle),
    )
    cutter = box(name, radial_length, depth_y, tangent_height, centre)
    cutter.rotation_euler = (0.0, -angle, 0.0)
    apply_transform(cutter)
    boolean(target, cutter, "DIFFERENCE")


def watch_side_cutout(ring, name, angle_deg, depth, tangent, depth_offset=0.0, radial_center=None, radial_length=None):
    p = PARAMS
    center_y = D["watch_inner_front_y"] + p["WATCH_INNER_D"] / 2.0 + depth_offset
    radial_cutout(
        ring,
        name,
        angle_deg,
        radial_center if radial_center is not None else p["WATCH_INNER_W"] / 2.0 + p["PORT_RADIAL_EXTRA"],
        radial_length if radial_length is not None else p["WALL"] * 4.0,
        depth,
        tangent,
        center_y,
    )


def screw_positions():
    p = PARAMS
    return [
        (sx, sz)
        for sx in (-p["SCREW_CENTER_X"], p["SCREW_CENTER_X"])
        for sz in (-p["SCREW_CENTER_Z"], p["SCREW_CENTER_Z"])
    ]


def add_ring_screw_bosses(ring):
    p = PARAMS
    boss_front_y = D["ring_back_y"] - p["SCREW_BOSS_FRONT_OVERLAP"]
    boss_depth = D["boss_end_y"] - boss_front_y
    boss_y = (boss_front_y + D["boss_end_y"]) / 2.0
    for x, z in screw_positions():
        boss = cylinder_y("m2_ring_boss", p["SCREW_BOSS_D"], boss_depth, (x, boss_y, z))
        boolean(ring, boss, "UNION")
        pilot_end = D["boss_end_y"] + p["BOOLEAN_EPS"]
        pilot_start = pilot_end - p["SCREW_PILOT_DEPTH"]
        pilot = cylinder_y(
            "m2_ring_pilot",
            p["SCREW_PILOT_D"],
            pilot_end - pilot_start,
            (x, (pilot_start + pilot_end) / 2.0, z),
        )
        boolean(ring, pilot, "DIFFERENCE")


def build_ring():
    p = PARAMS
    eps = p["BOOLEAN_EPS"]
    profile = rounded_rect_profile(
        D["ring_outer_w"],
        D["ring_outer_h"],
        p["RING_OUTER_FILLET"],
    )
    ring = extrude_xz_profile("toicamera_watch_ring", profile, D["front_y"], D["ring_back_y"])

    # Rear-open watch cradle, retaining a 2 mm front bezel around the Ø48 display.
    watch_start_y = D["watch_inner_front_y"]
    watch_end_y = D["ring_back_y"] + p["OPEN_CUTTER_OVERTRAVEL"]
    watch = rounded_box(
        "watch_cradle",
        p["WATCH_INNER_W"],
        watch_end_y - watch_start_y,
        p["WATCH_INNER_H"],
        p["WATCH_CAVITY_FILLET"],
        (0.0, (watch_start_y + watch_end_y) / 2.0, 0.0),
    )
    boolean(ring, watch, "DIFFERENCE")

    display = cylinder_y(
        "display_opening",
        p["DISPLAY_OPENING_D"],
        p["FRONT_BEZEL_DEPTH"] + 2.0 * eps,
        (0.0, D["front_y"] + p["FRONT_BEZEL_DEPTH"] / 2.0, 0.0),
        vertices=128,
    )
    boolean(ring, display, "DIFFERENCE")

    watch_side_cutout(
        ring,
        "keya_keyb_window_rear_left",
        p["BUTTON_ANGLE_DEG"],
        p["BUTTON_WINDOW_DEPTH"],
        p["BUTTON_WINDOW_TANGENT"],
        p["BUTTON_DEPTH_OFFSET"],
    )
    watch_side_cutout(
        ring,
        "usb_c_window_rear_right",
        p["USB_ANGLE_DEG"],
        p["USB_WINDOW_DEPTH"],
        p["USB_WINDOW_TANGENT"],
        p["USB_DEPTH_OFFSET"],
    )
    watch_side_cutout(
        ring,
        "power_button_window_rear_right",
        p["POWER_ANGLE_DEG"],
        p["POWER_WINDOW_DEPTH"],
        p["POWER_WINDOW_TANGENT"],
        p["POWER_DEPTH_OFFSET"],
        radial_center=29.0,
        radial_length=12.0,
    )

    # The 10 x 8 Grove window is at 4-5 o'clock and occupies the rear end of
    # the ring so the plug turns directly into the pod instead of protruding.
    grove_center_y = D["ring_back_y"] - p["GROVE_WINDOW_DEPTH"] / 2.0
    radial_cutout(
        ring,
        "grove_10x8_recess_rear_lower_right",
        p["GROVE_ANGLE_DEG"],
        p["GROVE_RING_RADIAL_CENTER"],
        p["GROVE_RING_RADIAL_LENGTH"],
        p["GROVE_WINDOW_DEPTH"],
        p["GROVE_WINDOW_TANGENT"],
        grove_center_y,
    )

    add_ring_screw_bosses(ring)
    ring.name = "toicamera_case_shell_watch_ring_v2"
    return ring


def build_pod():
    p = PARAMS
    eps = p["BOOLEAN_EPS"]
    shoulder = p["POD_SHOULDER"]
    front_profile = rounded_rect_profile(
        p["POD_OUTER_W"] - 2.0 * shoulder,
        p["POD_OUTER_H"] - 2.0 * shoulder,
        p["POD_OUTER_FILLET"] - shoulder,
        center_z=p["POD_CENTER_Z"],
    )
    full_profile = rounded_rect_profile(
        p["POD_OUTER_W"],
        p["POD_OUTER_H"],
        p["POD_OUTER_FILLET"],
        center_z=p["POD_CENTER_Z"],
    )
    pod = loft_xz_profiles(
        "toicamera_rear_pod",
        (
            (D["ring_back_y"], front_profile),
            (D["ring_back_y"] + shoulder, full_profile),
            (D["pod_back_y"], full_profile),
        ),
    )

    # A full-watch plenum guarantees a 2 mm unobstructed air gap over the
    # speaker, both header rows, and the 12/6 o'clock watch screws.
    plenum_start = D["ring_back_y"] - p["OPEN_CUTTER_OVERTRAVEL"]
    plenum_end = D["ring_back_y"] + p["POD_AIR_GAP"] + eps
    plenum = rounded_box(
        "watch_rear_air_plenum_2mm",
        p["WATCH_INNER_W"],
        plenum_end - plenum_start,
        p["WATCH_INNER_H"],
        p["WATCH_CAVITY_FILLET"],
        (0.0, (plenum_start + plenum_end) / 2.0, 0.0),
    )
    boolean(pod, plenum, "DIFFERENCE")

    # Camera and GPS pockets open toward the watch. Both boards register on the
    # rear skin, leaving 2.3 mm and 5.3 mm respectively to the actual watch back.
    cavity_start = D["ring_back_y"] - p["OPEN_CUTTER_OVERTRAVEL"]
    cavity_end = D["rear_inner_y"]
    camera = rounded_box(
        "cams3_rear_bay",
        p["CAM_INNER_W"],
        cavity_end - cavity_start,
        p["CAM_INNER_H"],
        p["POD_CAVITY_FILLET"],
        (p["CAM_CENTER_X"], (cavity_start + cavity_end) / 2.0, p["CAM_CENTER_Z"]),
    )
    boolean(pod, camera, "DIFFERENCE")
    gps = rounded_box(
        "gps_upper_bay",
        p["GPS_INNER_W"],
        cavity_end - cavity_start,
        p["GPS_INNER_H"],
        p["POD_CAVITY_FILLET"],
        (p["GPS_CENTER_X"], (cavity_start + cavity_end) / 2.0, p["GPS_CENTER_Z"]),
    )
    boolean(pod, gps, "DIFFERENCE")

    # 15 x 24 x 8 mm protected space for the Y splice and service loop.
    wire_end = D["ring_back_y"] + p["WIRE_BAY_D"]
    wire = rounded_box(
        "grove_y_and_service_loop_bay",
        p["WIRE_BAY_W"],
        wire_end - cavity_start,
        p["WIRE_BAY_H"],
        p["POD_CAVITY_FILLET"],
        (p["WIRE_CENTER_X"], (cavity_start + wire_end) / 2.0, p["WIRE_CENTER_Z"]),
    )
    boolean(pod, wire, "DIFFERENCE")

    # Matching pod-front notch. It opens only into the protected rear plenum;
    # the external cable run therefore ends at the ring edge.
    radial_cutout(
        pod,
        "grove_pod_entry_notch",
        p["GROVE_ANGLE_DEG"],
        p["GROVE_POD_RADIAL_CENTER"],
        p["GROVE_POD_RADIAL_LENGTH"],
        p["GROVE_POD_NOTCH_DEPTH"] + 2.0 * eps,
        p["GROVE_WINDOW_TANGENT"],
        D["ring_back_y"] + p["GROVE_POD_NOTCH_DEPTH"] / 2.0,
    )

    # Speaker opening stays completely free through the pod. The lens and
    # microSD openings only cross the 1.2 mm subject-side skin.
    speaker = cylinder_y(
        "speaker_clearance_opening",
        p["SPEAKER_OPENING_D"],
        D["pod_depth"] + 2.0 * eps,
        (p["SPEAKER_CENTER_X"], (D["ring_back_y"] + D["pod_back_y"]) / 2.0, p["SPEAKER_CENTER_Z"]),
        vertices=96,
    )
    boolean(pod, speaker, "DIFFERENCE")

    rear_cut_depth = p["REAR_SKIN"] + 2.0 * eps
    rear_cut_y = D["pod_back_y"] - p["REAR_SKIN"] / 2.0
    lens = cylinder_y(
        "rear_facing_lens_opening",
        p["LENS_OPENING_D"],
        rear_cut_depth,
        (
            p["CAM_CENTER_X"] + p["CAM_LENS_X_OFFSET"],
            rear_cut_y,
            p["CAM_CENTER_Z"] + p["CAM_LENS_Z_OFFSET"],
        ),
        vertices=64,
    )
    boolean(pod, lens, "DIFFERENCE")
    microsd = box(
        "rear_microsd_access_slot",
        p["MICROSD_SLOT_W"],
        rear_cut_depth,
        p["MICROSD_SLOT_H"],
        (
            p["CAM_CENTER_X"] + p["MICROSD_X_OFFSET"],
            rear_cut_y,
            p["CAM_CENTER_Z"] + p["MICROSD_Z_OFFSET"],
        ),
    )
    boolean(pod, microsd, "DIFFERENCE")

    clearance_depth = D["pod_depth"] + 2.0 * eps
    for x, z in screw_positions():
        hole = cylinder_y(
            "m2_pod_clearance",
            p["SCREW_CLEARANCE_D"],
            clearance_depth,
            (x, (D["ring_back_y"] + D["pod_back_y"]) / 2.0, z),
        )
        boolean(pod, hole, "DIFFERENCE")

    pod.name = "toicamera_case_lid_rear_pod_v2"
    return pod


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
        "shell": (D["shell_bbox_w"], D["shell_bbox_d"], D["shell_bbox_h"]),
        "lid": (PARAMS["POD_OUTER_W"], D["pod_depth"], PARAMS["POD_OUTER_H"]),
    }
    builders = {"shell": build_ring, "lid": build_pod}
    overall_ok = True

    print("UNIT_CONTRACT: 1 Blender Unit = 1 mm")
    print("LAYOUT_V2: display=-Y / rear-facing lens=+Y / camera=rear-right / GPS=upper")
    print(f"GPS_ANTENNA_SKIN: {PARAMS['REAR_SKIN']:.3f} mm (limit <= 1.200 mm)")
    print(
        "DEPTH_STACK: bezel {:.1f} + watch {:.1f} + air/camera {:.1f}+{:.1f} + rear skin {:.1f} = {:.1f} mm".format(
            PARAMS["FRONT_BEZEL_DEPTH"],
            PARAMS["WATCH_INNER_D"],
            PARAMS["POD_AIR_GAP"],
            PARAMS["CAM_INNER_D"],
            PARAMS["REAR_SKIN"],
            D["total_depth"],
        )
    )

    for part, path in paths.items():
        obj = builders[part]()
        label = "RING" if part == "shell" else "POD"
        object_ok = validate_object(label, obj, expected[part], args.bbox_tol)
        export_stl(obj, path)
        stl_ok = validate_exported_stl(label, path, expected[part], args.bbox_tol)
        overall_ok = overall_ok and object_ok and stl_ok

    print("CASE_BUILD_RESULT: " + ("PASS" if overall_ok else "FAIL"))
    raise SystemExit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
