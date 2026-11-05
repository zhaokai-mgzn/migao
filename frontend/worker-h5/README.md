# `frontend/worker-h5`（线上 `/w/`）—— **兼容期**

> 本目录**只为已印出的纸码服务**：纸上的码不可回收重印，所以这套静态多页（零构建纯 ESM）
> 继续在线、继续能直接打开。它**不再是任何跳转的目标**，也**不再新增功能**。

## 边界（三条，改这个目录前先读）

| # | 口径 | 落点 |
|---|---|---|
| 1 | **不再新增功能**：新的工人面一律做在 `frontend/bmini-app`（`/b/` + 小程序双编译），不在本目录长新页面 | 工人工作台 = `frontend/bmini-app/src/pages/worker/home/index.tsx` |
| 2 | **不再是 302 的目标**：纸码 `/s/<短码>` `/o/<短码>` 的服务端 302 落到 `/b/report/`（该前缀在 nginx 里**内部** rewrite 到 `/w/` 这一份页面，URL 始终在 `/b` 下） | `backend/admin-api/src/main/java/com/migao/admin/service/WorkerShortLinkService.java` 的 `REPORT_PAGE_PATH` |
| 3 | **没有任何链接指向 `/w/`**：bmini（商家端 / 小程序 / 工人工作台）里不许出现把用户送到 `/w/` 的跳转 | 判据 `tests/unit_ci_workflows/test_w_compat_period.py` |

「兼容期」保留的**唯一**通道 = **旧码直连**：已印出的纸上码被扫到时，服务端照旧 302；
工人手里存着的 `/w/?t=<token>` 书签 / 历史记录照旧 200 且仍能进裁高页（`machine.html`）。
**这条通道是消费者的，不是产品的**：不许拿它当新入口用。

## 为什么不能直接删（「已印出的码不许失效」）

`/s/<短码>` 与 `/o/<短码>` 印在实物上，**不可重印**；`/w/?t=<token>` 也随短链 302 发到过工人手机。
删掉本目录 / 拆掉 nginx 的 `location /w/` ⇒ 这些码落到 `location /` 的 SPA 兜底 =
**HTTP 200 + C 端首页**（不是 404，监控不红，工人只当"打不开"）。判据钉住这条链路的每一环。

## 判据

- `tests/unit_ci_workflows/test_w_compat_period.py`（扫描面 / 302 目标 / 旧码可用 / 兼容期声明）；
- `frontend/bmini-app/tests/page-entry-reachability.test.ts`（工人四条面各有入口且发射方都在 bmini）；
- `frontend/bmini-app/tests/report-landing.test.ts` 的 B4（本目录不再是跳转生产者）；
- 线上身份断言：`deploy/scripts/worker-h5-verify-served.sh`。

退役属 issue #7806 的 P3；本目录**本轮不删、不改功能**（issue #7813 P2c）。
