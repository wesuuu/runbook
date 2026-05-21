import { describe, it, expect } from "vitest";
import {
    normalizeParamKey,
    buildParamSchema,
    syncParamsToSchema,
} from "./protocolParamSchema";
import type { SchemaRow } from "$lib/components/shared/SchemaEditor.svelte";

function row(key: string, type: SchemaRow["type"] = "string", title = ""): SchemaRow {
    return { key, title, type };
}

describe("normalizeParamKey", () => {
    it("trims and collapses whitespace into underscores", () => {
        expect(normalizeParamKey("  buffer  volume ")).toBe("buffer_volume");
        expect(normalizeParamKey("speed\trpm")).toBe("speed_rpm");
    });

    it("preserves the original casing of the key (#7)", () => {
        expect(normalizeParamKey("temperature_C")).toBe("temperature_C");
        expect(normalizeParamKey("pH")).toBe("pH");
        expect(normalizeParamKey("OD600")).toBe("OD600");
    });
});

describe("buildParamSchema", () => {
    it("builds properties keyed by the normalized key", () => {
        const schema = buildParamSchema(
            [row("speed_rpm", "number", "Speed")],
            {},
        );
        expect(schema).toEqual({
            type: "object",
            properties: {
                speed_rpm: { type: "number", title: "Speed" },
            },
        });
    });

    it("skips rows whose key is blank after normalization", () => {
        const schema = buildParamSchema([row("   "), row("temp", "number")], {});
        expect(Object.keys(schema.properties)).toEqual(["temp"]);
    });

    it("keeps a mixed-case key intact so its value is not orphaned (#7)", () => {
        const schema = buildParamSchema(
            [row("temperature_C", "number", "Temperature")],
            {},
        );
        expect(Object.keys(schema.properties)).toEqual(["temperature_C"]);
    });

    it("merges exotic fields from the existing property of the same key", () => {
        const existing = {
            temperature_C: {
                type: "number",
                "x-ref-type": "material",
                enum: [4, 25, 37],
                default: 37,
            },
        };
        const schema = buildParamSchema(
            [row("temperature_C", "number", "Temp")],
            existing,
        );
        // type/title come from the row; enum, x-ref-type, default are preserved.
        expect(schema.properties.temperature_C).toEqual({
            type: "number",
            title: "Temp",
            "x-ref-type": "material",
            enum: [4, 25, 37],
            default: 37,
        });
    });

    it("does not merge exotic fields across a case mismatch", () => {
        // Existing prop keyed temperature_c; row keyed temperature_C.
        const existing = { temperature_c: { enum: [1, 2] } };
        const schema = buildParamSchema(
            [row("temperature_C", "number", "Temp")],
            existing,
        );
        expect(schema.properties.temperature_C.enum).toBeUndefined();
    });

    it("falls back to the raw key for the title when title is empty", () => {
        const schema = buildParamSchema([row("speed rpm", "number", "")], {});
        expect(schema.properties.speed_rpm.title).toBe("speed rpm");
    });
});

describe("syncParamsToSchema", () => {
    const schema = {
        type: "object",
        properties: {
            temperature_C: { type: "number" },
            buffer: { type: "string", default: "PBS" },
            mode: { type: "string", enum: ["A", "B"] },
        },
    };

    it("keeps a recorded value whose mixed-case key still exists (#7)", () => {
        const synced = syncParamsToSchema({ temperature_C: 37 }, schema);
        expect(synced.temperature_C).toBe(37);
    });

    it("falls back to the schema default for a missing key", () => {
        const synced = syncParamsToSchema({}, schema);
        expect(synced.buffer).toBe("PBS");
    });

    it("falls back to the first enum option when there is no default", () => {
        const synced = syncParamsToSchema({}, schema);
        expect(synced.mode).toBe("A");
    });

    it("drops values whose key is absent from the schema", () => {
        const synced = syncParamsToSchema(
            { temperature_C: 37, removed_field: "x" },
            schema,
        );
        expect("removed_field" in synced).toBe(false);
    });

    it("handles an empty schema", () => {
        expect(syncParamsToSchema({ a: 1 }, {})).toEqual({});
    });
});
