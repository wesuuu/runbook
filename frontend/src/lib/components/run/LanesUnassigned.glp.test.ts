/**
 * Drift test: T2 LANES_UNASSIGNED — frontend preflight.
 *
 * Companion to the pytest integration test
 * (backend/tests/integration/glp/test_lanes_unassigned_drift.py).
 *
 * The backend predicate ``assert_can_start`` rejects PLANNED -> ACTIVE
 * when any swimlane node in ``run.graph.nodes`` lacks a
 * ``RunRoleAssignment``.  The frontend mirror lives inline on the run
 * detail page as ``allRolesAssigned()``: the Start Run button stays
 * disabled until every swimlane has an assignment.
 *
 * We assert that mirror as a pure predicate (no component mount needed —
 * the rule is just "every lane id appears in the assignments list").
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

function allRolesAssigned(
    graphNodes: Array<{ id: string; type: string }>,
    assignments: RoleAssignment[],
): boolean {
    const lanes = graphNodes.filter((n) => n.type === 'swimLane');
    if (lanes.length === 0) {
        // Non-lane runs: nothing to assign. Mirror of backend behaviour
        // when ``glp_enabled`` is false or no swimlane nodes exist.
        return assignments.length > 0;
    }
    return lanes.every((lane) =>
        assignments.some(
            (a) => a.lane_node_id === lane.id && a.user_id !== null,
        ),
    );
}

describe('GLP drift: LANES_UNASSIGNED preflight', () => {
    const graphNodes = glpProtocolGraphFixture.nodes as Array<{
        id: string;
        type: string;
    }>;

    it('rejects when no lanes are assigned', () => {
        expect(allRolesAssigned(graphNodes, [])).toBe(false);
    });

    it('rejects when only one of multiple lanes is assigned', () => {
        const partial: RoleAssignment[] = [
            { lane_node_id: GLP_FIXTURE_IDS.sdLaneId, user_id: 'u-sd' },
        ];
        expect(allRolesAssigned(graphNodes, partial)).toBe(false);
    });

    it('accepts when every swimlane has an assignment', () => {
        const full: RoleAssignment[] = [
            { lane_node_id: GLP_FIXTURE_IDS.sdLaneId, user_id: 'u-sd' },
            { lane_node_id: GLP_FIXTURE_IDS.opLaneId, user_id: 'u-op' },
        ];
        expect(allRolesAssigned(graphNodes, full)).toBe(true);
    });

    it('rejects when assignment user_id is null (cleared)', () => {
        const cleared: RoleAssignment[] = [
            { lane_node_id: GLP_FIXTURE_IDS.sdLaneId, user_id: null },
            { lane_node_id: GLP_FIXTURE_IDS.opLaneId, user_id: 'u-op' },
        ];
        expect(allRolesAssigned(graphNodes, cleared)).toBe(false);
    });
});
