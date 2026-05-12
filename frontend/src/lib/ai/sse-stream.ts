import { getToken } from '$lib/auth.svelte';
import { API_BASE } from '$lib/config';

export type SseEvent =
    | { type: 'tool_start'; tool: string; label: string }
    | { type: 'tool_end'; tool: string }
    | { type: 'done'; user_message: unknown; assistant_message: unknown; sources: unknown[] }
    | { type: 'error'; detail: string; error_code?: string };

/**
 * POST a JSON body and stream back a `text/event-stream` response.
 * Invokes `onEvent` once per parsed `data:` JSON object, in order.
 *
 * Throws on non-2xx HTTP status. Returns after the server closes the stream.
 */
export async function streamSse(
    endpoint: string,
    body: unknown,
    onEvent: (event: SseEvent) => void,
): Promise<void> {
    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
    };
    const token = getToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
    });

    if (!response.ok) {
        const detail = await response.text().catch(() => '');
        throw new Error(`SSE request failed: ${response.status} ${detail}`);
    }
    if (!response.body) {
        throw new Error('SSE response has no body');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let sep: number;
        while ((sep = buffer.indexOf('\n\n')) !== -1) {
            const frame = buffer.slice(0, sep);
            buffer = buffer.slice(sep + 2);
            for (const line of frame.split('\n')) {
                const trimmed = line.trim();
                if (trimmed.startsWith('data:')) {
                    const json = trimmed.slice('data:'.length).trim();
                    if (json) {
                        try {
                            onEvent(JSON.parse(json) as SseEvent);
                        } catch (e) {
                            console.error('Bad SSE payload', json, e);
                        }
                    }
                }
            }
        }
    }
}
