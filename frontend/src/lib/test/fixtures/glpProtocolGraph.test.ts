import { describe, expect, it } from 'vitest';

import { GlpSettingsSchema } from '$lib/schemas/glpSignoff';

import { GLP_FIXTURE_IDS, glpProtocolGraphFixture } from './glpProtocolGraph';

describe('glpProtocolGraphFixture', () => {
    it('has glpSettings that parse against GlpSettingsSchema', () => {
        // GlpSettingsSchema only validates the canonical sign-off settings
        // subset; extra keys (study_title, sponsor_name, ...) are dropped
        // unless the schema is .passthrough()'d. The fixture must satisfy
        // at minimum every required key in the schema.
        const parsed = GlpSettingsSchema.parse(
            glpProtocolGraphFixture.glpSettings,
        );
        expect(parsed.require_study_director).toBe(true);
        expect(parsed.require_qau).toBe(true);
        expect(parsed.operator_attestation_text).toBeTruthy();
    });

    it('has two swimlanes and three unit-op nodes', () => {
        const swimlanes = glpProtocolGraphFixture.nodes.filter(
            (n) => n.type === 'swimLane',
        );
        const unitOps = glpProtocolGraphFixture.nodes.filter(
            (n) => n.type === 'unitOp',
        );
        expect(swimlanes).toHaveLength(2);
        expect(unitOps).toHaveLength(3);
    });

    it('exposes stable role/lane ids', () => {
        expect(GLP_FIXTURE_IDS.sdLaneId).toBe(
            `lane-${GLP_FIXTURE_IDS.sdRoleId}`,
        );
        expect(GLP_FIXTURE_IDS.opLaneId).toBe(
            `lane-${GLP_FIXTURE_IDS.opRoleId}`,
        );
    });
});
