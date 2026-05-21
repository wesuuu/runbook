export type SortDir = "asc" | "desc";

export function shortId(idStr: string): string {
    return idStr.slice(0, 8).toUpperCase();
}

export function formatDate(dateStr: string): string {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    const diffHr = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHr / 24);

    if (diffMin < 1) return "Just now";
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffHr < 24) return `${diffHr}h ago`;
    if (diffDay === 1) return "Yesterday";
    if (diffDay < 7) return `${diffDay}d ago`;
    const opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
    if (date.getFullYear() < now.getFullYear()) {
        opts.year = "numeric";
    }
    return date.toLocaleDateString("en-US", opts);
}

export function statusClasses(status: string): string {
    switch (status?.toUpperCase()) {
        // `ACTIVE` is the backend RunStatus value; `RUNNING`/`IN_PROGRESS`
        // are legacy aliases. All three share one style (#20).
        case "ACTIVE":
        case "RUNNING":
        case "IN_PROGRESS":
            return "bg-emerald-50 text-emerald-600 border border-emerald-200";
        case "COMPLETED":
        case "DONE":
            return "bg-emerald-600 text-white";
        case "NEEDS_REVIEW":
        case "REVIEW":
            return "bg-orange-500 text-white";
        case "EDITED":
            return "bg-amber-50 text-amber-600 border border-amber-200";
        case "DRAFT":
        case "PLANNED":
        default:
            return "bg-slate-500 text-white";
    }
}

export function statusLabel(status: string): string {
    switch (status?.toUpperCase()) {
        // The backend RunStatus enum uses `ACTIVE`; the run detail page shows
        // it as "Running". Map it here too so the runs table and History tab
        // stop showing the raw "ACTIVE" enum value (#20).
        case "ACTIVE":
        case "RUNNING":
        case "IN_PROGRESS":
            return "Running";
        case "COMPLETED":
        case "DONE":
            return "Completed";
        case "NEEDS_REVIEW":
        case "REVIEW":
            return "Needs Review";
        case "EDITED":
            return "Edited";
        case "ARCHIVED":
            return "Archived";
        case "DRAFT":
            return "Draft";
        case "PLANNED":
            return "Planned";
        default:
            return status || "Draft";
    }
}

/**
 * Number of protocols that are actually published (status APPROVED).
 *
 * The project header labelled the *total* protocol count as "Published", so
 * a DRAFT protocol — which the row badge correctly shows as "Draft" — was
 * still tallied under the "N Published Protocols" header (#10).
 */
export function publishedProtocolCount(
    protocols: Array<{ status?: string | null }>,
): number {
    return protocols.filter((p) => p.status?.toUpperCase() === "APPROVED")
        .length;
}

export function protocolStatusClasses(status: string): string {
    switch (status?.toUpperCase()) {
        case "APPROVED":
            return "bg-emerald-50 text-emerald-600 border border-emerald-200";
        case "PENDING_APPROVAL":
            return "bg-amber-50 text-amber-600 border border-amber-200";
        case "ARCHIVED":
            return "bg-slate-100 text-slate-500 border border-slate-200";
        case "DRAFT":
        default:
            return "bg-slate-100 text-slate-500 border border-slate-200";
    }
}

export function protocolStatusLabel(status: string): string {
    switch (status?.toUpperCase()) {
        case "APPROVED":
            return "Published";
        case "PENDING_APPROVAL":
            return "Pending Approval";
        case "ARCHIVED":
            return "Archived";
        case "DRAFT":
        default:
            return "Draft";
    }
}

export function actionVerb(action: string): string {
    switch (action) {
        case "CREATE":
            return "created";
        case "UPDATE":
            return "updated";
        case "DELETE":
            return "deleted";
        case "ARCHIVE":
            return "archived";
        case "STEP_EDIT":
            return "edited";
        case "STEP_COMPLETE":
            return "completed step in";
        case "STEP_UNCOMPLETE":
            return "uncompleted step in";
        default:
            return action.toLowerCase();
    }
}

export function actionColor(action: string): string {
    switch (action) {
        case "CREATE":
            return "bg-emerald-500";
        case "UPDATE":
            return "bg-blue-500";
        case "DELETE":
            return "bg-red-500";
        case "STEP_EDIT":
            return "bg-amber-500";
        default:
            return "bg-slate-400";
    }
}

export function stepEditSummary(changes: Record<string, any>): string | null {
    if (!changes?.step_name || !changes?.field_label) return null;
    const old_val = changes.old_value ?? "empty";
    const new_val = changes.new_value ?? "empty";
    return `${changes.step_name}: ${changes.field_label} from ${old_val} to ${new_val}`;
}

export function experimentStatusClasses(status: string): string {
    switch (status?.toUpperCase()) {
        case "ACTIVE":
            return "bg-emerald-50 text-emerald-600 border border-emerald-200";
        case "COMPLETED":
            return "bg-emerald-600 text-white";
        case "ARCHIVED":
            return "bg-slate-100 text-slate-400 border border-slate-200";
        case "DRAFT":
        default:
            return "bg-slate-500 text-white";
    }
}

export function experimentStatusLabel(status: string): string {
    switch (status?.toUpperCase()) {
        case "ACTIVE":
            return "Active";
        case "COMPLETED":
            return "Completed";
        case "ARCHIVED":
            return "Archived";
        case "DRAFT":
        default:
            return "Draft";
    }
}

export function entityBadgeClasses(entityType: string): string {
    switch (entityType) {
        case "Project":
            return "bg-purple-50 text-purple-600 border-purple-200";
        case "Protocol":
            return "bg-sky-50 text-sky-600 border-sky-200";
        case "Run":
            return "bg-amber-50 text-amber-600 border-amber-200";
        case "Experiment":
            return "bg-violet-50 text-violet-600 border-violet-200";
        default:
            return "bg-slate-50 text-slate-600 border-slate-200";
    }
}

export function changedKeys(changes: Record<string, any>): string[] {
    return Object.keys(changes).filter(
        (k) =>
            k !== "graph" &&
            k !== "execution_data" &&
            k !== "version_number" &&
            k !== "reverted_to_version",
    );
}

export function versionSummary(item: any): string | null {
    if (!item.changes) return null;
    const vn = item.changes.version_number;
    const revertedFrom = item.changes.reverted_to_version;
    if (revertedFrom != null && vn != null) {
        return `Reverted to v${revertedFrom} → saved as v${vn}`;
    }
    if (vn != null) {
        return `v${vn}`;
    }
    return null;
}

export function compareValues(a: any, b: any, key: string, dir: SortDir): number {
    let va = a[key];
    let vb = b[key];
    if (key === "updated_at") {
        va = va || a.created_at;
        vb = vb || b.created_at;
    }
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === "string") va = va.toLowerCase();
    if (typeof vb === "string") vb = vb.toLowerCase();
    const cmp = va < vb ? -1 : va > vb ? 1 : 0;
    return dir === "asc" ? cmp : -cmp;
}

export function sortIndicator(activeKey: string, dir: SortDir, key: string): string {
    if (activeKey !== key) return "";
    return dir === "asc" ? " \u25B2" : " \u25BC";
}
