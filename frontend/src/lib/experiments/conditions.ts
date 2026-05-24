type RunId = string;

export type CondCell = { value: unknown; unit?: string };
export type CondRow = {
    nodeLabel: string;
    paramKey: string;
    varied: boolean;
    unitConflict?: boolean;
    perRun: Map<RunId, CondCell>;
};

function canonicalize(value: unknown): unknown {
    if (value === null || value === undefined) return null;
    if (typeof value === 'string') {
        const trimmed = value.trim();
        return trimmed === '' ? null : trimmed;
    }
    return value;
}

// Equality key must match the Python port's json.dumps(sort_keys=True). For
// JSON-serializable values JSON.stringify is sufficient, but objects must be
// sorted to match Python's sort_keys=True.
function eqKey(value: unknown): string {
    return JSON.stringify(value, (_k, v) => {
        if (v && typeof v === 'object' && !Array.isArray(v)) {
            return Object.keys(v as object).sort().reduce<Record<string, unknown>>(
                (acc, k) => { acc[k] = (v as Record<string, unknown>)[k]; return acc; },
                {},
            );
        }
        return v;
    });
}

export function computeConditions(runs: any[]): CondRow[] {
    const perKey = new Map<string, Map<RunId, CondCell>>();
    const unitsSeen = new Map<string, Set<string>>();
    const runIds: RunId[] = [];

    for (const run of runs) {
        const runId: RunId = run.id;
        runIds.push(runId);
        const nodes = run.graph?.nodes ?? [];
        for (const node of nodes) {
            if (node.type !== 'unitOp') continue;
            const label = node.data?.label;
            const params = node.data?.params ?? {};
            const schemaProps = node.data?.paramSchema?.properties ?? {};
            if (!label) continue;
            for (const [k, v] of Object.entries(params)) {
                const key = `${label}::${k}`;
                const cell: CondCell = { value: canonicalize(v) };
                const unit = schemaProps[k]?.unit;
                if (unit) {
                    cell.unit = unit;
                    let seen = unitsSeen.get(key);
                    if (!seen) { seen = new Set(); unitsSeen.set(key, seen); }
                    seen.add(unit);
                }
                let perRun = perKey.get(key);
                if (!perRun) {
                    perRun = new Map();
                    perKey.set(key, perRun);
                }
                perRun.set(runId, cell);
            }
        }
    }

    const rows: CondRow[] = [];
    for (const [key, perRun] of perKey) {
        const [nodeLabel, paramKey] = key.split('::');
        const filled = new Map<RunId, CondCell>();
        for (const rid of runIds) {
            filled.set(rid, perRun.get(rid) ?? { value: null });
        }
        const units = unitsSeen.get(key) ?? new Set<string>();
        const unitConflict = units.size > 1;
        if (units.size === 1) {
            const [onlyUnit] = units;
            for (const cell of filled.values()) {
                if (cell.value !== null && cell.unit === undefined) cell.unit = onlyUnit;
            }
        }
        const values = new Set(Array.from(filled.values(), c => eqKey(c.value)));
        rows.push({
            nodeLabel,
            paramKey,
            varied: values.size > 1 || unitConflict,
            ...(unitConflict ? { unitConflict: true } : {}),
            perRun: filled,
        });
    }
    return rows;
}
