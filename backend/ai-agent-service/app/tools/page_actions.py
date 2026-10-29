"""页面动作登记表（F6 / P2-1，承接 issue #5989）—— 「怎么做」的**唯一真值源**（纯数据 + 只读查询）。

## 为什么需要

`nav_guide` 原先只回答「功能在哪一页」；用户问「怎么做」时按 prompt 口径只能说
「我没有步骤级指引」。而**页面步骤没有真值源**时，让模型说就是编 —— 本表把
**高频动作**的页面步骤显式登记下来，由 `nav_guide(action=how_to, topic=…)` **逐字投影**；
**未登记 ⇒ 保持原口径**（如实说没有步骤级指引 + 给页面路径），不猜、不补。

## 每条登记项的真值来源（判据 = `backend/ai-agent-service/tests/test_page_actions.py`）

- `route`：必须能在 `frontend/admin-web/src/app/**/page.tsx` 解析到（路由组 `(...)` 不计入路径）；
- `menu`：逐字取 `app/context/menu_navigator.py::MENU_TREE` 的菜单名（分组名取 `MENU_GROUPS`）；
- `steps`：逐条对应真实页面上的真实按钮 / 字段文案（来源写在每条的注释里，供复核）；
- `permission`：**页面码**，逐字取 `MENU_TREE` 的现取码集（与 `nav_guide` 的角色裁剪同源）。
  🔴 写动作的细码（如 `product:create`）**不在导航真值里** ⇒ 不塞进 `permission`（不编造码），
  写进 `preconditions` 的中文口径；`nav_guide` 的裁剪仍按页面码判。
- `keywords`：自由问句 → 动作的**确定性子串**匹配键；最长命中，同长歧义 ⇒ `None`（fail-closed）。

## 明确不做

- 不做业务写、不调 admin-api（纯本地只读，与 `nav_guide` 同口径）；
- 不猜步骤：页面文案证不实的动作**不登记**（宁少不假）；
- 不做同义词推断 / 模糊匹配：说法必须能在真实页面、菜单真值或用例语料里找到。

## 首批 5 个高频动作（2026-10-29）

改商品价 / 新建商品 / 改客户收货信息 / 新增员工 / 配置加工项。
原建议里的「改客户资料」在页面上**只支持改收货信息 / 备注 / 授信**（姓名与手机号来自微信授权，
后台不可改）⇒ 按「宁少不假」换成真实存在的「改客户收货信息」，见 PR body 的换项说明。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

#: 动作 id → 登记项。**新增动作 = 显式改本表**（语义判断必须人做），不许改成模糊匹配。
#:
#: 🔴 `steps` 里的按钮 / 字段文案全部**逐字**来自下列 admin-web 文件（不写行号，按符号检索）：
#: - `frontend/admin-web/src/app/(dashboard)/products/page.tsx`（「新增商品」按钮）
#: - `frontend/admin-web/src/components/products/ProductTable.tsx`（行内「编辑」）
#: - `frontend/admin-web/src/components/products/SkuMatrix.tsx`（「价格（元）」列）
#: - `frontend/admin-web/src/app/(dashboard)/products/[id]/edit/EditProduct.tsx`（`submitText="保存修改"`）
#: - `frontend/admin-web/src/app/(dashboard)/products/new/page.tsx`（`submitText="提交并上架"`）
#: - `frontend/admin-web/src/app/(dashboard)/customers/[id]/CustomerDetail.tsx`（「收货信息」卡片 + 「保存」）
#: - `frontend/admin-web/src/app/(dashboard)/employees/page.tsx`（「新增员工」/「创建」/ 表单字段）
#: - `frontend/admin-web/src/lib/config-center-domains.ts`（`processing-items` 域 label「加工项与分类」）
#: - `frontend/admin-web/src/components/production-config/ProcessingItemsPanel.tsx`（「新增加工项」/「保存」）
PAGE_ACTIONS: Dict[str, Dict[str, Any]] = {
    "product_price_update": {
        "label": "改商品价格",
        # 入口 = 商品列表（菜单真值 /products）；编辑页按商品 id 进入，故 route 取列表页。
        "route": "/products",
        "menu": "商品管理",
        "steps": [
            "打开侧边栏「商品管理」，进入商品列表页",
            "按商品标题或商品货号搜索，点该行右侧的「编辑」",
            "在 SKU 表的「价格（元）」列填入新价格",
            "点「保存修改」完成改价",
        ],
        "preconditions": [
            "该商品已存在，且当前状态可编辑（出售中 / 已下架 / 草稿）",
            "账号有商品编辑权限（product:create）",
        ],
        "permission": "product:list",
        "keywords": ("改商品价", "商品改价", "商品价格", "改商品价格", "商品调价"),
    },
    "product_create": {
        "label": "新建商品",
        "route": "/products/new",
        "menu": "商品管理",
        "steps": [
            "打开侧边栏「商品管理」，点右上角「新增商品」",
            "填写「商品标题」、选择「商品分类」，并设置售卖方式",
            "补「商品主图」，在「价格（元）」列填价格",
            "点「提交并上架」发布商品",
        ],
        "preconditions": [
            "账号有新增商品权限（product:create）",
            "商品分类已创建，商品主图已准备",
        ],
        "permission": "product:list",
        "keywords": ("新建商品", "新增商品", "创建商品", "商品上架", "上架新商品"),
    },
    "customer_receiver_update": {
        "label": "改客户收货信息",
        "route": "/customers",
        "menu": "客户服务 → 客户列表",
        "steps": [
            "打开「客户服务 → 客户列表」，搜索客户并点客户名进入详情",
            "在「收货信息」卡片里改收货人姓名、收货人电话、收货地址",
            "点「收货信息」标题右侧的「保存」",
        ],
        "preconditions": [
            "客户已存在于客户列表",
            "账号有客户维护权限（customer:create）",
        ],
        "permission": "customer:view",
        "keywords": ("客户资料", "改客户资料", "客户收货信息", "收货信息", "收货地址"),
    },
    "employee_create": {
        "label": "新增员工",
        "route": "/employees",
        "menu": "组织管理 → 员工管理",
        "steps": [
            "打开「组织管理 → 员工管理」，点右上角「新增员工」",
            "填写「姓名」「手机号」，选择「岗位」并勾选「账号权限」",
            "填写员工「登录用户名」和「初始密码」",
            "点弹窗右下角「创建」完成新增",
        ],
        "preconditions": [
            "账号有新增员工权限（employee:create）",
            "目标岗位已存在（岗位下拉里有可选项）",
        ],
        "permission": "employee:list",
        "keywords": ("新增员工", "添加员工", "创建员工", "员工账号", "给员工开账号", "开账号"),
    },
    "processing_item_create": {
        "label": "配置加工项",
        "route": "/settings",
        "menu": "企业基础设置",
        "steps": [
            "打开侧边栏「企业基础设置」",
            "在左侧配置域里点「加工项与分类」",
            "点「新增加工项」，填「加工项名称」并选「加工分类」",
            "点弹窗里的「保存」完成新增",
        ],
        "preconditions": [
            "账号有加工配置权限（processing:manage）",
            "至少有一个加工分类（没有可先在新增弹窗里创建）",
        ],
        "permission": "production:view",
        "keywords": ("配置加工项", "新增加工项", "加工项", "加工分类", "加工项与分类"),
    },
}


def lookup(keyword: str) -> Optional[Dict[str, Any]]:
    """自由文本 → 登记项（**只读、确定性、fail-closed**）。

    匹配口径（与 `menu_navigator.resolve_feature` 同族的最长命中）：
    1. 规范化（去首尾空白 + 去所有空白 + 小写）；
    2. 精确等于动作 id ⇒ 直接返回；
    3. 否则取 `keywords` 里**最长**的子串命中；**同长但分属不同动作 = 歧义 ⇒ None**
       （不猜「更可能的那条」）；
    4. 未命中 ⇒ `None`（调用方据此**如实说没有步骤级指引**）。
    """
    text = re.sub(r"\s+", "", (keyword or "").strip().lower())
    if not text:
        return None
    if text in PAGE_ACTIONS:
        return PAGE_ACTIONS[text]

    best_len = 0
    best_keys: List[str] = []
    for key, entry in PAGE_ACTIONS.items():
        for word in entry["keywords"]:
            token = re.sub(r"\s+", "", str(word).lower())
            if not token or token not in text:
                continue
            if len(token) > best_len:
                best_len = len(token)
                best_keys = [key]
            elif len(token) == best_len and key not in best_keys:
                best_keys.append(key)
    if len(best_keys) != 1:
        return None
    return PAGE_ACTIONS[best_keys[0]]
