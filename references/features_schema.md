# 三视图特征 JSON Schema（v1）

把三视图解读为一棵参数化特征树，写成本 JSON，再由 `scripts/catia_build.py` 驱动 CATIA。
所有尺寸单位 **mm**，草图坐标为零件坐标系下的 2D 坐标（X/Y 按所选平面的两个轴）。

## 顶层结构

```json
{
  "product_name": "Bracket",
  "unit": "mm",
  "output_dir": "O:/catia建模skill",
  "datum": { "origin": "...", "main_plane": "XY", "note": "..." },
  "parts": [ ... ]
}
```

- `datum.origin`：原点摆放规则（如 `base_corner` 底板角点、`base_center` 底板几何中心、`hole_center` 基准孔中心）。
  建模时把该点放在零件坐标系原点，使主要对称面/加工基准与 XY/YZ/ZX 平面对齐。
- `parts[]`：一个零件一个对象。单零件图纸就放一个；多零件装配图拆成多个并给各自 `position`。

## 零件对象

```json
{
  "name": "Bracket",
  "features": [ ... ],
  "position": [0, 0, 0]
}
```

- `position`：在产品中的平移量 [tx, ty, tz]，用于多零件装配定位。

## 特征类型

### pad 凸台（拉伸）
```json
{
  "type": "pad", "id": "base",
  "plane": "XY",            // XY / YZ / ZX
  "plane_offset": 0,        // 可选：草图平面相对基准面的偏移（如在底板顶面叠凸台时填底板厚）
  "height": 10,
  "profiles": [ {"loop": [ ... ]} ]
}
```
轮廓实体（按顺序首尾相接，闭合）：
- 直线：`{"e":"line","p1":[x1,y1],"p2":[x2,y2]}`
- 圆弧：`{"e":"arc","c":[cx,cy],"r":r,"a0":0,"a1":90}`（角度制，逆时针；a0→a1 为该弧在轮廓中的走向）
- 整圆（自成闭合，做圆柱/凸台）：`{"e":"circle","c":[cx,cy],"r":r}`，作为 profile 直接给出即可。

### hole 打孔（真实 Hole 特征，非 Pocket 替代）
```json
{
  "type": "hole", "id": "h1",
  "on": "base",             // 依附的 pad id
  "face": "top",            // top / bottom
  "point3d": [x, y, z],     // 孔中心在零件坐标系下的 3D 坐标（其拉伸轴分量必须落在该 pad 顶/底面：XY板看z、YZ板看x、ZX板看y）
  "diameter": 12,
  "depth": 10,              // 通孔时 = 板厚；盲孔填实际深度
  "hole_type": "simple",    // 可选：simple(默认) / counterbore(沉头)
  "head_diameter": 14,      // hole_type=counterbore 时必填：沉头直径
  "head_depth": 5           // hole_type=counterbore 时必填：沉头深度
}
```

### pocket 凹槽/通槽
```json
{
  "type": "pocket", "id": "p1",
  "on": "base",
  "depth": 5,
  "profiles": [ {"e":"circle","c":[50,30],"r":18} ]
}
```
草图自动建在 `on` 凸台顶面，向零件内部切 `depth`。

### fillet 圆角（对凸台竖边）
```json
{ "type": "fillet", "id": "f1", "on": "base", "radius": 3 }
```
自动对 `on` 凸台的全部竖边倒圆角。圆柱轮廓自动跳过。

### chamfer 倒角（对凸台竖边/四角）
```json
{ "type": "chamfer", "id": "c1", "on": "base", "length": 2 }
```
45° 等边长倒角，作用于该凸台的全部竖边（四角）。圆柱轮廓自动跳过。

## 特征顺序原则
1. 先所有 pad（基础凸台/底板/立板）；
2. 再 fillet/chamfer；
3. 最后 hole / pocket（减材特征放后面，特征树更干净）。

## 规范命名
脚本自动把节点命名为：`Sketch_<id>`、`Pad_<id>`、`Pocket_<id>`、`Hole_<id>`、`Fillet_<id>`、`Chamfer_<id>`，实体体 `MainBody`。`id` 用语义化短名（base/rib/hole1…）。

## 校验
```
python scripts/validate_features.py <你的.json> --out <规范化.json>
```
校验不通过会给出具体错误行号；**未通过不得进入建模**。
