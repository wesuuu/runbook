/**
 * Drift test: T3 lane-assignment progress.
 *
 * Per the GLP rule validation tiers table, RunSetup surfaces an
 * always-visible "N of M roles assigned" indicator. The closest existing
 * surface is the Role Assignments section in
 * ``frontend/src/routes/runs/[id]/+page.svelte``, which today renders
 * the per-lane selectors and gates Start Run on
 * ``allRolesAssigned()`` but does not yet render the "N of M" pill.
 *
 * This test encodes the count-derivation predicate the eventual
 * indicator must use, mirroring the same swimlane-and-assignment shape
 * the backend ``assert_can_start`` consumes.
 */

import { describe, it, expect } from 'vitest';
import {
    glpProtocolGraphFixture,
    GLP_FIXTURE_IDS,
} from '$lib/test/fixtures/glpProtocolGraph';

interface RoleAssignment {
    lane_node_id: string;
    user_id: string | null;
}

function laneAssignmentProgress(
    graphNodes: Array<{ id: string; type: string }>,
    assignments: RoleAssignment[],
): { assigned: number; total: number; label: string } {
    const lanes = graphNodes.filter((n) => n.type === 'swimLane');
    const total = lanes.length;
    const assigned = lanes.filter((lane) =>
        assignments.some(
            (a) => a.lane_node_id === lane.id && a.user_id !== null,
        ),
    ).length;
    return { assigned, total, label: `${assigned} of ${total} roles assigned` };
}

describe('GLP drift: lane-assignment progress indicator', () => {
    const graphNodes = glpProtocolGraphFixture.nodes as Array<{
        id: string;
        type: string;
    }>;

    it('reports 0 of 2 when no lanes are assigned', () => {
        const p = laneAssignmentProgress(graphNodes, []);
        expect(p).toEqual({
            assigned: 0,
            total: 2,
            label: '0 of 2 roles assigned',
        });
    });

    it('reports 1 of 2 when one lane is assigned', () => {
        const p = laneAssignmentProgress(graphNodes, [
            { lane_node_id: GLP_FIXTURE_IDS.sdLaneId, user_id: 'u-sd' },
        ]);
        expect(p).toEqual({
            assigned: 1,
            total: 2,
            label: '1 of 2 roles assigned',
        });
    });

    it('reports 2 of 2 when every lane is assigned', () => {
        const p = laneAssignmentProgress(graphNodes, [
            { lane_node_id: GLP_FIXTURE_IDS.sdLaneId, user_id: 'u-sd' },
            { lane_node_id: GLP_FIXTURE_IDS.opLaneId, user_id: 'u-op' },
        ]);
        expect(p).toEqual({
            assigned: 2,
            total: 2,
            label: '2 of 2 roles assigned',
        });
    });

    it('treats null user_id as unassigned', () => {
        const p = laneAssignmentProgress(graphNodes, [
            { lane_node_id: GLP_FIXTURE_IDS.sdLaneId, user_id: null },
            { lane_node_id: GLP_FIXTURE_IDS.opLaneId, user_id: 'u-op' },
        ]);
        expect(p.assigned).toBe(1);
        expect(p.total).toBe(2);
    });

    it('reports 0 of 0 when the graph has no swimlanes', () => {
        const p = laneAssignmentProgress(
            [
                { id: 'u1', type: 'unitOp' },
                { id: 'u2', type: 'unitOp' },
            ],
            [],
        );
        expect(p).toEqual({
            assigned: 0,
            total: 0,
            label: '0 of 0 roles assigned',
        });
    });
});
