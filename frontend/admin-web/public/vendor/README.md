# vendor/ — 厂商打印 SDK（静态资源）

## `lpapi-ble.umd.js`

德佟（DothanTech）标签打印机 SDK 的**浏览器 UMD bundle**，供 `src/lib/label-print/lpapi.ts`
在运行时以 `<script>` 注入（见 `LPAPI_SCRIPT_SRC = '/vendor/lpapi-ble.umd.js'`）。

| 项 | 值 |
|---|---|
| 来源 | npm 包 `lpapi-ble@1.7.260618` 的 `libs/index.umd.js` |
| 拷贝自 | `frontend/bmini-app/node_modules/lpapi-ble/libs/index.umd.js`（该包已由 bmini 侧依赖） |
| 校验 | `shasum -a 256` 与源文件一致（拷贝时核对） |

**为什么不加进 `package.json`**：厂商把浏览器 bundle 以 UMD 形态发在 npm 包里，
而 admin-web 是 Next.js 工程 —— 直接 `import` 会把 334KB 的 UMD 拖进构建图、
且它自带一份 Vue 运行时（仅用于厂商的预览渲染）。运行时按需注入是**最少代码**的接法：
不进构建图、不引第二个依赖树、换版本只需替换本文件。

⚠️ **只覆盖带 SDK 协议的机型**：Web Bluetooth 是点对点协议、**没有通用标准**
⇒ 直连通道永远不是「任意打印机」的答案。要打任意品牌请走**系统打印**（`window.print()`）。
边界全文见 `src/lib/label-print/capability.ts` 文件头。
