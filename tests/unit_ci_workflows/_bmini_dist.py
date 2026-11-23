"""B 端小程序**包体判据**的共用夹具 + 唯一预算读取口（issue #8979 / #8981）。

## 为什么有这一份

包体上限以前有两把尺子：`deploy/scripts/bmini-assert-dist.sh` 里写死 `2097152 × 90% = 1887436`，
判据文件里再抄一遍同样的两个数（`tests/unit_ci_workflows/test_bmini_dist_assert.py` 的
`CAP_BYTES` / `LIMIT_BYTES`）。两把尺子各改各的 ⇒ 闸门与判据说的不是同一件事，而**没有任何
东西会因此变红**（#8981 的同族形态：判据存在、但判的不是微信口径）。

⇒ 现在常量只有**一处**：`deploy/scripts/bmini-dist-budget.json`。脚本用 python3 读它，
判据经本模块读它（**同一个文件、同一个键名**）。第二份硬编码常量会被
`test_bmini_dist_budget.py::test_no_second_ruler` 判红。

## 口径（本模块只做读取，不解释口径；口径正文在 docs/deployment/bmini-experience-release.md）

* 判据算的是 **dist 字节**，实测 ≥ 微信开发者工具上传后报的 `TOTAL` 字节（2026-11-23：
  dist 1,465,245 → TOTAL 1,461,748，比值 0.998）⇒ 用 dist 字节判是**偏严**方向，不叠折算系数。
* 「主包」= dist 全量减去 `app.json` 的 `subPackages[].root` 覆盖的文件；`MAIN_LIMIT_BYTES`
  额外扣掉 `mainPackageReserveBytes`（#8979 要求的 ≥300KB 余量）。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSERT_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "bmini-assert-dist.sh"
EXPERIENCE_SCRIPT = REPO_ROOT / "scripts" / "bmini-experience.sh"
BUDGET_JSON = REPO_ROOT / "deploy" / "scripts" / "bmini-dist-budget.json"

PROD_ORIGIN = "https://app.cytda.com"
TEST_ORIGIN = "https://app.migaozn.com"
DEFAULT_PAGE = "pages/home/index"


def load_budget(path: Path | str | None = None) -> dict:
    """读**唯一**预算来源。缺文件 ⇒ 当场抛（缺预算 = 判据不可用，不许静默跳过）。"""
    target = Path(path) if path is not None else BUDGET_JSON
    if not target.is_file():
        raise FileNotFoundError(
            f"包体预算的唯一来源不存在：{target}（脚本与判据都只读它，没有它就没有闸门）"
        )
    with target.open(encoding="utf-8") as fh:
        return json.load(fh)


BUDGET = load_budget()
CAP_BYTES = BUDGET["wechatPackageCapBytes"]        # 微信单包上限（主包 / 每个分包各一份）
TOTAL_CAP_BYTES = BUDGET["wechatTotalCapBytes"]    # 微信总包上限（主包 + 全部分包）
RESERVE_BYTES = BUDGET["mainPackageReserveBytes"]  # 主包必须留出的余量（#8979）
MAIN_LIMIT_BYTES = CAP_BYTES - RESERVE_BYTES       # 主包预算 = 上限 − 余量


def build_dist(
    root: Path,
    *,
    body: str = TEST_ORIGIN,
    pages: tuple[str, ...] = (DEFAULT_PAGE,),
    omit: tuple[str, ...] = (),
    extra_bytes: int = 0,
    sub_packages: tuple[str, ...] = (),
    sub_bytes: dict[str, int] | None = None,
) -> Path:
    """造一棵**形状像 weapp 产物**的树：app.json(pages[+subPackages]) + app.js + 每页 js/wxml/json。

    * 刻意**不写** `.wxss`：Taro 对不含样式的页面本就不产出它（真实产物 25 页里有 4 页没有）；
    * `sub_packages` ⇒ `app.json` 的 `subPackages`（每项 `{"root": …, "pages": []}`），
      `sub_bytes[root]` ⇒ 在该 root 下塞一个**指定字节数**的文件（用来单独顶爆某个分包）；
    * `extra_bytes` ⇒ 主包里的 `padding.bin`（用来把主包顶到某个字节数）。
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    config: dict = {"pages": list(pages)}
    if sub_packages:
        config["subPackages"] = [{"root": pkg, "pages": []} for pkg in sub_packages]
    (root / "app.json").write_text(json.dumps(config), encoding="utf-8")
    (root / "app.js").write_text(
        '// compiled entry\nconst ORIGIN = "%s";\n' % body, encoding="utf-8"
    )
    for page in pages:
        for ext, content in (("js", "// page\n"), ("wxml", "<view/>\n"), ("json", "{}\n")):
            if f"{page}.{ext}" in omit:
                continue
            target = root / f"{page}.{ext}"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    if extra_bytes:
        (root / "padding.bin").write_bytes(b"x" * extra_bytes)
    for pkg, size in (sub_bytes or {}).items():
        target = root / pkg / "chunk.bin"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"y" * size)
    return root


def tree_bytes(root: Path) -> int:
    """一棵树里所有普通文件的**字节合计**（判据侧现取，不用脚本的读数）。"""
    return sum(p.stat().st_size for p in Path(root).rglob("*") if p.is_file())


def pad_dist_to(root: Path, target_bytes: int) -> Path:
    """把 `padding.bin` 调到「整棵树的字节合计 = target_bytes」；调不动（差值为负）⇒ 抛。"""
    root = Path(root)
    current = tree_bytes(root)
    delta = target_bytes - current
    if delta < 0:
        raise ValueError(f"目标 {target_bytes} 字节小于当前 {current} 字节，无法靠 padding 收敛")
    (root / "padding.bin").write_bytes(b"x" * delta)
    return root


def run_assert(dist: Path, env: str | None = None, extra: tuple[str, ...] = ()):
    """跑**真**断言脚本（不 mock）：判据必须对脚本的输出与退出码成立。"""
    cmd = ["bash", str(ASSERT_SCRIPT), str(dist)]
    if env is not None:
        cmd += ["--env", env]
    cmd += list(extra)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=180)
