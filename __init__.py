###
#Emma Krompascikova
#xkromp00
#Blender 5.0 add-on: interactive educational visualizer for shadow mapping techniques.
###

bl_info = {
    "name": "Shadow Map Visualizer",
    "author": "Emma Krompascikova",
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > ShadowMapVisualizer",
    "description": "Interactive educational visualizations of shadow mapping techniques.",
    "category": "Education",
}

import bpy
import math
import importlib
from bpy.props import FloatProperty, EnumProperty, PointerProperty, IntProperty, BoolProperty

try:
    from . import visualization_2d
    from . import visualization_3d
    from . import visualization_csm
    from . import visualization_cubemap
    from . import visualization_fitting
    importlib.reload(visualization_2d)
    importlib.reload(visualization_3d)
    importlib.reload(visualization_csm)
    importlib.reload(visualization_cubemap)
    importlib.reload(visualization_fitting)
except ImportError as e:
    print(f"[ShadowMapViz] Import error: {e}")

#suppression guard: prevents cascade updates during bulk property reset
_suppressing_updates = False

#flags set by the depsgraph handler; timer reads them and regenerates safely outside the handler
_needs_3d_update      = False
_needs_csm_update     = False
_needs_cubemap_update = False
_needs_rtw_update     = False

#direction for bias animation: +1 going up, -1 going down
_bias_direction = 1


#---- update callbacks ----

def update_viz(self, context):
    if _suppressing_updates:
        return None
    props = context.scene.sm_props
    if not props.is_2d_active:
        return None
    visualization_2d.generate_shadow_acne(context)
    return None


def update_csm(self, context):
    if _suppressing_updates:
        return None
    props = context.scene.sm_props
    if not props.is_csm_active or not props.auto_update:
        return None
    visualization_csm.generate_csm(context)
    return None


def update_csm_split1(self, context):
    global _suppressing_updates
    #clamp split2 up if split1 overtakes it; suppress split2 callback to avoid double regeneration
    if self.csm_split1 >= self.csm_split2:
        _suppressing_updates = True
        self.csm_split2 = min(self.csm_split1 + 0.05, 0.95)
        _suppressing_updates = False
    update_csm(self, context)


def update_csm_split2(self, context):
    global _suppressing_updates
    if self.csm_split2 <= self.csm_split1:
        _suppressing_updates = True
        self.csm_split1 = max(self.csm_split2 - 0.05, 0.05)
        _suppressing_updates = False
    update_csm(self, context)


def update_3d(self, context):
    if _suppressing_updates:
        return None
    props = context.scene.sm_props
    if not props.is_3d_active or not props.auto_update:
        return None
    visualization_3d.generate_3d_rays(context)
    return None


def update_cubemap(self, context):
    if _suppressing_updates:
        return None
    props = context.scene.sm_props
    if not props.is_cubemap_active or not props.auto_update:
        return None
    visualization_cubemap.generate_cubemap(context)
    return None


def cubemap_light_object_poll(self, obj):
    return obj.type == 'LIGHT' and obj.data.type == 'POINT'


def update_rtw(self, context):
    if _suppressing_updates:
        return None
    props = context.scene.sm_props
    if not props.is_rtw_active or not props.auto_update:
        return None
    visualization_fitting.generate_rtw(context)
    return None


def rtw_light_object_poll(self, obj):
    return obj.type == 'LIGHT' and obj.data.type == 'SUN'


def update_light_type(self, context):
    #suppress callbacks while batch-setting defaults to avoid multiple redraws
    global _suppressing_updates
    _suppressing_updates = True

    if self.light_type == 'SUN':
        self.light_angle = math.radians(-45)
        self.light_shift_x = 0.0
    elif self.light_type == 'POINT':
        self.light_angle = 0.0
        self.light_distance = 8.0
        self.light_shift_x = 0.0

    self.bias_min = 0.0
    self.bias_slope = 0.0

    _suppressing_updates = False
    update_viz(self, context)


def light_object_poll(self, obj):
    return obj.type == 'LIGHT'


def csm_light_object_poll(self, obj):
    #CSM requires sun (directional) lights; spot/point use a different algorithm
    return obj.type == 'LIGHT' and obj.data.type == 'SUN'


@bpy.app.handlers.persistent
def on_depsgraph_update(scene, depsgraph):
    #sets update flags only -- modifying GP data inside a depsgraph handler can crash Blender
    global _needs_3d_update, _needs_csm_update, _needs_cubemap_update, _needs_rtw_update
    try:
        props        = scene.sm_props
        is_3d        = props.is_3d_active
        is_csm       = props.is_csm_active
        is_cubemap   = props.is_cubemap_active
        is_rtw       = props.is_rtw_active
    except Exception:
        return
    if not is_3d and not is_csm and not is_cubemap and not is_rtw:
        return
    for update in depsgraph.updates:
        triggered = False
        if isinstance(update.id, (bpy.types.Object, bpy.types.Light)):
            #skip our own GP objects by name prefix (users_collection is unreliable in GP v3)
            name = getattr(update.id, 'name', '')
            if name.startswith('SM_Viz_') or name == 'SM_LightViewCamera':
                continue
            if update.is_updated_transform or update.is_updated_geometry:
                triggered = True
        #Scene-level trigger omitted: fires on almost any UI action causing constant re-generation
        if triggered:
            if is_3d:      _needs_3d_update     = True
            if is_csm:     _needs_csm_update     = True
            if is_cubemap: _needs_cubemap_update = True
            if is_rtw:     _needs_rtw_update     = True
            return


def timer_check_update():
    #runs every 0.3 s; regenerates any active visualization if the scene changed
    global _needs_3d_update, _needs_csm_update, _needs_cubemap_update, _needs_rtw_update
    ctx = bpy.context
    if ctx and ctx.screen and hasattr(ctx, 'scene') and ctx.scene:
        try:
            props = ctx.scene.sm_props

            #---- 3d rays ----
            if not props.light_object:
                if props.is_3d_active:
                    visualization_3d.clear_3d_objects()
                    props.is_3d_active = False
                if props.is_light_cam_active:
                    visualization_3d.exit_light_cam_view(ctx)
                    props.is_light_cam_active = False

            #detect if user navigated away from light cam view manually
            if props.is_light_cam_active:
                left_cam = True
                for area in ctx.screen.areas:
                    if area.type == 'VIEW_3D':
                        if area.spaces[0].region_3d.view_perspective == 'CAMERA':
                            left_cam = False
                        break
                if left_cam:
                    visualization_3d.exit_light_cam_view(ctx)
                    props.is_light_cam_active = False
            elif _needs_3d_update:
                _needs_3d_update = False
                if props.is_3d_active and props.auto_update:
                    visualization_3d.generate_3d_rays(ctx)

            #---- csm ----
            if not props.csm_light_object and props.is_csm_active:
                visualization_csm.clear_csm_objects()
                props.is_csm_active = False
            elif _needs_csm_update and not props.is_2d_active:
                _needs_csm_update = False
                if props.is_csm_active and props.auto_update:
                    visualization_csm.generate_csm(ctx)

            #---- cubemap ----
            if not props.cubemap_light_object and props.is_cubemap_active:
                visualization_cubemap.clear_cubemap_objects()
                props.is_cubemap_active = False

            #detect if user navigated away from face cam view manually
            if props.is_cube_face_cam_active:
                left_cam = True
                for area in ctx.screen.areas:
                    if area.type == 'VIEW_3D':
                        if area.spaces[0].region_3d.view_perspective == 'CAMERA':
                            left_cam = False
                        break
                if left_cam:
                    visualization_cubemap.exit_face_cam_view(ctx)
                    props.is_cube_face_cam_active = False

            if not props.is_cube_face_cam_active and _needs_cubemap_update and not props.is_2d_active:
                _needs_cubemap_update = False
                if props.is_cubemap_active and props.auto_update:
                    visualization_cubemap.generate_cubemap(ctx)

            #---- rtw ----
            if not props.rtw_light_object and props.is_rtw_active:
                visualization_fitting.clear_rtw_objects()
                props.is_rtw_active = False
            elif _needs_rtw_update and not props.is_2d_active:
                _needs_rtw_update = False
                if props.is_rtw_active and props.auto_update:
                    visualization_fitting.generate_rtw(ctx)

        except Exception as e:
            print(f"[ShadowMapViz] Timer error: {e}")
    else:
        _needs_3d_update     = False
        _needs_csm_update    = False
        _needs_cubemap_update = False
        _needs_rtw_update    = False
    return 0.3


def timer_bias_animate():
    #runs every 0.06 s; sweeps bias_min 0 → 0.7 → 0 → repeat
    global _bias_direction
    ctx = bpy.context
    if not ctx or not ctx.screen or not ctx.scene:
        return 0.06
    try:
        props = ctx.scene.sm_props
        if not props.is_bias_animating or not props.is_2d_active:
            return None
        new_val = props.bias_min + 0.008 * _bias_direction
        if new_val >= 0.7:
            new_val = 0.7
            _bias_direction = -1
        elif new_val <= 0.0:
            new_val = 0.0
            _bias_direction = 1
        props.bias_min = new_val  #triggers update_viz → generate_shadow_acne
    except Exception as e:
        print(f"[ShadowMapViz] Bias animation error: {e}")
        return None
    return 0.06


#---- properties ----

class SMProperties(bpy.types.PropertyGroup):

    #--- panel section expand/collapse state ---

    section_2d_expanded:   BoolProperty(name="2D Expanded",      default=False)
    section_3d_expanded:   BoolProperty(name="3D Expanded",      default=False)
    section_csm_expanded:  BoolProperty(name="CSM Expanded",     default=False)
    section_cube_expanded: BoolProperty(name="Cube Expanded",    default=False)
    section_rtw_expanded:  BoolProperty(name="Fitting Expanded", default=False)
    disp_2d_expanded:   BoolProperty(name="2D Display Settings",      default=False)
    disp_3d_expanded:   BoolProperty(name="3D Display Settings",      default=False)
    disp_csm_expanded:  BoolProperty(name="CSM Display Settings",     default=False)
    disp_cube_expanded: BoolProperty(name="Cube Display Settings",    default=False)
    disp_rtw_expanded:  BoolProperty(name="Fitting Display Settings", default=False)
    #--- global settings ---

    auto_update: BoolProperty(
        name="Auto Update",
        description="Automatically regenerate the active visualization when the scene changes. Disable on slower machines.",
        default=True,
    )

    #--- state flags ---

    is_2d_active: BoolProperty(
        name="2D Active",
        description="Whether the 2D visualization is currently running.",
        default=False
    )

    is_3d_active: BoolProperty(
        name="3D Active",
        description="Whether the 3D ray visualization is currently running.",
        default=False
    )

    #--- 2d properties (existing) ---

    light_type: EnumProperty(
        name="Light Setup",
        items=[
            ('SUN',   "Sun (Directional)", "All rays are parallel."),
            ('POINT', "Spot (Point)",      "All rays come from a single point.")
        ],
        default='SUN',
        update=update_light_type
    )

    light_angle: FloatProperty(
        name="Light Angle",
        description="Angle of light source.",
        default=math.radians(-20),
        min=math.radians(-85),
        max=math.radians(85),
        subtype='ANGLE',
        update=update_viz
    )

    light_distance: FloatProperty(
        name="Light Height",
        description="Distance or height of the light source from base.",
        default=9.0,
        min=3.0,
        max=30.0,
        update=update_viz
    )

    light_shift_x: FloatProperty(
        name="Light position (X axis)",
        description="Shift light left or right.",
        default=0.0,
        min=-20.0,
        max=20.0,
        update=update_viz
    )

    texel_size: FloatProperty(
        name="Texel Size",
        description="Size of a pixel (Visualization Scale).",
        default=1.0,
        min=0.2,
        max=4.0,
        update=update_viz
    )

    bias_min: FloatProperty(
        name="Min Bias",
        description="Constant offset (Factor of Texel Size). 1.0 = 1 Full Texel Shift.",
        default=0.0,
        min=0.0,
        max=1.0,
        precision=4,
        step=0.01,
        update=update_viz
    )

    bias_slope: FloatProperty(
        name="Slope Bias",
        description="Slope-dependent offset (Factor of Texel Size).",
        default=0.0,
        min=0.0,
        max=1.0,
        precision=4,
        step=0.01,
        update=update_viz
    )

    shadow_map_steps: IntProperty(
        name="Grid Steps",
        description="Number of shadow map texels from center. Steps=12 gives 25 total texels.",
        default=12,
        min=2,
        max=100,
        update=update_viz
    )

    ray_frequency: EnumProperty(
        name="Show Rays",
        items=[
            ('1', "Every Ray", "Show all rays."),
            ('2', "Every 2nd", "Show every second ray."),
            ('3', "Every 3rd", "Show every third ray."),
            ('0', "None",      "Hide all rays.")
        ],
        default='2',
        update=update_viz
    )

    floor_width: FloatProperty(
        name="Floor Width",
        description="Width of the white background floor.",
        default=7.0,
        min=4.0,
        max=30.0,
        update=update_viz
    )

    show_box: BoolProperty(
        name="Show Object",
        description="Display a 2D object to cast shadows.",
        default=False,
        update=update_viz
    )

    box_x: FloatProperty(
        name="Object Pos X",
        default=0.0,
        min=-15.0, max=15.0,
        update=update_viz
    )

    box_width: FloatProperty(
        name="Object Width",
        default=1.64,
        min=0.5, max=10.0,
        update=update_viz
    )

    box_height: FloatProperty(
        name="Object Height",
        default=0.83,
        min=0.5, max=10.0,
        update=update_viz
    )

    thick_floor: FloatProperty(
        name="Floor Line Width",
        default=0.020,
        min=0.010, max=0.060,
        step=0.001, precision=3,
        update=update_viz
    )

    thick_rays: FloatProperty(
        name="Rays Width",
        default=0.015,
        min=0.010, max=0.060,
        step=0.001, precision=3,
        update=update_viz
    )

    rays_yellow: BoolProperty(
        name="Orange Rays",
        description="Draw rays in orange instead of black (easier to see on the white background).",
        default=False,
        update=update_viz
    )

    #--- 3d properties (new) ---

    light_object: PointerProperty(
        name="Light",
        description="The light object to cast rays from.",
        type=bpy.types.Object,
        poll=light_object_poll
    )

    ray_frequency_3d: EnumProperty(
        name="Ray Density",
        description="How many rays from the grid to actually draw.",
        items=[
            ('1', "Every Ray",  "Draw every ray in the grid."),
            ('2', "Every 2nd",  "Draw every second ray in each direction (1/4 density)."),
            ('3', "Every 3rd",  "Draw every third ray in each direction (1/9 density)."),
            ('0', "None",       "Hide all rays.")
        ],
        default='1',
        update=update_3d
    )

    ray_grid_steps_3d: IntProperty(
        name="Grid Steps",
        description="Number of ray subdivisions in each direction. Steps=12 gives 25x25=625 rays, steps=40 gives 81x81=6561 rays.",
        default=12,
        min=1,
        max=40,
        update=update_3d
    )

    ray_grid_size_3d: FloatProperty(
        name="Grid Size",
        description="Total width of the ray grid in Blender units (used for Sun lights only).",
        default=12.0,
        min=1.0,
        max=50.0,
        update=update_3d
    )

    ray_length_3d: FloatProperty(
        name="Ray Length",
        description="How far above the hit surface the visible ray starts (Sun lights only).",
        default=5.0,
        min=0.5,
        max=30.0,
        update=update_3d
    )

    thick_rays_3d: FloatProperty(
        name="Ray Width",
        description="Thickness of the drawn rays.",
        default=0.010,
        min=0.005, max=0.050,
        step=0.001, precision=3,
        update=update_3d
    )

    dot_size_3d: FloatProperty(
        name="Dot Size",
        description="Size of the dots drawn at ray hit points.",
        default=0.06,
        min=0.005, max=0.200,
        step=0.001, precision=3,
        update=update_3d
    )

    square_line_width_3d: FloatProperty(
        name="Square Line Width",
        description="Thickness of the texel square outlines.",
        default=0.010,
        min=0.005, max=0.050,
        step=0.001, precision=3,
        update=update_3d
    )

    show_lines_3d: BoolProperty(
        name="Show Ray Lines",
        description="Show the ray lines. When off, only the hit dots are drawn.",
        default=True,
        update=update_3d
    )

    show_squares_3d: BoolProperty(
        name="Show Texel Squares",
        description="Draw a square around each hit dot showing the shadow map texel area.",
        default=False,
        update=update_3d
    )

    show_pcf_3d: BoolProperty(
        name="Show PCF",
        description="Enable Percentage Closer Filtering visualization. Each dot is tested with a 3x3 kernel (9 samples). Yellow = fully lit, grey = PCF boundary zone, black = fully in shadow.",
        default=False,
        update=update_3d
    )

    pcf_radius_3d: FloatProperty(
        name="PCF Kernel Radius",
        description="Spacing between the 9 PCF kernel samples in world units. Larger = wider soft shadow zone.",
        default=0.5,
        min=0.01,
        soft_max=2.0,
        max=10.0,
        step=0.01,
        precision=3,
        update=update_3d
    )

    is_light_cam_active: BoolProperty(
        name="Light Cam Active",
        description="Whether the light-view camera is currently in use.",
        default=False
    )

    #--- csm properties ---

    is_csm_active: BoolProperty(
        name="CSM Active",
        description="Whether the CSM visualization is currently shown.",
        default=False
    )

    csm_light_object: PointerProperty(
        name="Light",
        description="Sun light used as the CSM shadow caster. CSM only works with directional (sun) lights.",
        type=bpy.types.Object,
        poll=csm_light_object_poll,
        update=update_csm
    )

    csm_split1: FloatProperty(
        name="Split 1",
        description="End of cascade 1 as a fraction of Max Distance. Must be less than Split 2.",
        default=0.25,
        min=0.05,
        max=0.9,
        subtype='FACTOR',
        update=update_csm_split1
    )

    csm_split2: FloatProperty(
        name="Split 2",
        description="End of cascade 2 as a fraction of Max Distance. Must be greater than Split 1.",
        default=0.60,
        min=0.1,
        max=0.95,
        subtype='FACTOR',
        update=update_csm_split2
    )

    csm_base_steps: IntProperty(
        name="Base Steps",
        description="Grid resolution used for all three cascades. A higher value places more sample dots across each cascade area.",
        default=12,
        min=1,
        max=30,
        update=update_csm
    )

    csm_dot_size: FloatProperty(
        name="Dot Size",
        description="Size of the hit dots for each cascade.",
        default=0.06,
        min=0.0,
        max=0.2,
        step=0.01,
        precision=3,
        update=update_csm
    )

    show_csm_frustum: BoolProperty(
        name="Show Frustum Slices",
        description="Draw the colored frustum slice outlines for each cascade.",
        default=True,
        update=update_csm
    )

    is_csm_cam_view: BoolProperty(
        name="Camera View Active",
        description="Tracks whether the CSM camera view is currently active.",
        default=False,
    )

    csm_max_distance: FloatProperty(
        name="Max Distance",
        description="Total view distance covered by all 3 cascades.",
        default=20.0,
        min=1.0,
        max=200.0,
        update=update_csm
    )

    csm_overlap: FloatProperty(
        name="Cascade Overlap",
        description="How much adjacent cascades overlap at their boundary (fraction of each cascade's depth range). Dots in the overlap zone appear in both cascade colors, showing the blending region.",
        default=0.1,
        min=0.0,
        max=0.3,
        subtype='FACTOR',
        update=update_csm
    )

    is_bias_animating: BoolProperty(
        name="Bias Animating",
        description="Whether the automatic bias sweep is currently running.",
        default=False
    )

    #--- shadow map fitting properties ---

    is_rtw_active: BoolProperty(
        name="Fitting Active",
        description="Whether the Shadow Map Fitting visualization is currently shown.",
        default=False
    )

    rtw_light_object: PointerProperty(
        name="Light",
        description="Directional (sun) light used as the shadow caster for Shadow Map Fitting.",
        type=bpy.types.Object,
        poll=rtw_light_object_poll,
        update=update_rtw
    )

    rtw_cam_d_far: FloatProperty(
        name="Camera Far",
        description="How far the camera frustum extends. Controls the depth of the visible volume.",
        default=7.0,
        min=1.0,
        max=500.0,
        update=update_rtw
    )

    rtw_show_aabb: BoolProperty(
        name="Show Scene AABB",
        description="Draw the blue bounding box around all scene objects.",
        default=True,
        update=update_rtw
    )

    rtw_show_cam_frustum: BoolProperty(
        name="Show Camera Frustum",
        description="Draw the red camera view frustum (what the camera sees).",
        default=True,
        update=update_rtw
    )

    rtw_show_poly: BoolProperty(
        name="Show Intersection Polyhedron",
        description="Draw the actual 3D intersection shape (convex hull of frustum and scene AABB). This is the Potential Shadow Receivers (PSR) volume, shown in magenta.",
        default=True,
        update=update_rtw
    )
    rtw_show_poly_fill: BoolProperty(
        name="Fill Polyhedron with Colour",
        description="Fill the intersection polyhedron with a semi-transparent magenta colour (requires Intersection Polyhedron to be enabled).",
        default=False,
        update=update_rtw
    )

    rtw_show_loose: BoolProperty(
        name="Show Standard Frustum",
        description="Draw the orange shadow frustum covering the entire scene AABB -- this is what standard shadow mapping uses.",
        default=False,
        update=update_rtw
    )

    rtw_show_tight: BoolProperty(
        name="Show Tight Frustum",
        description="Draw the tight shadow frustum covering only the camera-frustum/AABB intersection -- this is what shadow map fitting produces.",
        default=False,
        update=update_rtw
    )

    rtw_show_psc: BoolProperty(
        name="Shadow Caster Volume (teal)",
        description="Show the Potential Shadow Casters (PSC) volume -- the PSR extended toward the light, clipped by the scene AABB. This captures objects outside the camera frustum that can still cast visible shadows.",
        default=False,
        update=update_rtw
    )

    rtw_show_psc_fill: BoolProperty(
        name="Fill PSC with Colour",
        description="Fill the PSC volume with a semi-transparent teal colour (requires Shadow Caster Volume to be enabled).",
        default=False,
        update=update_rtw
    )

    rtw_show_psc_rays: BoolProperty(
        name="Show PSC Extension",
        description="Draw dark blue rays from PSR convex hull vertices toward the light, showing how the PSC volume is constructed.",
        default=False,
        update=update_rtw
    )

    rtw_show_rays: BoolProperty(
        name="Show Shadow Rays",
        description="Cast a grid of parallel rays from the light and show lit (yellow) and shadowed (black) hits, same as the 3D Shadow Rays module.",
        default=True,
        update=update_rtw
    )

    rtw_ray_grid_steps: IntProperty(
        name="Ray Grid Steps",
        description="Number of ray subdivisions per axis across the tight shadow frustum. More steps = more rays.",
        default=5,
        min=1,
        max=30,
        update=update_rtw
    )

    rtw_ray_length: FloatProperty(
        name="Ray Length",
        description="How far back along the light direction to draw each ray line before it hits the surface.",
        default=5.0,
        min=0.1,
        max=100.0,
        update=update_rtw
    )

    rtw_rays_show_outside: BoolProperty(
        name="Show Rays Outside Camera View",
        description="When enabled, also show rays that fall outside the camera frustum / scene-AABB intersection. Disable to see only the rays that contribute to visible shadows.",
        default=True,
        update=update_rtw
    )

    rtw_dot_size: FloatProperty(
        name="Dot Size",
        description="Radius of the hit-point dots drawn on lit and shadowed surfaces.",
        default=0.06,
        min=0.005,
        soft_max=0.5,
        max=2.0,
        step=0.001,
        precision=3,
        update=update_rtw
    )

    rtw_show_ray_lines: BoolProperty(
        name="Show Ray Lines",
        description="Show the ray line segments. When off, only the hit-point dots are drawn.",
        default=True,
        update=update_rtw
    )

    rtw_thick_rays: FloatProperty(
        name="Ray Thickness",
        description="Line thickness of the shadow ray strokes.",
        default=0.008,
        min=0.001,
        max=0.05,
        update=update_rtw
    )

    #--- cubemap properties ---

    is_cubemap_active: BoolProperty(
        name="Cubemap Active",
        description="Whether the cube shadow map visualization is currently shown.",
        default=False
    )

    cubemap_light_object: PointerProperty(
        name="Light",
        description="Point light used as the cube shadow map caster. Only Point lights are supported.",
        type=bpy.types.Object,
        poll=cubemap_light_object_poll,
        update=update_cubemap
    )

    cubemap_max_distance: FloatProperty(
        name="Max Distance",
        description="Shadow map range -- geometry beyond this distance is outside the cube shadow map. Match to the light's attenuation radius.",
        default=20.0,
        min=0.5,
        max=500.0,
        update=update_cubemap
    )

    show_cubemap_frustums: BoolProperty(
        name="Show Frustums",
        description="Draw the 6 frustum wireframes, one per cube face.",
        default=True,
        update=update_cubemap
    )

    show_cubemap_dots: BoolProperty(
        name="Show Sample Dots",
        description="Cast rays into each face and draw dots on hit surfaces, colored by which cube face covers them.",
        default=False,
        update=update_cubemap
    )

    show_cubemap_rays: BoolProperty(
        name="Show Rays",
        description="Draw ray lines from the light to each hit surface, colored by cube face.",
        default=True,
        update=update_cubemap
    )

    cubemap_ray_width: FloatProperty(
        name="Ray Width",
        description="Thickness of the ray lines.",
        default=0.010,
        min=0.005, max=0.050,
        step=0.001, precision=3,
        update=update_cubemap
    )

    cubemap_dot_steps: IntProperty(
        name="Grid Size",
        description="Grid resolution per face. Steps=3 gives 7x7=49 rays per face (294 total).",
        default=6,
        min=1,
        max=15,
        update=update_cubemap
    )

    cubemap_dot_size: FloatProperty(
        name="Dot Size",
        description="Size of the hit dots for each face.",
        default=0.06,
        min=0.005,
        max=0.2,
        step=0.001,
        precision=3,
        update=update_cubemap
    )

    is_cube_face_cam_active: BoolProperty(
        name="Cube Face Cam Active",
        description="Whether a cube-face camera is currently active.",
        default=False
    )

    cubemap_face_view: EnumProperty(
        name="Face",
        description="Which cube map face to look through.",
        items=[
            ('0', '+X  (Red)',     ''),
            ('1', '-X  (Cyan)',    ''),
            ('2', '+Y  (Green)',   ''),
            ('3', '-Y  (Magenta)', ''),
            ('4', '+Z  (Blue)',    ''),
            ('5', '-Z  (Orange)',  ''),
        ],
        default='5'
    )


#---- panel ----

class SAV_PT_MainPanel(bpy.types.Panel):
    bl_label = "Shadow Map Visualizer"
    bl_idname = "SAV_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'ShadowMapVisualizer'
    bl_ui_units_x = 18

    def draw(self, context):
        layout = self.layout
        props = context.scene.sm_props

        #determine which module is active (at most one at a time)
        if props.is_2d_active:        active_module = "Shadow Acne & Bias (2D)"
        elif props.is_3d_active:      active_module = "3D Shadow Rays"
        elif props.is_csm_active:     active_module = "Cascaded Shadow Maps (CSM)"
        elif props.is_cubemap_active: active_module = "Cube Shadow Map"
        elif props.is_rtw_active:     active_module = "Shadow Map Fitting"
        else:                         active_module = None

        #===================== global settings =====================
        col = layout.column()
        col.prop(props, "auto_update", text="Auto Update")
        if not props.auto_update:
            col.label(text="Auto update is off.")
            col.label(text="Use Update buttons manually.")

        layout.separator()

        #===================== 2d section =====================
        main_2d = layout.box()
        row = main_2d.row()
        row.prop(props, "section_2d_expanded",
                 icon='TRIA_DOWN' if props.section_2d_expanded else 'TRIA_RIGHT',
                 emboss=False, text="")
        row.label(text="Shadow Acne & Bias (2D)")
        if props.is_2d_active:
            row.label(text="", icon='RADIOBUT_ON')
        else:
            row.label(text="", icon='RADIOBUT_OFF')

        if not props.section_2d_expanded:
            pass
        elif active_module and not props.is_2d_active:
            main_2d.label(text=f"Stop '{active_module}' first.")
        elif not props.is_2d_active:
            row = main_2d.row()
            row.scale_y = 1.5
            row.operator("sav.start_2d", text="Start 2D View")
        else:
            row = main_2d.row(align=True)
            row.scale_y = 1.4
            row.operator("sav.set_default", text="Reset Defaults")
            row.operator("sav.stop_2d",    text="Stop 2D View")

            main_2d.separator()

            box = main_2d.box()
            box.label(text="Light Setup", icon='LIGHT')
            box.prop(props, "light_type", text="")
            box.prop(props, "light_angle")
            if props.light_type == 'POINT':
                box.prop(props, "light_distance", text="Height")
                box.prop(props, "light_shift_x")

            box = main_2d.box()
            box.label(text="Scene Setup")
            box.prop(props, "floor_width")
            box.prop(props, "show_box")
            if props.show_box:
                col = box.column(align=True)
                col.prop(props, "box_x")
                col.prop(props, "box_width")
                col.prop(props, "box_height")

            box = main_2d.box()
            box.label(text="Shadow Map & Bias")
            box.prop(props, "shadow_map_steps")
            box.prop(props, "texel_size")
            col = box.column(align=True)
            col.label(text="Bias Calculation (x Texel Size):")
            col.prop(props, "bias_min")
            col.prop(props, "bias_slope")

            col.separator()
            if not props.is_bias_animating:
                col.operator("sav.start_bias_anim", text="Play Bias Animation")
            else:
                col.operator("sav.stop_bias_anim",  text="Stop Animation")

            disp_box = main_2d.box()
            disp_row = disp_box.row()
            disp_row.prop(props, "disp_2d_expanded",
                          icon='TRIA_DOWN' if props.disp_2d_expanded else 'TRIA_RIGHT',
                          emboss=False, text="")
            disp_row.label(text="Display Settings", icon='BRUSH_DATA')
            if props.disp_2d_expanded:
                col = disp_box.column()
                col.prop(props, "ray_frequency", text="Ray Frequency")
                col.prop(props, "rays_yellow",  text="Orange Rays")
                col.separator()
                col.label(text="Line Widths:")
                col.prop(props, "thick_floor",  text="Floor Line")
                col.prop(props, "thick_rays",   text="Rays")

        layout.separator()

        #===================== 3d section =====================
        main_3d = layout.box()
        row = main_3d.row()
        row.prop(props, "section_3d_expanded",
                 icon='TRIA_DOWN' if props.section_3d_expanded else 'TRIA_RIGHT',
                 emboss=False, text="")
        row.label(text="3D Shadow Rays")
        if props.is_3d_active:
            row.label(text="", icon='RADIOBUT_ON')
        else:
            row.label(text="", icon='RADIOBUT_OFF')

        if not props.section_3d_expanded:
            pass
        elif active_module and not props.is_3d_active:
            main_3d.label(text=f"Stop '{active_module}' first.")
        else:
            main_3d.prop(props, "light_object", text="Light")
            if props.light_object:
                main_3d.label(text=f"Type: {props.light_object.data.type}", icon='LIGHT')

            if not props.light_object:
                main_3d.label(text="Select any light to get started.")
            else:
                light_type_3d = props.light_object.data.type if props.light_object else ''

                col = main_3d.column(align=True)
                col.prop(props, "ray_grid_steps_3d")
                if light_type_3d == 'SUN':
                    col.prop(props, "ray_grid_size_3d")
                    col.prop(props, "ray_length_3d")
                col.separator(factor=0.4)
                freq_split = col.split(factor=0.45)
                freq_split.label(text="Ray Density")
                freq_split.prop(props, "ray_frequency_3d", text="")

                main_3d.separator(factor=0.2)
                col = main_3d.column(align=True)
                lines_row = col.row()
                lines_row.enabled = not props.is_light_cam_active
                lines_row.prop(props, "show_lines_3d", text="Show Ray Lines")
                if light_type_3d not in ('POINT', 'AREA'):
                    col.prop(props, "show_squares_3d", text="Show Texel Squares")
                    col.prop(props, "show_pcf_3d", text="Show PCF")

                main_3d.separator(factor=0.2)

                if not props.is_3d_active:
                    row = main_3d.row()
                    row.scale_y = 1.3
                    row.operator("sav.show_3d", text="Show Rays")
                else:
                    row = main_3d.row(align=True)
                    row.scale_y = 1.3
                    row.operator("sav.show_3d", text="Update")
                    row.operator("sav.hide_3d", text="Hide Rays")

                main_3d.separator(factor=0.5)

                box_cam = main_3d.box()
                box_cam.label(text="Light View Camera", icon='CAMERA_DATA')
                if not props.is_light_cam_active:
                    row = box_cam.row()
                    row.scale_y = 1.3
                    row.operator("sav.enter_light_cam", text="Switch to Light View")
                else:
                    row = box_cam.row()
                    row.scale_y = 1.3
                    row.operator("sav.exit_light_cam", text="Exit Light View")

                main_3d.separator(factor=0.5)
                disp_box = main_3d.box()
                disp_row = disp_box.row()
                disp_row.prop(props, "disp_3d_expanded",
                              icon='TRIA_DOWN' if props.disp_3d_expanded else 'TRIA_RIGHT',
                              emboss=False, text="")
                disp_row.label(text="Display Settings", icon='BRUSH_DATA')
                if props.disp_3d_expanded:
                    dcol = disp_box.column(align=True)
                    dcol.prop(props, "thick_rays_3d", text="Ray Width")
                    dcol.prop(props, "dot_size_3d",   text="Dot Size")
                    if props.show_squares_3d and light_type_3d not in ('POINT', 'AREA'):
                        dcol.prop(props, "square_line_width_3d", text="Square Line Width")

        layout.separator()

        #===================== csm section =====================
        main_csm = layout.box()
        row = main_csm.row()
        row.prop(props, "section_csm_expanded",
                 icon='TRIA_DOWN' if props.section_csm_expanded else 'TRIA_RIGHT',
                 emboss=False, text="")
        row.label(text="Cascaded Shadow Maps (CSM)")
        if props.is_csm_active:
            row.label(text="", icon='RADIOBUT_ON')
        else:
            row.label(text="", icon='RADIOBUT_OFF')

        if not props.section_csm_expanded:
            pass
        elif active_module and not props.is_csm_active:
            main_csm.label(text=f"Stop '{active_module}' first.")
        else:
            main_csm.prop(props, "csm_light_object", text="Light")
            if context.scene.camera:
                main_csm.label(text=f"Camera: {context.scene.camera.name}", icon='CAMERA_DATA')

            if not context.scene.camera:
                main_csm.label(text="No active camera in scene.")
            elif not props.csm_light_object:
                main_csm.label(text="No sun light selected.")
                has_sun = any(
                    obj.type == 'LIGHT' and obj.data.type == 'SUN'
                    for obj in context.scene.objects
                )
                if not has_sun:
                    row = main_csm.row()
                    row.scale_y = 1.3
                    row.operator("sav.add_sun_csm", text="Add Sun Light")
            else:
                col = main_csm.column(align=True)
                col.prop(props, "csm_max_distance")
                col.prop(props, "csm_split1", text="Split 1 (cascade 1 end)")
                col.prop(props, "csm_split2", text="Split 2 (cascade 2 end)")
                col.prop(props, "csm_overlap", text="Cascade Overlap")
                col.prop(props, "csm_base_steps")

                main_csm.separator(factor=0.5)
                col = main_csm.column(align=True)
                frustum_row = col.row()
                frustum_row.enabled = not props.is_csm_cam_view
                frustum_row.prop(props, "show_csm_frustum")

                main_csm.separator(factor=0.5)
                disp_box = main_csm.box()
                disp_row = disp_box.row()
                disp_row.prop(props, "disp_csm_expanded",
                              icon='TRIA_DOWN' if props.disp_csm_expanded else 'TRIA_RIGHT',
                              emboss=False, text="")
                disp_row.label(text="Display Settings", icon='BRUSH_DATA')
                if props.disp_csm_expanded:
                    disp_box.prop(props, "csm_dot_size", text="Dot Size")

                main_csm.separator(factor=0.5)
                if not props.is_csm_active:
                    row = main_csm.row()
                    row.scale_y = 1.3
                    row.operator("sav.show_csm", text="Show CSM")
                else:
                    row = main_csm.row(align=True)
                    row.scale_y = 1.3
                    row.operator("sav.show_csm",  text="Update")
                    row.operator("sav.hide_csm",  text="Hide CSM")

                main_csm.separator(factor=0.5)
                row = main_csm.row()
                row.scale_y = 1.3
                if not props.is_csm_cam_view:
                    row.operator("sav.csm_camera_view", text="Switch to Camera View")
                else:
                    row.operator("sav.csm_exit_camera_view", text="Exit Camera View")


        layout.separator()

        #===================== cubemap section =====================
        main_cube = layout.box()
        row = main_cube.row()
        row.prop(props, "section_cube_expanded",
                 icon='TRIA_DOWN' if props.section_cube_expanded else 'TRIA_RIGHT',
                 emboss=False, text="")
        row.label(text="Cube Shadow Map")
        if props.is_cubemap_active:
            row.label(text="", icon='RADIOBUT_ON')
        else:
            row.label(text="", icon='RADIOBUT_OFF')

        if not props.section_cube_expanded:
            pass
        elif active_module and not props.is_cubemap_active:
            main_cube.label(text=f"Stop '{active_module}' first.")
        else:
            main_cube.prop(props, "cubemap_light_object", text="Point Light")

            if not props.cubemap_light_object:
                main_cube.label(text="Select a Point light.")
            else:
                col = main_cube.column(align=True)
                col.prop(props, "cubemap_max_distance")
                col.prop(props, "show_cubemap_frustums", text="Show Frustums")
                col.prop(props, "show_cubemap_rays",     text="Show Rays")
                col.prop(props, "show_cubemap_dots",     text="Show Sample Dots")
                if props.show_cubemap_rays or props.show_cubemap_dots:
                    col.prop(props, "cubemap_dot_steps", text="Grid Size")

                main_cube.separator(factor=0.5)
                disp_box = main_cube.box()
                disp_row = disp_box.row()
                disp_row.prop(props, "disp_cube_expanded",
                              icon='TRIA_DOWN' if props.disp_cube_expanded else 'TRIA_RIGHT',
                              emboss=False, text="")
                disp_row.label(text="Display Settings", icon='BRUSH_DATA')
                if props.disp_cube_expanded:
                    dcol = disp_box.column(align=True)
                    dcol.prop(props, "cubemap_dot_size", text="Dot Size")
                    if props.show_cubemap_rays:
                        dcol.prop(props, "cubemap_ray_width", text="Ray Width")

                main_cube.separator(factor=0.5)
                if not props.is_cubemap_active:
                    row = main_cube.row()
                    row.scale_y = 1.3
                    row.operator("sav.show_cubemap", text="Show Cube Map")
                else:
                    row = main_cube.row(align=True)
                    row.scale_y = 1.3
                    row.operator("sav.show_cubemap", text="Update")
                    row.operator("sav.hide_cubemap", text="Hide Cube Map")

                if props.is_cubemap_active:
                    main_cube.separator(factor=0.4)
                    cam_box = main_cube.box()
                    cam_box.label(text="Face View Camera", icon='CAMERA_DATA')
                    if not props.is_cube_face_cam_active:
                        cam_box.prop(props, "cubemap_face_view", text="Face")
                        row = cam_box.row()
                        row.scale_y = 1.2
                        row.operator("sav.enter_cube_face_cam", text="Switch to Face View")
                    else:
                        row = cam_box.row()
                        row.scale_y = 1.2
                        row.operator("sav.exit_cube_face_cam", text="Exit Face View")


        layout.separator()

        #===================== fitting section =====================
        main_rtw = layout.box()
        row = main_rtw.row()
        row.prop(props, "section_rtw_expanded",
                 icon='TRIA_DOWN' if props.section_rtw_expanded else 'TRIA_RIGHT',
                 emboss=False, text="")
        row.label(text="Shadow Map Fitting")
        if props.is_rtw_active:
            row.label(text="", icon='RADIOBUT_ON')
        else:
            row.label(text="", icon='RADIOBUT_OFF')

        if not props.section_rtw_expanded:
            pass
        elif active_module and not props.is_rtw_active:
            main_rtw.label(text=f"Stop '{active_module}' first.")
        else:
            main_rtw.prop(props, "rtw_light_object", text="Light")
            if context.scene.camera:
                main_rtw.label(text=f"Camera: {context.scene.camera.name}", icon='CAMERA_DATA')

            if not context.scene.camera:
                main_rtw.label(text="No active camera in scene.")
            elif not props.rtw_light_object:
                main_rtw.label(text="No sun light selected.")
                has_sun = any(
                    obj.type == 'LIGHT' and obj.data.type == 'SUN'
                    for obj in context.scene.objects
                )
                if not has_sun:
                    row = main_rtw.row()
                    row.scale_y = 1.3
                    row.operator("sav.add_sun_rtw", text="Add Sun Light")
            else:
                col = main_rtw.column(align=True)
                col.prop(props, "rtw_cam_d_far",         text="Camera Far Distance")
                col.separator(factor=0.5)
                col.prop(props, "rtw_show_aabb",         text="Scene AABB (blue)")
                col.prop(props, "rtw_show_cam_frustum",  text="Camera Frustum (red)")
                col.prop(props, "rtw_show_poly",         text="Potential Shadow Receivers (magenta)")
                sub = col.column()
                sub.enabled = props.rtw_show_poly
                sub.prop(props, "rtw_show_poly_fill",    text="Fill PSR (magenta)")
                col.prop(props, "rtw_show_psc",          text="Potential Shadow Casters (teal)")
                sub2 = col.column()
                sub2.enabled = props.rtw_show_psc
                sub2.prop(props, "rtw_show_psc_fill",    text="Fill PSC (teal)")
                col.prop(props, "rtw_show_tight",        text="Tight Frustum (black)")
                col.separator(factor=1.0)
                col.prop(props, "rtw_show_psc_rays",     text="Construction Rays (dark blue)")
                col.prop(props, "rtw_show_loose",        text="Standard Frustum (orange)")
                col.separator(factor=0.5)

                col.prop(props, "rtw_show_rays", text="Shadow Rays (yellow/black)")
                if props.rtw_show_rays:
                    ray_box = main_rtw.box()
                    ray_col = ray_box.column(align=True)
                    ray_col.prop(props, "rtw_ray_grid_steps",      text="Grid Steps")
                    ray_col.prop(props, "rtw_ray_length",          text="Ray Length")
                    ray_col.prop(props, "rtw_show_ray_lines",      text="Show Ray Lines")
                    ray_col.separator(factor=0.5)
                    ray_col.prop(props, "rtw_rays_show_outside",   text="Show Rays Outside Camera View")

                main_rtw.separator(factor=0.5)
                disp_box = main_rtw.box()
                disp_row = disp_box.row()
                disp_row.prop(props, "disp_rtw_expanded",
                              icon='TRIA_DOWN' if props.disp_rtw_expanded else 'TRIA_RIGHT',
                              emboss=False, text="")
                disp_row.label(text="Display Settings", icon='BRUSH_DATA')
                if props.disp_rtw_expanded:
                    disp_col = disp_box.column(align=True)
                    disp_col.prop(props, "rtw_dot_size",   text="Dot Size")
                    disp_col.prop(props, "rtw_thick_rays", text="Ray Width")

                main_rtw.separator(factor=0.5)
                if not props.is_rtw_active:
                    row = main_rtw.row()
                    row.scale_y = 1.3
                    row.operator("sav.show_rtw", text="Show Fitting")
                else:
                    row = main_rtw.row(align=True)
                    row.scale_y = 1.3
                    row.operator("sav.show_rtw", text="Update")
                    row.operator("sav.hide_rtw", text="Hide Fitting")




#---- operator helper functions ----

def _apply_default_props(props):
    #batch-sets all 2D properties using suppression guard to avoid per-assignment redraws
    global _suppressing_updates
    _suppressing_updates = True
    props.texel_size = 1.0
    props.bias_min = 0.0
    props.bias_slope = 0.0
    props.is_bias_animating = False
    props.thick_floor = 0.02
    props.thick_rays = 0.015
    props.rays_yellow = False
    props.ray_frequency = '2'
    props.shadow_map_steps = 12
    props.floor_width = 7.0
    props.show_box = False
    props.box_x = 0.0
    props.box_width = 1.64
    props.box_height = 0.83
    if props.light_type == 'SUN':
        props.light_angle = math.radians(-45)
        props.light_shift_x = 0.0
    else:
        props.light_angle = 0.0
        props.light_distance = 8.0
        props.light_shift_x = 0.0
    _suppressing_updates = False


def _fix_viewport_for_3d(context):
    #switches to perspective mode, leaves view direction unchanged
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            r3d = area.spaces[0].region_3d
            if r3d.view_perspective != 'CAMERA':
                r3d.view_perspective = 'PERSP'
            area.spaces[0].overlay.show_cursor = True
            break


def _fix_viewport_for_2d(context):
    #switches to front orthographic and centers on the 2D scene
    area = None
    for a in context.screen.areas:
        if a.type == 'VIEW_3D':
            area = a
            break
    if not area:
        return
    region = None
    for r in area.regions:
        if r.type == 'WINDOW':
            region = r
            break
    if region:
        with context.temp_override(area=area, region=region):
            bpy.ops.view3d.view_axis(type='FRONT')
        r3d = area.spaces[0].region_3d
        r3d.view_perspective = 'ORTHO'
        r3d.view_distance = 22.0
        r3d.view_location = (0.0, 0.0, 3.0)
        area.spaces[0].overlay.show_cursor = False


#---- operators ----

class SAV_OT_SetDefault(bpy.types.Operator):
    bl_idname = "sav.set_default"
    bl_label = "Set Default Scene"
    bl_description = "Resets scene parameters to default and fixes view."

    def execute(self, context):
        props = context.scene.sm_props
        _apply_default_props(props)
        _fix_viewport_for_2d(context)
        update_viz(None, context)
        return {'FINISHED'}


class SAV_OT_Start2D(bpy.types.Operator):
    bl_idname = "sav.start_2d"
    bl_label = "Start 2D View"
    bl_description = "Hides all scene objects and starts the 2D shadow mapping visualization."

    def execute(self, context):
        props = context.scene.sm_props

        if props.is_3d_active:
            visualization_3d.clear_3d_objects()
            props.is_3d_active = False

        visualization_3d.save_viewport_state(context)
        visualization_3d.hide_scene_objects()
        props.is_2d_active = True

        #call helpers directly instead of bpy.ops.sav.set_default() which requires correct operator context
        _apply_default_props(props)
        _fix_viewport_for_2d(context)
        update_viz(None, context)
        return {'FINISHED'}


class SAV_OT_Stop2D(bpy.types.Operator):
    bl_idname = "sav.stop_2d"
    bl_label = "Stop 2D View"
    bl_description = "Removes the 2D visualization and restores all hidden scene objects."

    def execute(self, context):
        props = context.scene.sm_props
        visualization_2d.clear_old_objects()
        visualization_3d.restore_scene_objects()
        props.is_bias_animating = False
        visualization_3d.restore_viewport_state(context)
        props.is_2d_active = False
        return {'FINISHED'}


class SAV_OT_Show3D(bpy.types.Operator):
    bl_idname = "sav.show_3d"
    bl_label = "Show 3D Rays"
    bl_description = "Casts rays from the selected light and draws them on your scene."

    def execute(self, context):
        props = context.scene.sm_props

        if not props.light_object:
            self.report({'WARNING'}, "No light selected. Pick a light in the 3D Shadow Rays section.")
            return {'CANCELLED'}

        _fix_viewport_for_3d(context)
        props.is_3d_active = True
        visualization_3d.generate_3d_rays(context)
        return {'FINISHED'}


class SAV_OT_Hide3D(bpy.types.Operator):
    bl_idname = "sav.hide_3d"
    bl_label = "Hide 3D Rays"
    bl_description = "Removes the 3D ray visualization from the scene."

    def execute(self, context):
        props = context.scene.sm_props
        visualization_3d.clear_3d_objects()
        props.is_3d_active = False
        return {'FINISHED'}


class SAV_OT_EnterLightCam(bpy.types.Operator):
    bl_idname = "sav.enter_light_cam"
    bl_label = "Switch to Light View"
    bl_description = "Places a camera at the light and switches the viewport into it."

    def execute(self, context):
        props = context.scene.sm_props
        if not props.light_object:
            self.report({'WARNING'}, "No light selected.")
            return {'CANCELLED'}
        #guard: skip if already active to avoid stacking a second camera
        if props.is_light_cam_active:
            return {'CANCELLED'}
        visualization_3d.enter_light_cam_view(context, props.light_object)
        props.is_light_cam_active = True
        return {'FINISHED'}


class SAV_OT_ExitLightCam(bpy.types.Operator):
    bl_idname = "sav.exit_light_cam"
    bl_label = "Exit Light View"
    bl_description = "Removes the light camera and restores the previous viewport."

    def execute(self, context):
        props = context.scene.sm_props
        visualization_3d.exit_light_cam_view(context)
        props.is_light_cam_active = False
        return {'FINISHED'}


class SAV_OT_StartBiasAnim(bpy.types.Operator):
    bl_idname = "sav.start_bias_anim"
    bl_label = "Play Bias Animation"
    bl_description = "Sweeps Min Bias from 0 to 0.5 and back so you can see shadow acne vs peter panning live."

    def execute(self, context):
        global _bias_direction
        props = context.scene.sm_props
        #start from zero so acne is visible first, then watch it disappear
        props.bias_min = 0.0
        _bias_direction = 1
        props.is_bias_animating = True
        if not bpy.app.timers.is_registered(timer_bias_animate):
            bpy.app.timers.register(timer_bias_animate, persistent=True)
        return {'FINISHED'}


class SAV_OT_StopBiasAnim(bpy.types.Operator):
    bl_idname = "sav.stop_bias_anim"
    bl_label = "Stop Animation"
    bl_description = "Stops the bias sweep animation."

    def execute(self, context):
        context.scene.sm_props.is_bias_animating = False
        #timer checks is_bias_animating each tick and unregisters itself
        return {'FINISHED'}


class SAV_OT_CSMCameraView(bpy.types.Operator):
    bl_idname = "sav.csm_camera_view"
    bl_label = "Camera View"
    bl_description = "Switch the viewport to the scene camera so you can see exactly what each cascade covers."

    def execute(self, context):
        if not context.scene.camera:
            self.report({'WARNING'}, "No active camera in scene.")
            return {'CANCELLED'}
        props = context.scene.sm_props
        props.show_csm_frustum = False
        props.is_csm_cam_view  = True
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        with context.temp_override(area=area, region=region):
                            bpy.ops.view3d.view_camera()
                        break
                break
        return {'FINISHED'}


class SAV_OT_CSMExitCameraView(bpy.types.Operator):
    bl_idname = "sav.csm_exit_camera_view"
    bl_label = "Exit Camera View"
    bl_description = "Exit the camera view and re-enable frustum slice display."

    def execute(self, context):
        props = context.scene.sm_props
        props.is_csm_cam_view = False
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        with context.temp_override(area=area, region=region):
                            bpy.ops.view3d.view_camera()
                        break
                break
        return {'FINISHED'}


class SAV_OT_ShowCSM(bpy.types.Operator):
    bl_idname = "sav.show_csm"
    bl_label = "Show CSM"
    bl_description = "Generate the Cascaded Shadow Map visualization based on the active camera and selected light."

    def execute(self, context):
        props = context.scene.sm_props
        if not context.scene.camera:
            self.report({'WARNING'}, "No active camera in scene.")
            return {'CANCELLED'}
        _fix_viewport_for_3d(context)
        visualization_csm.generate_csm(context)
        props.is_csm_active = True
        return {'FINISHED'}


class SAV_OT_HideCSM(bpy.types.Operator):
    bl_idname = "sav.hide_csm"
    bl_label = "Hide CSM"
    bl_description = "Remove the CSM visualization from the scene."

    def execute(self, context):
        props = context.scene.sm_props
        visualization_csm.clear_csm_objects()
        props.is_csm_active = False
        return {'FINISHED'}


class SAV_OT_AddSunRTW(bpy.types.Operator):
    bl_idname = "sav.add_sun_rtw"
    bl_label = "Add Sun Light"
    bl_description = "Add a sun light and use it for Shadow Map Fitting visualization."

    def execute(self, context):
        props = context.scene.sm_props
        for obj in context.scene.objects:
            if obj.type == 'LIGHT' and obj.data.type == 'SUN':
                props.rtw_light_object = obj
                return {'FINISHED'}
        light_data = bpy.data.lights.new(name="Fitting_Sun", type='SUN')
        light_obj  = bpy.data.objects.new("Fitting_Sun", light_data)
        context.scene.collection.objects.link(light_obj)
        light_obj.location      = (0.0, 0.0, 10.0)
        light_obj.rotation_euler = (math.radians(20), 0.0, 0.0)
        props.rtw_light_object  = light_obj
        return {'FINISHED'}


class SAV_OT_ShowRTW(bpy.types.Operator):
    bl_idname = "sav.show_rtw"
    bl_label = "Show Fitting"
    bl_description = "Generate the Shadow Map Fitting visualization (scene AABB, camera frustum, loose and tight shadow boxes)."

    def execute(self, context):
        props = context.scene.sm_props
        if not props.rtw_light_object:
            self.report({'WARNING'}, "No sun light selected.")
            return {'CANCELLED'}
        if not context.scene.camera:
            self.report({'WARNING'}, "No active camera in scene.")
            return {'CANCELLED'}
        if not props.is_rtw_active:
            props.rtw_show_aabb        = True
            props.rtw_show_cam_frustum = True
        _fix_viewport_for_3d(context)
        visualization_fitting.generate_rtw(context)
        props.is_rtw_active = True
        return {'FINISHED'}


class SAV_OT_HideRTW(bpy.types.Operator):
    bl_idname = "sav.hide_rtw"
    bl_label = "Hide Fitting"
    bl_description = "Remove the Shadow Map Fitting visualization from the scene."

    def execute(self, context):
        props = context.scene.sm_props
        visualization_fitting.clear_rtw_objects()
        props.is_rtw_active = False
        return {'FINISHED'}


class SAV_OT_ShowCubemap(bpy.types.Operator):
    bl_idname = "sav.show_cubemap"
    bl_label = "Show Cube Map"
    bl_description = "Generate the cube shadow map visualization (6 frustums) around the selected light."

    def execute(self, context):
        props = context.scene.sm_props
        if not props.cubemap_light_object:
            self.report({'WARNING'}, "No light selected.")
            return {'CANCELLED'}
        if not props.is_cubemap_active:
            props.show_cubemap_frustums = True
            props.show_cubemap_rays     = True
        _fix_viewport_for_3d(context)
        visualization_cubemap.generate_cubemap(context)
        props.is_cubemap_active = True
        return {'FINISHED'}


class SAV_OT_HideCubemap(bpy.types.Operator):
    bl_idname = "sav.hide_cubemap"
    bl_label = "Hide Cube Map"
    bl_description = "Remove the cube shadow map visualization from the scene."

    def execute(self, context):
        props = context.scene.sm_props
        visualization_cubemap.clear_cubemap_objects()
        props.is_cubemap_active = False
        return {'FINISHED'}


class SAV_OT_EnterCubeFaceCam(bpy.types.Operator):
    bl_idname = "sav.enter_cube_face_cam"
    bl_label = "Switch to Face View"
    bl_description = "Place a 90-degree camera at the light and look through the selected cube map face."

    def execute(self, context):
        props = context.scene.sm_props
        if props.is_cube_face_cam_active:
            return {'CANCELLED'}
        face_idx = int(props.cubemap_face_view)
        visualization_cubemap.enter_face_cam_view(context, props.cubemap_light_object, face_idx)
        props.is_cube_face_cam_active = True
        return {'FINISHED'}


class SAV_OT_ExitCubeFaceCam(bpy.types.Operator):
    bl_idname = "sav.exit_cube_face_cam"
    bl_label = "Exit Face View"
    bl_description = "Remove the cube face camera and restore the previous viewport."

    def execute(self, context):
        props = context.scene.sm_props
        visualization_cubemap.exit_face_cam_view(context)
        props.is_cube_face_cam_active = False
        return {'FINISHED'}


class SAV_OT_AddSunCSM(bpy.types.Operator):
    bl_idname = "sav.add_sun_csm"
    bl_label = "Add Sun Light"
    bl_description = "Add a sun light to the scene and use it for CSM visualization."

    def execute(self, context):
        props = context.scene.sm_props

        #reuse existing sun light if available
        existing_sun = None
        for obj in context.scene.objects:
            if obj.type == 'LIGHT' and obj.data.type == 'SUN':
                existing_sun = obj
                break

        if existing_sun:
            props.csm_light_object = existing_sun
            return {'FINISHED'}

        light_data = bpy.data.lights.new(name="CSM_Sun", type='SUN')
        light_obj  = bpy.data.objects.new("CSM_Sun", light_data)
        context.scene.collection.objects.link(light_obj)
        light_obj.location     = (0.0, 0.0, 10.0)
        light_obj.rotation_euler = (0.0, 0.0, 0.0)
        props.csm_light_object = light_obj
        return {'FINISHED'}


#---- registration ----

classes = (
    SMProperties,
    SAV_PT_MainPanel,
    SAV_OT_SetDefault,
    SAV_OT_Start2D,
    SAV_OT_Stop2D,
    SAV_OT_Show3D,
    SAV_OT_Hide3D,
    SAV_OT_EnterLightCam,
    SAV_OT_ExitLightCam,
    SAV_OT_StartBiasAnim,
    SAV_OT_StopBiasAnim,
    SAV_OT_CSMCameraView,
    SAV_OT_CSMExitCameraView,
    SAV_OT_ShowCSM,
    SAV_OT_HideCSM,
    SAV_OT_AddSunCSM,
    SAV_OT_AddSunRTW,
    SAV_OT_ShowRTW,
    SAV_OT_HideRTW,
    SAV_OT_ShowCubemap,
    SAV_OT_HideCubemap,
    SAV_OT_EnterCubeFaceCam,
    SAV_OT_ExitCubeFaceCam,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.sm_props = PointerProperty(type=SMProperties)
    bpy.app.handlers.depsgraph_update_post.append(on_depsgraph_update)
    if not bpy.app.timers.is_registered(timer_check_update):
        bpy.app.timers.register(timer_check_update, persistent=True)


def unregister():
    #remove timer and handler before unregistering classes
    if bpy.app.timers.is_registered(timer_check_update):
        bpy.app.timers.unregister(timer_check_update)
    if bpy.app.timers.is_registered(timer_bias_animate):
        bpy.app.timers.unregister(timer_bias_animate)
    if on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(on_depsgraph_update)
    #remove GP materials to avoid orphaned data blocks after uninstall
    cube_mat_names = [f"SMViz_Cube_{i}" for i in range(6)] + \
                     [f"SMViz_Cube_{i}_Fill" for i in range(6)]
    for mat_name in ("SMViz_White_Fill", "SMViz_Yellow", "SMViz_Black", "SMViz_Orange",
                     "SMViz_Yellow_3D_Fill", "SMViz_Black_3D_Fill", "SMViz_Grey_3D_Fill", "SMViz_Grey_3D",
                     "SMViz_Yellow_3D", "SMViz_Black_3D",
                     "SMViz_Yellow_3D_Sq", "SMViz_Black_3D_Sq", "SMViz_Grey_3D_Sq",
                     "SMViz_CSM_0", "SMViz_CSM_1", "SMViz_CSM_2",
                     "SMViz_CSM_0_Fill", "SMViz_CSM_1_Fill", "SMViz_CSM_2_Fill",
                     *cube_mat_names,
                     "SMViz_Fitting_AABB", "SMViz_Fitting_Frustum",
                     "SMViz_Fitting_Loose", "SMViz_Fitting_Tight", "SMViz_Fitting_Poly", "SMViz_Fitting_PolyFill",
                     "SMViz_Fitting_PSC", "SMViz_Fitting_PSCFill", "SMViz_Fitting_PSCRays",
                     "SMViz_Fitting_LitFill", "SMViz_Fitting_ShadFill",
                     "SMViz_Fitting_LitRay", "SMViz_Fitting_ShadRay",
                     ):
        if mat_name in bpy.data.materials:
            bpy.data.materials.remove(bpy.data.materials[mat_name])
    del bpy.types.Scene.sm_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
