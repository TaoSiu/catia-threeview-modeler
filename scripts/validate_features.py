# -*- coding: utf-8 -*-
"""校验并规范化三视图特征 JSON。

用法:
    python validate_features.py features.json [--out features.normalized.json]

退出码: 0=通过(可建模); 1=有错误(需修正后再建模); 2=文件/JSON 错误。
"""
import sys, json, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from features_common import normalize  # noqa: E402


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out_path = None
    for i, a in enumerate(sys.argv[1:]):
        if a == "--out" and i + 1 < len(sys.argv) - 1:
            out_path = sys.argv[sys.argv.index(a) + 1]
    if not args:
        print("用法: python validate_features.py <features.json> [--out normalized.json]")
        return 2
    src = args[0]
    if not os.path.exists(src):
        print(f"[ERROR] 文件不存在: {src}")
        return 2
    try:
        data = json.load(open(src, encoding="utf-8"))
    except Exception as e:
        print(f"[ERROR] JSON 解析失败: {e}")
        return 2

    norm, errors, warnings = normalize(data)

    print("=== 特征树摘要 ===")
    print(f"产品: {norm['product_name']}")
    for p in norm["parts"]:
        print(f" 零件 {p['name']}  position={p['position']}")
        for f in p["features"]:
            extra = ""
            if f["type"] == "pad":
                extra = f"plane={f['plane']} h={f['height']}"
            elif f["type"] == "pocket":
                extra = f"on={f['on']} depth={f['depth']}"
            elif f["type"] == "hole":
                extra = f"on={f['on']} dia={f['diameter']} dep={f['depth']} @{f['point3d']}"
            elif f["type"] == "fillet":
                extra = f"on={f['on']} R={f['value']} {'(应用)' if f['can_apply'] else '(跳过:圆柱)'}"
            elif f["type"] == "chamfer":
                extra = f"on={f['on']} C={f['value']}"
            print(f"    - {f['type']:8s} {f['id']:14s} {extra}")

    if warnings:
        print("\n=== 警告 ===")
        for w in warnings:
            print(" ! " + w)
    if errors:
        print("\n=== 错误（必须修复）===")
        for e in errors:
            print(" X " + e)
        print(f"\n结果: 校验未通过（{len(errors)} 个错误）。")
        return 1

    dst = out_path or (os.path.splitext(src)[0] + ".normalized.json")
    json.dump(norm, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n结果: 校验通过。已写出规范化文件: {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
