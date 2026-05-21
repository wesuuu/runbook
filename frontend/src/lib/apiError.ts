/**
 * Derive a human-readable message from a parsed FastAPI error response body.
 *
 * FastAPI's `detail` field may be:
 *  - a plain string (`HTTPException(detail="...")`),
 *  - a structured object (`HTTPException(detail={ error, message, ... })`),
 *  - a list of 422 validation errors (`[{ loc, msg, type }, ...]`).
 *
 * Without this, a structured-object `detail` stringifies to `[object Object]`
 * when assigned to an `Error` message. Returns `fallback` when no usable
 * message can be found.
 */
export function extractErrorMessage(body: unknown, fallback: string): string {
    if (!body || typeof body !== 'object') return fallback;
    const obj = body as Record<string, unknown>;
    const detail = obj.detail;

    if (typeof detail === 'string' && detail.trim()) return detail;

    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
        const d = detail as Record<string, unknown>;
        if (typeof d.message === 'string' && d.message.trim()) return d.message;
        if (typeof d.error === 'string' && d.error.trim()) return d.error;
    }

    if (Array.isArray(detail) && detail.length > 0) {
        const first = detail[0] as Record<string, unknown> | undefined;
        if (first && typeof first.msg === 'string' && first.msg.trim()) {
            return first.msg;
        }
    }

    if (typeof obj.message === 'string' && obj.message.trim()) return obj.message;
    return fallback;
}
