# 用例 id 悬空引用清单（全库，报告型）

> 🔴 **本文件是读数快照，不是门禁**：悬空引用**不阻塞合并**（可能是历史遗留）。变更集里的悬空引用由 `growth_gate.case_trace_check` **阻塞**（`QA Growth Gate` 腿）；**新增**的悬空引用由基线台账阻塞（新增即红，见下表）。
> 工具 = `.github/case_ids_dangling.py`（单一实现，解析规则全部复用 `growth_gate`）。

## 本次读数

- 生成日期：**2026-11-03**
- 用例库：**999** 条（`.github/cases/*.yml`）
- 扫描面：**2149** 个声明了 `case_ids` 的测试文件（`.py` / `.java` / `.ts` / `.tsx`，文件名含 test/spec）
- **悬空引用：0 条**

✅ 全库无悬空引用：每个测试文件声明的 `case_ids` 都能在用例库里找到对应用例。

## 复算（零成本，一条命令）

```bash
python3 .github/case_ids_dangling.py            # 打印（退出码：0 无 / 1 有 / 3 无法判定）
python3 .github/case_ids_dangling.py --write docs/testing/case-ids-dangling.md   # 重生成本文件
```

## 为什么需要这份全库读数（与既有判据的分工）

| 面 | 判据 | 行为 |
|---|---|---|
| 变更集 | `growth_gate.case_trace_check`（`QA Growth Gate`，required） | 悬空 ⇒ **阻塞** |
| 全库 · 报告 | 本文件 + `.github/case_ids_dangling.py` | 悬空 ⇒ **只列出、不阻塞**（全貌） |
| 全库 · 基线 | `.github/case-ids-dangling-baseline.json` + `baseline_violations()`（D7 断言） | **新增即红**；少于基线 ⇒ 要求同批下沉；`history` 回升 ⇒ **红**（不得放宽） |

基线台账现值：**0** 条（实测必须与它相等 —— 多一条要修、少一条要同批下沉）。

为什么需要它：**只改 YAML 的批次提交**（让号）可能在不碰测试文件的前提下新增悬空引用 ⇒ 变更集判据看不见；报告面是**全貌**、基线面是**唯一的拦截机制**（只 warn = 没人看 = 等于没有）。
