/**
 * 商品表单的**一处上限常量**（issue #6354）—— `SkuMatrix` 渲染用、预填侧（`image-recognize.ts`）
 * 也要按同一个数裁剪识别结果。
 *
 * 为什么单独一个模块：这两个数原先只写在 `components/products/SkuMatrix.tsx` 里，
 * 而**图片识别预填**（`lib/image-recognize.ts`）是第二个消费点 —— 它不 import 组件（那会
 * 把 React 拉进纯函数库），于是要么各写一份（本仓反复复发的「第二份口径」），要么谁都不知道
 * 上限在哪。抽到这里后「上限」只有一个定义点，守卫
 * `tests/unit/lib/image-recognize-color-split.test.ts` 直接读 `SkuMatrix` 的输入框 `maxLength`
 * 与这里比对（两处漂移即红）。
 */

/** 单个颜色名的字符上限（= 颜色行名称框的 `maxLength`） */
export const COLOR_NAME_MAX = 30

/** 颜色分类条数上限 */
export const MAX_COLORS = 200

/** SKU 行数上限（颜色 × 门幅） */
export const MAX_SKUS = 600
