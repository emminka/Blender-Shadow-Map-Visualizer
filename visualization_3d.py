###
#Emma Krompascikova
#xkromp00
#3D shadow ray visualization and shared scene utilities (hide/restore, viewport state, PCF kernel sampling).
###

import bpy
import math
from mathutils import Vector

from .visualization_2d import get_gp_material, draw_strokes, COLOR_YELLOW, COLOR_BLACK, COLOR_GREY

COL_3D_NAME    = "ShadowMap_3D"
GP_3D_NAME     = "SM_Viz_3D_Rays"
GP_3D_SQ_NAME  = "SM_Viz_3D_Squares"
LIGHT_CAM_NAME = "SM_LightViewCamera"

_hidden_objects_state  = {}
_saved_viewport        = {}
_saved_light_cam_state = {}


def hide_scene_objects():
    global _hidden_objects_state
    _hidden_objects_state = {}
    from .visualization_2d import COL_NAME as COL_2D_NAME
    our_names = set()
    for col_name in (COL_2D_NAME, COL_3D_NAME):
        if col_name in bpy.data.collections:
            for obj in bpy.data.collections[col_name].objects:
                our_names.add(obj.name)

    for obj in bpy.context.scene.objects:
        if obj.name in our_names:
            continue
        _hidden_objects_state[obj.name] = obj.hide_viewport
        obj.hide_viewport = True


def restore_scene_objects():
    global _hidden_objects_state
    for obj_name, was_hidden in _hidden_objects_state.items():
        if obj_name in bpy.data.objects:
            bpy.data.objects[obj_name].hide_viewport = was_hidden
    _hidden_objects_state = {}


def save_viewport_state(context):
    global _saved_viewport
    _saved_viewport = {}
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            space = area.spaces[0]
            r3d = space.region_3d
            _saved_viewport = {
                'perspective':  r3d.view_perspective,
                'distance':     r3d.view_distance,
                'location':     r3d.view_location.copy(),
                'rotation':     r3d.view_rotation.copy(),
                'show_cursor':  space.overlay.show_cursor,
            }
            break


def restore_viewport_state(context):
    global _saved_viewport
    if not _saved_viewport:
        return
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            space = area.spaces[0]
            r3d = space.region_3d
            r3d.view_perspective = _saved_viewport.get('perspective', 'PERSP')
            r3d.view_distance    = _saved_viewport.get('distance', 10.0)
            loc = _saved_viewport.get('location')
            if loc:
                r3d.view_location = loc
            rot = _saved_viewport.get('rotation')
            if rot:
                r3d.view_rotation = rot
            space.overlay.show_cursor = _saved_viewport.get('show_cursor', True)
            break
    _saved_viewport = {}


def get_3d_collection():
    if COL_3D_NAME in bpy.data.collections:
        return bpy.data.collections[COL_3D_NAME]
    col = bpy.data.collections.new(COL_3D_NAME)
    bpy.context.scene.collection.children.link(col)
    return col


def clear_3d_objects():
    if COL_3D_NAME not in bpy.data.collections:
        return
    col = bpy.data.collections[COL_3D_NAME]
    for obj in list(col.objects):
        bpy.data.objects.remove(obj, do_unlink=True)



def get_3d_grease_pencil_object():
    col = get_3d_collection()
    if GP_3D_NAME in col.objects:
        obj = col.objects[GP_3D_NAME]
        gp_data = obj.data
        for layer in list(gp_data.layers):
            gp_data.layers.remove(layer)
        gp_data.materials.clear()
        return obj
    gp_data = bpy.data.grease_pencils.new(GP_3D_NAME + "_Data")
    obj = bpy.data.objects.new(GP_3D_NAME, gp_data)
    col.objects.link(obj)
    return obj


def get_3d_squares_gp_object():
    col = get_3d_collection()
    if GP_3D_SQ_NAME in col.objects:
        obj = col.objects[GP_3D_SQ_NAME]
        gp_data = obj.data
        for layer in list(gp_data.layers):
            gp_data.layers.remove(layer)
        gp_data.materials.clear()
        return obj
    gp_data = bpy.data.grease_pencils.new(GP_3D_SQ_NAME + "_Data")
    obj = bpy.data.objects.new(GP_3D_SQ_NAME, gp_data)
    col.objects.link(obj)
    return obj


def compute_scene_bounds(context):
    from .visualization_2d import COL_NAME as COL_2D_NAME

    min_co = Vector(( float('inf'),  float('inf'),  float('inf')))
    max_co = Vector((-float('inf'), -float('inf'), -float('inf')))
    found = False

    for obj in context.scene.objects:
        if obj.type != 'MESH' or obj.hide_viewport:
            continue
        is_ours = any(c.name in (COL_2D_NAME, COL_3D_NAME) for c in obj.users_collection)
        if is_ours:
            continue

        found = True
        for corner in obj.bound_box:
            wc = obj.matrix_world @ Vector(corner)
            min_co.x = min(min_co.x, wc.x)
            min_co.y = min(min_co.y, wc.y)
            min_co.z = min(min_co.z, wc.z)
            max_co.x = max(max_co.x, wc.x)
            max_co.y = max(max_co.y, wc.y)
            max_co.z = max(max_co.z, wc.z)

    if not found:
        return Vector((0, 0, 0)), 5.0

    center = (min_co + max_co) / 2
    half_size = max((max_co - min_co).length / 2, 1.0)
    return center, half_size


def make_circle_on_surface(center, normal, radius, segments=16):
    ref = Vector((0, 0, 1)) if abs(normal.z) < 0.9 else Vector((1, 0, 0))
    t1 = ref.cross(normal).normalized()
    t2 = normal.cross(t1).normalized()
    return [
        center + (t1 * math.cos(2 * math.pi * i / segments) + t2 * math.sin(2 * math.pi * i / segments)) * radius
        for i in range(segments)
    ]


def make_square_on_surface(center, normal, half_size):
    ref = Vector((0, 0, 1)) if abs(normal.z) < 0.9 else Vector((1, 0, 0))
    t1 = ref.cross(normal).normalized()
    t2 = normal.cross(t1).normalized()
    return [
        center + t1 * half_size + t2 * half_size,
        center - t1 * half_size + t2 * half_size,
        center - t1 * half_size - t2 * half_size,
        center + t1 * half_size - t2 * half_size,
    ]


def make_texel_footprint(center, normal, light_right, light_dir, texel_d):
    light_up = light_right.cross(light_dir).normalized()
    ndotl = light_dir.dot(normal)

    if abs(ndotl) < 1e-5:
        ndotl = 1e-5 if ndotl >= 0 else -1e-5

    half = texel_d / 2.0
    corners = []

    for dx, dy in [(-1, 1), (1, 1), (1, -1), (-1, -1)]:
        offset = light_right * (dx * half) + light_up * (dy * half)
        t = -normal.dot(offset) / ndotl
        pt = center + offset + light_dir * t
        corners.append(pt)

    return corners



def generate_3d_rays(context):
    props = context.scene.sm_props
    light_obj = props.light_object

    if not light_obj or light_obj.type != 'LIGHT':
        return

    steps = props.ray_grid_steps_3d
    light_data = light_obj.data
    light_type = light_data.type

    #all blender lights point along local -Z
    quat = light_obj.matrix_world.to_quaternion()
    light_dir   = (quat @ Vector((0,  0, -1))).normalized()
    light_right = (quat @ Vector((1,  0,  0))).normalized()
    light_up    = (quat @ Vector((0,  1,  0))).normalized()
    light_pos   = light_obj.matrix_world.translation.copy()

    depsgraph = context.evaluated_depsgraph_get()

    def cast_ray(ray_start, ray_dir):
        #fires a primary ray then a secondary ray to find lit and shadowed hits
        result, loc1, norm1, _, hit_obj1, _ = context.scene.ray_cast(depsgraph, ray_start, ray_dir)
        if not result:
            return None, None, None, None, None, None
        loc2 = norm2 = hit_obj2 = None
        nxt = loc1 + ray_dir * 0.001
        for _ in range(8):
            #loop past back-faces of the same object to find a different object behind
            r2, l2, n2, _, obj2_candidate, _ = context.scene.ray_cast(depsgraph, nxt, ray_dir)
            if not r2:
                break
            if obj2_candidate != hit_obj1:
                #shadow test: cast toward the light -- blocked = genuinely in shadow
                if light_type == 'SUN':
                    toward_light = -light_dir
                else:
                    toward_light = (light_pos - l2).normalized()
                shadow_blocked, _, _, _, _, _ = context.scene.ray_cast(
                    depsgraph, l2 + toward_light * 0.001, toward_light)
                if shadow_blocked:
                    loc2, norm2, hit_obj2 = l2, n2, obj2_candidate
                break
            nxt = l2 + ray_dir * 0.001  #same object (back face) -- advance past it
        return loc1, norm1, loc2, norm2, hit_obj1, hit_obj2

    #---- main ray grid ----

    lit_rays     = []
    lit_dots     = []
    lit_squares  = []       #all grid positions for binary display
    lit_sq_pcf   = []       #strided positions for PCF display
    shad_rays    = []
    shad_dots    = []
    shad_squares = []
    shad_sq_pcf  = []

    show_squares = props.show_squares_3d
    show_pcf     = props.show_pcf_3d

    rf = props.ray_frequency_3d
    stride = int(rf) if rf != '0' else 0

    #grid-based PCF data -- only populated for SUN and SPOT (regular grids)
    grid_shadow   = {}   #(ix,iy) -> bool
    grid_obj1     = {}   #(ix,iy) -> primary hit object
    grid_obj2     = {}   #(ix,iy) -> secondary hit object (shadowed only)
    lit_grid_idx  = []   #(ix,iy) for each entry in lit_dots
    shad_grid_idx = []   #(ix,iy) for each entry in shad_dots

    if light_type == 'SUN':
        center, half_size = compute_scene_bounds(context)

        grid_size   = props.ray_grid_size_3d
        ray_length  = props.ray_length_3d
        texel_d     = grid_size / max(steps, 1)

        for ix in range(-steps, steps + 1):
            for iy in range(-steps, steps + 1):
                fx = ix / max(steps, 1)
                fy = iy / max(steps, 1)
                grid_point   = (center
                                + light_right * (fx * grid_size)
                                + light_up    * (fy * grid_size))
                ray_origin   = grid_point - light_dir * 200
                visual_start = grid_point - light_dir * ray_length

                loc1, norm1, loc2, norm2, obj1, obj2 = cast_ray(ray_origin, light_dir)
                if loc1 is None:
                    continue

                grid_shadow[(ix, iy)] = (loc2 is not None)
                grid_obj1[(ix, iy)]   = obj1
                if obj2 is not None:
                    grid_obj2[(ix, iy)] = obj2

                if show_squares:
                    lit_squares.append(make_texel_footprint(loc1 + norm1 * 0.01, norm1, light_right, light_dir, texel_d))
                    if loc2 is not None:
                        shad_squares.append(make_texel_footprint(loc2 + norm2 * 0.01, norm2, light_right, light_dir, texel_d))

                if stride == 0 or ix % stride != 0 or iy % stride != 0:
                    continue
                lit_rays.append([visual_start, loc1])
                lit_dots.append(make_circle_on_surface(loc1 + norm1 * 0.002, norm1, props.dot_size_3d))
                lit_grid_idx.append((ix, iy))
                if show_squares:
                    lit_sq_pcf.append(make_texel_footprint(loc1 + norm1 * 0.01, norm1, light_right, light_dir, texel_d))
                if loc2 is not None:
                    shad_rays.append([loc1, loc2])
                    shad_dots.append(make_circle_on_surface(loc2 + norm2 * 0.002, norm2, props.dot_size_3d))
                    shad_grid_idx.append((ix, iy))
                    if show_squares:
                        shad_sq_pcf.append(make_texel_footprint(loc2 + norm2 * 0.01, norm2, light_right, light_dir, texel_d))

    elif light_type == 'SPOT':
        half_angle  = light_data.spot_size / 2
        proj_dist   = 1.0
        max_offset  = math.tan(half_angle) * proj_dist

        for ix in range(-steps, steps + 1):
            for iy in range(-steps, steps + 1):
                fx = ix / max(steps, 1)
                fy = iy / max(steps, 1)
                if fx * fx + fy * fy > 1.0:
                    continue  #outside cone

                target  = (light_pos
                           + light_dir   * proj_dist
                           + light_right * (fx * max_offset)
                           + light_up    * (fy * max_offset))
                ray_dir = (target - light_pos).normalized()

                loc1, norm1, loc2, norm2, obj1, obj2 = cast_ray(light_pos, ray_dir)
                if loc1 is None:
                    continue

                grid_shadow[(ix, iy)] = (loc2 is not None)
                grid_obj1[(ix, iy)]   = obj1
                if obj2 is not None:
                    grid_obj2[(ix, iy)] = obj2

                if show_squares:
                    dist = (loc1 - light_pos).length
                    half = (max_offset / max(steps, 1)) * dist / proj_dist / 2
                    lit_squares.append(make_square_on_surface(loc1 + norm1 * 0.01, norm1, half))
                    if loc2 is not None:
                        dist2 = (loc2 - light_pos).length
                        half2 = (max_offset / max(steps, 1)) * dist2 / proj_dist / 2
                        shad_squares.append(make_square_on_surface(loc2 + norm2 * 0.01, norm2, half2))

                if stride == 0 or ix % stride != 0 or iy % stride != 0:
                    continue
                lit_rays.append([light_pos, loc1])
                lit_dots.append(make_circle_on_surface(loc1 + norm1 * 0.002, norm1, props.dot_size_3d))
                lit_grid_idx.append((ix, iy))
                if show_squares:
                    dist = (loc1 - light_pos).length
                    half = (max_offset / max(steps, 1)) * dist / proj_dist / 2
                    lit_sq_pcf.append(make_square_on_surface(loc1 + norm1 * 0.01, norm1, half))
                if loc2 is not None:
                    shad_rays.append([loc1, loc2])
                    shad_dots.append(make_circle_on_surface(loc2 + norm2 * 0.002, norm2, props.dot_size_3d))
                    shad_grid_idx.append((ix, iy))
                    if show_squares:
                        dist2 = (loc2 - light_pos).length
                        half2 = (max_offset / max(steps, 1)) * dist2 / proj_dist / 2
                        shad_sq_pcf.append(make_square_on_surface(loc2 + norm2 * 0.01, norm2, half2))

    else:
        #POINT and AREA: Fibonacci sphere sampling for uniform full-sphere coverage
        n_rays = steps * steps * 2
        golden = (1.0 + math.sqrt(5)) / 2  #golden ratio

        for i in range(n_rays):
            if stride == 0:
                continue
            if i % max(stride, 1) != 0:
                continue
            #uniform cos(theta) spacing avoids pole crowding
            cos_theta = 1.0 - 2.0 * (i + 0.5) / n_rays
            sin_theta = math.sqrt(max(0.0, 1.0 - cos_theta * cos_theta))
            phi       = 2.0 * math.pi * i / golden

            sx = sin_theta * math.cos(phi)
            sy = sin_theta * math.sin(phi)
            sz = cos_theta
            ray_dir = (light_right * sx + light_up * sy + light_dir * sz).normalized()

            loc1, norm1, loc2, norm2, *_ = cast_ray(light_pos, ray_dir)
            if loc1 is None:
                continue
            lit_rays.append([light_pos, loc1])
            lit_dots.append(make_circle_on_surface(loc1 + norm1 * 0.002, norm1, props.dot_size_3d))
            if loc2 is not None:
                shad_rays.append([loc1, loc2])
                shad_dots.append(make_circle_on_surface(loc2 + norm2 * 0.002, norm2, props.dot_size_3d))

    #---- draw everything as grease pencil strokes ----

    clear_3d_objects()

    gp_obj  = get_3d_grease_pencil_object()
    gp_data = gp_obj.data

    #slot 0 = yellow fill, slot 1 = black fill, slot 2 = yellow stroke, slot 3 = black stroke
    get_gp_material(gp_data, "SMViz_Yellow_3D_Fill", COLOR_YELLOW, use_fill=True)
    get_gp_material(gp_data, "SMViz_Black_3D_Fill",  COLOR_BLACK,  use_fill=True)
    get_gp_material(gp_data, "SMViz_Yellow_3D",      COLOR_YELLOW)
    get_gp_material(gp_data, "SMViz_Black_3D",       COLOR_BLACK)
    IDX_LIT_FILL  = 0
    IDX_SHAD_FILL = 1
    IDX_LIT       = 2
    IDX_SHAD      = 3

    if show_pcf:
        get_gp_material(gp_data, "SMViz_Grey_3D_Fill", COLOR_GREY, use_fill=True)
        get_gp_material(gp_data, "SMViz_Grey_3D",      COLOR_GREY)
        IDX_GREY_FILL = 4
        IDX_GREY      = 5

    if show_squares:
        sq_obj     = get_3d_squares_gp_object()
        sq_gp_data = sq_obj.data
        get_gp_material(sq_gp_data, "SMViz_Yellow_3D_Sq", COLOR_YELLOW)
        get_gp_material(sq_gp_data, "SMViz_Black_3D_Sq",  COLOR_BLACK)
        SQ_LIT  = 0
        SQ_SHAD = 1
        if show_pcf:
            get_gp_material(sq_gp_data, "SMViz_Grey_3D_Sq", COLOR_GREY)
            SQ_GREY = 2

    draw_lines = props.show_lines_3d

    if draw_lines and lit_rays:
        draw_strokes(gp_data, "Lit_Rays",  lit_rays,  IDX_LIT,  props.thick_rays_3d)
    if draw_lines and shad_rays:
        draw_strokes(gp_data, "Shad_Rays", shad_rays, IDX_SHAD, props.thick_rays_3d)

    if show_pcf:
        #PCF uses object identity so dots only count same-surface neighbors.
        #lit dot votes: neighbor's primary hit is a different object AND has my object as secondary (shadowed).
        #shadow dot votes: neighbor also has the same secondary object in shadow.
        def pcf_count_lit(ix, iy):
            my_obj = grid_obj1.get((ix, iy))
            return sum(
                1
                for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                if (ix+dx, iy+dy) in grid_obj1
                and grid_obj1[(ix+dx, iy+dy)] != my_obj
                and grid_obj2.get((ix+dx, iy+dy)) == my_obj
            )

        def pcf_count_shad(ix, iy):
            my_obj2 = grid_obj2.get((ix, iy))
            return sum(
                1
                for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                if grid_obj2.get((ix+dx, iy+dy)) == my_obj2
            )

        lit_votes  = [pcf_count_lit(ix, iy)  for ix, iy in lit_grid_idx]
        shad_votes = [pcf_count_shad(ix, iy) for ix, iy in shad_grid_idx]

        def classify(items, votes):
            y, g, b = [], [], []
            for item, v in zip(items, votes):
                if v == 0:    y.append(item)
                elif v >= 9:  b.append(item)
                else:         g.append(item)
            return y, g, b

        yl, gl, bl = classify(lit_dots,  lit_votes)
        ys, gs, bs = classify(shad_dots, shad_votes)
        yellow_dots = yl + ys
        grey_dots   = gl + gs
        black_dots  = bl + bs

        yellow_rays, grey_lit_rays,  black_lit_rays  = classify(lit_rays,  lit_votes)
        yellow_shad, grey_shad_rays, black_shad_rays = classify(shad_rays, shad_votes)

        if draw_lines:
            if yellow_rays:
                draw_strokes(gp_data, "PCF_Rays_Lit",      yellow_rays,    IDX_LIT,  props.thick_rays_3d)
            if grey_lit_rays:
                draw_strokes(gp_data, "PCF_Rays_Grey_Lit", grey_lit_rays,  IDX_GREY, props.thick_rays_3d)
            if black_lit_rays:
                draw_strokes(gp_data, "PCF_Rays_Blk_Lit",  black_lit_rays, IDX_SHAD, props.thick_rays_3d)
            if yellow_shad:
                draw_strokes(gp_data, "PCF_SRays_Lit",     yellow_shad,    IDX_LIT,  props.thick_rays_3d)
            if grey_shad_rays:
                draw_strokes(gp_data, "PCF_SRays_Grey",    grey_shad_rays, IDX_GREY, props.thick_rays_3d)
            if black_shad_rays:
                draw_strokes(gp_data, "PCF_SRays_Blk",     black_shad_rays,IDX_SHAD, props.thick_rays_3d)

        if yellow_dots: draw_strokes(gp_data, "PCF_Lit",     yellow_dots, IDX_LIT_FILL,  0.001, cyclic=True)
        if grey_dots:   draw_strokes(gp_data, "PCF_Partial", grey_dots,   IDX_GREY_FILL, 0.001, cyclic=True)
        if black_dots:  draw_strokes(gp_data, "PCF_Shad",    black_dots,  IDX_SHAD_FILL, 0.001, cyclic=True)

        if show_squares:
            yl2, gl2, bl2 = classify(lit_sq_pcf,  lit_votes)
            ys2, gs2, bs2 = classify(shad_sq_pcf, shad_votes)
            yellow_sq = yl2 + ys2
            grey_sq   = gl2 + gs2
            black_sq  = bl2 + bs2
            if yellow_sq: draw_strokes(sq_gp_data, "PCF_Sq_Lit",  yellow_sq, SQ_LIT,  props.square_line_width_3d, cyclic=True)
            if grey_sq:   draw_strokes(sq_gp_data, "PCF_Sq_Grey", grey_sq,   SQ_GREY, props.square_line_width_3d, cyclic=True)
            if black_sq:  draw_strokes(sq_gp_data, "PCF_Sq_Shad", black_sq,  SQ_SHAD, props.square_line_width_3d, cyclic=True)
    else:
        if lit_dots:
            draw_strokes(gp_data, "Lit_Dots",  lit_dots,  IDX_LIT_FILL,  0.001, cyclic=True)
        if shad_dots:
            draw_strokes(gp_data, "Shad_Dots", shad_dots, IDX_SHAD_FILL, 0.001, cyclic=True)

        if show_squares:
            if lit_squares:
                draw_strokes(sq_gp_data, "Lit_Squares",  lit_squares,  SQ_LIT,  props.square_line_width_3d, cyclic=True)
            if shad_squares:
                draw_strokes(sq_gp_data, "Shad_Squares", shad_squares, SQ_SHAD, props.square_line_width_3d, cyclic=True)


#---- light-view camera ----

def enter_light_cam_view(context, light_obj):
    #creates a temporary camera at the light and switches the viewport into it
    global _saved_light_cam_state

    light_data = light_obj.data
    light_type = light_data.type

    _saved_light_cam_state = {
        'scene_camera': context.scene.camera,
    }
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            r3d = area.spaces[0].region_3d
            _saved_light_cam_state['perspective'] = r3d.view_perspective
            _saved_light_cam_state['distance']    = r3d.view_distance
            _saved_light_cam_state['location']    = r3d.view_location.copy()
            _saved_light_cam_state['rotation']    = r3d.view_rotation.copy()
            break

    props = context.scene.sm_props

    #save show_lines_3d so both the operator and the timer restore correctly
    _saved_light_cam_state['show_lines_3d'] = props.show_lines_3d
    props.show_lines_3d = False
    if props.is_3d_active:
        generate_3d_rays(context)

    cam_data = bpy.data.cameras.new(name=LIGHT_CAM_NAME + "_Data")

    if light_type == 'SUN':
        #ortho matches the shadow map exactly; ortho_scale covers -grid..+grid
        cam_data.type = 'ORTHO'
        cam_data.ortho_scale = props.ray_grid_size_3d * 2
    else:
        cam_data.type = 'PERSP'
        if light_type == 'SPOT':
            cam_data.angle = light_data.spot_size
        else:
            cam_data.angle = math.radians(90)

    cam_data.clip_start = 0.01
    cam_data.clip_end   = 1000.0

    cam_obj = bpy.data.objects.new(LIGHT_CAM_NAME, cam_data)
    context.scene.collection.objects.link(cam_obj)
    cam_obj.matrix_world = light_obj.matrix_world.copy()

    if light_type == 'SUN':
        #sun grid is centered on scene bbox, not light position -- align camera to match
        quat = light_obj.matrix_world.to_quaternion()
        light_dir = (quat @ Vector((0, 0, -1))).normalized()
        center, _ = compute_scene_bounds(context)
        cam_obj.location = center - light_dir * 200  #depth irrelevant for ortho

    context.scene.camera = cam_obj
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            for region in area.regions:
                if region.type == 'WINDOW':
                    with context.temp_override(area=area, region=region):
                        bpy.ops.view3d.view_camera()
                    break
            break


def exit_light_cam_view(context):
    #removes the temporary camera and restores the previous viewport state
    global _saved_light_cam_state

    context.scene.camera = _saved_light_cam_state.get('scene_camera')

    if LIGHT_CAM_NAME in bpy.data.objects:
        cam_obj = bpy.data.objects[LIGHT_CAM_NAME]
        cam_data = cam_obj.data
        bpy.data.objects.remove(cam_obj, do_unlink=True)
        bpy.data.cameras.remove(cam_data)

    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            space = area.spaces[0]
            r3d   = space.region_3d
            for region in area.regions:
                if region.type == 'WINDOW':
                    with context.temp_override(area=area, region=region):
                        if r3d.view_perspective == 'CAMERA':
                            bpy.ops.view3d.view_camera()
                    break
            r3d.view_perspective = _saved_light_cam_state.get('perspective', 'PERSP')
            r3d.view_distance    = _saved_light_cam_state.get('distance', 10.0)
            loc = _saved_light_cam_state.get('location')
            if loc:
                r3d.view_location = loc
            rot = _saved_light_cam_state.get('rotation')
            if rot:
                r3d.view_rotation = rot
            break

    props = context.scene.sm_props
    props.show_lines_3d = _saved_light_cam_state.get('show_lines_3d', True)
    if props.is_3d_active:
        generate_3d_rays(context)

    _saved_light_cam_state = {}
