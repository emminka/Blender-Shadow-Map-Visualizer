###
#Emma Krompascikova
#xkromp00
#Visualizes Shadow Map Fitting: PSR (frustum-AABB intersection) and PSC (shadow caster volume).
###

import bpy
import bmesh
import math
from mathutils import Vector

from .visualization_2d import get_gp_material, draw_strokes, COLOR_YELLOW, COLOR_BLACK
from .visualization_csm import get_camera_fov_aspect, get_frustum_corners, draw_frustum_slice
from .visualization_3d import make_circle_on_surface

COL_RTW_NAME = "ShadowMap_Fitting"
GP_RTW_NAME  = "SM_Viz_Fitting"

#colors match milet dissertation obr.c. 8.3
COLOR_AABB      = (0.20, 0.45, 0.90, 1.0)  #blue    -- scene AABB
COLOR_FRUSTUM   = (0.85, 0.20, 0.20, 1.0)  #red     -- camera frustum
COLOR_LOOSE     = (0.95, 0.45, 0.10, 1.0)  #orange  -- loose shadow frustum (full scene AABB)
COLOR_TIGHT     = (0.0, 0.0, 0.0, 1.0)     #black   -- tight shadow frustum (PSC)
COLOR_POLY      = (0.85, 0.15, 0.75, 1.0)  #magenta -- PSR wireframe
COLOR_POLY_FILL = (0.90, 0.50, 0.85, 0.25) #light magenta fill
COLOR_PSC       = (0.10, 0.70, 0.65, 1.0)  #teal    -- PSC volume
COLOR_PSC_FILL  = (0.10, 0.70, 0.65, 0.18) #light teal fill
COLOR_PSC_RAYS  = (0.05, 0.15, 0.60, 1.0)  #dark blue -- PSR-to-light construction rays


#gp helpers

def get_rtw_collection():
    if COL_RTW_NAME in bpy.data.collections:
        return bpy.data.collections[COL_RTW_NAME]
    col = bpy.data.collections.new(COL_RTW_NAME)
    bpy.context.scene.collection.children.link(col)
    return col


def clear_rtw_objects():
    if COL_RTW_NAME not in bpy.data.collections:
        return
    col = bpy.data.collections[COL_RTW_NAME]
    for obj in list(col.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def get_rtw_grease_pencil():
    col = get_rtw_collection()
    if GP_RTW_NAME in bpy.data.objects and GP_RTW_NAME in col.objects:
        obj     = bpy.data.objects[GP_RTW_NAME]
        gp_data = obj.data
        for layer in list(gp_data.layers):
            gp_data.layers.remove(layer)
        gp_data.materials.clear()
        obj.show_in_front = False
        return obj
    gp_data = bpy.data.grease_pencils.new(GP_RTW_NAME + "_Data")
    obj     = bpy.data.objects.new(GP_RTW_NAME, gp_data)
    col.objects.link(obj)
    obj.show_in_front = False
    return obj


#scene aabb

def compute_scene_aabb(context):
    #excludes our own visualization collections so they don't skew the bounds
    from .visualization_2d import COL_NAME as COL_2D_NAME
    from .visualization_3d    import COL_3D_NAME
    from .visualization_csm   import COL_CSM_NAME
    from .visualization_cubemap import COL_CUBEMAP_NAME

    our_cols = {COL_2D_NAME, COL_3D_NAME, COL_CSM_NAME, COL_CUBEMAP_NAME, COL_RTW_NAME}

    INF = 1e9
    min_co = Vector(( INF,  INF,  INF))
    max_co = Vector((-INF, -INF, -INF))
    found  = False

    for obj in context.scene.objects:
        if obj.type != 'MESH' or obj.hide_viewport:
            continue
        if any(c.name in our_cols for c in obj.users_collection):
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
        return Vector((-5.0, -5.0, -5.0)), Vector((5.0, 5.0, 5.0))
    return min_co, max_co


def aabb_8_corners(min_co, max_co):
    #ordering: for sz in(-1,1) for sy in(-1,1) for sx in(-1,1)
    corners = []
    for sz in (-1, 1):
        for sy in (-1, 1):
            for sx in (-1, 1):
                corners.append(Vector((
                    min_co.x if sx < 0 else max_co.x,
                    min_co.y if sy < 0 else max_co.y,
                    min_co.z if sz < 0 else max_co.z,
                )))
    return corners


#frustum half-space test

def build_frustum_planes(corners):
    #6 inward-facing half-space planes; normal.dot(p) >= d means inside
    #corners: first 4 = near face, last 4 = far face (from get_frustum_corners)
    c        = corners
    centroid = Vector((0.0, 0.0, 0.0))
    for corner in c:
        centroid += corner
    centroid /= len(c)

    def make_plane(p0, p1, p2):
        n = (p1 - p0).cross(p2 - p0)
        if n.length < 1e-10:
            return None
        n = n.normalized()
        d = n.dot(p0)
        if n.dot(centroid) < d:
            n = -n
            d = -d
        return (n, d)

    planes = []
    for fn in [
        make_plane(c[0], c[1], c[2]),   #near face
        make_plane(c[4], c[5], c[6]),   #far face
        make_plane(c[0], c[4], c[2]),   #left face  (sx = -1 side)
        make_plane(c[1], c[3], c[5]),   #right face (sx = +1 side)
        make_plane(c[0], c[1], c[4]),   #bottom face (sy = -1 side)
        make_plane(c[2], c[3], c[6]),   #top face   (sy = +1 side)
    ]:
        if fn is not None:
            planes.append(fn)
    return planes


def point_in_frustum(p, planes, eps=1e-4):
    return all(n.dot(p) >= d - eps for n, d in planes)


def point_in_aabb(p, min_co, max_co, eps=1e-4):
    return (min_co.x - eps <= p.x <= max_co.x + eps and
            min_co.y - eps <= p.y <= max_co.y + eps and
            min_co.z - eps <= p.z <= max_co.z + eps)


#intersection polyhedron

def _segment_vs_aabb(a, b, aabb_min, aabb_max):
    #returns points where segment AB crosses AABB planes and lands inside the AABB face
    result = []
    d = b - a
    for axis in range(3):
        if abs(d[axis]) < 1e-10:
            continue
        for val in (aabb_min[axis], aabb_max[axis]):
            t = (val - a[axis]) / d[axis]
            if 0.0 < t < 1.0:
                p = a + d * t
                if point_in_aabb(p, aabb_min, aabb_max):
                    result.append(p)
    return result


def _segment_vs_frustum(a, b, planes):
    #returns points where segment AB crosses a frustum plane and lands inside the frustum
    result = []
    d = b - a
    for n, pd in planes:
        denom = n.dot(d)
        if abs(denom) < 1e-10:
            continue
        t = (pd - n.dot(a)) / denom
        if 0.0 < t < 1.0:
            p = a + d * t
            if point_in_frustum(p, planes):
                result.append(p)
    return result


def intersection_vertex_set(frustum_corners, aabb_min, aabb_max):
    #full vertex set of the frustum-AABB intersection polyhedron (PSR):
    #1. frustum corners inside AABB
    #2. AABB corners inside frustum
    #3. frustum edges vs AABB planes
    #4. AABB edges vs frustum planes (covers edge-pierce-face cases with no corner inside)
    result = []
    planes = build_frustum_planes(frustum_corners)
    c = frustum_corners

    for pt in frustum_corners:
        if point_in_aabb(pt, aabb_min, aabb_max):
            result.append(pt)

    aabb_c = aabb_8_corners(aabb_min, aabb_max)
    for pt in aabb_c:
        if point_in_frustum(pt, planes):
            result.append(pt)

    frustum_edges = [
        (c[0],c[1]), (c[1],c[3]), (c[3],c[2]), (c[2],c[0]),   #near face
        (c[4],c[5]), (c[5],c[7]), (c[7],c[6]), (c[6],c[4]),   #far face
        (c[0],c[4]), (c[1],c[5]), (c[2],c[6]), (c[3],c[7]),   #connecting
    ]
    for a, b in frustum_edges:
        result.extend(_segment_vs_aabb(a, b, aabb_min, aabb_max))

    aabb_edges = [
        (aabb_c[0],aabb_c[1]), (aabb_c[1],aabb_c[3]),         #bottom face
        (aabb_c[3],aabb_c[2]), (aabb_c[2],aabb_c[0]),
        (aabb_c[4],aabb_c[5]), (aabb_c[5],aabb_c[7]),         #top face
        (aabb_c[7],aabb_c[6]), (aabb_c[6],aabb_c[4]),
        (aabb_c[0],aabb_c[4]), (aabb_c[1],aabb_c[5]),         #vertical
        (aabb_c[2],aabb_c[6]), (aabb_c[3],aabb_c[7]),
    ]
    for a, b in aabb_edges:
        result.extend(_segment_vs_frustum(a, b, planes))

    return result


#---- PSC: potential shadow casters ----

def compute_psc(psr_pts, light_dir, aabb_min, aabb_max):
    #PSC = PSR extended toward the light, clipped by scene AABB.
    #captures objects outside the camera frustum that can still cast visible shadows.
    if not psr_pts:
        return []

    result = list(psr_pts)
    ray_dir = -light_dir

    for pt in psr_pts:
        for axis in range(3):
            if abs(ray_dir[axis]) < 1e-10:
                continue
            for val in (aabb_min[axis], aabb_max[axis]):
                t = (val - pt[axis]) / ray_dir[axis]
                if t <= 1e-6:
                    continue
                candidate = pt + ray_dir * t
                if point_in_aabb(candidate, aabb_min, aabb_max):
                    result.append(candidate)

    return result


def compute_psc_construction_rays(psr_pts, light_dir, aabb_min, aabb_max):
    #rays from convex hull vertices of PSR to their AABB exit point toward the light
    if len(psr_pts) < 4:
        hull_pts = psr_pts
    else:
        bm = bmesh.new()
        verts = [bm.verts.new(p) for p in psr_pts]
        bmesh.ops.convex_hull(bm, input=verts, use_existing_faces=False)
        hull_pts = [v.co.copy() for v in bm.verts if v.is_valid]
        bm.free()

    ray_dir  = -light_dir
    segments = []
    for pt in hull_pts:
        best_t   = None
        best_end = None
        for axis in range(3):
            if abs(ray_dir[axis]) < 1e-10:
                continue
            for val in (aabb_min[axis], aabb_max[axis]):
                t = (val - pt[axis]) / ray_dir[axis]
                if t <= 1e-6:
                    continue
                candidate = pt + ray_dir * t
                if point_in_aabb(candidate, aabb_min, aabb_max):
                    if best_t is None or t < best_t:
                        best_t   = t
                        best_end = candidate
        if best_end is not None:
            segments.append([pt, best_end])
    return segments


#---- convex hull of intersection polyhedron ----

def convex_hull_edges(points):
    #use bmesh convex hull; skip internal triangulation diagonals (coplanar face edges)
    if len(points) < 4:
        return [[points[i], points[j]] for i in range(len(points)) for j in range(i+1, len(points))]

    bm = bmesh.new()
    verts = [bm.verts.new(p) for p in points]
    bmesh.ops.convex_hull(bm, input=verts, use_existing_faces=False)
    bm.normal_update()

    edges = []
    for e in bm.edges:
        link = e.link_faces
        if len(link) != 2:
            edges.append([e.verts[0].co.copy(), e.verts[1].co.copy()])
            continue
        #0.9995 threshold to keep edges between nearly-coplanar faces visible
        if link[0].normal.dot(link[1].normal) < 0.9995:
            edges.append([e.verts[0].co.copy(), e.verts[1].co.copy()])

    bm.free()
    return edges


def convex_hull_faces(points):
    #triangulated faces for GP fill
    if len(points) < 4:
        return []
    bm = bmesh.new()
    verts = [bm.verts.new(p) for p in points]
    bmesh.ops.convex_hull(bm, input=verts, use_existing_faces=False)
    faces = [[v.co.copy() for v in f.verts] for f in bm.faces]
    bm.free()
    return faces


def point_in_cam_frustum_and_aabb(point, cam_obj, d_near, d_far, fov_y, aspect,
                                   aabb_min, aabb_max, eps=1e-4):
    if not point_in_aabb(point, aabb_min, aabb_max, eps):
        return False
    #Blender camera looks along local -Z
    p_cam = cam_obj.matrix_world.inverted() @ point
    depth = -p_cam.z
    if depth < d_near - eps or depth > d_far + eps:
        return False
    half_h = math.tan(fov_y / 2.0) * depth
    half_w = half_h * aspect
    return abs(p_cam.x) <= half_w + eps and abs(p_cam.y) <= half_h + eps


#---- orthographic shadow box ----

def shadow_box_corners(points, light_dir, light_right, light_up):
    #tightest orthographic box around points aligned to light axes (core of shadow map fitting)
    if not points:
        return None

    proj_r = [p.dot(light_right) for p in points]
    proj_u = [p.dot(light_up)    for p in points]
    proj_d = [p.dot(light_dir)   for p in points]

    min_r, max_r = min(proj_r), max(proj_r)
    min_u, max_u = min(proj_u), max(proj_u)
    min_d, max_d = min(proj_d), max(proj_d)

    half_w = (max_r - min_r) / 2.0
    half_h = (max_u - min_u) / 2.0
    half_d = (max_d - min_d) / 2.0

    mid_r = (min_r + max_r) / 2.0
    mid_u = (min_u + max_u) / 2.0
    mid_d = (min_d + max_d) / 2.0

    ref = Vector((0.0, 0.0, 0.0))
    for p in points:
        ref += p
    ref /= len(points)
    center = (ref
              + light_right * (mid_r - ref.dot(light_right))
              + light_up    * (mid_u - ref.dot(light_up))
              + light_dir   * (mid_d - ref.dot(light_dir)))

    #same corner ordering as aabb_8_corners
    corners = []
    for sd in (-1, 1):
        for su in (-1, 1):
            for sr in (-1, 1):
                corners.append(center
                                + light_right * sr * half_w
                                + light_up    * su * half_h
                                + light_dir   * sd * half_d)
    return corners


#---- drawing ----

def draw_box_12_edges(gp_data, layer_name, corners, mat_idx, thickness):
    #corner ordering: for sz(-1,1) for sy(-1,1) for sx(-1,1) -- same as aabb_8_corners
    c = corners
    edges = [
        #bottom face (sz = -1, indices 0-3)
        [c[0], c[1]], [c[1], c[3]], [c[3], c[2]], [c[2], c[0]],
        #top face (sz = +1, indices 4-7)
        [c[4], c[5]], [c[5], c[7]], [c[7], c[6]], [c[6], c[4]],
        #vertical edges
        [c[0], c[4]], [c[1], c[5]], [c[2], c[6]], [c[3], c[7]],
    ]
    draw_strokes(gp_data, layer_name, edges, mat_idx, thickness)


#---- main fitting generation ----

def generate_rtw(context):
    #blue=AABB, red=camera frustum, magenta=PSR, teal=PSC, orange=loose frustum, black=tight frustum
    props     = context.scene.sm_props
    light_obj = props.rtw_light_object
    cam_obj   = context.scene.camera

    if not light_obj or light_obj.type != 'LIGHT' or light_obj.data.type != 'SUN':
        return
    if not cam_obj:
        return

    fov_y, aspect = get_camera_fov_aspect(context, cam_obj)
    if fov_y is None:
        return  #ortho cameras not supported

    quat        = light_obj.matrix_world.to_quaternion()
    light_dir   = (quat @ Vector((0,  0, -1))).normalized()
    light_right = (quat @ Vector((1,  0,  0))).normalized()
    light_up    = (quat @ Vector((0,  1,  0))).normalized()

    d_near      = cam_obj.data.clip_start
    d_far       = props.rtw_cam_d_far
    frustum_c   = get_frustum_corners(cam_obj, d_near, d_far, fov_y, aspect)

    aabb_min, aabb_max = compute_scene_aabb(context)
    aabb_c             = aabb_8_corners(aabb_min, aabb_max)

    inter_pts = intersection_vertex_set(frustum_c, aabb_min, aabb_max)

    psc_pts = compute_psc(inter_pts, light_dir, aabb_min, aabb_max) if inter_pts else []

    loose_c = shadow_box_corners(aabb_c, light_dir, light_right, light_up)

    #tight fitting: prefer PSC, fall back to PSR, then full frustum
    if psc_pts:
        tight_c = shadow_box_corners(psc_pts, light_dir, light_right, light_up)
    elif inter_pts:
        tight_c = shadow_box_corners(inter_pts, light_dir, light_right, light_up)
    else:
        tight_c = shadow_box_corners(list(frustum_c), light_dir, light_right, light_up)

    clear_rtw_objects()
    gp_obj  = get_rtw_grease_pencil()
    gp_data = gp_obj.data

    IDX_AABB      = 0
    IDX_FRUSTUM   = 1
    IDX_LOOSE     = 2
    IDX_TIGHT     = 3
    IDX_POLY      = 4
    IDX_POLY_FILL = 5
    IDX_LIT_FILL  = 6
    IDX_SHAD_FILL = 7
    IDX_LIT_RAY   = 8
    IDX_SHAD_RAY  = 9
    IDX_PSC       = 10
    IDX_PSC_FILL  = 11
    IDX_PSC_RAYS  = 12

    get_gp_material(gp_data, "SMViz_Fitting_AABB",      COLOR_AABB)
    get_gp_material(gp_data, "SMViz_Fitting_Frustum",   COLOR_FRUSTUM)
    get_gp_material(gp_data, "SMViz_Fitting_Loose",     COLOR_LOOSE)
    get_gp_material(gp_data, "SMViz_Fitting_Tight",     COLOR_TIGHT)
    get_gp_material(gp_data, "SMViz_Fitting_Poly",      COLOR_POLY)
    get_gp_material(gp_data, "SMViz_Fitting_PolyFill",  COLOR_POLY_FILL, use_fill=True)
    get_gp_material(gp_data, "SMViz_Fitting_LitFill",   COLOR_YELLOW, use_fill=True)
    get_gp_material(gp_data, "SMViz_Fitting_ShadFill",  COLOR_BLACK,  use_fill=True)
    get_gp_material(gp_data, "SMViz_Fitting_LitRay",    COLOR_YELLOW)
    get_gp_material(gp_data, "SMViz_Fitting_ShadRay",   COLOR_BLACK)
    get_gp_material(gp_data, "SMViz_Fitting_PSC",       COLOR_PSC)
    get_gp_material(gp_data, "SMViz_Fitting_PSCFill",   COLOR_PSC_FILL, use_fill=True)
    get_gp_material(gp_data, "SMViz_Fitting_PSCRays",   COLOR_PSC_RAYS)

    if props.rtw_show_aabb:
        draw_box_12_edges(gp_data, "AABB", aabb_c, IDX_AABB, 0.015)

    if props.rtw_show_cam_frustum:
        draw_frustum_slice(gp_data, "CamFrustum", frustum_c, IDX_FRUSTUM, 0.020)

    if props.rtw_show_loose and loose_c:
        draw_box_12_edges(gp_data, "LooseFrustum", loose_c, IDX_LOOSE, 0.020)

    if props.rtw_show_poly and inter_pts:
        centroid = Vector((0.0, 0.0, 0.0))
        for p in inter_pts:
            centroid += p
        centroid /= len(inter_pts)
        expanded = [centroid + (p - centroid) * 1.003 for p in inter_pts]
        if props.rtw_show_poly_fill:
            poly_faces = convex_hull_faces(expanded)
            if poly_faces:
                draw_strokes(gp_data, "Polyhedron_Fill", poly_faces, IDX_POLY_FILL, 0.001, cyclic=True)
        poly_edges = convex_hull_edges(expanded)
        if poly_edges:
            draw_strokes(gp_data, "Polyhedron", poly_edges, IDX_POLY, 0.018)

    if props.rtw_show_psc and psc_pts:
        psc_centroid = Vector((0.0, 0.0, 0.0))
        for p in psc_pts:
            psc_centroid += p
        psc_centroid /= len(psc_pts)
        psc_expanded = [psc_centroid + (p - psc_centroid) * 1.003 for p in psc_pts]
        if props.rtw_show_psc_fill:
            psc_faces = convex_hull_faces(psc_expanded)
            if psc_faces:
                draw_strokes(gp_data, "PSC_Fill", psc_faces, IDX_PSC_FILL, 0.001, cyclic=True)
        psc_edges = convex_hull_edges(psc_expanded)
        if psc_edges:
            draw_strokes(gp_data, "PSC", psc_edges, IDX_PSC, 0.018)

    if props.rtw_show_psc_rays and inter_pts:
        ray_segs = compute_psc_construction_rays(inter_pts, light_dir, aabb_min, aabb_max)
        if ray_segs:
            draw_strokes(gp_data, "PSC_Rays", ray_segs, IDX_PSC_RAYS, 0.013)

    if props.rtw_show_tight and tight_c:
        draw_box_12_edges(gp_data, "TightFrustum", tight_c, IDX_TIGHT, 0.025)

    if props.rtw_show_rays and tight_c:
        proj_r    = [c.dot(light_right) for c in tight_c]
        proj_u    = [c.dot(light_up)    for c in tight_c]
        half_w    = (max(proj_r) - min(proj_r)) / 2
        half_h    = (max(proj_u) - min(proj_u)) / 2
        tight_ctr = Vector((0.0, 0.0, 0.0))
        for c in tight_c:
            tight_ctr += c
        tight_ctr /= len(tight_c)
        mid_r     = (min(proj_r) + max(proj_r)) / 2
        mid_u     = (min(proj_u) + max(proj_u)) / 2
        grid_orig = (tight_ctr
                     + light_right * (mid_r - tight_ctr.dot(light_right))
                     + light_up    * (mid_u - tight_ctr.dot(light_up)))

        steps      = props.rtw_ray_grid_steps
        ray_length = props.rtw_ray_length
        depsgraph  = context.evaluated_depsgraph_get()

        filter_to_poly = not props.rtw_rays_show_outside

        lit_rays  = []
        lit_dots  = []
        shad_rays = []
        shad_dots = []

        for ix in range(-steps, steps + 1):
            for iy in range(-steps, steps + 1):
                fx = ix / max(steps, 1)
                fy = iy / max(steps, 1)
                grid_pt    = grid_orig + light_right * (fx * half_w) + light_up * (fy * half_h)
                ray_origin = grid_pt - light_dir * 200
                vis_start  = grid_pt - light_dir * ray_length

                result, loc1, norm1, _, hit_obj1, _ = context.scene.ray_cast(depsgraph, ray_origin, light_dir)
                if not result:
                    continue

                loc2 = norm2 = None
                nxt = loc1 + light_dir * 0.001
                for _ in range(8):
                    r2, l2, n2, _, hit_obj2, _ = context.scene.ray_cast(depsgraph, nxt, light_dir)
                    if not r2:
                        break
                    if hit_obj2 != hit_obj1:
                        loc2, norm2 = l2, n2
                        break
                    nxt = l2 + light_dir * 0.001

                #when filtering: keep only rays where loc1 or loc2 lands inside PSR
                if filter_to_poly:
                    in1 = point_in_cam_frustum_and_aabb(
                              loc1, cam_obj, d_near, d_far, fov_y, aspect, aabb_min, aabb_max)
                    in2 = (loc2 is not None and
                           point_in_cam_frustum_and_aabb(
                               loc2, cam_obj, d_near, d_far, fov_y, aspect, aabb_min, aabb_max))
                    if not (in1 or in2):
                        continue

                lit_rays.append([vis_start, loc1])
                lit_dots.append(make_circle_on_surface(loc1 + norm1 * 0.002, norm1, props.rtw_dot_size))
                if loc2 is not None:
                    shad_rays.append([loc1, loc2])
                    shad_dots.append(make_circle_on_surface(loc2 + norm2 * 0.002, norm2, props.rtw_dot_size))

        if lit_rays and props.rtw_show_ray_lines:
            draw_strokes(gp_data, "RTW_Lit_Rays",  lit_rays,  IDX_LIT_RAY,  props.rtw_thick_rays)
        if shad_rays and props.rtw_show_ray_lines:
            draw_strokes(gp_data, "RTW_Shad_Rays", shad_rays, IDX_SHAD_RAY, props.rtw_thick_rays)
        if lit_dots:
            draw_strokes(gp_data, "RTW_Lit_Dots",  lit_dots,  IDX_LIT_FILL, 0.001, cyclic=True)
        if shad_dots:
            draw_strokes(gp_data, "RTW_Shad_Dots", shad_dots, IDX_SHAD_FILL, 0.001, cyclic=True)
