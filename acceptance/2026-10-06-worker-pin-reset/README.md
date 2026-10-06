# 工人档案「重置 PIN」页面多模态验收（issue #6432）

被测面：本机唯一入口 `admin-web :3001` + `admin-api :8090`（worktree `feat/6432-worker-pin-reset` 的代码；
:8080 上跑着**主工作区**的旧进程，故本包用 8090，避免污染他人会话）。
**被测 SHA = `c8bfe9076`**（本目录与 PR 同 commit）。测量时间 2026-10-06 16:10–16:16 (+08)。
登录：管理员手机验证码（`13800138000` + 本机 `SMS_BYPASS_CODE`），租户 25「米高测试环境」。

## 0. 一句话

**用户报障的那条路已经通了**：工人档案每行多了「重置 PIN」，弹窗可手输或留空随机；确认后当场显示新 PIN；
真 HTTP 打过去后，`908696` 这个新 PIN **真的能登录工人端**，旧 PIN `111111` **真的被拒**。

## 1. 一条命令复跑（承载体 = preset skill 的 ui-multimodal-acceptance.mjs）

```bash
node /Users/guangzhen.zk/.dsh/.agent-presets/migao/skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs \
  --site http://localhost:3001 --path /employees --click 工人档案 --click 重置 PIN \
  --out acceptance/2026-10-06-worker-pin-reset/out
```

读数：`loginOk=true` · `loginShape=login-tabs-v5485 ✓` · `testids=15` · `http5xx=[]`（`out/summary.json`）。

## 2. 多模态判定（我自己读图；"看到了什么"而非"应该是什么"）

| 截图 | 我看到的 | 判定项 |
|---|---|---|
| `out/01-full.png` | 工人档案 tab 激活；表头 工号/姓名/状态/操作；**每一行的操作列是「重置 PIN 停用」两个动作**（改前只有「停用」）；10 行演示工人、分页「共 24 条记录」 | 入口可达 + 与既有动作并列、未挤掉原动作 |
| `out/02-reset-pin-modal.png` | 弹窗标题「重置工人 PIN」；正文「工人：SD07演示W1767345 SD07演示工人5」；输入框 placeholder「4~12 位数字；留空则由系统随机生成 6 位」；灰字说明「系统只保存不可逆的加密结果，原 PIN 无法查看 ⇒ 工人忘记时只能重置为新值。重置后旧 PIN 立即失效，请当面告知本人。」；底部「取消 / 确认重置」 | 目标工人可辨认（工号+姓名）+ 明文口径如实告知 + 无 markdown 星号外溢 |
| `out/03-reset-pin-result.png` | 弹窗标题变「新 PIN（只显示这一次）」；大号等宽数字 `908696`；下方「关掉本窗口后就查不到了 —— 请立刻告知工人，让他用工号 + 这个 PIN 在工人端登录一次确认可用。」；按钮变「完成」 | **结果可见**（§15.1）+ 一次性提醒在位 |
| `out/04-after-disable.png` | 右上 toast「已停用（该工人不能再登录工人端）」；该行状态徽章 = 停用、操作列变「重置 PIN 启用」 | 清理动作生效（见 §4） |

## 3. 端到端真跑（不是替身）—— 读数逐条

| 步骤 | 命令/动作 | 读数 |
|---|---|---|
| 建号 | UI「新建工人档案」`W-PIN6432-CHK / PIN验收临时工 / 111111` | 列表出现该行（共 1 条记录） |
| 重置 | UI「重置 PIN」→ 留空 → 确认重置（真 HTTP `PUT /api/admin/workers/{id}/pin`） | 服务端返回并显示 **`908696`**（6 位随机） |
| 新 PIN 登录工人端 | `POST :8090/api/worker/login`（`X-Tenant-Id: 25`） | `success:true`，`worker_no=W-PIN6432-CHK`、`worker_name=PIN验收临时工` |
| 旧 PIN 登录工人端 | 同上，`pin=111111` | `AUTH_FAILED 工号或 PIN 不正确`（旧 PIN 立即失效 ✓） |

## 4. 清理（不留尾巴）

临时档案 `W-PIN6432-CHK` 已按 UI「停用」处置（不删，留痕可见，见 `out/04-after-disable.png`）——
它只存在于**测试租户 25**，且已不能再登录工人端。

## 5. 未覆盖项（照实登记）

- **工人端 H5 真机走查未做**：本次只验到「工人端登录接口用新 PIN 拿到 session」这一层；
  `frontend/worker-h5` 页面本身的渲染未跑（本包一字未改 H5，且验收点不在那儿）。
- **`--shot` 逐元素截图未跑**：本页无 fixed 浮动元素改动，几何探针（§15.2 第 3 条）不适用；
  米宝 FAB 与分页的相对位置在 `out/01-full.png` 上可见无重叠。
