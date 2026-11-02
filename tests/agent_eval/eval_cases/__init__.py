# GENERATED FILE — DO NOT EDIT
# 本文件由 render_cases.py 生成，勿手改（改了也留不住：下次重渲染会覆盖）
# 源: cases/*.yml（case-contract 单一源）
# 重新生成: python3 render_cases.py --cases <dir> --out-eval <包目录> --out-md <md>
# 包顶层：按固定顺序（= `<domain>.yml` 文件名字典序）汇总各域 CASES ⇒ ALL_CASES 顺序与拆分前逐位相同

from typing import List

from ._schema import Difficulty, EvalCase, Skill  # noqa: F401 —— 包顶层再导出（local_runner 的导入面）


from .aftersales import CASES as _aftersales
from .agents import CASES as _agents
from .api import CASES as _api
from .auth import CASES as _auth
from .bmini import CASES as _bmini
from .category import CASES as _category
from .chat import CASES as _chat
from .cross import CASES as _cross
from .customer import CASES as _customer
from .data import CASES as _data
from .defense import CASES as _defense
from .finance import CASES as _finance
from .hr import CASES as _hr
from .knowledge import CASES as _knowledge
from .migration import CASES as _migration
from .misc import CASES as _misc
from .onboarding import CASES as _onboarding
from .ontology import CASES as _ontology
from .order import CASES as _order
from .processing_order import CASES as _processing_order
from .processing import CASES as _processing
from .product import CASES as _product
from .registry import CASES as _registry
from .settings import CASES as _settings
from .token_refresh import CASES as _token_refresh
from .ui import CASES as _ui
from .utils import CASES as _utils

ALL_CASES = (
    *_aftersales,
    *_agents,
    *_api,
    *_auth,
    *_bmini,
    *_category,
    *_chat,
    *_cross,
    *_customer,
    *_data,
    *_defense,
    *_finance,
    *_hr,
    *_knowledge,
    *_migration,
    *_misc,
    *_onboarding,
    *_ontology,
    *_order,
    *_processing_order,
    *_processing,
    *_product,
    *_registry,
    *_settings,
    *_token_refresh,
    *_ui,
    *_utils,
)

def get_active_cases() -> List[EvalCase]:
    return [c for c in ALL_CASES if not c.skip_reason]

def get_smoke_cases() -> List[EvalCase]:
    return [c for c in ALL_CASES if c.difficulty == Difficulty.SMOKE and not c.skip_reason]

def get_adversarial_cases() -> List[EvalCase]:
    return [c for c in ALL_CASES if c.difficulty == Difficulty.ADVERSARIAL and not c.skip_reason]

def print_summary():
    active = get_active_cases()
    print(f"评测用例总数: {len(active)} (跳过 {len(ALL_CASES) - len(active)})")
    print(f"  冒烟: {len(get_smoke_cases())}")
    print(f"  正常: {len([c for c in active if c.difficulty == Difficulty.NORMAL])}")
    print(f"  对抗: {len(get_adversarial_cases())}")
    for skill in Skill:
        cs = [c for c in active if c.skill == skill]
        if cs:
            print(f"\n## {skill.value}")
            for c in cs:
                print(f"  [{c.difficulty.value.upper():4}] {c.id}: {c.title}")

if __name__ == "__main__":
    print_summary()
