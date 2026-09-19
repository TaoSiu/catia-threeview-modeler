# -*- coding: utf-8 -*-
"""检查本 Skill 的运行环境：Python 包与 CATIA COM 连通性。

用法: python check_env.py
退出码 0=就绪; 1=缺依赖; 2=CATIA 不可连。
"""
import sys


def main():
    ok = True
    try:
        import pycatia  # noqa: F401
        print("[OK] pycatia 已安装")
    except Exception:
        print("[缺失] pycatia 未安装 -> 运行: pip install pycatia")
        ok = False
    try:
        import win32com.client  # noqa: F401
        print("[OK] pywin32 已安装")
    except Exception:
        print("[缺失] pywin32 未安装 -> 运行: pip install pywin32")
        ok = False
    if not ok:
        return 1

    try:
        from pycatia import catia
        c = catia()
        print(f"[OK] 已连接 CATIA: {c.system_service.com_object if False else '运行中'}")
        return 0
    except Exception as e:
        print(f"[失败] 无法连接 CATIA: {e}")
        print("  请确认: 1) 已安装 CATIA V5 (R2016 及以上); 2) CATIA 已启动; 3) 已至少运行过一次 COM。")
        return 2


if __name__ == "__main__":
    sys.exit(main())
