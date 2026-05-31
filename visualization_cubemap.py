###
#Emma Krompascikova
#xkromp00
#Visualizes Cube Shadow Maps: six 90-degree perspective frustums around a point light.
###

import bpy
import math
from mathutils import Vector, Matrix

from .visualization_2d import get_gp_material, draw_strokes
from .visualization_3d import make_circle_on_surface

COL_CUBEMAP_NAME = "ShadowMap_Cubemap"
GP_CUBEMAP_NAME  = "SM_Viz_Cubemap"
CUBE_CAM_NAME    = "SM_CubeFace_Cam"

_saved_cube_cam_state = {}

#6 cube map faces in standard order: +X, -X, +Y, -Y, +Z, -Z
FACE_DIRS = [
    Vector(( 1,  0,  0)),
    Vector((-1,  0,  0)),
    Vector(( 0,  1,  0)),
    Vector(( 0, -1,  0)),
    Vector(( 0,  0,  1)),
    Vector(( 0,  0, -1)),
]
FACE_NAMES  = ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]
FACE_COLORS = [
    (0.9, 0.2, 0.2, 1.0),  #+x  red
    (0.2, 0.8, 0.8, 1.0),  #-x  cyan
    (0.2, 0.85, 0.2, 1.0), #+y  green
    (0.8, 0.2, 0.8, 1.0),  #-y  magenta
    (0.2, 0.4, 0.9, 1.0),  #+z  blue
    (0.9, 0.6, 0.1, 1.0),  #-z  orange
]

NEAR_CLIP = 0.3


def get_cubemap_collection():
    if COL_CUBEMAP_NAME in bpy.data.collections:
        return bpy.data.collections[COL_CUBEMAP_NAME]
    col = bpy.data.collections.new(COL_CUBEMAP_NAME)
    bpy.context.scene.collection.children.link(col)
    return col


def clear_cubemap_objects():
    if COL_CUBEMAP_NAME not in bpy.data.collections:
        return
    col = bpy.data.collections[COL_CUBEMAP_NAME]
    for obj in list(col.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def get_cubemap_grease_pencil():
    col = get_cubemap_collection()
    if GP_CUBEMAP_NAME in bpy.data.objects and GP_CUBEMAP_NAME in col.objects:
        obj     = bpy.data.objects[GP_CUBEMAP_NAME]
        gp_data = obj.data
        for layer in list(gp_data.layers):
            gp_data.layers.remove(layer)
        gp_data.materials.clear()
        obj.show_in_front = False
        return obj
    gp_data = bpy.data.grease_pencils.new(GP_CUBEMAP_NAME + "_Data")
    obj     = bpy.data.objects.new(GP_CUBEMAP_NAME, gp_data)
    col.objects.link(obj)
    obj.show_in_front = False
    return obj


def get_face_axes(face_dir):
    #tangent frame for the given face direction
    ref   = Vector((0, 0, 1)) if abs(face_dir.z) < 0.9 else Vector((1, 0, 0))
    right = face_dir.cross(ref).normalized()
    up    = face_dir.cross(right).normalized()
    return right, up


def get_face_index(v):
    #dominant-axis face selection, mirroring GPU cube map lookup
    ax, ay, az = abs(v.x), abs(v.y), abs(v.z)
    if ax >= ay and ax >= az:
        return 0 if v.x >= 0 else 1
    elif ay >= ax and ay >= az:
        return 2 if v.y >= 0 else 3
    else:
        return 4 if v.z >= 0 else 5


def draw_frustum(gp_data, layer_name, apex, face_dir, d_near, d_far, mat_idx, thickness, shrink=0.97):
    #shrink < 1 keeps each face color visible (prevents all 6 sharing the same 8 cube corners)
    right, up = get_face_axes(face_dir)

    def face_corners(d):
        c    = apex + face_dir * d
        half = d * shrink
        return [
            c + right * half + up * half,
            c - right * half + up * half,
            c - right * half - up * half,
            c + right * half - up * half,
        ]

    near = face_corners(d_near)
    far  = face_corners(d_far)

    edges = [
        [near[0], near[1]], [near[1], near[2]], [near[2], near[3]], [near[3], near[0]],
        [far[0],  far[1]],  [far[1],  far[2]],  [far[2],  far[3]],  [far[3],  far[0]],
        [near[0], far[0]],  [near[1], far[1]],  [near[2], far[2]],  [near[3], far[3]],
    ]
    draw_strokes(gp_data, layer_name, edges, mat_idx, thickness)


def generate_cubemap(context):
    props     = context.scene.sm_props
    light_obj = props.cubemap_light_object

    if not light_obj or light_obj.type != 'LIGHT':
        return
    if light_obj.data.type != 'POINT':
        return

    light_pos = light_obj.matrix_world.translation.copy()
    d_far     = props.cubemap_max_distance
    d_near    = min(NEAR_CLIP, d_far * 0.1)
    depsgraph = context.evaluated_depsgraph_get()

    clear_cubemap_objects()
    gp_obj  = get_cubemap_grease_pencil()
    gp_data = gp_obj.data

    for fi, color in enumerate(FACE_COLORS):
        get_gp_material(gp_data, f"SMViz_Cube_{fi}",      color)
    for fi, color in enumerate(FACE_COLORS):
        get_gp_material(gp_data, f"SMViz_Cube_{fi}_Fill", color, use_fill=True)

    show_frustums = props.show_cubemap_frustums
    show_dots     = props.show_cubemap_dots
    show_rays     = props.show_cubemap_rays
    steps         = props.cubemap_dot_steps
    dot_size      = props.cubemap_dot_size
    ray_width     = props.cubemap_ray_width

    for fi, face_dir in enumerate(FACE_DIRS):
        if show_frustums:
            draw_frustum(gp_data, f"Face_{FACE_NAMES[fi]}",
                         light_pos, face_dir, d_near, d_far, fi, 0.02,
                         shrink=0.993)

        if not show_dots and not show_rays:
            continue

        right, up = get_face_axes(face_dir)
        dots = []
        rays = []

        for ix in range(-steps, steps + 1):
            for iy in range(-steps, steps + 1):
                fx = ix / max(steps, 1)
                fy = iy / max(steps, 1)
                ray_dir = (face_dir + right * fx + up * fy).normalized()
                #project onto the flat face end-cap so endpoints stay on the square, not a sphere
                t_face   = d_far / ray_dir.dot(face_dir)
                ray_end  = light_pos + ray_dir * t_face
                dot_here = False

                result, loc, normal, _, _, _ = context.scene.ray_cast(
                    depsgraph, light_pos, ray_dir)

                dot_normal = normal

                if result:
                    depth = (loc - light_pos).dot(face_dir)
                    if depth <= d_far:
                        ray_end = loc
                        if get_face_index(ray_dir) == fi:
                            dot_here = True
                            #offset circle toward the light regardless of normal orientation
                            dot_normal = normal if normal.dot(light_pos - loc) >= 0 else -normal

                if show_rays and dot_here:
                    rays.append([light_pos.copy(), ray_end])
                if show_dots and dot_here:
                    dots.append(make_circle_on_surface(loc + dot_normal * 0.002, dot_normal, dot_size))

        if dots:
            draw_strokes(gp_data, f"Dots_{FACE_NAMES[fi]}", dots, fi + 6, 0.001, cyclic=True)
        if rays:
            draw_strokes(gp_data, f"Rays_{FACE_NAMES[fi]}", rays, fi, ray_width)


#---- face-view camera ----

def enter_face_cam_view(context, light_obj, face_idx):
    global _saved_cube_cam_state

    light_pos = light_obj.matrix_world.translation.copy()
    face_dir  = FACE_DIRS[face_idx]
    right, up = get_face_axes(face_dir)

    render = context.scene.render
    _saved_cube_cam_state = {
        'scene_camera': context.scene.camera,
        'res_x': render.resolution_x,
        'res_y': render.resolution_y,
    }
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            r3d = area.spaces[0].region_3d
            _saved_cube_cam_state['perspective'] = r3d.view_perspective
            _saved_cube_cam_state['distance']    = r3d.view_distance
            _saved_cube_cam_state['location']    = r3d.view_location.copy()
            _saved_cube_cam_state['rotation']    = r3d.view_rotation.copy()
            break

    #force square resolution so the camera shows a true 90x90 view
    render.resolution_x = 1024
    render.resolution_y = 1024

    #camera -Z points toward face_dir
    rot = Matrix((
        (right.x,      right.y,      right.z     ),
        (up.x,         up.y,         up.z        ),
        (-face_dir.x,  -face_dir.y,  -face_dir.z ),
    )).transposed().to_4x4()
    rot.translation = light_pos

    cam_data             = bpy.data.cameras.new(CUBE_CAM_NAME + "_Data")
    cam_data.type        = 'PERSP'
    cam_data.sensor_fit  = 'VERTICAL'   #vertical FOV = 90 regardless of viewport aspect
    cam_data.angle       = math.radians(90)
    cam_data.clip_start  = 0.01
    cam_data.clip_end    = 1000.0

    cam_obj = bpy.data.objects.new(CUBE_CAM_NAME, cam_data)
    context.scene.collection.objects.link(cam_obj)
    cam_obj.matrix_world = rot

    context.scene.camera = cam_obj
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            for region in area.regions:
                if region.type == 'WINDOW':
                    with context.temp_override(area=area, region=region):
                        bpy.ops.view3d.view_camera()
                    break
            break


def exit_face_cam_view(context):
    global _saved_cube_cam_state

    context.scene.camera = _saved_cube_cam_state.get('scene_camera')

    render = context.scene.render
    render.resolution_x = _saved_cube_cam_state.get('res_x', render.resolution_x)
    render.resolution_y = _saved_cube_cam_state.get('res_y', render.resolution_y)

    if CUBE_CAM_NAME in bpy.data.objects:
        cam_obj  = bpy.data.objects[CUBE_CAM_NAME]
        cam_data = cam_obj.data
        bpy.data.objects.remove(cam_obj, do_unlink=True)
        if cam_data and cam_data.name in bpy.data.cameras:
            bpy.data.cameras.remove(cam_data)

    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            r3d = area.spaces[0].region_3d
            for region in area.regions:
                if region.type == 'WINDOW':
                    with context.temp_override(area=area, region=region):
                        if r3d.view_perspective == 'CAMERA':
                            bpy.ops.view3d.view_camera()
                    break
            r3d.view_perspective = _saved_cube_cam_state.get('perspective', 'PERSP')
            r3d.view_distance    = _saved_cube_cam_state.get('distance', 10.0)
            loc = _saved_cube_cam_state.get('location')
            if loc:
                r3d.view_location = loc
            rot = _saved_cube_cam_state.get('rotation')
            if rot:
                r3d.view_rotation = rot
            break

    _saved_cube_cam_state = {}
