### 集成侧补的真库读数（对象侧收口，2026-10-03 07:45 +08）

本包存疑①「真库上停用后 `status` 真的变 `disabled` 未复验」—— 集成侧已在租户 20 的真库上补跑
（脚本 `acceptance/2026-10-03/dispatch-routing-sweep/harness/p11-status-vocab.mjs`，读数 `out/p11-status-vocab.json`，3/3 pass）：

| 动作 | 读数 |
|---|---|
| `PUT /api/admin/production/operations/{质检}` body `{"status":"disabled"}`（= 本包改后 UI 会发的值） | **HTTP 200**；库内 `active` → **`disabled`** ✅ |
| 同上 body `{"status":"inactive"}`（= 修复前的错域值） | **HTTP 422** `status 仅支持 active/disabled`；库内不变 ✅（这就是 F1 病根，修的是 UI 侧） |
| 还原 `{"status":"active"}` | HTTP 200；库内回到 `active` ✅ |

⇒ 「UI 发出的 payload ∈ 后端受理词表」这一半是**真对象实测**，不是单测推断；剩下的一半（**部署后**用真浏览器点一次「停用」看到列表状态真的变）需要部署窗口，重启条件不变。
