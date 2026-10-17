#!/usr/bin/env python3
"""版本号一致性离线测试。

不访问网络。三处版本来源必须一致：

  * `pyproject.toml` 的 `version`（安装后即 `importlib.metadata.version`）
  * `hltv_mcp.__version__`
  * `MCPServer(version=...)` —— 客户端握手时 `serverInfo.version` 就是它

第三处曾经写死成 `1.6.0`：发版把前两处改成 `1.0` 时漏了它，结果客户端报的
版本与包版本不符，排查「部署的到底是哪个版本」时会直接误判。

    python tests/test_version.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import hltv_mcp  # noqa: E402
import hltv_mcp.server as server_module  # noqa: E402


def main() -> int:
    failures: list[str] = []

    def check(label: str, actual, expected) -> None:
        ok = actual == expected
        print(f"{'✓' if ok else '✗'} {label}")
        if not ok:
            print(f"     期望 {expected!r}\n     实际 {actual!r}")
            failures.append(label)

    print("--- 1. server 与包版本一致 ---")
    check("server.version == __version__",
          getattr(server_module.server, "version", None), hltv_mcp.__version__)

    print()
    print("--- 2. 与 pyproject 声明一致 ---")
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # Python < 3.8
        print("(跳过：当前解释器没有 importlib.metadata)")
    else:
        try:
            dist_version = version("hltv-mcp")
        except PackageNotFoundError:
            # 未安装（例如只在仓库根目录跑源码）时没有可比对的元数据。
            print("(跳过：hltv-mcp 未安装为发行包)")
        else:
            check("__version__ == 发行版版本", hltv_mcp.__version__, dist_version)

    print()
    if failures:
        print(f"{len(failures)} 项失败：{', '.join(failures)}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
