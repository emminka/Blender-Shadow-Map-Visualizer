###
#Emma Krompascikova
#xkromp00
#2D visualization of shadow acne and bias.
###

import bpy
import math
from mathutils import Vector, Matrix

EPSILON   = 1e-6  #small enough to avoid fp issues
MAX_SLOPE = 4.0   #~76 deg, beyond this bias gets too large

COL_NAME    = "ShadowMap_Viz"
GP_OBJ_NAME = "SM_Viz_GreasePencil"

COLOR_YELLOW       = (1.0, 0.7,  0.0, 1.0)
COLOR_BLACK        = (0.0, 0.0,  0.0, 1.0)
COLOR_WHITE        = (1.0, 1.0,  1.0, 1.0)
COLOR_ORANGE = (1.0, 0.45, 0.0, 1.0)
COLOR_GREY         = (0.5, 0.5,  0.5, 1.0)


def get_collection():
    if COL_NAME in bpy.data.collections:
        return bpy.data.collections[COL_NAME]
    col = bpy.data.collections.new(COL_NAME)
    bpy.context.scene.collection.children.link(col)
    return col


def clear_old_objects():
    col = get_collection()
    for obj in list(col.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def get_grease_pencil_object():
    col = get_collection()

    if GP_OBJ_NAME in col.objects:
        obj = col.objects[GP_OBJ_NAME]
        gp_data = obj.data
        #list() so i dont modify while iterating
        for layer in list(gp_data.layers):
            gp_data.layers.remove(layer)
        gp_data.materials.clear()
        return obj

    gp_data = bpy.data.grease_pencils.new(GP_OBJ_NAME + "_Data")
    obj = bpy.data.objects.new(GP_OBJ_NAME, gp_data)
    col.objects.link(obj)
    return obj


def get_gp_material(gp_data, name, color, use_fill=False):
    #reuse existing material to avoid duplicates
    if name in bpy.data.materials:
        mat = bpy.data.materials[name]
    else:
        mat = bpy.data.materials.new(name=name)
        mat.use_nodes = False
        if not mat.is_grease_pencil:
            if hasattr(bpy.data.materials, "create_gpencil_data"):
                bpy.data.materials.create_gpencil_data(mat)
            else:
                print(f"[ShadowMapViz] Warning: create_gpencil_data not found for '{name}'."
                      " Material may not render correctly in this Blender version.")

    #GP v3: grease_pencil may be missing if material init failed
    try:
        gp = mat.grease_pencil
    except AttributeError:
        print(f"[ShadowMapViz] Error: mat.grease_pencil inaccessible for '{name}'.")
        gp_data.materials.append(mat)
        return mat

    if bpy.app.version >= (5, 1, 0):
        #5.1+: show_fill/show_stroke removed from materials; fill is per-stroke via fill_id.
        #set both color slots so the right one is available regardless of stroke type.
        try:
            gp.color      = color
            gp.fill_color = color
        except AttributeError:
            pass
    else:
        if use_fill:
            gp.show_stroke = False
            gp.show_fill   = True
            gp.fill_color  = color
        else:
            gp.show_stroke = True
            gp.show_fill   = False
            gp.color       = color

    gp_data.materials.append(mat)
    return mat


def draw_strokes(gp_data, layer_name, strokes, material_index=0, thickness=0.05, cyclic=False):
    if not strokes:
        return

    layer = gp_data.layers.get(layer_name)
    if not layer:
        layer = gp_data.layers.new(name=layer_name)

    frame = layer.frames.new(1)
    drawing = frame.drawing

    drawing.add_strokes([len(s) for s in strokes])

    #5.1+: fill is per-stroke via fill_id; detect fill materials by "Fill" in name
    is_fill_mat = (
        bpy.app.version >= (5, 1, 0)
        and cyclic
        and material_index < len(gp_data.materials)
        and gp_data.materials[material_index] is not None
        and "Fill" in gp_data.materials[material_index].name
    )

    for i, pts in enumerate(strokes):
        stroke = drawing.strokes[i]
        stroke.material_index = material_index
        stroke.cyclic = cyclic
        if is_fill_mat:
            try:
                stroke.fill_id     = i + 1  #unique per stroke -- same fill_id triangulates together
                stroke.hide_stroke = True
            except AttributeError:
                pass
        for j, p in enumerate(pts):
            stroke.points[j].position = p
            stroke.points[j].radius   = thickness


def add_arrow_head(tip_pos, direction, size=0.5):
    dir_norm = direction.normalized()
    back = -dir_norm * size
    right = Vector((-dir_norm.z, 0.0, dir_norm.x)) * (size * 0.5)
    p1 = tip_pos + back + right
    p2 = tip_pos + back - right
    return [p1, tip_pos, p2]


def intersect_ray_segment(ray_start, ray_dir, pA, pB):
    #2d ray-segment intersection in xz plane; returns t along ray or -1 if no hit
    dx = pB.x - pA.x
    dz = pB.z - pA.z

    denom = ray_dir.x * dz - ray_dir.z * dx
    if abs(denom) < EPSILON:
        return -1.0  #parallel

    diff_x = pA.x - ray_start.x
    diff_z = pA.z - ray_start.z

    t = (diff_x * dz - diff_z * dx) / denom
    u = (diff_x * ray_dir.z - diff_z * ray_dir.x) / denom  #position along segment

    if 0.0 <= u <= 1.0 and t > EPSILON:
        return t
    return -1.0


def ray_cast_scene(ray_start, ray_dir, scene_segments):
    closest_t = float('inf')
    hit_normal = None
    hit_pA = None
    hit_pB = None

    for pA, pB, norm in scene_segments:
        t = intersect_ray_segment(ray_start, ray_dir, pA, pB)
        if t > 0 and t < closest_t:
            closest_t = t
            hit_normal = norm
            hit_pA = pA
            hit_pB = pB

    if closest_t == float('inf'):
        return None, None, None, None

    hit_point = ray_start + ray_dir * closest_t
    return hit_point, hit_normal, hit_pA, hit_pB



def check_shadow(test_pt, shadow_map_dict, light_origin, main_dir, light_right, mode, proj_dist, texel_size):
    vec = test_pt - light_origin

    if mode == 'POINT':
        z_depth = vec.dot(main_dir)
        if z_depth < EPSILON:
            return False
        offset = vec.dot(light_right) / z_depth * proj_dist
    else:
        offset = vec.dot(light_right)

    bucket_index = round(offset / texel_size)
    if bucket_index not in shadow_map_dict:
        return False

    if mode == 'POINT':
        #project onto the actual ray direction of this bucket to avoid false acne on flat perpendicular surfaces
        ray_dir_i = (main_dir * proj_dist + light_right * (bucket_index * texel_size)).normalized()
        my_dist = vec.dot(ray_dir_i)
    else:
        my_dist = vec.dot(main_dir)

    sm_dist = shadow_map_dict[bucket_index]
    return my_dist > sm_dist + 1e-4


def generate_shadow_acne(context):
    props = context.scene.sm_props

    angle = props.light_angle
    texel_size = props.texel_size
    height = props.light_distance
    shift_x = props.light_shift_x
    steps = props.shadow_map_steps
    mode = props.light_type

    bias_min = props.bias_min
    bias_slope = props.bias_slope

    t_floor = props.thick_floor
    t_ray = props.thick_rays

    w = props.floor_width

    clear_old_objects()
    gp_obj = get_grease_pencil_object()
    gp_data = gp_obj.data

    #material slots -- order matters, index = slot position
    get_gp_material(gp_data, "SMViz_White_Fill",   COLOR_WHITE,        use_fill=True)
    get_gp_material(gp_data, "SMViz_Yellow",       COLOR_YELLOW)
    get_gp_material(gp_data, "SMViz_Black",        COLOR_BLACK)
    get_gp_material(gp_data, "SMViz_Orange",  COLOR_ORANGE)

    IDX_WHITE        = 0
    IDX_YELLOW       = 1
    IDX_BLACK        = 2
    IDX_ORANGE = 3

    IDX_RAY = IDX_ORANGE if props.rays_yellow else IDX_BLACK

    #each segment: (pA, pB, outward normal)
    scene_segments = []

    if props.show_box:
        bw = props.box_width
        bh = props.box_height
        bx = props.box_x

        scene_segments.extend([
            (Vector((-w,        0, 0)),  Vector((bx - bw/2, 0, 0)),  Vector((0, 0, 1))),   #floor left
            (Vector((bx-bw/2,   0, 0)),  Vector((bx - bw/2, 0, bh)), Vector((-1, 0, 0))),  #box left wall
            (Vector((bx-bw/2,   0, bh)), Vector((bx + bw/2, 0, bh)), Vector((0, 0, 1))),   #box top
            (Vector((bx+bw/2,   0, bh)), Vector((bx + bw/2, 0, 0)),  Vector((1, 0, 0))),   #box right wall
            (Vector((bx+bw/2,   0, 0)),  Vector((w,          0, 0)),  Vector((0, 0, 1))),   #floor right
        ])
    else:
        bw = 0.0
        bh = 0.0
        bx = 0.0
        scene_segments.append((Vector((-w, 0, 0)), Vector((w, 0, 0)), Vector((0, 0, 1))))

    rot_mat = Matrix.Rotation(angle, 4, 'Y')
    main_dir = rot_mat @ Vector((0, 0, -1))

    #light_right is perpendicular to light dir -- the shadow map's horizontal axis
    light_right = Vector((main_dir.z, 0, -main_dir.x))

    if mode == 'POINT':
        light_origin = Vector((shift_x, 0, height))
    else:
        #sun: place origin far behind so rays are parallel
        light_origin = -main_dir * 40

    projection_dist = 5.0

    strokes_rays = []
    zig_strokes  = []  #completed zigzag segments
    zig_current  = []  #zigzag segment currently being built
    shadow_map_dict = {}

    #+1 ensures the last boundary texel is always included
    for i in range(-steps, steps + 1):
        offset = i * texel_size

        if mode == 'POINT':
            target_point = light_origin + (main_dir * projection_dist) + (light_right * offset)
            ray_dir = (target_point - light_origin).normalized()
            ray_start = light_origin
        else:
            ray_start = light_origin + (light_right * offset)
            ray_dir = main_dir

        hit, norm, seg_pA, seg_pB = ray_cast_scene(ray_start, ray_dir, scene_segments)

        if not hit:
            #flush current zigzag on miss (gap in coverage)
            if zig_current:
                zig_strokes.append(zig_current)
                zig_current = []
            continue

        ndotl = max(norm.dot(-ray_dir), 0.0001)
        slope = math.sqrt(max(0.0, 1.0 - ndotl**2)) / ndotl
        slope = min(slope, MAX_SLOPE)  #clamp to avoid huge bias at grazing angles

        bias = (bias_min + bias_slope * slope) * texel_size

        #shift hit point slightly toward the light
        biased = hit + ray_dir * bias

        if mode == 'POINT':
            dist = (biased - ray_start).length
        else:
            dist = (biased - light_origin).dot(main_dir)
        shadow_map_dict[i] = dist

        perp = Vector((-ray_dir.z, 0, ray_dir.x)).normalized()

        pL = biased + perp * texel_size * 0.5
        pR = biased - perp * texel_size * 0.5

        is_wall = (abs(norm.z) < 0.3)  #near-vertical surface

        if is_wall and mode == 'POINT':
            #skip tooth for wall surfaces in POINT mode (looks like random dashes)
            #don't flush zig_current so zigzag stays connected across the box
            pass
        else:
            zig_current.append(pL)
            zig_current.append(pR)

        rf = props.ray_frequency
        should_draw_ray = False
        if rf == '1':
            should_draw_ray = True
        elif rf == '2':
            should_draw_ray = (i % 2 == 0)
        elif rf == '3':
            should_draw_ray = (i % 3 == 0)

        if should_draw_ray:
            strokes_rays.append([ray_start, biased])
            arrow = add_arrow_head(biased, ray_dir, size=0.4)
            strokes_rays.append(arrow)

    if zig_current:
        zig_strokes.append(zig_current)

    yellow_segments = []
    black_segments  = []

    for pA, pB, normal in scene_segments:
        length = (pB - pA).length
        if length < EPSILON:
            continue

        sample_steps = int(length / 0.05) + 2
        curr_segment_start = pA

        def eval_shadow(pt, norm):
            if mode == 'SUN':
                ldir = main_dir
            else:
                ldir = (pt - light_origin).normalized()
            #surfaces facing away from the light are always in shadow
            if norm.dot(-ldir) <= 0.0001:
                return True
            return check_shadow(pt, shadow_map_dict, light_origin, main_dir, light_right, mode, projection_dist, texel_size)

        prev_shadow = eval_shadow(pA, normal)
        prev_pt = pA

        for i in range(1, sample_steps + 1):
            t = min(1.0, i / sample_steps)
            curr_pt = pA + (pB - pA) * t
            curr_shadow = eval_shadow(curr_pt, normal)

            if curr_shadow != prev_shadow:
                #binary search for exact shadow boundary
                lo_pt = prev_pt
                hi_pt = curr_pt
                for _ in range(10):
                    mid_pt = (lo_pt + hi_pt) * 0.5
                    if eval_shadow(mid_pt, normal) == prev_shadow:
                        lo_pt = mid_pt
                    else:
                        hi_pt = mid_pt
                boundary = hi_pt

                if prev_shadow:
                    black_segments.append([curr_segment_start, boundary])
                else:
                    yellow_segments.append([curr_segment_start, boundary])
                curr_segment_start = boundary
                prev_shadow = curr_shadow

            elif i == sample_steps:
                if prev_shadow:
                    black_segments.append([curr_segment_start, curr_pt])
                else:
                    yellow_segments.append([curr_segment_start, curr_pt])

            prev_pt = curr_pt

    #zigzag thickness scales with texel size for consistent proportions
    t_zig = texel_size * 0.04

    #two separate background strokes avoids GP fill artifacts at concave box corners
    bg_shapes = [[Vector((-w,0,-2.0)), Vector((-w,0,0)), Vector((w,0,0)), Vector((w,0,-2.0))]]
    if props.show_box:
        bg_shapes.append([Vector((bx-bw/2,0,0)), Vector((bx-bw/2,0,bh)),
                          Vector((bx+bw/2,0,bh)), Vector((bx+bw/2,0,0))])
    draw_strokes(gp_data, "00_Background", bg_shapes, IDX_WHITE, 0.001, cyclic=True)
    draw_strokes(gp_data, "01_Floor_Yellow", yellow_segments, IDX_YELLOW, t_floor)
    draw_strokes(gp_data, "02_Floor_Black",  black_segments,  IDX_BLACK,  t_floor)
    draw_strokes(gp_data, "03_Rays",         strokes_rays,    IDX_RAY,    t_ray)
    if zig_strokes:
        draw_strokes(gp_data, "04_ZigZag",   zig_strokes,     IDX_YELLOW, t_zig)
