# -*- coding: utf-8 -*-
"""三视图建模 Skill 共享库：特征 JSON 规范化、轮廓闭合校验、BRep 引用名构造。

约定（全部单位 mm，草图坐标为零件坐标系下的 2D 坐标）：
- 平面: "XY" / "YZ" / "ZX"（绝对基准平面）
- 轮廓实体:
    line  : {"e":"line","p1":[x1,y1],"p2":[x2,y2]}
    arc   : {"e":"arc","c":[cx,cy],"r":R,"a0":起始角度,"a1":终止角度}  CCW，1..N 条边按顺序首尾相接
    circle: {"e":"circle","c":[cx,cy],"r":R}  单轮廓自成闭合
"""
import math

TOL = 1e-6


# ---------- 轮廓实体解析 ----------
def segment_points(e):
    """把一个实体展开为有向线段 (x1,y1,x2,y2)；arc 由圆心/半径/角度展开。"""
    t = e.get("e")
    if t == "line":
        p1, p2 = e["p1"], e["p2"]
        return (float(p1[0]), float(p1[1]), float(p2[0]), float(p2[1]))
    if t == "arc":
        cx, cy = float(e["c"][0]), float(e["c"][1])
        r = float(e["r"])
        a0 = math.radians(float(e["a0"]))
        a1 = math.radians(float(e["a1"]))
        return (cx + r * math.cos(a0), cy + r * math.sin(a0),
                cx + r * math.cos(a1), cy + r * math.sin(a1))
    raise ValueError(f"未知实体类型: {t}")


def loop_segments(profile):
    """把一个 profile 展开为有向线段列表。
    profile 形式: {"loop":[...]} | 实体列表 | 单个实体 {"e":...}。"""
    ents = profile_ents(profile)
    return [segment_points(e) for e in ents]


def is_closed(segs, tol=TOL):
    if not segs:
        return False
    sx, sy = segs[0][0], segs[0][1]
    ex, ey = segs[-1][2], segs[-1][3]
    if abs(sx - ex) > tol or abs(sy - ey) > tol:
        return False
    for i in range(len(segs) - 1):
        x1, y1 = segs[i][2], segs[i][3]
        x2, y2 = segs[i + 1][0], segs[i + 1][1]
        if abs(x1 - x2) > tol or abs(y1 - y2) > tol:
            return False
    return True


def profile_kind(profile):
    """返回 'circle' | 'loop'。"""
    ents = profile_ents(profile)
    if len(ents) == 1 and ents[0].get("e") == "circle":
        return "circle"
    return "loop"


def profile_ents(profile):
    if isinstance(profile, dict) and "loop" in profile:
        return profile["loop"]
    if isinstance(profile, dict) and "e" in profile:
        return [profile]
    return profile


def profile_edge_count(profile):
    ents = profile_ents(profile)
    return len(ents)


# ---------- BRep 引用名 ----------
def face_brep(shape_name, face_index):
    """顶/底面 BRep 名。face_index: 2=顶面(拉伸端), 1=底面(草图侧)。"""
    return (f"RSur:(Face:(Brp:({shape_name};{face_index});None:());"
            f"WithTemporaryBody;WithoutBuildError;WithSelectingFeatureSupport)")


def vertical_edge_brep(shape_name, edge_i, total):
    """竖边 BRep 名：草图第 edge_i 条边与第 edge_i+1 条边之间的面交所成竖边。
    edge_i: 1..total（与草图曲线创建顺序一致）。"""
    j = (edge_i % total) + 1
    return (f"REdge:(Edge:(Face:(Brp:({shape_name};0:(Brp:(Sketch.1;{edge_i})));None:());"
            f"Face:(Brp:({shape_name};0:(Brp:(Sketch.1;{j})));None:());"
            f"None:(Limits1:();Limits2:()));WithTemporaryBody;WithoutBuildError;WithSelectingFeatureSupport)")


# ---------- 特征 JSON 规范化与校验 ----------
def _require(cond, msg, errors, path):
    if not cond:
        errors.append(f"{path}: {msg}")


def normalize(data):
    """校验并规范化特征 JSON。返回 (normalized, errors, warnings)。"""
    errors, warnings = [], []

    _require(isinstance(data, dict), "根节点必须是对象", errors, "$")
    product_name = data.get("product_name", "Product")
    output_dir = data.get("output_dir")
    parts = data.get("parts")
    _require(isinstance(parts, list) and len(parts) > 0, "必须提供 parts 数组且至少一个零件", errors, "$")

    norm_parts = []
    if isinstance(parts, list):
        for pi, part in enumerate(parts):
            ppath = f"$.parts[{pi}]"
            features = part.get("features", [])
            _require(isinstance(features, list) and features, f"{ppath} 必须有非空 features", errors, ppath)
            pid = part.get("name", f"Part{pi+1}")

            stack = {}   # id -> {"height":z, "edges":n, "plane":plane}
            norm_features = []
            for fi, feat in enumerate(features):
                fpath = f"{ppath}.features[{fi}]"
                ftype = feat.get("type")
                fid = feat.get("id") or f"f{fi}"
                item = {"type": ftype, "id": fid, "raw": feat}

                if ftype == "pad":
                    plane = feat.get("plane", "XY")
                    _require(plane in ("XY", "YZ", "ZX"), f"{fpath} plane 必须 XY/YZ/ZX", errors, fpath)
                    h = float(feat.get("height", 0))
                    _require(h > 0, f"{fpath} height 必须 >0", errors, fpath)
                    off = float(feat.get("plane_offset", 0))
                    _require(off >= 0, f"{fpath} plane_offset 必须 >=0", errors, fpath)
                    profiles = feat.get("profiles", [])
                    _require(len(profiles) > 0, f"{fpath} pad 至少一个 profile", errors, fpath)
                    n_edges = 0
                    for prof in profiles:
                        kind = profile_kind(prof)
                        if kind == "loop":
                            segs = loop_segments(prof)
                            n_edges = len(segs)
                            _require(is_closed(segs), f"{fpath} 轮廓未闭合", errors, fpath)
                    item.update(plane=plane, height=h, plane_offset=off, profiles=profiles,
                                is_cylinder=(profile_kind(profiles[0]) == "circle" if profiles else False))
                    stack[fid] = {"height": h, "edges": n_edges, "plane": plane, "offset": off}

                elif ftype == "pocket":
                    on = feat.get("on")
                    _require(on in stack, f"{fpath} on='{on}' 必须指向已存在的 pad", errors, fpath)
                    depth = float(feat.get("depth", 0))
                    _require(depth > 0, f"{fpath} depth 必须 >0", errors, fpath)
                    profiles = feat.get("profiles", [])
                    _require(len(profiles) > 0, f"{fpath} pocket 至少一个 profile", errors, fpath)
                    for prof in profiles:
                        if profile_kind(prof) == "loop":
                            segs = loop_segments(prof)
                            _require(is_closed(segs), f"{fpath} pocket 轮廓未闭合", errors, fpath)
                    item.update(depth=depth, profiles=profiles, on=on,
                                plane=stack[on]["plane"], top_z=stack[on]["height"])

                elif ftype == "hole":
                    on = feat.get("on")
                    _require(on in stack, f"{fpath} hole on='{on}' 必须指向已存在的 pad", errors, fpath)
                    face = feat.get("face", "top")
                    p3d = feat.get("point3d")
                    _require(isinstance(p3d, list) and len(p3d) == 3, f"{fpath} hole 需要 point3d=[x,y,z]", errors, fpath)
                    dia = float(feat.get("diameter", 0))
                    dep = float(feat.get("depth", 0))
                    _require(dia > 0, f"{fpath} diameter 必须 >0", errors, fpath)
                    _require(dep > 0, f"{fpath} depth 必须 >0（通孔填板厚）", errors, fpath)
                    hole_type = feat.get("hole_type", "simple")
                    _require(hole_type in ("simple", "counterbore"),
                             f"{fpath} hole_type 仅支持 simple/counterbore", errors, fpath)
                    head_dia = float(feat.get("head_diameter", 0))
                    head_dep = float(feat.get("head_depth", 0))
                    if hole_type == "counterbore":
                        _require(head_dia > dia, f"{fpath} counterbore head_diameter 必须 > 直径", errors, fpath)
                        _require(head_dep > 0, f"{fpath} counterbore 需要 head_depth", errors, fpath)
                    # point3d 应落在该 pad 的顶/底面（按草图平面确定拉伸轴，含 plane_offset）
                    h = stack[on]["height"]
                    off = stack[on].get("offset", 0)
                    plane = stack[on]["plane"]
                    axis_idx = {"XY": 2, "YZ": 0, "ZX": 1}.get(plane, 2)
                    expect = (off + h) if face == "top" else off
                    got = float(p3d[axis_idx])
                    axis_name = "XYZ"[axis_idx]
                    if abs(got - expect) > 1.0:
                        warnings.append(
                            f"{fpath}: point3d {axis_name}={got} 与 {on} 的{face}面 {axis_name}={expect} 偏差较大"
                            f"（pad 在 {plane} 面 offset={off}，沿{axis_name}拉伸）")
                    item.update(on=on, face=face, point3d=[float(v) for v in p3d],
                                diameter=dia, depth=dep, hole_type=hole_type,
                                head_diameter=head_dia, head_depth=head_dep)

                elif ftype in ("fillet", "chamfer"):
                    on = feat.get("on")
                    _require(on in stack, f"{fpath} {ftype} on='{on}' 必须指向已存在的 pad", errors, fpath)
                    if stack[on]["edges"] < 3:
                        warnings.append(f"{fpath}: {on} 为圆柱轮廓，竖边圆角/倒角自动跳过")
                    val = float(feat.get("radius" if ftype == "fillet" else "length", 0))
                    _require(val > 0, f"{fpath} radius/length 必须 >0", errors, fpath)
                    item.update(on=on, value=val, edges=stack[on]["edges"],
                                can_apply=(stack[on]["edges"] >= 3))

                else:
                    errors.append(f"{fpath}: 未知特征类型 {ftype!r}（支持 pad/pocket/hole/fillet/chamfer）")
                    continue
                norm_features.append(item)

            pos = part.get("position", [0, 0, 0])
            norm_parts.append({"name": pid, "features": norm_features,
                               "position": [float(v) for v in pos]})

    return {
        "product_name": product_name,
        "output_dir": output_dir,
        "parts": norm_parts,
    }, errors, warnings
