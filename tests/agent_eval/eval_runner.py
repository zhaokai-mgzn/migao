"""
米宝 Agent 评测 Runner — 基于 EvalScope general_fc

两步：
1. convert_cases_to_dataset() → 43 用例 → evalscope JSONL 格式
2. 运行 evalscope eval → 产出 F1 / schema_accuracy / tool_call 统计

用法:
  python eval_runner.py convert          # 生成数据集
  python eval_runner.py run              # 跑评测
  python eval_runner.py run --limit 5   # 先跑 5 条试水
"""

import json
import os
import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Any

from eval_cases import (
    ALL_CASES,
    get_smoke_cases,
    get_adversarial_cases,
    get_active_cases,
)

# Mibao 的 Tool Schema 映射 — 转成 OpenAI function 格式
MIBAO_TOOLS = {
    "product_search": {
        "name": "product_search",
        "description": "搜索商品列表，支持关键词、分类过滤",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词"},
                "category_id": {"type": "string", "description": "分类ID"},
                "page": {"type": "integer", "default": 1},
                "size": {"type": "integer", "default": 5},
            },
        },
    },
    "product_detail": {
        "name": "product_detail",
        "description": "查看商品详情（含 SKU、规格、加工项），下单前必须先调此工具查看 SKU",
        "parameters": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "商品32位UUID。支持名称/序号/UUID，服务端自动解析",
                },
            },
            "required": ["product_id"],
        },
    },
    "product_manage": {
        "name": "product_manage",
        "description": "创建/修改/上下架商品。create 必填 name+price。update 需 product_id",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "update", "toggle_status"]},
                "product_id": {"type": "string", "description": "商品UUID（update/toggle_status 必填）"},
                "name": {"type": "string", "description": "商品名称（create 必填）"},
                "price": {"type": "number", "description": "价格"},
                "category_id": {"type": "string", "description": "分类ID"},
                "colors": {"type": "array", "items": {"type": "string"}},
                "selling_methods": {"type": "array", "items": {"type": "string"}},
                "door_widths": {"type": "array", "items": {"type": "string"}},
                "sku_code": {"type": "string"},
                "status": {"type": "string", "enum": ["on_sale", "off_sale"]},
            },
            "required": ["action"],
        },
    },
    "product_processing_item_manage": {
        "name": "product_processing_item_manage",
        "description": "为商品增删加工项。product_id 支持名称/序号/UUID，item_ids 支持名称/序号/UUID",
        "parameters": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "description": "商品标识，支持名称/序号/UUID"},
                "action": {"type": "string", "enum": ["add", "remove"]},
                "item_ids": {"type": "array", "items": {"type": "string"}, "description": "加工项ID列表"},
            },
            "required": ["product_id", "action", "item_ids"],
        },
    },
    "processing_item_query": {
        "name": "processing_item_query",
        "description": "查询加工项目录。创建商品时选择加工项用",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string"},
                "category_id": {"type": "string"},
                "page": {"type": "integer", "default": 1},
                "size": {"type": "integer", "default": 10},
            },
        },
    },
    "order_query": {
        "name": "order_query",
        "description": "查询订单列表/详情/统计",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "detail", "statistics"]},
                "order_id": {"type": "string", "description": "订单ID或订单号(ORD-xxx)"},
                "keyword": {"type": "string"},
                "status": {"type": "string"},
                "page": {"type": "integer", "default": 1},
                "size": {"type": "integer", "default": 10},
            },
        },
    },
    "order_manage": {
        "name": "order_manage",
        "description": "修改订单状态/发货/取消/退款",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["update_status", "update_logistics", "cancel", "confirm_payment", "refund"]},
                "order_id": {"type": "string", "description": "订单ID或订单号(ORD-xxx)"},
                "status": {"type": "string"},
                "logistics_company": {"type": "string"},
                "tracking_number": {"type": "string"},
                "cancel_reason": {"type": "string"},
            },
            "required": ["action", "order_id"],
        },
    },
    "order_create": {
        "name": "order_create",
        "description": "创建新订单。必填 customer_name+customer_phone+items",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string"},
                "customer_phone": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "product_name": {"type": "string"},
                            "quantity": {"type": "integer"},
                            "unit_price": {"type": "number"},
                            "colorName": {"type": "string"},
                            "sellingMethod": {"type": "string"},
                            "doorWidth": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["customer_name", "customer_phone", "items"],
        },
    },
    "customer_manage": {
        "name": "customer_manage",
        "description": "客户管理：列表/详情/更新/标签",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "detail", "update", "add_tag", "remove_tag"]},
                "customer_id": {"type": "string"},
                "keyword": {"type": "string"},
            },
            "required": ["action"],
        },
    },
    "aftersale_create": {
        "name": "aftersale_create",
        "description": "创建售后工单（退款/换货/维修/投诉）",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单ID，支持订单号(ORD-xxx)"},
                "ticket_type": {"type": "string", "enum": ["refund", "exchange", "repair", "complaint", "other"]},
                "reason": {"type": "string"},
            },
            "required": ["order_id", "ticket_type", "reason"],
        },
    },
    "validate_input": {
        "name": "validate_input",
        "description": "写操作前置校验",
        "parameters": {
            "type": "object",
            "properties": {
                "target_tool": {"type": "string"},
                "target_action": {"type": "string"},
                "params": {"type": "object"},
            },
            "required": ["target_tool", "target_action", "params"],
        },
    },
    "interact": {
        "name": "interact",
        "description": "交互组件：choice/confirm/form",
        "parameters": {
            "type": "object",
            "properties": {
                "component": {"type": "string", "enum": ["choice", "confirm", "form"]},
                "options": {"type": "array", "items": {"type": "object"}},
                "pageMeta": {"type": "object"},
            },
            "required": ["component"],
        },
    },
}


def build_tool_list(tool_names: List[str]) -> List[dict]:
    """根据 tool 名称列表构建 OpenAI function 格式的工具列表"""
    tools = []
    for name in tool_names:
        if name in MIBAO_TOOLS:
            tool = MIBAO_TOOLS[name]
            tools.append({"type": "function", "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            }})
    return tools


def convert_cases_to_dataset(cases, output_path: str, subset: str = "smoke"):
    """将 EvalCase 列表转为 evalscope general_fc JSONL 格式"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w") as f:
        for case in cases:
            if case.skip_reason:
                continue

            # 从 expectations 中提取预期调用的 tool 名称
            expected_tools = set()
            should_call = False
            for exp in case.expectations:
                for tool_name in MIBAO_TOOLS:
                    if tool_name in exp:
                        expected_tools.add(tool_name)
                        should_call = True

            # 如果没有明确预期 tool，默认应该调 tool
            if not expected_tools:
                should_call = True

            record = {
                "id": case.id,
                "messages": [
                    {"role": "system", "content": f"你是米宝AI助手,当前在{case.skill.value}领域"},
                    {"role": "user", "content": case.user_inputs[0]},
                ],
                "tools": build_tool_list(expected_tools) if expected_tools else [],
                "should_call_tool": should_call,
                "expected_tools": list(expected_tools),
                "tags": case.tags,
                "difficulty": case.difficulty.value,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"✅ 生成 {sum(1 for c in cases if not c.skip_reason)} 条评测数据 → {output_path}")
    return output_path


def run_eval(dataset_path: str, model: str = "deepseek-v4-pro", limit: int = None, api_url: str = None):
    """运行 evalscope 评测"""
    cmd = [
        sys.executable, "-m", "evalscope", "eval",
        "--model", model,
        "--api-url", api_url or "https://api.deepseek.com",
        "--eval-type", "openai_api",
        "--eval-backend", "Native",
        "--datasets", "general_fc",
        "--dataset-args",
        json.dumps({
            "general_fc": {
                "dataset_id": dataset_path,
                "default_subset": "default",
                "eval_split": "test",
            }
        }),
        "--work-dir", f"./outputs/eval_{model.replace('/', '_')}",
        "--no-timestamp",
    ]
    if limit:
        cmd.extend(["--limit", str(limit)])

    env = os.environ.copy()
    env["DEEPSEEK_API_KEY"] = os.environ.get("PRIMARY_API_KEY", os.environ.get("DEEPSEEK_API_KEY", ""))
    safe_cmd = [a[:12] + "..." if a.startswith("sk-") else a for a in cmd]
    print(f"🚀 运行评测: {' '.join(safe_cmd)}")
    subprocess.run(cmd, check=True, env=env)


def run_quick_eval(model: str = "deepseek-v4-pro", limit: int = 10):
    """快速评测 — 仅冒烟用例"""
    cases = get_smoke_cases()
    path = "/tmp/mibao_eval/text/fc/smoke.jsonl"
    convert_cases_to_dataset(cases, path, subset="smoke")
    run_eval(path, model=model, limit=limit)


def run_full_eval(model: str = "deepseek-v4-pro"):
    """全量评测 — 所有 43 个用例"""
    cases = get_active_cases()
    path = "/tmp/mibao_eval/text/fc/full.jsonl"
    convert_cases_to_dataset(cases, path, subset="full")
    run_eval(path, model=model)


def run_adversarial_eval(model: str = "deepseek-v4-pro"):
    """对抗性评测 — 24 个对抗用例"""
    cases = get_adversarial_cases()
    path = "/tmp/mibao_eval/text/fc/adversarial.jsonl"
    convert_cases_to_dataset(cases, path, subset="adversarial")
    run_eval(path, model=model)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="米宝 Agent 评测")
    parser.add_argument("action", choices=["convert", "run", "smoke", "full", "adversarial"])
    parser.add_argument("--model", default="deepseek-v4-pro")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--api-url", default=None)
    args = parser.parse_args()

    if args.action == "smoke":
        run_quick_eval(model=args.model, limit=args.limit or 10)
    elif args.action == "full":
        run_full_eval(model=args.model)
    elif args.action == "adversarial":
        run_adversarial_eval(model=args.model)
    elif args.action == "convert":
        cases = get_active_cases()
        convert_cases_to_dataset(cases, "/tmp/mibao_eval/text/fc/full.jsonl")
    elif args.action == "run":
        run_eval("/tmp/mibao_eval/text/fc/full.jsonl", model=args.model, limit=args.limit, api_url=args.api_url)
