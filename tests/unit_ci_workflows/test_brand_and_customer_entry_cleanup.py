# case_ids: UI-082
"""品牌与 C 端入口清理守卫（issue #9229）。

用户 2026-11-26 要求：清理 MIGAO 称呼，以及 C 端小程序等旧方案概念。

判据：
1. 官网 openGraph `siteName` 只写「生意管家」，不得再并排 `MIGAO`；
2. 官网「四端」的顾客侧入口是**微信客服**，不再把「顾客小程序」当主入口；
3. 后台企业编码示例用中性示例，不再拿 `migao` 当默认租户编码。

扫面只覆盖用户可见文案文件；`frontend/mini-app` 工程保留（可选承载页），不因本判据删除。
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN = REPO_ROOT / "frontend/admin-web/src"


def _read(rel: str) -> str:
    return (ADMIN / rel).read_text(encoding="utf-8")


def test_corporate_site_name_has_no_migao():
    src = _read("app/(corporate)/layout.tsx")
    assert "MIGAO" not in src, "官网 siteName/描述仍出现旧英文品牌 MIGAO"
    assert "生意管家" in src


def test_customer_entry_is_wechat_kf_not_mini_program():
    home = _read("components/corporate/home-content.ts")
    start = home.index("export const terminals")
    terminals = home[start:]
    assert "微信客服" in terminals, "四端里没有微信客服入口"
    assert "顾客小程序" not in home, "官网仍在把顾客小程序当 C 端入口"

    services = _read("app/(corporate)/services/page.tsx")
    assert "顾客小程序" not in services, "产品能力页仍在把顾客小程序当 C 端终端"


def test_tenant_code_example_is_neutral():
    src = _read("app/(dashboard)/settings/page.tsx")
    assert "zhangsan@migao" not in src
    assert 'placeholder="如 migao"' not in src
