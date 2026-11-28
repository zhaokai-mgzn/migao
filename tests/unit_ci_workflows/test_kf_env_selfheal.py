# case_ids: MC-393
"""微信客服（qyapi kf）的**部署级配置自愈**（issue #9355）。

## 病灶（2026-11-28 实测）

代码侧把整条微信客服腿做完了（回调 `/api/kf/callback`、`KfSyncWorker` 30s 轮询、
`KfOutboxSender`、商户自助接入页），但**部署面一个字都没配**：
`GET https://api.migaozn.com/api/kf/callback` ⇒ **404**（端点随
`wechat.kf.enabled=false` 一起不存在），商户接入页拿不到 Token/EncodingAESKey ⇒
拿到了企微测试账号也接不进来。

`.env.admin-api` 是**每机一份手工文件**（`docker-compose.yml` 的 `env_file`），
所以正确的修法是照 `AI_AGENT_SERVICE_TOKEN` 的既有范式：**缺则生成并追加，幂等**。

## 两个必须守住的坑（否则"修好"等于"打崩"）

1. **三者原子写入**：`wechat.kf.enabled=true` + 空 `secret-master-key` ⇒ `SecretCipher`
   初始化失败 ⇒ **admin-api 启动即崩**（fail-closed）。所以只追加 `ENABLED=true` 是事故形态，
   必须 Token/AESKey/主密钥一起算好、校验长度、再一次性追加。
2. **幂等不可覆盖**：换 Token ⇒ 已配好的企微后台校验失败；换主密钥 ⇒ 已加密落库的商户
   Secret **全部解不开**。

## 判据（含行为级，不只是静态 grep）

1. 静态：deploy.sh 的 KF 段把 `ENABLED` 与三个键写在**同一个 `{ … } >>` 组**里；
2. 静态：**不得**出现"单独追加 `WECHAT_KF_ENABLED=true`"的写法（事故形态）；
3. 静态：生成器用 `/dev/urandom`（SWAS 镜像里**没有 openssl**，实测）；
4. 行为级：把该段抽出来在临时目录真跑一次 ⇒ 四行齐、长度分别 32/43/64；
5. 行为级：再跑一次 ⇒ **不新增任何行**（幂等）、`ENABLED` 仍只出现一次；
6. 红证：把"长度校验"那一行摘掉后，同一夹具上人为把生成器改成短值 ⇒ 段内 `exit 1` 生效、
   **不写半个键**（证明长度校验不是摆设）。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy" / "swas" / "deploy.sh"

START = "# 1.5b 微信客服（qyapi kf）配置自愈"
END = "# 1.6 SMS 万能码 fail-closed"


def _kf_block() -> str:
    text = DEPLOY.read_text(encoding="utf-8")
    assert START in text, f"deploy.sh 里找不到 KF 自愈段（{START}）"
    assert END in text, f"deploy.sh 里找不到 KF 段的下界标记（{END}）"
    start = text.index(START)
    end = text.index(END)
    assert start < end, "KF 段起止标记顺序反了"
    return text[start:end]


def test_enabled_and_keys_are_written_atomically():
    """判据 1：四个键必须在同一个 `{ … } >>` 组里 —— 单独追加 ENABLED 会让 admin-api 起不来。"""
    block = _kf_block()
    groups = re.findall(r"\{\n(.*?)\n  \} >> \.env\.admin-api", block, re.DOTALL)
    assert groups, "找不到原子写入组（`{ … } >> .env.admin-api`）"
    joined = "\n".join(groups)
    for key in ("WECHAT_KF_ENABLED", "WECHAT_KF_TOKEN", "WECHAT_KF_ENCODING_AES_KEY",
                "WECHAT_KF_SECRET_MASTER_KEY"):
        assert key in joined, f"{key} 不在原子写入组里 ⇒ 可能被单独追加（事故形态）"


def test_no_standalone_enabled_append():
    """判据 2：禁止任何"只追加 ENABLED"的写法。"""
    block = _kf_block()
    standalone = re.findall(r"^[^#\n]*echo\s+'WECHAT_KF_ENABLED=true'\s*>>\s*\.env\.admin-api", block, re.MULTILINE)
    assert not standalone, f"发现单独追加 ENABLED 的写法（会让 master-key 缺失 ⇒ 启动崩）：{standalone}"


def test_generator_does_not_depend_on_openssl():
    """判据 3：SWAS 镜像里没有 openssl（实测 0 处引用）⇒ 必须用 /dev/urandom。"""
    block = _kf_block()
    # ⚠️ 只看**可执行行**：本段注释里正大光明写着「openssl 在 SWAS 镜像里没有」——
    #    拿整段文本判 `"openssl" not in block` 会被自己的注释咬到（本判据第一版就是这么红的）。
    code = "\n".join(l for l in block.splitlines() if not l.lstrip().startswith("#"))
    assert "/dev/urandom" in code, "生成器没用 /dev/urandom"
    assert "openssl" not in code, "生成器用了 openssl，但 SWAS 镜像里没有它"


def _run_block(tmp: Path, block: str) -> str:
    (tmp / ".env.admin-api").write_text("JWT_ISSUER=x\n", encoding="utf-8")
    script = tmp / "block.sh"
    script.write_text(block, encoding="utf-8")
    r = subprocess.run(["bash", str(script)], cwd=tmp, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"段执行失败 rc={r.returncode}: {r.stderr[-400:]}"
    return (tmp / ".env.admin-api").read_text(encoding="utf-8")


def test_block_generates_all_three_with_required_lengths(tmp_path):
    """判据 4：真跑一次 ⇒ 四行齐 + 长度 32/43/64（企微对 AESKey 恰好 43 位有硬要求）。"""
    env = _run_block(tmp_path, _kf_block())
    got = dict(l.split("=", 1) for l in env.splitlines() if "=" in l and not l.startswith("JWT_ISSUER"))
    assert got.get("WECHAT_KF_ENABLED") == "true"
    assert len(got.get("WECHAT_KF_TOKEN", "")) == 32, got.get("WECHAT_KF_TOKEN")
    assert len(got.get("WECHAT_KF_ENCODING_AES_KEY", "")) == 43, got.get("WECHAT_KF_ENCODING_AES_KEY")
    assert len(got.get("WECHAT_KF_SECRET_MASTER_KEY", "")) == 64, got.get("WECHAT_KF_SECRET_MASTER_KEY")
    assert got.get("WECHAT_KF_CALLBACK_URL", "").endswith("/api/kf/callback")


def test_block_is_idempotent(tmp_path):
    """判据 5：再跑一次不许新增行（换 Token/AESKey/主密钥各有各的事故后果）。"""
    block = _kf_block()
    first = _run_block(tmp_path, block)
    before = first.splitlines()
    r = subprocess.run(["bash", str(tmp_path / "block.sh")], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0
    after = (tmp_path / ".env.admin-api").read_text(encoding="utf-8").splitlines()
    assert after == before, "段不幂等：第二次执行又改了 .env.admin-api"
    assert sum(1 for l in after if l.startswith("WECHAT_KF_ENABLED=")) == 1


def test_red_proof_length_guard_blocks_a_partial_write(tmp_path):
    """判据 6·红证：生成器给出短值 ⇒ 段必须 `exit 1` 且**不写半个键**。"""
    block = _kf_block()
    mutated = block.replace(
        "head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | cut -c1-32", "echo short")
    assert mutated != block, "红证前提不成立：没能把生成器改短"
    (tmp_path / ".env.admin-api").write_text("JWT_ISSUER=x\n", encoding="utf-8")
    script = tmp_path / "block.sh"
    script.write_text(mutated, encoding="utf-8")
    r = subprocess.run(["bash", str(script)], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0, "短值生成器居然没让段失败"
    env = (tmp_path / ".env.admin-api").read_text(encoding="utf-8")
    assert "WECHAT_KF_TOKEN=" not in env and "WECHAT_KF_ENABLED" not in env, (
        f"长度校验失效：写了半个键 ⇒ {env!r}")
