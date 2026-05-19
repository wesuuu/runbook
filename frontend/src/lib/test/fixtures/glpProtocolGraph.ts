/**
 * Shared GLP protocol graph fixture for frontend tests (F-0087 Task 41.0).
 *
 * Mirrors the backend ``glp_protocol`` conftest fixture: two swimlane
 * nodes, three unit-op nodes, and a ``glpSettings`` snapshot that parses
 * cleanly against ``GlpSettingsSchema`` in ``$lib/schemas/glpSignoff``.
 *
 * Drift tests (Task 41a) and component tests should import this fixture
 * rather than constructing graphs inline.
 */

const SD_ROLE_ID = '11111111-1111-4111-8111-111111111111';
const OP_ROLE_ID = '22222222-2222-4222-8222-222222222222';
const SD_LANE_ID = `lane-${SD_ROLE_ID}`;
const OP_LANE_ID = `lane-${OP_ROLE_ID}`;

export const glpProtocolGraphFixture = {
    layout: 'horizontal' as const,
    handleOrientation: 'horizontal' as const,
    nodes: [
        { id: 'ps', type: 'processStart', data: {} },
        {
            id: SD_LANE_ID,
            type: 'swimLane',
            position: { x: 0, y: 0 },
            data: {
                label: 'Study Director',
                roleId: SD_ROLE_ID,
                orientation: 'horizontal',
            },
            style: 'width: 800px; height: 200px;',
        },
        {
            id: OP_LANE_ID,
            type: 'swimLane',
            position: { x: 0, y: 220 },
            data: {
                label: 'Operator',
                roleId: OP_ROLE_ID,
                orientation: 'horizontal',
            },
            style: 'width: 800px; height: 200px;',
        },
        {
            id: 'u0',
            type: 'unitOp',
            parentId: SD_LANE_ID,
            position: { x: 20, y: 60 },
            data: { label: 'Review', params: {} },
        },
        {
            id: 'u1',
            type: 'unitOp',
            parentId: OP_LANE_ID,
            position: { x: 20, y: 60 },
            data: { label: 'Buffer Mix', params: {} },
        },
        {
            id: 'u2',
            type: 'unitOp',
            parentId: OP_LANE_ID,
            position: { x: 220, y: 60 },
            data: { label: 'Seeding', params: {} },
        },
    ],
    edges: [
        { id: 'e0', source: 'ps', target: 'u0' },
        { id: 'e1', source: 'u0', target: 'u1' },
        { id: 'e2', source: 'u1', target: 'u2' },
    ],
    glpSettings: {
        glp_enabled: true,
        require_study_director: true,
        require_qau: true,
        study_title: 'Test GLP Study',
        sponsor_name: 'Acme Pharma',
        operator_attestation_text: 'I performed this run accurately.',
        study_director_attestation_text:
            'I attest this study is in compliance with the protocol.',
        qau_attestation_text: 'I have audited this study for GLP compliance.',
        step_attestation_text: 'Step recorded under GLP.',
    },
};

export const GLP_FIXTURE_IDS = {
    sdRoleId: SD_ROLE_ID,
    opRoleId: OP_ROLE_ID,
    sdLaneId: SD_LANE_ID,
    opLaneId: OP_LANE_ID,
};
