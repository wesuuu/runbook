import type { ZodSchema } from 'zod';

export interface RequestOptions<T> {
    schema?: ZodSchema<T>;
}

export function _validateResponse<T>(data: unknown, schema: ZodSchema<T>, endpoint: string): T | unknown {
    const result = schema.safeParse(data);
    if (result.success) {
        return result.data;
    }
    const message = `API response validation failed for ${endpoint}: ${result.error.message}`;
    if (import.meta.env.DEV) {
        throw new Error(message);
    }
    console.warn(message);
    return data;
}
