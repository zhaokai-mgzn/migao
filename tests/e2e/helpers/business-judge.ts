/**
 * LLM 业务裁判 — 自动评判页面业务行为是否合理
 *
 * 用法：
 *   const judge = new BusinessJudge({ apiKey: process.env.JUDGE_API_KEY })
 *   const result = await judge.evaluate({
 *     scenario: '商品创建后列表验证',
 *     criteria: ['商品名称出现在列表首页', '价格与创建时一致'],
 *     evidence: { pageText: '...', apiCalls: [...] }
 *   })
 *   expect(result.passed).toBe(true)
 *
 * 设计原则：
 *   1. 不判 UI 好不好看 — 只判业务逻辑对不对
 *   2. 不靠截图 — 靠 DOM 文本 + API 响应
 *   3. 失败带具体原因 — "价格显示 99 但创建时输入 199"
 */

interface JudgeConfig {
  apiKey: string
  baseUrl?: string
  model?: string
}

interface EvaluateInput {
  scenario: string      // 业务场景描述，如 "创建商品后验证列表页"
  criteria: string[]    // 评判标准列表，自然语言
  evidence: {
    pageText?: string   // 页面提取的文本内容
    pageUrl?: string    // 当前页面 URL
    apiCalls?: Array<{   // 捕获的 API 调用
      method: string
      url: string
      requestBody?: unknown
      responseBody?: unknown
      statusCode: number
    }>
    domSummary?: string  // 关键 DOM 元素摘要
  }
}

interface JudgeResult {
  passed: boolean
  score: number           // 0-100
  criteriaResults: Array<{
    criterion: string
    passed: boolean
    reason: string        // 为什么过/不过
  }>
  summary: string         // 一两句话总结
}

export class BusinessJudge {
  private config: Required<JudgeConfig>

  constructor(config: JudgeConfig) {
    this.config = {
      apiKey: config.apiKey,
      baseUrl: config.baseUrl || 'https://api.deepseek.com',
      model: config.model || 'deepseek-v4-flash',  // 裁判用 fast 模型就够了
    }
  }

  async evaluate(input: EvaluateInput): Promise<JudgeResult> {
    const prompt = this.buildPrompt(input)
    const response = await this.callLLM(prompt)
    return this.parseResponse(response)
  }

  private buildPrompt(input: EvaluateInput): string {
    const evidence = JSON.stringify(input.evidence, null, 2)
    const criteria = input.criteria.map((c, i) => `${i + 1}. ${c}`).join('\n')

    return `你是 SaaS 管理后台的业务逻辑裁判。你要判断一个页面操作是否符合业务规则。

## 场景
${input.scenario}

## 评判标准（必须全部满足才通过）
${criteria}

## 页面证据
${evidence}

## 输出格式（严格 JSON）
{
  "passed": true/false,
  "score": 0-100,
  "criteriaResults": [
    {"criterion": "标准原文", "passed": true/false, "reason": "具体判断依据"}
  ],
  "summary": "一两句话总结判断结果"
}

## 评判原则
- 只判断业务逻辑，不判断 UI 美观
- 字段名不严格匹配没关系，语义对就行（如 "订单编号" = "orderNo"）
- 数据不完全匹配时标注差异（如 "价格应为 199，实际显示 99"）
- 页面有合理的业务流程跳转（如创建后自动跳转到列表页）算通过`
  }

  private async callLLM(prompt: string): Promise<string> {
    const resp = await fetch(`${this.config.baseUrl}/v1/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.config.apiKey}`,
      },
      body: JSON.stringify({
        model: this.config.model,
        messages: [{ role: 'user', content: prompt }],
        temperature: 0,
        max_tokens: 2000,
        response_format: { type: 'json_object' },
      }),
    })
    const data = await resp.json() as any
    return data.choices?.[0]?.message?.content || ''
  }

  private parseResponse(text: string): JudgeResult {
    // 提取 JSON 块 — 支持 ```json ... ``` 和裸 JSON
    let json = text
    const codeBlock = text.match(/```(?:json)?\s*([\s\S]*?)```/)
    if (codeBlock) {
      json = codeBlock[1]
    } else {
      const match = text.match(/\{[\s\S]*\}/)
      if (match) json = match[0]
    }
    try {
      const result = JSON.parse(json) as JudgeResult
      // Normalize: if criteriaResults is missing, create from passed/score
      if (!result.criteriaResults || result.criteriaResults.length === 0) {
        result.criteriaResults = [{ criterion: '综合评判', passed: result.passed, reason: result.summary }]
      }
      return result
    } catch {
      return { passed: false, score: 0, criteriaResults: [], summary: `JSON 解析失败: ${text.slice(0, 200)}` }
    }
  }
}

/**
 * Playwright helper — 从页面抓证据
 */
export async function captureEvidence(page: import('@playwright/test').Page) {
  // 抓页面可见文本
  const pageText = await page.locator('body').innerText()

  // 抓关键数据（表格行数、主要标题等）
  const headingTexts = await page.locator('h1, h2, h3').allTextContents()
  const tableRowCount = await page.locator('tbody tr').count()
  const pageUrl = page.url()

  return {
    pageText: pageText.slice(0, 3000),  // 截断，LLM 不需要看全部
    pageUrl,
    domSummary: `标题: ${headingTexts.join(', ')}\n表格行数: ${tableRowCount}`,
  }
}

/**
 * Playwright helper — 拦截 API 调用
 */
export function startApiCapture(page: import('@playwright/test').Page): Array<{
  method: string; url: string; requestBody?: unknown; responseBody?: unknown; statusCode: number
}> {
  const captured: Array<{
    method: string; url: string; requestBody?: unknown; responseBody?: unknown; statusCode: number
  }> = []

  page.on('response', async (response) => {
    const url = response.url()
    // 只捕获业务 API
    if (url.includes('/api/admin/')) {
      try {
        const body = await response.json().catch(() => undefined)
        captured.push({
          method: response.request().method(),
          url,
          statusCode: response.status(),
          responseBody: body,
        })
      } catch { /* skip non-JSON */ }
    }
  })

  return captured
}
