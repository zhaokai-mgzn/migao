#!/usr/bin/env python3
"""agent-preset-wiring-guard — 预设技能**接线**可解析性守卫（2026-11-25 实证）。

## 这守的是什么

2026-11-25 的真实故障：本机生效的 `migao` preset 是 `~/.dsh/profiles/web/cordis.patch.yml` 里的
**声明行**（dsh 0.2.2 升级时从目录 preset 迁过去的），它的 `skill-filesystem` 行写着

    customSkillDirs: [ <anchor>/skills ]        # 2026-11-21 改布局后该路径已不存在

而**插件的缺省行为是静默跳过不存在的根** ⇒ preset 自带的两个技能从未加载、catalog 只剩宿主技能、
**没有任何判据会红**；真正让技能可见的是 `~/.dsh/skills` 里的两条**临时软链**（host 默认根兜底）——
于是「新会话里有技能」这个读数看起来是绿的，实际接线早就断了。

三颗地雷各有判据，缺一条就漏：

1. **根路径不存在**（本单主因）⇒ 技能静默消失；
2. **指向的不是活锚的技能目录**（改错副本 / 旧布局）⇒ 内容与镜像脱钩，改了也不生效；
3. **兜底遮蔽**：`$DSH_HOME/skills` 里同名的软链/目录会让断掉的接线继续「看起来能用」⇒
   真实加载点失效无人知（本单实测形态）。

## 判定（三态退出码）

| 码 | 含义 |
|---|---|
| 0 | 接线可解析：每个技能根都存在且含技能；覆盖活锚里的全部技能；至少一个根就是活锚的技能目录；无宿主兜底遮蔽 |
| 1 | **红**：任一判据不成立（缺根 / 少技能 / 指错目录 / 兜底遮蔽 / 表达式求值失败） |
| 3 | **无法判定**（没找到 profile patch / 没找到该 preset 的声明行）—— **不得当 0 读** |
| 2 | 用法或环境错误（缺 node / 参数非法） |

## 为什么不只看「文件存在」

`$DSH_HOME/skills` 的兜底能同时在「文件存在」与「catalog 有技能」两个读数上给出**假绿**。
故本守卫额外要求：根 realpath 必须等于 `<活锚>/skills`（防改错副本），且 `$DSH_HOME/skills`
下不得出现活锚里的同名技能（防遮蔽）。

用法：
    python3 scripts/agent-preset-wiring-guard.py                 # 默认读 $DSH_HOME/profiles/web/cordis.patch.yml
    python3 scripts/agent-preset-wiring-guard.py --profile-patch P --anchor A --preset-id migao
    python3 scripts/agent-preset-wiring-guard.py --json          # 机器可读（CI / 自检脚本可解析）
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

PRESET_PLUGIN = "@deepseek-ai/dsh-agent-preset"
SKILL_PLUGIN = "@deepseek-ai/dsh-skill-filesystem"
JS_TAG = "tag:yaml.org,2002:js"

#: `!!js` 表达式的求值上下文与 Loader 一致（`with (ctx) { eval(expr) }`，见 vendor/loader）；
#: 这里额外补上 `dshHomePath`（app-boot 在 Loader 上下文里 provide 的那个）。
_EVAL = r"""
const fs = require('node:fs')
const path = require('node:path')
const { expr, baseUrl, dshHome } = JSON.parse(fs.readFileSync(0, 'utf8'))
const ctx = { baseUrl, dshHomePath: (...s) => path.join(dshHome, ...s) }
const fn = new Function('ctx', 'expr', 'with (ctx) { return eval(expr) }')
process.stdout.write(String(fn(ctx, expr)))
"""


class JsLoader(yaml.SafeLoader):
    """把 `!!js` 标量解析成 `{'__jsExpr': '<表达式>'}`（与 Loader 的表达式节点同形）。"""


JsLoader.add_constructor(JS_TAG, lambda loader, node: {"__jsExpr": loader.construct_scalar(node)})


def load_document(path: Path) -> object:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=JsLoader)


def _walk_rows(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_rows(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_rows(child)


def find_preset_row(document: object, preset_id: str) -> dict | None:
    for row in _walk_rows(document):
        if row.get("name") != PRESET_PLUGIN:
            continue
        config = row.get("config")
        if isinstance(config, dict) and config.get("id") == preset_id:
            return row
    return None


def skill_rows(preset_row: dict) -> list[dict]:
    config = preset_row.get("config") or {}
    plugins = config.get("plugins") or []
    return [row for row in plugins if isinstance(row, dict) and row.get("name") == SKILL_PLUGIN]


def evaluate(expression: str, base_url: str, dsh_home: Path) -> str:
    """按 Loader 口径求值一个 `!!js` 表达式；失败即 fail-closed（调用方判红）。"""
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("找不到 node，无法求值 !!js 表达式（本判据不得退化成放行）")
    proc = subprocess.run(
        [node, "-e", _EVAL],
        input=json.dumps({"expr": expression, "baseUrl": base_url, "dshHome": str(dsh_home)}),
        capture_output=True, text=True, timeout=20, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"!!js 求值失败：{proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def wiring_roots(rows: list[dict], base_url: str, dsh_home: Path) -> tuple[list[tuple[str, str]], list[str]]:
    """返回（根路径, 来源说明）与**表达式错误**清单。"""
    roots: list[tuple[str, str]] = []
    errors: list[str] = []
    for row in rows:
        config = row.get("config") or {}
        row_id = row.get("id") or SKILL_PLUGIN
        for key in ("customSkillDirs", "bundledSkillDir"):
            value = config.get(key)
            if value is None:
                continue
            values = value if isinstance(value, list) else [value]
            for item in values:
                try:
                    if isinstance(item, dict) and "__jsExpr" in item:
                        resolved = evaluate(str(item["__jsExpr"]), base_url, dsh_home)
                    elif isinstance(item, str):
                        resolved = item
                    else:
                        errors.append(f"{row_id}.{key}：不是字符串/表达式（{item!r}）")
                        continue
                except Exception as exc:  # noqa: BLE001 — 判据要对任何求值失败 fail-closed
                    errors.append(f"{row_id}.{key}：{exc}")
                    continue
                roots.append((resolved, f"{row_id}.{key}"))
    return roots, errors


def anchor_skills(anchor: Path) -> dict[str, Path]:
    """活锚 `skills/` 下的技能名 → 路径（目录带 SKILL.md，或平铺 `.md`）。"""
    skills_dir = anchor / "skills"
    found: dict[str, Path] = {}
    if not skills_dir.is_dir():
        return found
    for entry in sorted(skills_dir.iterdir()):
        if entry.is_dir() and (entry / "SKILL.md").is_file():
            found[entry.name] = entry
        elif entry.is_file() and entry.suffix == ".md":
            found[entry.stem] = entry
    return found


def discovered_skills(root: Path) -> set[str]:
    names: set[str] = set()
    if not root.is_dir():
        return names
    for entry in root.iterdir():
        if entry.is_dir() and (entry / "SKILL.md").is_file():
            names.add(entry.name)
        elif entry.is_file() and entry.suffix == ".md":
            names.add(entry.stem)
    return names


def judge(profile_patch: Path, anchor: Path, preset_id: str, dsh_home: Path,
          out=sys.stdout) -> int:
    """执行全部判据；返回三态退出码（0/1/3）。"""
    def say(text: str) -> None:
        print(text, file=out)

    expected = anchor_skills(anchor)
    say(f"🔌 预设接线自检（preset={preset_id}）")
    say(f"   活锚：{anchor}")
    say(f"   profile：{profile_patch}")
    if not profile_patch.is_file():
        say(f"⏭️ **未跑判定**（exit 3）：profile patch 不存在 {profile_patch}")
        say("   ⇒ 这台机器没有声明行接线，本判据不适用；**不得当 0 读**。")
        return 3
    document = load_document(profile_patch)
    preset_row = find_preset_row(document, preset_id)
    if preset_row is None:
        say(f"⏭️ **未跑判定**（exit 3）：{profile_patch} 里没有 preset id={preset_id!r} 的声明行")
        say("   ⇒ 可能仍在用目录 preset，或本机未接线；**不得当 0 读**。")
        return 3

    rows = skill_rows(preset_row)
    problems: list[str] = []
    if expected and not rows:
        problems.append(
            f"声明行 id={preset_id} 没有任何 {SKILL_PLUGIN} 行，而活锚里有 {len(expected)} 个技能"
            f"（{', '.join(sorted(expected))}）⇒ 技能无处加载"
        )
    roots, errors = wiring_roots(rows, base_url=(profile_patch.parent.as_uri() + "/"), dsh_home=dsh_home)
    problems.extend(errors)
    if not roots and not problems:
        problems.append("声明行的 skill 行既没有 customSkillDirs 也没有 bundledSkillDir ⇒ 没接任何技能根")

    real_anchor_skills = (anchor / "skills").resolve()
    covered: set[str] = set()
    root_reals: list[Path] = []
    for value, origin in roots:
        path = Path(os.path.expanduser(value))
        try:
            path = path.resolve()
        except OSError:
            pass
        if not path.is_dir():
            problems.append(f"{origin} 指向的技能根不存在：{path} ⇒ 插件会**静默跳过**（今晚的故障形态）")
            continue
        root_reals.append(path)
        names = discovered_skills(path)
        if not names:
            problems.append(f"{origin} 的技能根里没有任何 SKILL.md：{path}")
        covered |= names

    missing = sorted(set(expected) - covered)
    if missing:
        problems.append(f"活锚里有但接线根覆盖不到的技能：{', '.join(missing)}（改了预设也不会生效）")
    if root_reals and real_anchor_skills not in root_reals:
        problems.append(
            "没有一个技能根就是活锚的技能目录 "
            f"{real_anchor_skills}（实际：{', '.join(str(p) for p in root_reals)}）⇒ 改错副本或旧布局"
        )

    masked = sorted(name for name in expected if (dsh_home / "skills" / name).exists())
    if masked:
        problems.append(
            f"宿主兜底遮蔽：{dsh_home / 'skills'} 下存在 {', '.join(masked)}"
            " ⇒ 接线断掉时 catalog 仍会“看起来有技能”（今晚的假绿形态）；删掉这些软链，让加载点唯一"
        )

    if problems:
        say("")
        for item in problems:
            say(f"❌ {item}")
        say("")
        say("❌ 接线不可解析（exit 1）—— 修好上面的接线后重跑本判据。")
        return 1
    say(f"✅ 接线可解析（{len(roots)} 个技能根，覆盖 {len(covered)} 个技能；加载点 = 活锚）")
    return 0


def main(argv: list[str] | None = None) -> int:
    dsh_home_default = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
    parser = argparse.ArgumentParser(
        prog="agent-preset-wiring-guard",
        description="预设技能接线可解析性（缺根 / 指错副本 / 兜底遮蔽 ⇒ 红；无声明行 ⇒ 3）",
    )
    parser.add_argument("--profile-patch", default=None,
                        help="profile patch 路径（默认 $DSH_HOME/profiles/web/cordis.patch.yml）")
    parser.add_argument("--anchor", default=None,
                        help="活锚 preset 目录（默认 $DSH_HOME/.agent-presets/<preset-id>）")
    parser.add_argument("--preset-id", default="migao", help="要判的 preset id（默认 migao）")
    parser.add_argument("--dsh-home", default=str(dsh_home_default), help="DSH home（默认 $DSH_HOME 或 ~/.dsh）")
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = parser.parse_args(argv)

    dsh_home = Path(args.dsh_home).expanduser()
    profile_patch = Path(args.profile_patch).expanduser() if args.profile_patch \
        else dsh_home / "profiles" / "web" / "cordis.patch.yml"
    anchor = Path(args.anchor).expanduser() if args.anchor else dsh_home / ".agent-presets" / args.preset_id

    if args.json:
        import io
        buffer = io.StringIO()
        code = judge(profile_patch, anchor, args.preset_id, dsh_home, out=buffer)
        print(json.dumps({"exit": code, "output": buffer.getvalue().splitlines()}, ensure_ascii=False))
        return code
    return judge(profile_patch, anchor, args.preset_id, dsh_home)


if __name__ == "__main__":
    sys.exit(main())
