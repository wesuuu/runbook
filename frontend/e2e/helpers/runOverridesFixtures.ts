import { type Page } from '@playwright/test';
import {
    createProtocolViaApi,
    updateProtocolGraph,
    submitForApprovalViaApi,
    approveProtocolViaApi,
    forceCleanupProtocol,
    createRoleViaApi,
} from './protocol';
import { API_BASE } from './apiBase';

const SUITE_NONCE = `${Date.now().toString(36)}-${Math.floor(Math.random() * 1e6).toString(36)}`;
export const FIXTURE_PREFIX = `F0081-E2E-${SUITE_NONCE}`;

export interface RoleSpec {
    /** Caller-supplied placeholder id; replaced with the API-issued UUID at seed time. */
    id: string;
    name: string;
    color: string;
}

export interface Fixture {
    protocolId: string;
    runIds: string[];
    /** Experiments created alongside the protocol that should be cleaned up. */
    experimentIds: string[];
    label: string;
    /** Map of caller placeholder id → real role UUID from the API. */
    roleIdMap: Record<string, string>;
}

const REGISTRY: Fixture[] = [];

export function registerFixture(f: Fixture): Fixture {
    REGISTRY.push(f);
    return f;
}

export function shouldKeepFixtures(): boolean {
    return process.env.KEEP_FIXTURES === '1';
}

export function printKeptFixtures(): void {
    if (REGISTRY.length === 0) return;
    // eslint-disable-next-line no-console
    console.log(
        `\n[KEEP_FIXTURES] keeping ${REGISTRY.length} fixture(s) (prefix "${FIXTURE_PREFIX}"):\n` +
        REGISTRY.map(
            (f) =>
                `  • ${f.label} → protocol=${f.protocolId} runs=[${f.runIds.join(', ')}]`,
        ).join('\n') +
        `\n  Filter UI by name prefix: "${FIXTURE_PREFIX}"\n`,
    );
}

async function apiToken(page: Page): Promise<string | null> {
    return page.evaluate(() => localStorage.getItem('auth_token'));
}

async function apiDelete(page: Page, path: string): Promise<void> {
    const token = await apiToken(page);
    await page.request.fetch(`${API_BASE}${path}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
    });
}

export async function cleanupAllFixtures(page: Page): Promise<void> {
    if (shouldKeepFixtures()) {
        printKeptFixtures();
        REGISTRY.length = 0;
        return;
    }
    for (const f of REGISTRY) {
        for (const runId of f.runIds) {
            await apiDelete(page, `/science/runs/${runId}`).catch(() => undefined);
        }
        for (const expId of f.experimentIds) {
            await apiDelete(page, `/science/experiments/${expId}`).catch(() => undefined);
        }
        await forceCleanupProtocol(page, f.protocolId).catch(() => undefined);
    }
    REGISTRY.length = 0;
}

/** Create an experiment via API and register it for cleanup against `fixture`. */
export async function seedExperimentForFixture(
    page: Page,
    fixture: Fixture,
    projectId: string,
    name: string,
): Promise<string> {
    const token = await apiToken(page);
    const resp = await page.request.fetch(`${API_BASE}/science/experiments`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        data: { name, project_id: projectId },
    });
    if (!resp.ok()) {
        throw new Error(`POST experiment failed: ${resp.status()} ${await resp.text()}`);
    }
    const body = (await resp.json()) as { id: string };
    fixture.experimentIds.push(body.id);
    return body.id;
}

// ────────────────────────────────────────────────────────────────────────
// Graph builders
// ────────────────────────────────────────────────────────────────────────

interface GraphBuildOptions {
    /** Resolved roles (with real UUIDs) to inject as swimlane nodes. */
    roles?: RoleSpec[];
    /** Linear/fork: number of UOs to emit. Ignored when `unitOpsByRole` is set. */
    unitOpCount?: number;
    /** Per-role UO count keyed by role.id. */
    unitOpsByRole?: Record<string, number>;
    /** Defaults merged into every UO's `data`. */
    uoDefaults?: Record<string, unknown>;
    topology?: 'linear' | 'fork' | 'empty';
}

interface UnitOpData extends Record<string, unknown> {
    label: string;
    category: string;
    duration_min: number;
    params: Record<string, unknown>;
    paramSchema: { type: string; properties: Record<string, unknown> };
    description: string;
    equipment: Array<Record<string, unknown>>;
}

interface GraphNode {
    id: string;
    type: string;
    parentId?: string;
    position: { x: number; y: number };
    data: Record<string, unknown>;
}

export interface BuiltGraph {
    nodes: GraphNode[];
    edges: Array<{ id: string; source: string; target: string }>;
    layout: 'horizontal';
    handleOrientation: 'horizontal';
}

function baseUnitOpData(idx: number, defaults: Record<string, unknown> = {}): UnitOpData {
    return {
        label: `UO-${idx + 1}`,
        category: 'Reaction',
        duration_min: 10,
        params: { temperature: 25 + idx },
        paramSchema: {
            type: 'object',
            properties: {
                temperature: { type: 'number', title: 'Temperature' },
            },
        },
        description: 'Hold at {{temperature}}°C',
        equipment: [],
        ...defaults,
    };
}

export function buildGraph(opts: GraphBuildOptions): BuiltGraph {
    const nodes: GraphNode[] = [];
    const edges: BuiltGraph['edges'] = [];

    for (const r of opts.roles ?? []) {
        nodes.push({
            id: `lane-${r.id}`,
            type: 'swimLane',
            position: { x: 0, y: 0 },
            data: { label: r.name, roleId: r.id, color: r.color },
        });
    }

    if (opts.topology === 'empty') {
        return { nodes, edges, layout: 'horizontal', handleOrientation: 'horizontal' };
    }

    if (opts.unitOpsByRole) {
        let i = 0;
        for (const [roleId, count] of Object.entries(opts.unitOpsByRole)) {
            for (let k = 0; k < count; k++, i++) {
                nodes.push({
                    id: `uo-${i + 1}`,
                    type: 'unitOp',
                    parentId: `lane-${roleId}`,
                    position: { x: 100 + k * 200, y: 100 },
                    data: baseUnitOpData(i, opts.uoDefaults),
                });
            }
        }
        return { nodes, edges, layout: 'horizontal', handleOrientation: 'horizontal' };
    }

    const count = opts.unitOpCount ?? 1;
    const singleLane =
        opts.roles && opts.roles.length === 1 ? `lane-${opts.roles[0].id}` : undefined;
    for (let i = 0; i < count; i++) {
        nodes.push({
            id: `uo-${i + 1}`,
            type: 'unitOp',
            ...(singleLane ? { parentId: singleLane } : {}),
            position: { x: 100 + i * 200, y: 100 },
            data: baseUnitOpData(i, opts.uoDefaults),
        });
    }

    if (opts.topology === 'fork' && count >= 3) {
        edges.push({ id: 'e1', source: 'uo-1', target: 'uo-2' });
        edges.push({ id: 'e2', source: 'uo-1', target: 'uo-3' });
    } else {
        for (let i = 0; i < count - 1; i++) {
            edges.push({
                id: `e${i}`,
                source: `uo-${i + 1}`,
                target: `uo-${i + 2}`,
            });
        }
    }

    return { nodes, edges, layout: 'horizontal', handleOrientation: 'horizontal' };
}

// ────────────────────────────────────────────────────────────────────────
// Seeding
// ────────────────────────────────────────────────────────────────────────

export interface SeedOptions {
    /** Roles to create on the protocol AND seed into the graph. The placeholder
     *  ids in `graphRoles` are swapped for real UUIDs before the graph is PUT. */
    roles?: RoleSpec[];
    /** Build a graph using `buildGraph(...)` AFTER role UUIDs are resolved.
     *  Receives a map of placeholder id → real UUID. */
    buildWithResolvedRoles?: (resolved: RoleSpec[]) => BuiltGraph;
    /** Static graph (used when no roles are involved). Ignored when
     *  `buildWithResolvedRoles` is set. */
    graph?: BuiltGraph;
    /** If true, leave the protocol in DRAFT (skip submit + approve). */
    skipPublish?: boolean;
}

export async function seedScenarioProtocol(
    page: Page,
    projectId: string,
    label: string,
    opts: SeedOptions,
): Promise<Fixture> {
    const name = `${FIXTURE_PREFIX} ${label}`;
    const proto = await createProtocolViaApi(page, projectId, name);
    const protocolId = proto.id as string;

    const roleIdMap: Record<string, string> = {};
    const resolved: RoleSpec[] = [];
    for (const r of opts.roles ?? []) {
        const created = await createRoleViaApi(page, protocolId, r.name, r.color);
        const realId = created.id as string;
        roleIdMap[r.id] = realId;
        resolved.push({ id: realId, name: r.name, color: r.color });
    }

    const graph = opts.buildWithResolvedRoles
        ? opts.buildWithResolvedRoles(resolved)
        : opts.graph ?? { nodes: [], edges: [], layout: 'horizontal', handleOrientation: 'horizontal' };

    await updateProtocolGraph(page, protocolId, graph as unknown as Record<string, unknown>);

    if (!opts.skipPublish) {
        await submitForApprovalViaApi(page, protocolId);
        await approveProtocolViaApi(page, protocolId, 'E2E auto-approve');
    }

    return registerFixture({ protocolId, runIds: [], experimentIds: [], label, roleIdMap });
}
