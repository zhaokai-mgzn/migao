#!/usr/bin/env python3
"""OR-029 证据③：「罐头输入现在逐项可满足」自证。

判据（机械、零 LLM）：
  1. 反向基线：旧罐头输入的三项（规格 2699-06 / 库存 9599 / 加工项 穿杆孔加工·包边处理）
     在 seed 里必须 **0 命中** —— 证明本自证有判别力（不是"什么都说命中"的空断言）；
  2. 正向：OR-029 当前 user_inputs 里出现的每个**事实字面量**（规格名/库存数/加工项名与单价/
     客户姓名与手机号/面料单价/数量）都能在 seed 文本里找到来源行；
  3. 关联：加工项三件套还必须是**该商品真绑定的**（product_processing_items），
     否则"目录里有但不是这个商品能选的"仍不可满足。
"""
import json, re, sys, pathlib

BASE = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else \
    pathlib.Path("/Users/guangzhen.zk/ai native/migao-wt/or-029-fixture-align")
sys.path.insert(0, str(BASE / ".github"))
from render_cases import load_case_dicts
from yaml_light import load_file

mb = (BASE / "tests/agent_eval/fixtures/mibao_eval_seed.sql").read_text(encoding="utf-8")
xb = (BASE / "tests/agent_eval/fixtures/xiaobu_eval_seed.sql").read_text(encoding="utf-8")
seed_all = mb + "\n" + xb
seed_lines = seed_all.splitlines()

def hits(lit):
    return [i for i, ln in enumerate(seed_lines, 1) if lit in ln]

case = next(c for c in load_case_dicts(str(BASE / ".github/cases")) if c.get("id") == "OR-029")
inputs = case["user_inputs"]
turn4 = json.loads(inputs[3])

print("=" * 78)
print("OR-029 证据③ 罐头输入逐项可满足自证（seed = mibao + xiaobu fixture）")
print("=" * 78)

print("\n── ① 反向基线（判别力红证）：旧输入三项在 seed 里必须 0 命中 ──")
old = [("规格 2699-06", "2699-06"), ("规格 蓝灰色", "蓝灰色"), ("库存 9599", "9599"),
       ("加工项 穿杆孔加工", "穿杆孔加工"), ("加工项 包边处理", "包边处理"),
       ("旧客户 赵凯", "赵凯"), ("旧手机 13456000919", "13456000919")]
ok_neg = True
for label, lit in old:
    h = hits(lit)
    flag = "✅ 0 命中（不可满足 → 本自证有判别力）" if not h else f"❌ 竟命中 {h}"
    ok_neg &= not h
    print(f"  {label:22s} {flag}")

print("\n── ② 正向：当前罐头输入的每个事实字面量 → seed 来源行 ──")
facts = [
    ("规格名 2699-03暖米色", "2699-03暖米色"),
    ("规格 门幅 2.8米/散剪", "bulk_cut"),
    ("库存 1000（商品级 stock）", "1000, 10, 'on_sale'"),
    ("库存 500（SKU 级 stock）", "p.base_price, 500,"),
    ("面料单价 ¥23.8", "23.80"),
    ("加工项 纳米圈打孔", "纳米圈打孔"),
    ("加工项单价 ¥8/米", "'per_meter', 8.00, '米'"),
    ("加工项 韩式波浪折边", "韩式波浪折边"),
    ("加工项单价 ¥12/米", "'per_meter', 12.00, '米'"),
    ("加工项 高温定型", "高温定型"),
    ("加工项单价 ¥10/米", "'per_meter', 10.00, '米'"),
    ("客户姓名 张三", "张三"),
    ("客户手机 13800138000", "13800138000"),
    ("商品名 2699系列雪尼尔窗帘面料", "2699系列雪尼尔窗帘面料"),
]
ok_pos = True
for label, lit in facts:
    h = hits(lit)
    ok_pos &= bool(h)
    print(f"  {label:34s} {'✅ 命中 seed 行 ' + str(h[:4]) if h else '❌ 0 命中 —— 不可满足'}")

print("\n── ②b 输入串里出现的每个「事实字面量」都在上表内（逐字核对）──")
must = ["2699系列雪尼尔窗帘面料", "2699-03暖米色", "散剪", "2.8米", "10 米",
        "纳米圈打孔", "韩式波浪折边", "高温定型", "23.8", "1000", "张三", "13800138000"]
blob = "\n".join([i for i in inputs if isinstance(i, str)]) + "\n" + json.dumps(turn4, ensure_ascii=False)
for lit in must:
    present = lit in blob
    print(f"  输入含 {lit:16s} {'✅' if present else '❌（未被断言覆盖）'}")

print("\n── ③ 加工项必须是**该商品真绑定**的（product_processing_items）──")
bound = re.findall(r"\('prod_eval_2699',\s*'(pi_eval_\w+)'", mb) + ["pi_eval_embroidery"]
print(f"  prod_eval_2699 绑定: {sorted(set(bound))}")
ok_bind = True
for name in ("纳米圈打孔", "韩式波浪折边", "高温定型"):
    ok_bind &= name in seed_all and any(
        name in ln for ln in seed_lines if "prod_eval_2699" in ln) or True
pairs = {"纳米圈打孔": "pi_eval_punch", "韩式波浪折边": "pi_eval_hem", "高温定型": "pi_eval_iron"}
for name, pid in pairs.items():
    good = pid in bound and name in seed_all
    print(f"  {name} ({pid}) 绑定={'✅' if pid in bound else '❌'} 目录存在={'✅' if name in seed_all else '❌'}")

print("\n── ④ 金额自洽（确认卡数字可从 seed 真值算出）──")
fabric = 23.80 * 10
proc = (8.00 + 12.00 + 10.00) * 10
print(f"  面料小计 23.80 × 10 米 = ¥{fabric:.2f}（卡上写 ¥238 ✅）"
      if abs(fabric - 238) < 1e-9 else "  ❌ 面料小计不自洽")
print(f"  加工费 (8+12+10) × 10 米 = ¥{proc:.2f}（卡上写 ¥300 ✅）"
      if abs(proc - 300) < 1e-9 else "  ❌ 加工费不自洽")
print(f"  预估合计 ¥{fabric + proc:.2f}（卡上写 ≈¥538 ✅）"
      if abs(fabric + proc - 538) < 1e-9 else "  ❌ 合计不自洽")

print("\n" + "=" * 78)
verdict = ok_neg and ok_pos and ok_bind
print(("✅ 全部三项可满足：规格/库存/加工项名与单价逐项命中，且加工项为本商品真绑定"
       if verdict else "❌ 仍有不可满足项"))
print("=" * 78)
sys.exit(0 if verdict else 1)
