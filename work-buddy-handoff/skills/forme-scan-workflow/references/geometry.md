# 每单几何证据准备

生产生成器读取 `data/cover_tasks/{id}/scan_reference`，不能直接复制其他订单或 reconstruction_trials 的结果当新输入。

## 1. 标尺与当前相机

本单 COLMAP 到达 scale_review 后，使用 `scripts/calibrate_ruler.py` 或面板标尺工具。至少三张有明显基线的当前建模帧，在每帧点击相同物理 A/B 圆心。圆心建议只辅助标注，不等于实际标尺长度。

校准输出放到本单 `ruler_calibration.json`。保留 sourceVideoSha256、modelFilesSha256、knownTargetLengthMm、mmPerColmapUnit、targetAColmap/B、quality。相机文件来自该 model_job.metrics.colmapModel，位于本单 model_jobs/{jobId}/sparse 下。若改用另一轮重建，必须重标／复算，不能沿用旧尺度。

## 2. 裁剪与刚体坐标

从当前 fused.ply 提取主体原始点子集，保留 RGB；排除床、地、鞋和标靶。用当前 pycolmap 相机将点投回至少三个相隔方向的原图，检查主体、上口及螺栓下段。透明/反光/内腔点需要明确处理，不以凸包填补当实测。

构造 4×4 `colmapToUprightMm`：

- 线性部分只能是本单标尺尺度乘以正交旋转，行列式为正；不能额外轴向缩放、镜像或剪切。
- 先由地面可靠区域拟合法向，标尺／相机给出前后方向；不要把相机画面竖直直接当假肢轴。
- 使用主体多个高度的外轮廓中心做鲁棒直线拟合，比较 bbox/凸包/椭圆中心估计，使用稳定共同趋势做刚体定轴。不能把每截面独立平移成笔直而丢失真实曲率。
- 在模板坐标中 X 为左右，前面是负 Y，参考中心为 (0,24) mm。当前首版引擎保留 06 模板上部高度 315.2504 mm；Z=0 为未延长模板底，不是地面。
- 按实际最高边缘和露出高翻边的目标选择竖直平移。下缘 Z 由当前连接段决定，落在螺栓下方且避开踝部／鞋，并以 10 mm 网格取值。不能复制历史 -60 当测量结果。

frame JSON 至少包含 sourceVideoSha256 和 colmapToUprightMm。坐标与原图证据必须相符。

## 3. 上口、螺栓与复核图

- 从裁剪点云按相同中心的 36 个 10° 扇区估计外上缘 q99.5，投回相机核对物理边缘。生成器按当前边缘裁低，默认露出 20 mm；内腔／纸翘边不能误当外边界。
- 在至少两到三张相机中标注同一个螺栓基部及尖端，三角化估计基部 baseMm、归一化外向轴 axis；报告重投影误差。特征遮挡时用侧视图约束，不猜另一侧。
- 孔径由当前螺栓头／操作通道估计并给合理试配余量；记录估计依据。下缘应在孔下还有实质覆盖，后台会拒绝孔下不足 10 mm 的配方。
- 至少三张复核图要包含：正面／侧面主体轴线与外轮廓、上口真实边缘、螺栓孔和下缘的原相机回投。单纯三张漂亮渲染图不足以批准。

recipe JSON 的结构如下，数值必须填本单实际结果：

```json
{
  "templateId":"06", "centerXYMm":[0,24],
  "bottomZMm":-60, "rimExposureMm":20, "clearanceMm":2,
  "bolt":{"baseMm":[35.46,9.91,9.26],"axis":[0.98404,0.17792,0.00076],"diameterMm":38}
}
```

上面是历史结构示例，禁止直接作为另一订单的参数。当前生成器仅接受 06 模板；其他模板的坐标、双片结构与扣件需独立接入。

## 4. 封存为复核卡

在后端目录用带科学库的几何 Python 运行：

```sh
/实际几何Python scripts/prepare_scan_reference.py \
  --data-dir ./data --submission 实际任务号 \
  --crop-ply /本单/原始坐标主体子集.ply \
  --frame-json /本单/刚体毫米坐标.json \
  --recipe-json /本单/配方.json \
  --overlay /本单/正侧回投.png \
  --overlay /本单/上口回投.png \
  --overlay /本单/螺栓下缘回投.png \
  --target-mm 已确认的实体长度 --notes '本单分割、轴线、上口和螺栓证据说明'
```

helper 校验裁剪是本单原始点云子集、坐标仅旋转与标尺尺度、源视频和标尺一致；写入标准 NPZ、几何报告、36扇区边缘、图片和文件哈希。它不替代人工／Agent 判断图像中的实物边缘。

已存在 scan_reference 时默认拒绝覆盖。需要修改时先确认队列未在运行，再将旧 reference 移到本单具名历史目录并记录原因，然后重新准备；旧批准失效。不得改哈希文件来掩盖旧输入。
