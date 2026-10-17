import bpy
import math
import numpy as np
from mathutils import Vector

PREFIX = "DS Trial"
REF_NAME = "01 Reference prosthesis | 120 mm top scale"
BOLT_CUTTER_NAME = "Bolt relief | 42 wide x 52 tall"

ref = bpy.data.objects.get(REF_NAME)
if ref is None:
    raise RuntimeError("Reference object not found: " + REF_NAME)

# ---- 读取参考网格世界坐标顶点 ----
ref_verts = np.array([(ref.matrix_world @ v.co)[:] for v in ref.data.vertices], dtype=float)
if ref_verts.shape[0] < 100:
    raise RuntimeError("Reference mesh too sparse")

z_all = ref_verts[:, 2]
z_min = float(np.min(z_all))
z_max = float(np.max(z_all))
H = z_max - z_min
if H <= 0.0:
    raise RuntimeError("Invalid reference height")

# 参考对象的 XY 中心只作粗基准，后续按高度带局部重估
xy_all = ref_verts[:, 0:2]
cx0 = float(np.mean(xy_all[:, 0]))
cy0 = float(np.mean(xy_all[:, 1]))

# ---- 高度带离散 ----
N_Z = 16
Z_LEVELS = np.linspace(z_min, z_max, N_Z)
# 每层角度分箱数（用于估计径向轮廓）
N_ANG_BINS = 72

# 背侧开口：+Y 方向，开口半角 gap 随高度略变化
# 角度范围从 pi/2 + gap 到 5*pi/2 - gap，覆盖约 300° 以上
def gap_half_at(t):
    return math.radians(17.0 + 4.0 * t)

# ---- 每层估计局部中心与轮廓采样 ----
# 对每个高度带：先剔除硬件突出点，再估计中心，再按角度取中位半径
z_band = max(H * 0.035, 1.0)

ring_centers = []
ring_radii = []
ring_z = []

for i in range(N_Z):
    z0 = Z_LEVELS[i]
    mask = np.abs(z_all - z0) < z_band
    if mask.sum() < 8:
        # 数据不足时向前一层的中心/半径退化
        if ring_centers:
            ring_centers.append(ring_centers[-1].copy())
            ring_radii.append(ring_radii[-1].copy())
            ring_z.append(z0)
        continue
    band_xy = xy_all[mask]

    # 局部中心：中位数，对硬件突出更稳健
    c_est = np.median(band_xy, axis=0)

    # 距中心的径向距离
    d = np.linalg.norm(band_xy - c_est[None, :], axis=1)
    d_med = np.median(d)
    mad = np.median(np.abs(d - d_med)) + 1e-6
    # 剔除明显突出点：距离超过中位数 + 2.5*MAD 视为硬件/噪声
    keep = d < (d_med + 2.5 * mad)
    if keep.sum() < 8:
        keep = np.ones_like(d, dtype=bool)
    band_xy = band_xy[keep]

    # 用保留点重新估计局部中心（中位数）
    c_est = np.median(band_xy, axis=0)

    # 按角度分箱取中位半径
    rel = band_xy - c_est[None, :]
    ang = np.arctan2(rel[:, 1], rel[:, 0])  # -pi..pi
    r = np.linalg.norm(rel, axis=1)

    # 角度分箱到 [0, 2pi)
    ang01 = np.mod(ang, 2.0 * math.pi)
    bins = np.floor(ang01 / (2.0 * math.pi) * N_ANG_BINS).astype(int)
    bins = np.clip(bins, 0, N_ANG_BINS - 1)

    med_r = np.full(N_ANG_BINS, np.nan)
    for b in range(N_ANG_BINS):
        sel = bins == b
        if sel.sum() > 0:
            med_r[b] = np.median(r[sel])

    # 角度分箱中值平顺（循环）
    valid = ~np.isnan(med_r)
    if valid.sum() >= 3:
        idx = np.arange(N_ANG_BINS)
        med_r = np.interp(idx, idx[valid], med_r[valid], period=N_ANG_BINS)
    else:
        med_r = np.nan_to_num(np.where(np.isnan(med_r), d_med, med_r), nan=d_med)

    # 轻度平顺：简单移动平均
    kernel = np.array([0.25, 0.5, 0.25])
    padded = np.concatenate([med_r[-1:], med_r, med_r[:1]])
    med_r = np.convolve(padded, kernel, mode='same')[1:-1]

    ring_centers.append(c_est.astype(float))
    ring_radii.append(med_r.astype(float))
    ring_z.append(z0)

if len(ring_z) < 4:
    raise RuntimeError("Not enough valid height bands")

# 统一中心序列为数组
centers = np.array(ring_centers, dtype=float)  # (nz, 2)
radii = np.array(ring_radii, dtype=float)      # (nz, n_ang)
zs = np.array(ring_z, dtype=float)

# ---- 构建 C 壳径向环 ----
# 周向采样数（沿开口路径）
N_RING = 96

# 外层概念偏置（mm 概念值，非实测）
offset_side = 3.0
offset_front = 2.5
offset_back = 4.0

rings = []
for i in range(len(zs)):
    t = i / max(1, len(zs) - 1)
    gap_half = gap_half_at(t)
    theta_start = math.pi * 0.5 + gap_half
    theta_end = math.pi * 2.5 - gap_half
    cx, cy = centers[i]
    r_ang = radii[i]

    ring = []
    for j in range(N_RING):
        a = j / (N_RING - 1)
        theta = theta_start + a * (theta_end - theta_start)
        # 查表半径：角度对应到 [0, 2pi) 分箱
        th01 = (theta % (2.0 * math.pi))
        fidx = th01 / (2.0 * math.pi) * (N_ANG_BINS - 1)
        i0 = int(math.floor(fidx))
        i1 = min(i0 + 1, N_ANG_BINS - 1)
        w = fidx - i0
        r_base = r_ang[i0] * (1.0 - w) + r_ang[i1] * w

        nx = math.cos(theta)
        ny = math.sin(theta)
        # 方向相关偏置：侧向较小、前后适度
        if abs(nx) > abs(ny):
            off = offset_side
        elif ny > 0.0:
            off = offset_front
        else:
            off = offset_back

        px = cx + (r_base + off) * nx
        py = cy + (r_base + off) * ny
        rings.append([px, py, zs[i]])

rings = np.array(rings, dtype=float)

# ---- 上口异形边缘：从参考网格按角度提取最高点 ----
# 在开口路径上按角度采样，找参考中同角度附近的最高 z
N_EDGE = 64
edge_thetas = np.linspace(math.pi * 0.5 + gap_half_at(1.0),
                          math.pi * 2.5 - gap_half_at(1.0), N_EDGE)

# 参考顶点相对全局粗中心的极角
rel_ref = ref_verts[:, 0:2] - np.array([cx0, cy0])[None, :]
ang_ref = np.mod(np.arctan2(rel_ref[:, 1], rel_ref[:, 0]), 2.0 * math.pi)
z_ref = ref_verts[:, 2]

edge_heights = np.full(N_EDGE, np.nan)
for k, th in enumerate(edge_thetas):
    th01 = (th % (2.0 * math.pi))
    d_ang = np.abs(((ang_ref - th01 + math.pi) % (2.0 * math.pi)) - math.pi)
    sel = d_ang < math.radians(6.0)
    if sel.sum() > 0:
        edge_heights[k] = np.percentile(z_ref[sel], 92.0)

valid_e = ~np.isnan(edge_heights)
if valid_e.sum() >= 3:
    idx_e = np.arange(N_EDGE)
    edge_heights = np.interp(idx_e, idx_e[valid_e], edge_heights[valid_e])
else:
    edge_heights = np.full(N_EDGE, z_max)

# 轻度平顺上口曲线
kernel_e = np.array([0.25, 0.5, 0.25])
pad_e = np.concatenate([edge_heights[-1:], edge_heights, edge_heights[:1]])
edge_heights = np.convolve(pad_e, kernel_e, mode='same')[1:-1]

# 按边缘曲线抬升最高环
top_z_mean = float(np.mean(rings[-N_RING:, 2]))
for j in range(N_RING):
    a = j / (N_RING - 1)
    k = int(round(a * (N_EDGE - 1)))
    target_z = float(edge_heights[k])
    # 不凭空叠加双峰，只按参考边缘曲线微调顶环，限制幅度
    dz = target_z - top_z_mean
    dz = max(-0.15 * H, min(0.15 * H, dz))
    rings[-N_RING + j, 2] = top_z_mean + dz

# ---- 构建壳体网格 ----
verts = [tuple(p) for p in rings]
faces = []
nz = len(zs)
for i in range(nz - 1):
    a0 = i * N_RING
    a1 = (i + 1) * N_RING
    for j in range(N_RING - 1):
        faces.append((a0 + j, a0 + j + 1, a1 + j + 1, a1 + j))

# 关闭顶部与底部边界环（保持薄壳开口）
mesh = bpy.data.meshes.new(PREFIX + " shell mesh")
mesh.from_pydata(verts, [], faces)
mesh.update()
obj = bpy.data.objects.new(PREFIX + " Shell", mesh)
bpy.context.collection.objects.link(obj)

# ---- 壁厚与平顺 ----
solid = obj.modifiers.new(name="Solidify", type='SOLIDIFY')
solid.thickness = 2.4
solid.offset = 1.0
bev = obj.modifiers.new(name="Bevel", type='BEVEL')
bev.width = 0.8
bev.segments = 2
bev.limit_method = 'ANGLE'
subs = obj.modifiers.new(name="Subdivision", type='SUBSURF')
subs.levels = 1
subs.render_levels = 2

# ---- 螺栓避让：从场景已有概念切割器复制并做 Boolean DIFFERENCE ----
cut_src = bpy.data.objects.get(BOLT_CUTTER_NAME)
bolt_relief_obj = None
if cut_src is not None and cut_src.type == 'MESH':
    # 复制数据，不动原对象
    cutter_mesh = cut_src.data.copy()
    cutter_obj = bpy.data.objects.new(PREFIX + " Bolt relief cutter", cutter_mesh)
    bpy.context.collection.objects.link(cutter_obj)
    cutter_obj.matrix_world = cut_src.matrix_world.copy()
    # 布尔差集：真正从壳体减去材料
    bool_mod = obj.modifiers.new(name="Bolt relief boolean", type='BOOLEAN')
    bool_mod.operation = 'DIFFERENCE'
    bool_mod.object = cutter_obj
    bool_mod.solver = 'EXACT'
    bolt_relief_obj = cutter_obj

# 将修改器结果显式化，便于查看
bpy.context.view_layer.objects.active = obj
obj.select_set(True)

print("Created:", obj.name)
if bolt_relief_obj is not None:
    print("Boolean cutter:", bolt_relief_obj.name)
else:
    print("Bolt cutter not found, shell created without relief")
