/**
 * Drift test: T3 GLP-enabled badge.
 *
 * Per the GLP rule validation tiers table, a GLP-enabled badge must
 * render on the protocol / run header whenever
 * ``protocol.graph.glpSettings.glp_enabled === true``. This is a pure
 * derivation off graph state — no preflight, no API call.
 *
 * The badge component does not yet exist on this branch. This test
 * encodes the predicate the component must follow when introduced so
 * the rule is captured before its rendering surface ships.
 */

import { describe, it, expect } from 'vitest';
import { glpProtocolGraphFixture } from '$lib/test/fixtures/glpProtocolGraph';

interface Graph {
    glpSettings?: { glp_enabled?: boolean };
}

function shouldShowGlpEnabledBadge(graph: Graph | null | undefined): boolean {
    return graph?.glpSettings?.glp_enabled === true;
}

describe('GLP drift: GLP-enabled badge predicate', () => {
    it('renders when glpSettings.glp_enabled === true', () => {
        expect(shouldShowGlpEnabledBadge(glpProtocolGraphFixture)).toBe(true);
    });

    it('does NOT render when glpSettings.glp_enabled === false', () => {
        expect(
            shouldShowGlpEnabledBadge({ glpSettings: { glp_enabled: false } }),
        ).toBe(false);
    });

    it('does NOT render when glpSettings is absent', () => {
        expect(shouldShowGlpEnabledBadge({})).toBe(false);
    });

    it('does NOT render when graph itself is null/undefined', () => {
        expect(shouldShowGlpEnabledBadge(null)).toBe(false);
        expect(shouldShowGlpEnabledBadge(undefined)).toBe(false);
    });

    it('does NOT render for truthy non-boolean values (strict equality)', () => {
        expect(
            shouldShowGlpEnabledBadge({
                glpSettings: { glp_enabled: 'true' as unknown as boolean },
            }),
        ).toBe(false);
    });
});
