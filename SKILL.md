---
name: catia-threeview-modeler
description: "从一张标准工程三视图（主/俯/左视，含尺寸标注）自动在 CATIA V5 中建立参数化三维模型，并输出 .CATProduct 装配体文件（含其引用的 .CATPart）。当用户上传三视图/工程图/零件图并要求用 CATIA 建模、转三维、生成 CATPart/CATProduct、按图纸建实体时使用。产物保留完整特征树（Pad/Pocket/Hole/Fillet/Chamfer + 关联草图），基准与 XY/YZ/ZX 平面对齐；尺寸缺失或投影矛盾时先提问、不臆造尺寸。"
---

# 三视图转 CATIA 自动建模

把一张标准三视图图片解读为参数化特征树，驱动本机 CATIA V5 生成可编辑的三维模型，最终交付 `.CATProduct`（+ 引用的 `.CATPart`）。

## 前置环境

运行前先自检（Python 用 anaconda3 解释器）：

```
python scripts/check_env.py
```

要求：Windows + 已安装并运行 CATIA V5（R2016 及以上）；Python 已装 `pycatia`、`pywin32`。
未装依赖则 `pip install pycatia pywin32`。**CATIA 未运行/不可连时不得继续建模，直接告知用户。**

## 工作流

### 第 1 步：读图与特征识别
用 Read 工具读三视图（必要时分区域放大、提高清晰度）。按 `references/threeview_reading.md` 解读：
- 判断投影法（第一角/第三角），对齐长对正/高平齐/宽相等；
- 提取全部尺寸、孔位、圆角、厚度；
- 确定基准面与原点（`datum.origin`）。

### 第 2 步：防呆提问（硬门槛）
只要出现以下任一情况，**立即停止、先向用户提问**，严禁编造尺寸：
- 关键尺寸缺失/模糊；三视图投影矛盾；隐藏结构无法唯一确定；缺视图；比例/单位不明。

提问一次问完并给候选值（见 threeview_reading.md 示例）。用户答复后再继续。

### 第 3 步：写特征 JSON
按 `references/features_schema.md` 写特征树 JSON（支持 pad/pocket/hole/fillet/chamfer、单/多零件、装配 position）。
- 特征顺序：先 pad，再 fillet/chamfer，最后 hole/pocket；
- 节点 id 用语义短名，脚本自动规范命名（Sketch_/Pad_/Hole_…，实体 MainBody）；
- 单零件 → 一个 part；多零件装配 → 多 part + position 定位。

### 第 4 步：校验（未通过不得建模）
```
python scripts/validate_features.py <你的.json> --out <规范化.json>
```
脚本报轮廓未闭合/尺寸非法/特征引用错误时，先修 JSON 再进下一步。

### 第 5 步：驱动 CATIA 建模
```
python scripts/catia_build.py <规范化.json> --output-dir <输出目录> --capture <输出目录>
```
- 自动建：关联草图 → Pad/Pocket → Hole → Fillet/Chamfer → 存 .CATPart → 挂入产品树 → 存 .CATProduct；
- `--capture` 同时导出 JPG 预览图用于核对。

### 第 6 步：核对交付
用 Read 打开预览 JPG，与三视图逐一核对（轮廓、孔位、圆角、厚度、装配位置）。
不一致就修 JSON 重跑。核对通过后，用 present_files 交付 `.CATProduct`（并附 `.CATPart` 与预览图）。

## 能力边界（v1）
- 支持：直线/圆弧/整圆、任意多边形（含缺口/L形/圆角）轮廓的棱柱与圆柱凸台；在已有凸台顶面叠加凸台（plane_offset）；直孔与沉头孔（counterbore）；矩形/圆形 Pocket（任意基准面）；竖边圆角/倒角；多凸台、多零件装配定位。
- 不支持：埋头孔/螺纹孔（建模后在 CATIA 中手工补）、抽壳/拔模/扫掠/肋板/加强筋、阵列特征（用多个独立 Hole 表达）、自由曲面、工程图(.CATDrawing)输出。遇到需这些特征的图纸，告知用户该部分需在 CATIA 中手工补充。

## 脚本速查
| 脚本 | 作用 |
| --- | --- |
| `scripts/check_env.py` | 环境与 CATIA 连通自检 |
| `scripts/validate_features.py` | 校验/规范化特征 JSON，输出可读特征树摘要 |
| `scripts/catia_build.py` | 驱动 CATIA 建模，产出 .CATPart/.CATProduct，可截图 |

## 参考
- `references/threeview_reading.md`：读图方法 + 防呆提问规则 + 核对清单
- `references/features_schema.md`：特征 JSON 完整字段说明与示例
