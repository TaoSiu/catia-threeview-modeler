# -*- coding: utf-8 -*-
"""按规范化特征 JSON 驱动 CATIA 建模，产出 .CATPart 与 .CATProduct。

用法:
    python catia_build.py features.normalized.json [--output-dir DIR] [--capture DIR]
    python catia_build.py features.normalized.json --dry-run

设计要点（均经 CATIA V5 实测验证）：
- 新零件必须先 part.in_work_object = body，否则 AddNewPad 报 E_FAIL
- 草图: sketches.add(plane) -> sketch.open_edition() 画线 -> 相邻端点加 catCstTypeOn 重合约束 -> close_edition
- 凸台: shape_factory.add_new_pad(sketch, height)
- 顶面引用: part.create_reference_from_b_rep_name("RSur:(Face:(Brp:(Pad名;2);None:());...", pad)
- 孔: 混合点(3D) + 顶面引用 -> add_new_hole_from_ref_point(point, face, depth); diameter 用 .value 赋值
- 竖边圆角: 由草图相邻曲线对构造 REdge BRep 名 -> add_new_edge_fillet_with_constant_radius + add_object_to_fillet
"""
import sys, os, json, argparse, traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from features_common import (  # noqa: E402
    face_brep, vertical_edge_brep, profile_ents, profile_kind,
)

from pycatia import catia  # noqa: E402
from pycatia.enumeration.enumeration_types import (  # noqa: E402
    cat_constraint_type, cat_hole_type, cat_chamfer_mode,
    cat_chamfer_orientation, cat_chamfer_propagation,
    cat_fillet_edge_propagation, cat_capture_format,
)
from pycatia.sketcher_interfaces.point_2D import Point2D  # noqa: E402

ON = cat_constraint_type.index("catCstTypeOn")
PROP_TANG = cat_fillet_edge_propagation.index("catTangencyFilletEdgePropagation")
CHAMF_PROP = cat_chamfer_propagation.index("catMinimalChamfer")
CHAMF_MODE = cat_chamfer_mode.index("catTwoLengthChamfer")
CHAMF_ORI = cat_chamfer_orientation.index("catNoReverseChamfer")
FMT_JPG = cat_capture_format.index("catCaptureFormatJPEG")


class BuildError(Exception):
    pass


def _line(f2d, e):
    return f2d.create_line(float(e["p1"][0]), float(e["p1"][1]),
                          float(e["p2"][0]), float(e["p2"][1]))


def _arc(f2d, e):
    """真实圆弧: 圆心/半径/起始角/终止角(度, CCW)。"""
    import math
    cx, cy, r = float(e["c"][0]), float(e["c"][1]), float(e["r"])
    a0, a1 = math.radians(float(e["a0"])), math.radians(float(e["a1"]))
    return f2d.create_circle(cx, cy, r, a0, a1)


def _raw(curve):
    """取曲线的原始 COM 对象（Line2D.line_2d / Circle2D.circle_2d）。"""
    return getattr(curve, "line_2d", None) or getattr(curve, "circle_2d", None)


def _start_end(curve):
    raw = _raw(curve)
    return raw.StartPoint, raw.EndPoint


class CatiaBuilder:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.c = None
        if not dry_run:
            try:
                self.c = catia()
            except Exception as e:
                raise BuildError(f"无法连接 CATIA（请确认 CATIA V5 已安装并运行）: {e}")

    # ---------- 基础工具 ----------
    def _plane_ref(self, part, plane):
        origin = part.origin_elements
        obj = {"XY": origin.plane_xy, "YZ": origin.plane_yz, "ZX": origin.plane_zx}[plane]
        return part.create_reference_from_object(obj)

    def _draw_profiles(self, body, plane_ref, profiles):
        """建草图并画全部轮廓（含重合约束），返回 sketch、曲线数。"""
        sketch = body.sketches.add(plane_ref)
        f2d = sketch.open_edition()
        total_edges = 0
        for prof in profiles:
            kind = profile_kind(prof)
            ents = profile_ents(prof)
            if kind == "circle":
                c0 = ents[0]
                f2d.create_closed_circle(float(c0["c"][0]), float(c0["c"][1]), float(c0["r"]))
                total_edges = 1
            else:
                lines = []
                for e in ents:
                    if e.get("e") == "line":
                        lines.append(_line(f2d, e))
                    else:  # arc -> 展开直线段
                        lines.append(_arc(f2d, e))
                total_edges = len(lines)
                cons = sketch.constraints
                for i in range(len(lines)):
                    s_prev, e_cur = _start_end(lines[i])
                    s_next, e_next = _start_end(lines[(i + 1) % len(lines)])
                    cons.add_bi_elt_cst(
                        ON,
                        Point2D(e_cur),
                        Point2D(s_next),
                    )
        sketch.close_edition()
        return sketch, total_edges

    # ---------- 零件构建 ----------
    def build_part(self, part_spec, out_dir):
        name = part_spec["name"]
        doc = self.c.documents.add("Part")
        part = doc.part
        body = part.bodies.item(1)
        part.in_work_object = body
        try:
            body.name = "MainBody"
        except Exception:
            pass

        hsf = part.hybrid_shape_factory
        try:
            hb = part.hybrid_bodies.item(1)
        except Exception:
            hb = part.hybrid_bodies.add()

        sf = part.shape_factory
        stack = {}          # id -> {"height":z, "edges":n, "top","bot","vert"}
        pad_seq = 0         # 零件内凸台序号（对应 BRep 内部名 Pad.N / Sketch.N）

        for feat in part_spec["features"]:
            ftype, fid = feat["type"], feat["id"]

            if ftype == "pad":
                pad_seq += 1
                brep_pad = f"Pad.{pad_seq}"
                brep_sketch = f"Sketch.{pad_seq}"
                base_plane_ref = self._plane_ref(part, feat["plane"])
                off = float(feat.get("plane_offset", 0))
                if off > 0:
                    off_plane = hsf.add_new_plane_offset(base_plane_ref, off, False)
                    hb.append_hybrid_shape(off_plane)
                    part.update()
                    plane_ref = off_plane
                else:
                    plane_ref = base_plane_ref
                sketch, n_edges = self._draw_profiles(body, plane_ref, feat["profiles"])
                part.update()
                pad = sf.add_new_pad(sketch, float(feat["height"]))
                part.update()
                # 先按默认内部名抓 BRep 引用，再重命名显示名
                top_ref = part.create_reference_from_b_rep_name(
                    face_brep(brep_pad, 2), pad)
                bot_ref = part.create_reference_from_b_rep_name(
                    face_brep(brep_pad, 1), pad)
                vert_refs = []
                if n_edges >= 3:
                    for k in range(1, n_edges + 1):
                        lbl = vertical_edge_brep(brep_pad, k, n_edges).replace(
                            "Sketch.1", brep_sketch)
                        vert_refs.append(part.create_reference_from_b_rep_name(lbl, pad))
                try:
                    sketch.name = f"Sketch_{fid}"
                    pad.name = f"Pad_{fid}"
                except Exception:
                    pass
                part.update()
                stack[fid] = {"height": float(feat["height"]), "edges": n_edges,
                              "top": top_ref, "bot": bot_ref, "vert": vert_refs}

            elif ftype == "pocket":
                on = feat["on"]
                base = stack[on]
                plane_ref = self._plane_ref(part, feat["plane"])
                off_plane = hsf.add_new_plane_offset(plane_ref, float(feat["top_z"]), False)
                hb.append_hybrid_shape(off_plane)
                part.update()
                sketch, _ = self._draw_profiles(body, off_plane, feat["profiles"])
                part.update()
                pocket = sf.add_new_pocket(sketch, float(feat["depth"]))
                part.update()
                try:
                    sketch.name = f"Sketch_Pocket_{fid}"
                    pocket.name = f"Pocket_{fid}"
                except Exception:
                    pass

            elif ftype == "hole":
                base = stack[feat["on"]]
                x, y, z = [float(v) for v in feat["point3d"]]
                pt = hsf.add_new_point_coord(x, y, z)
                hb.append_hybrid_shape(pt)
                part.update()
                ref_pt = part.create_reference_from_object(pt)
                face_ref = base["top"] if feat["face"] == "top" else base["bot"]
                hole = sf.add_new_hole_from_ref_point(ref_pt, face_ref, float(feat["depth"]))
                hole.diameter.value = float(feat["diameter"])
                htype = feat.get("hole_type", "simple")
                if htype == "counterbore":
                    hole.type = cat_hole_type.index("catCounterboredHole")
                    part.update()
                    hole.head_diameter.value = float(feat["head_diameter"])
                    hole.head_depth.value = float(feat["head_depth"])
                else:
                    hole.type = cat_hole_type.index("catSimpleHole")
                part.update()
                try:
                    hole.name = f"Hole_{fid}"
                except Exception:
                    pass

            elif ftype == "fillet":
                base = stack[feat["on"]]
                if not base["vert"]:
                    print(f"  [跳过] fillet {fid}: 圆柱轮廓无竖边")
                    continue
                fillet = sf.add_new_edge_fillet_with_constant_radius(
                    base["vert"][0], PROP_TANG, float(feat["value"]))
                for vr in base["vert"][1:]:
                    fillet.add_object_to_fillet(vr)
                part.update()
                try:
                    fillet.name = f"Fillet_{fid}"
                except Exception:
                    pass

            elif ftype == "chamfer":
                base = stack[feat["on"]]
                if not base["vert"]:
                    print(f"  [跳过] chamfer {fid}: 圆柱轮廓无竖边")
                    continue
                # 倒角作用于竖边（四角 45°），与圆角一致用边引用
                cham = sf.add_new_chamfer(base["vert"][0], CHAMF_PROP, CHAMF_MODE,
                                          CHAMF_ORI, float(feat["value"]),
                                          float(feat["value"]))
                for vr in base["vert"][1:]:
                    try:
                        cham.add_object_to_chamfer(vr)
                    except Exception:
                        pass
                part.update()
                try:
                    cham.name = f"Chamfer_{fid}"
                except Exception:
                    pass

        out_path = os.path.join(out_dir, f"{name}.CATPart")
        if os.path.exists(out_path):
            os.remove(out_path)
        doc.save_as(out_path, overwrite=True)
        # 保存后关闭零件文档，避免遗留在 CATIA 里导致用户重复打开时"无反应"
        try:
            doc.close()
        except Exception:
            pass
        return out_path

    # ---------- 装配 ----------
    def build_product(self, product_name, part_paths_positions, out_dir, capture_dir=None):
        doc = self.c.documents.add("Product")
        product = doc.product
        products = product.products
        for path, pos in part_paths_positions:
            products.add_components_from_files((path,), "All")
            comp = products.item(products.count)
            # 把实例名改成零件文件名，避免树里全是 Part1/Part2
            try:
                comp.name = os.path.splitext(os.path.basename(path))[0]
            except Exception:
                pass
            if any(abs(v) > 1e-9 for v in pos):
                comp.position.set_components(
                    (1, 0, 0, 0, 1, 0, 0, 0, 1, float(pos[0]), float(pos[1]), float(pos[2])))
        prod_path = os.path.join(out_dir, f"{product_name}.CATProduct")
        if os.path.exists(prod_path):
            os.remove(prod_path)
        doc.save_as(prod_path, overwrite=True)

        cap = None
        if capture_dir:
            try:
                os.makedirs(capture_dir, exist_ok=True)
                cap = os.path.join(capture_dir, f"{product_name}_preview.jpg")
                self.c.active_window.active_viewer.capture_to_file(FMT_JPG, cap)
            except Exception as e:
                print(f"  [警告] 截图失败: {e}")
        return prod_path, cap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("feature_json")
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--capture", default=None, help="预览图输出目录；不传则不截图")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    norm = json.load(open(args.feature_json, encoding="utf-8"))
    out_dir = args.output_dir or norm.get("output_dir") or os.getcwd()
    os.makedirs(out_dir, exist_ok=True)

    if args.dry_run:
        print("[dry-run] 将构建:")
        for p in norm["parts"]:
            print(" 零件", p["name"], "features:", [f["type"] for f in p["features"]])
            print("  ->", os.path.join(out_dir, p["name"] + ".CATPart"))
        print("  ->", os.path.join(out_dir, norm["product_name"] + ".CATProduct"))
        return 0

    builder = CatiaBuilder()
    paths = []
    for part_spec in norm["parts"]:
        print(f"构建零件 {part_spec['name']} ...")
        p = builder.build_part(part_spec, out_dir)
        print(f"  -> {p}")
        paths.append((p, part_spec["position"]))
    prod_path, cap = builder.build_product(
        norm["product_name"], paths, out_dir, args.capture)
    print(f"[完成] 产品: {prod_path}")
    if cap:
        print(f"[预览] {cap}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BuildError as e:
        print("[构建失败]", e)
        sys.exit(1)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
