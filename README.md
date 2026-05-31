# Shadow Map Visualizer -- Blender Add-on

An interactive educational Blender add-on that visualizes the principles of shadow mapping algorithms. Developed as a Master's thesis at the Faculty of Information Technology, Brno University of Technology, 2026.

## What it visualizes

| Module | Technique | Supported lights |
|--------|-----------|-----------------|
| 1 | **Shadow Acne & Bias (2D)** -- 2D cross-section view demonstrating shadow acne, depth bias, and the Peter Panning artifact | Sun, Point |
| 2 | **3D Shadow Rays** -- casts a ray grid from the selected light onto the real scene geometry; lit surfaces marked yellow, shadowed black; optional PCF and texel square overlays | Sun, Spot, Point, Area |
| 3 | **Cascaded Shadow Maps (CSM)** -- divides the camera frustum into three depth cascades and visualizes their frustum slices and sampling grids | Sun |
| 4 | **Cube Shadow Maps** -- visualizes the six 90-degree frustums of a point light cube shadow map, each in a distinct color; includes a Face View Camera | Point |
| 5 | **Shadow Map Fitting** -- draws the scene AABB, camera frustum, Potential Shadow Receivers (PSR) and Potential Shadow Casters (PSC), and compares loose vs. tight shadow frustum | Sun |

## Requirements

- **Blender 5.0 or newer** (including Blender 5.1+)
- No external Python packages needed

## Installation

1. Download `ShadowMapVisualizer.zip` from [Releases](../../releases).
2. Open Blender and go to **Edit -> Preferences -> Add-ons**.
3. Click the **down-arrow button** in the top-right corner and select **Install from Disk...**
4. Select the downloaded `.zip` file.
5. Enable the **Shadow Map Visualizer** add-on by checking its checkbox.
6. The panel is available in the **3D Viewport -> Sidebar (N key) -> ShadowMapVisualizer** tab.

## Usage

Open the **ShadowMapVisualizer** tab in the 3D Viewport sidebar. Each module has its own collapsible section. For modules 2--5, open the corresponding pre-prepared scene, select a light source, and click **Show**.

Enable **Auto Update** to refresh the visualization automatically when the scene changes.

### Pre-prepared scenes

| Scene | Module |
|-------|--------|
| `Module2_3D_Shadow_Rays.blend` | 3D Shadow Rays |
| `Module3_Cascaded_Shadow_Maps.blend` | Cascaded Shadow Maps |
| `Module4_Cube_Shadow_Map.blend` | Cube Shadow Maps |
| `Module5_Shadow_Map_Fitting.blend` | Shadow Map Fitting |

## Author

Emma Krompaščiková -- Faculty of Information Technology, Brno University of Technology, 2026  
Supervisor: Ing. Tomas Milet, Ph.D.
