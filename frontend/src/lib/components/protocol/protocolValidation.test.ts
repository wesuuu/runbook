import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import type { Node, Edge } from "@xyflow/svelte";

import {
    computeBranchValidationErrors,
    // @ts-expect-error - BranchTimeContext exported in Task 8
    type BranchTimeContext,
} from "./protocolValidation";

// frontend/src/lib/components/protocol/protocolValidation.test.ts
// → ../../../../../tests/fixtures/branch_role_validation.json (5 ups to repo root)
const FIXTURE_PATH = join(
    dirname(fileURLToPath(import.meta.url)),
    "../../../../../tests/fixtures/branch_role_validation.json",
);

interface FixtureCase {
    name: string;
    graph: {
        nodes: unknown[];
        edges: unknown[];
        timeEnabled?: boolean;
        pixelsPerHour?: number;
        layout?: "horizontal" | "vertical";
    };
    expected: { fires_on: string[] };
}

const FIXTURE: { cases: FixtureCase[] } = JSON.parse(
    readFileSync(FIXTURE_PATH, "utf-8"),
);

function timeContextOf(c: FixtureCase): BranchTimeContext {
    return {
        timeEnabled: c.graph.timeEnabled ?? false,
        pixelsPerHour: c.graph.pixelsPerHour ?? 200,
        layout: c.graph.layout ?? "horizontal",
    };
}

describe("computeBranchValidationErrors (shared fixture)", () => {
    // Shared behavior contract — cases live in
    // tests/fixtures/branch_role_validation.json. Adding/changing a case
    // forces both backend and frontend to update together.
    it.each(FIXTURE.cases.map((c) => [c.name, c] as const))(
        "%s",
        (_name, c) => {
            const nodes = c.graph.nodes as unknown as Node[];
            const edges = c.graph.edges as unknown as Edge[];
            const errs = computeBranchValidationErrors(
                nodes,
                edges,
                timeContextOf(c),
            );
            const actual = errs.map((e) => e.sourceNodeId).sort();
            const expected = [...c.expected.fires_on].sort();
            expect(actual).toEqual(expected);
        },
    );

    // Frontend-specific shape assertions on BranchValidationError.
    it("error shape includes source label and target labels", () => {
        const c = FIXTURE.cases.find(
            (x) => x.name === "branching with two targets in same parentId fires",
        )!;
        const errs = computeBranchValidationErrors(
            c.graph.nodes as unknown as Node[],
            c.graph.edges as unknown as Edge[],
            timeContextOf(c),
        );
        expect(errs).toHaveLength(1);
        expect(errs[0].sourceNodeId).toBe("b");
        expect(errs[0].sourceNodeLabel).toBe("B");
        expect(errs[0].targetNodeLabels.sort()).toEqual(["C", "D"]);
    });
});
