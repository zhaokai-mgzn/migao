/**
 * SSE Helper — Intercept and inspect Server-Sent Events streams in E2E tests.
 *
 * The chat feature (src/store/chat.ts) sends POST to `${AI_SERVICE_URL}/api/chat/send`
 * which returns an SSE stream.  SSE events follow the W3C format:
 *
 *   event: <type>\n
 *   data: <json>\n
 *   \n
 *
 * Known event types (src/types/index.ts SSEEventType):
 *   message_start | text_delta | text | tool_start | tool_call |
 *   tool_result | card | loading | message_end | error |
 *   message | done | suggestions
 *
 * Strategy:
 *   We inject a `fetch` monkey-patch into the page context that:
 *   1. Lets the real request proceed normally
 *   2. Clones the Response and reads the body as a ReadableStream
 *   3. Parses SSE chunks and pushes parsed events into `window.__sseEvents`
 *
 * This approach works with the real AI service AND with mocked routes.
 */
import { type Page } from '@playwright/test'

/** A single parsed SSE event captured from the page */
export interface CapturedSSEEvent {
  type: string
  data: unknown
  timestamp: number
}

export class SSEHelper {
  private page: Page
  private intercepting = false

  constructor(page: Page) {
    this.page = page
  }

  /**
   * Start intercepting SSE streams.
   * Must be called BEFORE the chat message is sent.
   *
   * Injects a fetch monkey-patch that captures SSE events into
   * `window.__sseEvents` without disrupting the real stream.
   */
  async startIntercept(): Promise<void> {
    this.intercepting = true

    // Reset captured events and install the fetch interceptor
    await this.page.evaluate(() => {
      // Collected events array
      ;(window as any).__sseEvents = []
      ;(window as any).__sseIntercepting = true

      // Save original fetch
      if (!(window as any).__originalFetch) {
        ;(window as any).__originalFetch = window.fetch.bind(window)
      }
      const originalFetch = (window as any).__originalFetch

      window.fetch = async function patchedFetch(
        input: RequestInfo | URL,
        init?: RequestInit,
      ): Promise<Response> {
        const response = await originalFetch(input, init)

        // Only intercept SSE responses (chat send endpoint)
        const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
        const isSSE =
          url.includes('/api/chat/send') ||
          (response.headers.get('content-type') || '').includes('text/event-stream')

        if (!isSSE || !response.body || !(window as any).__sseIntercepting) {
          return response
        }

        // Clone the response so the original stream is not consumed
        const cloned = response.clone()

        // Read and parse the SSE stream in the background
        ;(async () => {
          try {
            const reader = cloned.body!.getReader()
            const decoder = new TextDecoder()
            let buffer = ''
            let currentEventType = ''

            while (true) {
              const { done, value } = await reader.read()
              if (done) break

              buffer += decoder.decode(value, { stream: true })
              const lines = buffer.split('\n')
              buffer = lines.pop() || ''

              for (const line of lines) {
                const trimmed = line.trim()

                if (trimmed.startsWith('event: ')) {
                  currentEventType = trimmed.substring(7).trim()
                  continue
                }

                if (trimmed.startsWith('data: ')) {
                  const dataStr = trimmed.substring(6)
                  let parsed: unknown
                  try {
                    parsed = JSON.parse(dataStr)
                  } catch {
                    parsed = dataStr
                  }

                  ;(window as any).__sseEvents.push({
                    type: currentEventType || 'message',
                    data: parsed,
                    timestamp: Date.now(),
                  })
                  currentEventType = ''
                  continue
                }

                // Empty line = event separator, reset
                if (trimmed === '') {
                  currentEventType = ''
                }
              }
            }
          } catch {
            // Stream ended or aborted — expected during navigation
          }
        })()

        return response
      }
    })
  }

  /**
   * Get all captured SSE events, optionally filtered by type.
   */
  async getEvents(type?: string): Promise<CapturedSSEEvent[]> {
    const events: CapturedSSEEvent[] = await this.page.evaluate(() => {
      return (window as any).__sseEvents || []
    })

    if (!type) return events
    return events.filter((e) => e.type === type)
  }

  /**
   * Wait until at least one event of the given type is captured.
   */
  async waitForEvent(type: string, timeout = 15_000): Promise<CapturedSSEEvent> {
    const deadline = Date.now() + timeout

    while (Date.now() < deadline) {
      const events = await this.getEvents(type)
      if (events.length > 0) return events[0]
      await this.page.waitForTimeout(250)
    }

    throw new Error(`Timed out waiting for SSE event of type "${type}"`)
  }

  /**
   * Wait until the stream completes (a `done` or `message_end` event is captured).
   */
  async waitForStreamEnd(timeout = 30_000): Promise<void> {
    const deadline = Date.now() + timeout

    while (Date.now() < deadline) {
      const events = await this.getEvents()
      const hasEnd = events.some(
        (e) => e.type === 'done' || e.type === 'message_end',
      )
      if (hasEnd) return
      await this.page.waitForTimeout(250)
    }

    throw new Error('Timed out waiting for SSE stream to end')
  }

  /**
   * Check if a tool_start / tool_call event with the given tool name occurred.
   */
  async hasToolCall(toolName: string): Promise<boolean> {
    const toolEvents = [
      ...(await this.getEvents('tool_start')),
      ...(await this.getEvents('tool_call')),
    ]

    return toolEvents.some((e) => {
      const data = e.data as Record<string, unknown>
      const name = data?.tool_name || data?.tool || data?.name
      return name === toolName
    })
  }

  /**
   * Check if a card event with the given card type occurred.
   * Card types: 'product_list' | 'product_detail' | 'logistics' | 'order' | 'knowledge'
   */
  async hasCard(cardType: string): Promise<boolean> {
    const cardEvents = await this.getEvents('card')

    return cardEvents.some((e) => {
      const data = e.data as Record<string, unknown>
      return data?.type === cardType
    })
  }

  /**
   * Check if any text content was received (text_delta or text events).
   */
  async hasTextContent(): Promise<boolean> {
    const textEvents = [
      ...(await this.getEvents('text_delta')),
      ...(await this.getEvents('text')),
      ...(await this.getEvents('message')),
    ]
    return textEvents.length > 0
  }

  /**
   * Get the full concatenated text from all text_delta/text/message events.
   */
  async getFullText(): Promise<string> {
    const textEvents = [
      ...(await this.getEvents('text_delta')),
      ...(await this.getEvents('text')),
      ...(await this.getEvents('message')),
    ]

    return textEvents
      .map((e) => {
        const data = e.data as Record<string, unknown>
        return (data?.content || data?.delta || '') as string
      })
      .join('')
  }

  /**
   * Get all suggestion strings from the 'suggestions' event.
   */
  async getSuggestions(): Promise<string[]> {
    const events = await this.getEvents('suggestions')
    if (events.length === 0) return []

    const lastEvent = events[events.length - 1]
    const data = lastEvent.data as Record<string, unknown>
    return (data?.questions || []) as string[]
  }

  /**
   * Check if an error event was captured.
   */
  async hasError(): Promise<boolean> {
    const errorEvents = await this.getEvents('error')
    return errorEvents.length > 0
  }

  /**
   * Stop intercepting and restore original fetch.
   */
  async stopIntercept(): Promise<void> {
    this.intercepting = false
    await this.page.evaluate(() => {
      ;(window as any).__sseIntercepting = false
      if ((window as any).__originalFetch) {
        window.fetch = (window as any).__originalFetch
        delete (window as any).__originalFetch
      }
    })
  }

  /**
   * Clear captured events without stopping the interceptor.
   */
  async clearEvents(): Promise<void> {
    await this.page.evaluate(() => {
      ;(window as any).__sseEvents = []
    })
  }
}
