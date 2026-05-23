/**
 * API error type and the shared logic for turning a backend error body into a
 * human-readable string.
 *
 * FastAPI returns errors under a `detail` key, which may be:
 *  - a plain string  (`raise HTTPException(400, "lot_number is required")`)
 *  - a structured object  (`detail={"error": "QAU_NOT_INDEPENDENT", "message": ...}`)
 *  - a 422 validation array (`[{loc, msg, type}, ...]`)
 *
 * Passing a non-string straight into `new Error(...)` stringifies it to the
 * useless literal "[object Object]" — `extractErrorMessage` prevents that so
 * callers (e.g. the run-creator wizard's `createError`) always show real text.
 */

export class ApiError extends Error {
    status: number;
    data: unknown;

    constructor(status: number, message: string, data: unknown = null) {
        super(message);
        this.status = status;
        this.data = data;
    }
}

interface StructuredDetail {
    error?: unknown;
    message?: unknown;
    [key: string]: unknown;
}

interface ValidationItem {
    msg?: unknown;
}

/**
 * Derive a display string from a parsed JSON error body.
 *
 * @param body Parsed response JSON (any shape, may be null).
 * @param fallback Message to use when nothing usable is found.
 */
export function extractErrorMessage(body: unknown, fallback: string): string {
    if (body === null || typeof body !== 'object') {
        return fallback;
    }

    const detail = (body as { detail?: unknown }).detail;

    // Plain-string detail — the common HTTPException case.
    if (typeof detail === 'string' && detail) {
        return detail;
    }

    // FastAPI 422 validation array: [{loc, msg, type}, ...].
    if (Array.isArray(detail)) {
        const msgs = detail
            .map((item) =>
                item && typeof item === 'object'
                    ? (item as ValidationItem).msg
                    : undefined,
            )
            .filter((m): m is string => typeof m === 'string' && m.length > 0);
        if (msgs.length > 0) {
            return msgs.join('; ');
        }
    }

    // Structured detail object — prefer a human message, fall back to the
    // stable error code so the user never sees "[object Object]".
    if (detail && typeof detail === 'object') {
        const structured = detail as StructuredDetail;
        if (typeof structured.message === 'string' && structured.message) {
            return structured.message;
        }
        if (typeof structured.error === 'string' && structured.error) {
            return structured.error;
        }
    }

    // No detail — try a top-level message.
    const topMessage = (body as { message?: unknown }).message;
    if (typeof topMessage === 'string' && topMessage) {
        return topMessage;
    }

    return fallback;
}
