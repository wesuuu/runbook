import type { SchemaRow } from "$lib/components/shared/SchemaEditor.svelte";

/**
 * Normalize a user-entered param key: trim it and collapse internal
 * whitespace runs into single underscores.
 *
 * Case is deliberately preserved. Scientific parameter names carry
 * meaning in their casing — `temperature_C`, `pH`, `OD600` — and
 * lowercasing the key on every Inspector apply renamed it (e.g.
 * `temperature_C` → `temperature_c`). That desynced the node's recorded
 * `params` (still keyed `temperature_C`) from its `paramSchema`, so the
 * value was dropped and exotic schema fields (enum, x-ref-type) keyed by
 * the original case were no longer merged forward (#7).
 */
export function normalizeParamKey(rawKey: string): string {
    return rawKey.trim().replace(/\s+/g, "_");
}

/**
 * Build a JSON-Schema `properties` object from the Inspector's editable
 * rows. Each property is merged over the matching existing property so
 * exotic fields (enum, x-ref-type, default) survive a schema edit.
 */
export function buildParamSchema(
    rows: SchemaRow[],
    existingProps: Record<string, any>,
): Record<string, any> {
    const properties: Record<string, any> = {};
    for (const row of rows) {
        const key = normalizeParamKey(row.key);
        if (!key) continue;
        properties[key] = {
            ...(existingProps[key] || {}),
            type: row.type,
            title: row.title || row.key,
        };
    }
    return { type: "object", properties };
}

/**
 * Reconcile a node's recorded `params` against a (possibly edited)
 * schema: keep values whose key still exists, fall back to the schema
 * `default` (then first `enum` option) for newly added keys, and drop
 * values whose key was removed.
 */
export function syncParamsToSchema(
    current: Record<string, any>,
    schema: Record<string, any>,
): Record<string, any> {
    const props = (schema.properties || {}) as Record<string, any>;
    const synced: Record<string, any> = {};
    for (const [key, prop] of Object.entries(props)) {
        if (key in current) {
            synced[key] = current[key];
        } else if (prop.default !== undefined) {
            synced[key] = prop.default;
        } else if (prop.enum?.[0] !== undefined) {
            synced[key] = prop.enum[0];
        }
    }
    return synced;
}
