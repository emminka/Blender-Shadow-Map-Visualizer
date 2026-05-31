###
#Emma Krompascikova
#xkromp00
#Visualizes Cascaded Shadow Maps: splits camera frustum into depth ranges, one shadow map per cascade.
###

import bpy
import math
from mathutils import Vector

from .visualization_2d import get_gp_material, draw_strokes
from .visualization_3d import make_circle_on_surface

COL_CSM_NAME = "ShadowMap_CSM"
GP_CSM_NAME  = "SM_Viz_CSM"

#green = near (dense), orange = mid, red = far (sparse)
COLOR_C1 = (0.2, 0.9, 0.2, 1.0)
COLOR_C2 = (1.0, 0.55, 0.0, 1.0)
COLOR_C3 = (0.9, 0.15, 0.15, 1.0)
CASCADE_COLORS = [COLOR_C1, COLOR_C2, COLOR_C3]


def get_csm_collection():
    if COL_CSM_NAME in bpy.data.collections:
        return bpy.data.collections[COL_CSM_NAME]
    col = bpy.data.collections.new(COL_CSM_NAME)
    bpy.context.scene.collection.children.link(col)
    return col


def clear_csm_objects():
    if COL_CSM_NAME not in bpy.data.collections:
        return
    col = bpy.data.collections[COL_CSM_NAME]
    for obj in list(col.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def get_csm_grease_pencil():
    col = get_csm_collection()
    if GP_CSM_NAME in col.objects:
        obj = col.objects[GP_CSM_NAME]
        gp_data = obj.data
        for layer in list(gp_data.layers):
            gp_data.layers.remove(layer)
        gp_data.materials.clear()
        return obj
    gp_data = bpy.data.grease_pencils.new(GP_CSM_NAME + "_Data")
    obj = bpy.data.objects.new(GP_CSM_NAME, gp_data)
    col.objects.link(obj)
    return obj


def get_camera_fov_aspect(context, cam_obj):
    #returns (fov_y, aspect) for perspective cameras; (None, aspect) for orthographic
    cam = cam_obj.data
    render = context.scene.render
    aspect = render.resolution_x / render.resolution_y
    if cam.type != 'PERSP':
        return None, aspect
    #sensor_fit determines whether cam.angle is horizontal or vertical FOV
    if cam.sensor_fit == 'VERTICAL':
        fov_y = cam.angle
    else:
        fov_y = 2.0 * math.atan(math.tan(cam.angle / 2.0) / aspect)
    return fov_y, aspect


def get_frustum_corners(cam_obj, d_near, d_far, fov_y, aspect):
    #returns 8 world-space corners of the camera frustum between d_near and d_far
    tan_y = math.tan(fov_y / 2.0)
    tan_x = tan_y * aspect

    corners = []
    for d in (d_near, d_far):
        hw = d * tan_x
        hh = d * tan_y
        for sy in (-1.0, 1.0):
            for sx in (-1.0, 1.0):
                local_pos = Vector((sx * hw, sy * hh, -d, 1.0))
                world_pos = cam_obj.matrix_world @ local_pos
                corners.append(world_pos.xyz)

    return corners


def compute_light_bbox(corners, light_right, light_up):
    #returns bounding box center and half-extents of frustum corners in light space
    proj_r = [c.dot(light_right) for c in corners]
    proj_u = [c.dot(light_up)    for c in corners]

    min_r = min(proj_r)
    max_r = max(proj_r)
    min_u = min(proj_u)
    max_u = max(proj_u)

    half_w = (max_r - min_r) / 2.0
    half_h = (max_u - min_u) / 2.0

    centroid = Vector((0.0, 0.0, 0.0))
    for c in corners:
        centroid += c
    centroid /= len(corners)

    mid_r = (min_r + max_r) / 2.0
    mid_u = (min_u + max_u) / 2.0
    center_world = centroid + light_right * (mid_r - centroid.dot(light_right)) \
                            + light_up    * (mid_u - centroid.dot(light_up))

    return center_world, half_w, half_h


def draw_frustum_slice(gp_data, layer_name, corners, mat_idx, thickness):
    #corners[0:4] = near face, corners[4:8] = far face
    near = corners[:4]
    far  = corners[4:]

    edges = [
        [near[0], near[1]], [near[1], near[3]], [near[3], near[2]], [near[2], near[0]],
        [far[0],  far[1]],  [far[1],  far[3]],  [far[3],  far[2]],  [far[2],  far[0]],
        [near[0], far[0]],  [near[1], far[1]],  [near[2], far[2]],  [near[3], far[3]],
    ]
    draw_strokes(gp_data, layer_name, edges, mat_idx, thickness)


def generate_csm(context):
    props     = context.scene.sm_props
    light_obj = props.csm_light_object
    cam_obj   = context.scene.camera

    if not light_obj or light_obj.type != 'LIGHT' or light_obj.data.type != 'SUN':
        return
    if not cam_obj:
        return

    fov_y, aspect = get_camera_fov_aspect(context, cam_obj)
    if fov_y is None:
        return

    quat        = light_obj.matrix_world.to_quaternion()
    light_dir   = (quat @ Vector((0,  0, -1))).normalized()
    light_right = (quat @ Vector((1,  0,  0))).normalized()
    light_up    = (quat @ Vector((0,  1,  0))).normalized()

    cam_pos = cam_obj.matrix_world.translation.copy()
    cam_fwd = (cam_obj.matrix_world.to_quaternion() @ Vector((0, 0, -1))).normalized()

    depsgraph = context.evaluated_depsgraph_get()

    max_dist = props.csm_max_distance
    s1       = props.csm_split1 * max_dist
    s2       = props.csm_split2 * max_dist

    if s1 >= s2 or s2 >= max_dist:
        return

    base    = props.csm_base_steps
    overlap = props.csm_overlap

    #overlap extends dot depth ranges into adjacent cascades so blending zones are visible
    ov1 = overlap * (s1 - 0.1)
    ov2 = overlap * (s2 - s1)

    cascades = [
        #(d_near_frustum, d_far_frustum, d_near_dots, d_far_dots, steps)
        (0.1, s1,       0.1,       s1 + ov1,       base),
        (s1,  s2,       s1 - ov1,  s2 + ov2,       base),
        (s2,  max_dist, s2 - ov2,  max_dist,        base),
    ]

    clear_csm_objects()
    gp_obj  = get_csm_grease_pencil()
    gp_data = gp_obj.data

    for ci, color in enumerate(CASCADE_COLORS):
        get_gp_material(gp_data, f"SMViz_CSM_{ci}",      color)
    for ci, color in enumerate(CASCADE_COLORS):
        get_gp_material(gp_data, f"SMViz_CSM_{ci}_Fill", color, use_fill=True)

    show_frustum = props.show_csm_frustum

    DOT_SCALE = [1.0, 1.0, 1.0]

    cascade_dot_lists = [[], [], []]

    for ci, (d_near, d_far, d_dot_near, d_dot_far, steps) in enumerate(cascades):
        corners = get_frustum_corners(cam_obj, d_near, d_far, fov_y, aspect)

        if show_frustum:
            draw_frustum_slice(gp_data, f"C{ci}_Frustum", corners, ci, 0.02)

        center, half_w, half_h = compute_light_bbox(corners, light_right, light_up)

        dot_radius = props.csm_dot_size * DOT_SCALE[ci]

        for ix in range(-steps, steps + 1):
            for iy in range(-steps, steps + 1):
                fx = ix / max(steps, 1)
                fy = iy / max(steps, 1)
                grid_pt    = center + light_right * (fx * half_w) + light_up * (fy * half_h)
                ray_origin = grid_pt - light_dir * 200
                result, loc, normal, _, _, _ = context.scene.ray_cast(depsgraph, ray_origin, light_dir)
                if not result:
                    continue
                depth = (loc - cam_pos).dot(cam_fwd)
                if not (d_dot_near <= depth <= d_dot_far):
                    continue
                cascade_dot_lists[ci].append(
                    make_circle_on_surface(loc + normal * 0.002, normal, dot_radius))

    for ci, dots in enumerate(cascade_dot_lists):
        if dots:
            draw_strokes(gp_data, f"C{ci}_Dots", dots, ci + 3, 0.001, cyclic=True)
