<script lang="ts">
    import { onMount } from "svelte";
    import { page } from "$app/stores";
    import { goto } from "$app/navigation";
    import { api } from "$lib/api";
    import { getCurrentOrg } from "$lib/auth.svelte";
    import Modal from "$lib/components/Modal.svelte";
    import { Button } from "$lib/components/ui/button";
    import { Input } from "$lib/components/ui/input";
    import { Label } from "$lib/components/ui/label";
    import { Textarea } from "$lib/components/ui/textarea";
    import {
        Card,
        CardContent,
        CardDescription,
        CardFooter,
        CardHeader,
        CardTitle,
    } from "$lib/components/ui/card";

    const id = $derived($page.params.id);

    let project = $state<any>(null);
    let protocols = $state<any[]>([]);
    let runs = $state<any[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);

    // -- Tab State (derived from URL ?tab= param) --
    type TabName = "protocols" | "runs" | "activity" | "settings";
    const validTabs: TabName[] = ["protocols", "runs", "activity", "settings"];

    const activeTab: TabName = $derived.by(() => {
        const t = $page.url.searchParams.get("tab");
        if (t && validTabs.includes(t as TabName)) return t as TabName;
        return "protocols";
    });

    function setTab(tab: TabName) {
        if (tab === activeTab) return;
        goto(`?tab=${tab}`, { replaceState: false, keepFocus: true, noScroll: true });
    }

    // Lazy-load data when tab changes (works for both clicks and back/forward)
    $effect(() => {
        if (activeTab === "activity" && !activityLoaded) loadActivity(0);
        if (activeTab === "settings") loadSettings();
    });

    // -- Multi-run export --
    let selectedRunIds = $state<Set<string>>(new Set());
    const exportableRuns = $derived(
        runs.filter((r: any) => r.status === 'COMPLETED' || r.status === 'EDITED')
    );

    function toggleRunSelection(runId: string) {
        const next = new Set(selectedRunIds);
        if (next.has(runId)) {
            next.delete(runId);
        } else {
            next.add(runId);
        }
        selectedRunIds = next;
    }

    function toggleAllExportable() {
        const exportableIds = exportableRuns.map((r: any) => r.id);
        const allSelected = exportableIds.every((id: string) => selectedRunIds.has(id));
        if (allSelected) {
            selectedRunIds = new Set();
        } else {
            selectedRunIds = new Set(exportableIds);
        }
    }

    // -- Search --
    let searchQuery = $state("");

    // -- Sorting --
    type SortDir = "asc" | "desc";
    let protoSortKey = $state<string>("updated_at");
    let protoSortDir = $state<SortDir>("desc");
    let runSortKey = $state<string>("updated_at");
    let runSortDir = $state<SortDir>("desc");

    function toggleSort(
        tab: "protocols" | "runs",
        key: string,
    ) {
        if (tab === "protocols") {
            if (protoSortKey === key) {
                protoSortDir = protoSortDir === "asc" ? "desc" : "asc";
            } else {
                protoSortKey = key;
                protoSortDir = key === "name" ? "asc" : "desc";
            }
            protoPage = 1;
        } else {
            if (runSortKey === key) {
                runSortDir = runSortDir === "asc" ? "desc" : "asc";
            } else {
                runSortKey = key;
                runSortDir = key === "name" ? "asc" : "desc";
            }
            runPage = 1;
        }
    }

    function sortIndicator(tab: "protocols" | "runs", key: string): string {
        const activeKey = tab === "protocols" ? protoSortKey : runSortKey;
        const dir = tab === "protocols" ? protoSortDir : runSortDir;
        if (activeKey !== key) return "";
        return dir === "asc" ? " \u25B2" : " \u25BC";
    }

    function compareValues(a: any, b: any, key: string, dir: SortDir): number {
        let va = a[key];
        let vb = b[key];
        // Fallback for date fields
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

    // -- Pagination --
    let protoPageSize = $state(25);
    let protoPage = $state(1);
    let runPageSize = $state(25);
    let runPage = $state(1);

    // -- Run Modal --
    let showRunModal = $state(false);
    let newRunName = $state("");
    let selectedProtocolId = $state<string | null>(null);

    // -- Activity State --
    let activityItems = $state<any[]>([]);
    let activityTotal = $state(0);
    let activityOffset = $state(0);
    let activityLoading = $state(false);
    let activityLoaded = $state(false);
    const activityLimit = 50;

    // -- Activity Filters --
    let activityEntityFilter = $state<string[]>([]);  // empty = all
    let activityActionFilter = $state<string[]>([]);  // empty = all
    let activitySearch = $state("");
    let activitySearchDebounce: ReturnType<typeof setTimeout> | null = null;

    const allEntityTypes = ["Project", "Protocol", "Run"];
    const allActionTypes = [
        { value: "CREATE", label: "Created" },
        { value: "UPDATE", label: "Updated" },
        { value: "DELETE", label: "Deleted" },
        { value: "STEP_COMPLETE", label: "Step Complete" },
        { value: "STEP_UNCOMPLETE", label: "Step Uncomplete" },
        { value: "STEP_EDIT", label: "Step Edit" },
    ];

    function toggleEntityFilter(type: string) {
        if (activityEntityFilter.includes(type)) {
            activityEntityFilter = activityEntityFilter.filter((t) => t !== type);
        } else {
            activityEntityFilter = [...activityEntityFilter, type];
        }
        activityLoaded = false;
        loadActivity(0);
    }

    function toggleActionFilter(act: string) {
        if (activityActionFilter.includes(act)) {
            activityActionFilter = activityActionFilter.filter((a) => a !== act);
        } else {
            activityActionFilter = [...activityActionFilter, act];
        }
        activityLoaded = false;
        loadActivity(0);
    }

    function clearActivityFilters() {
        activityEntityFilter = [];
        activityActionFilter = [];
        activitySearch = "";
        activityLoaded = false;
        loadActivity(0);
    }

    const hasActiveFilters = $derived(
        activityEntityFilter.length > 0 ||
        activityActionFilter.length > 0 ||
        activitySearch.trim().length > 0,
    );

    // -- Settings State --
    let requireApproval = $state(false);
    let approvers = $state<any[]>([]);
    let orgMembers = $state<any[]>([]);
    let settingsLoaded = $state(false);
    let settingsSaving = $state(false);
    let settingsMessage = $state<string | null>(null);
    let newApproverUserId = $state<string>("");

    // -- Form State for "New Project" mode --
    let form = $state({ name: "", description: "", organization_id: "" });
    let organizations = $state<any[]>([]);

    // -- Derived --
    const shortProjectId = $derived(
        project?.id ? "PRJ-" + project.id.slice(0, 6).toUpperCase() : "",
    );

    const filteredProtocols = $derived(() => {
        let list = protocols;
        if (searchQuery.trim()) {
            const q = searchQuery.toLowerCase();
            list = list.filter(
                (p) =>
                    p.name.toLowerCase().includes(q) ||
                    (p.description && p.description.toLowerCase().includes(q)),
            );
        }
        list = [...list].sort((a, b) => compareValues(a, b, protoSortKey, protoSortDir));
        return list;
    });

    const protoTotalFiltered = $derived(filteredProtocols().length);
    const protoTotalPages = $derived(Math.max(1, Math.ceil(protoTotalFiltered / protoPageSize)));
    const paginatedProtocols = $derived(() => {
        const all = filteredProtocols();
        const start = (protoPage - 1) * protoPageSize;
        return all.slice(start, start + protoPageSize);
    });

    const filteredRuns = $derived(() => {
        let list = runs;
        if (searchQuery.trim()) {
            const q = searchQuery.toLowerCase();
            list = list.filter(
                (r) =>
                    r.name.toLowerCase().includes(q) ||
                    (r.status && r.status.toLowerCase().includes(q)),
            );
        }
        list = [...list].sort((a, b) => compareValues(a, b, runSortKey, runSortDir));
        return list;
    });

    const runTotalFiltered = $derived(filteredRuns().length);
    const runTotalPages = $derived(Math.max(1, Math.ceil(runTotalFiltered / runPageSize)));
    const paginatedRuns = $derived(() => {
        const all = filteredRuns();
        const start = (runPage - 1) * runPageSize;
        return all.slice(start, start + runPageSize);
    });

    // Reset to page 1 when search query changes
    $effect(() => {
        searchQuery;
        protoPage = 1;
        runPage = 1;
    });

    const showProtocolStatus = $derived(true);

    function shortId(idStr: string): string {
        return idStr.slice(0, 8).toUpperCase();
    }

    function formatDate(dateStr: string): string {
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
        return date.toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
        });
    }

    function statusClasses(status: string): string {
        switch (status?.toUpperCase()) {
            case "RUNNING":
            case "IN_PROGRESS":
                return "bg-emerald-50 text-emerald-600 border border-emerald-200";
            case "COMPLETED":
            case "DONE":
                return "bg-emerald-600 text-white";
            case "NEEDS_REVIEW":
            case "REVIEW":
                return "bg-orange-500 text-white";
            case "DRAFT":
            case "PLANNED":
            default:
                return "bg-slate-500 text-white";
        }
    }

    function statusLabel(status: string): string {
        switch (status?.toUpperCase()) {
            case "RUNNING":
            case "IN_PROGRESS":
                return "Running";
            case "COMPLETED":
            case "DONE":
                return "Completed";
            case "NEEDS_REVIEW":
            case "REVIEW":
                return "Needs Review";
            case "DRAFT":
                return "Draft";
            case "PLANNED":
                return "Planned";
            default:
                return status || "Draft";
        }
    }

    function actionVerb(action: string): string {
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

    function actionColor(action: string): string {
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

    function stepEditSummary(changes: Record<string, any>): string | null {
        if (!changes?.step_name || !changes?.field_label) return null;
        const old_val = changes.old_value ?? "empty";
        const new_val = changes.new_value ?? "empty";
        return `${changes.step_name}: ${changes.field_label} from ${old_val} to ${new_val}`;
    }

    function entityBadgeClasses(entityType: string): string {
        switch (entityType) {
            case "Project":
                return "bg-purple-50 text-purple-600 border-purple-200";
            case "Protocol":
                return "bg-sky-50 text-sky-600 border-sky-200";
            case "Run":
                return "bg-amber-50 text-amber-600 border-amber-200";
            default:
                return "bg-slate-50 text-slate-600 border-slate-200";
        }
    }

    function changedKeys(changes: Record<string, any>): string[] {
        return Object.keys(changes).filter(
            (k) =>
                k !== "graph" &&
                k !== "execution_data" &&
                k !== "version_number" &&
                k !== "reverted_to_version",
        );
    }

    function versionSummary(item: any): string | null {
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

    async function loadActivity(offset: number = 0) {
        activityLoading = true;
        try {
            const params = new URLSearchParams();
            params.set("offset", String(offset));
            params.set("limit", String(activityLimit));
            if (activityEntityFilter.length > 0) {
                params.set("entity_type", activityEntityFilter.join(","));
            }
            if (activityActionFilter.length > 0) {
                params.set("action", activityActionFilter.join(","));
            }
            if (activitySearch.trim()) {
                params.set("search", activitySearch.trim());
            }
            const data: any = await api.get(
                `/projects/${id}/activity?${params.toString()}`,
            );
            activityItems = data.items;
            activityTotal = data.total;
            activityOffset = data.offset;
            activityLoaded = true;
        } catch (e: any) {
            console.error("Failed to load activity:", e);
        } finally {
            activityLoading = false;
        }
    }

    async function loadSettings() {
        if (settingsLoaded || !project) return;
        try {
            requireApproval =
                project.settings?.require_protocol_approval || false;

            approvers = await api.get(`/projects/${id}/approvers`);

            // Load org members for the approver dropdown
            const members = await api.get(`/science/projects/${id}/members`);
            orgMembers = members as any[];

            settingsLoaded = true;
        } catch (e: any) {
            console.error("Failed to load settings:", e);
        }
    }

    async function saveSettings() {
        if (!project) return;
        settingsSaving = true;
        settingsMessage = null;
        try {
            const updated: any = await api.put(`/projects/${id}`, {
                settings: {
                    ...project.settings,
                    require_protocol_approval: requireApproval,
                },
            });
            project = updated;
            settingsMessage = "Settings saved";
            setTimeout(() => (settingsMessage = null), 2000);
        } catch (e: any) {
            settingsMessage = `Failed: ${e.message}`;
        } finally {
            settingsSaving = false;
        }
    }

    async function addApprover() {
        if (!newApproverUserId) return;
        try {
            const entry: any = await api.post(`/projects/${id}/approvers`, {
                principal_type: "USER",
                principal_id: newApproverUserId,
            });
            approvers = [...approvers, entry];
            newApproverUserId = "";
        } catch (e: any) {
            settingsMessage = `Failed: ${e.message}`;
            setTimeout(() => (settingsMessage = null), 3000);
        }
    }

    async function removeApprover(permId: string) {
        try {
            await api.delete(`/projects/${id}/approvers/${permId}`);
            approvers = approvers.filter((a: any) => a.id !== permId);
        } catch (e: any) {
            console.error("Failed to remove approver:", e);
        }
    }

    function protocolStatusClasses(status: string): string {
        switch (status?.toUpperCase()) {
            case "APPROVED":
                return "bg-emerald-50 text-emerald-600 border border-emerald-200";
            case "PENDING_APPROVAL":
                return "bg-amber-50 text-amber-600 border border-amber-200";
            case "DRAFT":
            default:
                return "bg-slate-100 text-slate-500 border border-slate-200";
        }
    }

    function protocolStatusLabel(status: string): string {
        switch (status?.toUpperCase()) {
            case "APPROVED":
                return "Published";
            case "PENDING_APPROVAL":
                return "Pending Approval";
            case "DRAFT":
            default:
                return "Draft";
        }
    }

    onMount(() => {
        if (id === "new") {
            loadCreateData();
        } else {
            loadData();
        }
    });

    async function loadData() {
        loading = true;
        try {
            if (id === "new") return;

            const [p, protos, exps] = await Promise.all([
                api.get(`/projects/${id}`),
                api.get(`/science/projects/${id}/protocols`),
                api.get(`/science/projects/${id}/runs`),
            ]);

            project = p;
            protocols = protos as any[];
            runs = exps as any[];
        } catch (e: any) {
            error = e.message;
        } finally {
            loading = false;
        }
    }

    async function createProtocol() {
        try {
            const existingNames = protocols.map((p: any) => p.name);
            let name = "Untitled Protocol";
            if (existingNames.includes(name)) {
                let i = 2;
                while (existingNames.includes(`Untitled Protocol ${i}`)) {
                    i++;
                }
                name = `Untitled Protocol ${i}`;
            }

            const newProto: any = await api.post("/science/protocols", {
                name,
                project_id: project.id,
                description: "",
            });
            goto(`/protocols/${newProto.id}`);
        } catch (e: any) {
            console.error(e);
        }
    }

    async function createRun() {
        if (!newRunName || !selectedProtocolId) return;

        try {
            const payload: any = {
                name: newRunName,
                project_id: project.id,
                protocol_id: selectedProtocolId,
            };
            const newRun: any = await api.post("/science/runs", payload);
            showRunModal = false;
            newRunName = "";
            selectedProtocolId = null;
            goto(`/runs/${newRun.id}`);
        } catch (e: any) {
            console.error(e);
        }
    }

    async function loadCreateData() {
        const org = getCurrentOrg();
        organizations = await api.get("/iam/organizations");
        if (org) {
            form.organization_id = org.id;
        } else if (organizations.length > 0) {
            form.organization_id = organizations[0].id;
        }
        loading = false;
    }

    async function saveNewProject() {
        try {
            await api.post("/projects", form);
            goto("/projects");
        } catch (e: any) {
            console.error(e);
        }
    }
</script>

{#if id === "new"}
    <!-- CREATE MODE -->
    <div class="max-w-4xl mx-auto py-8 px-4">
        <div class="max-w-xl mx-auto">
            <h1 class="text-3xl font-bold text-slate-900 mb-6">New Project</h1>
            <Card>
                <CardHeader>
                    <CardTitle>Project Details</CardTitle>
                    <CardDescription
                        >Create a new project to organize your work.</CardDescription
                    >
                </CardHeader>
                <CardContent class="space-y-4">
                    <div class="space-y-2">
                        <Label for="name">Name</Label>
                        <Input
                            id="name"
                            bind:value={form.name}
                            placeholder="My Project"
                        />
                    </div>
                    <div class="space-y-2">
                        <Label for="desc">Description</Label>
                        <Textarea
                            id="desc"
                            bind:value={form.description}
                            placeholder="Describe the project..."
                        />
                    </div>
                    <div class="space-y-2">
                        <Label for="org">Organization</Label>
                        <select
                            id="org"
                            bind:value={form.organization_id}
                            class="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {#each organizations as org}
                                <option value={org.id}>{org.name}</option>
                            {/each}
                        </select>
                    </div>
                </CardContent>
                <CardFooter>
                    <Button onclick={saveNewProject} class="w-full"
                        >Create Project</Button
                    >
                </CardFooter>
            </Card>
        </div>
    </div>
{:else if loading}
    <div
        class="flex items-center justify-center min-h-[calc(100vh-57px)] bg-gray-100 text-sm text-slate-400"
    >
        Loading project...
    </div>
{:else if error}
    <div
        class="max-w-xl mx-auto mt-8 p-4 bg-red-50 text-red-600 rounded-lg text-sm"
    >
        Error: {error}
    </div>
{:else if project}
    <!-- DASHBOARD MODE -->
    <div
        class="min-h-[calc(100vh-57px)] w-full mx-auto bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden"
    >
        <!-- Header -->
        <div class="flex justify-between items-start pt-7 px-8">
            <div class="flex-1 min-w-0">
                <!-- Breadcrumb -->
                <nav class="flex items-center gap-2 mb-2.5 text-[13px]">
                    <a
                        href="/projects"
                        class="text-teal-600 font-medium hover:underline"
                        >Projects</a
                    >
                    <span class="text-slate-400">&rsaquo;</span>
                    <span class="text-slate-600 font-mono font-medium"
                        >{shortProjectId}</span
                    >
                </nav>

                <!-- Title + Badge -->
                <div class="flex items-center gap-3.5 mb-1.5">
                    <h1
                        class="text-[26px] font-bold text-slate-900 leading-tight"
                    >
                        {project.name}
                    </h1>
                    <span
                        class="text-xs font-semibold px-3 py-0.5 rounded-full bg-emerald-50 text-emerald-600 border border-emerald-200 whitespace-nowrap"
                        >Active</span
                    >
                </div>

                <!-- Description -->
                {#if project.description}
                    <p class="text-sm text-slate-500 mb-3 leading-relaxed">
                        {project.description}
                    </p>
                {/if}

                <!-- Stats -->
                <div class="flex items-center gap-3 pb-5">
                    <div
                        class="flex items-center gap-1.5 text-[13px] text-slate-500 font-medium"
                    >
                        <svg
                            class="w-4 h-4 text-slate-400"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="1.5"
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            ><path
                                d="M9.75 3.104v5.714a2.25 2.25 0 0 1-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 0 1 4.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0 1 12 15a9.065 9.065 0 0 0-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0 1 12 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5"
                            /></svg
                        >
                        <span
                            >{runs.length} Active Run{runs.length !== 1
                                ? "s"
                                : ""}</span
                        >
                    </div>
                    <span class="w-[3px] h-[3px] rounded-full bg-slate-300"
                    ></span>
                    <div
                        class="flex items-center gap-1.5 text-[13px] text-slate-500 font-medium"
                    >
                        <svg
                            class="w-4 h-4 text-slate-400"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="1.5"
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            ><path
                                d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
                            /></svg
                        >
                        <span
                            >{protocols.length} Published Protocol{protocols.length !==
                            1
                                ? "s"
                                : ""}</span
                        >
                    </div>
                </div>
            </div>

            <!-- Action buttons -->
            <div class="shrink-0 flex gap-2.5 items-start pt-6">
                {#if activeTab === "runs"}
                    <button
                        class="px-4.5 py-2 bg-slate-800 text-white rounded-lg text-[13px] font-semibold cursor-pointer whitespace-nowrap transition-colors hover:bg-slate-900"
                        onclick={() => (showRunModal = true)}
                    >
                        + New Run
                    </button>
                {:else if activeTab === "protocols"}
                    <button
                        class="px-4.5 py-2 bg-slate-800 text-white rounded-lg text-[13px] font-semibold cursor-pointer whitespace-nowrap transition-colors hover:bg-slate-900"
                        onclick={createProtocol}
                    >
                        + New Protocol
                    </button>
                {/if}
            </div>
        </div>

        <!-- Tab Navigation -->
        <nav class="flex px-8 border-b border-gray-200">
            <button
                class="px-5 py-3 text-sm font-medium text-slate-500 bg-transparent border-b-2 border-transparent cursor-pointer transition-all -mb-px hover:text-slate-800 {activeTab ===
                'protocols'
                    ? '!text-slate-900 !font-semibold !border-slate-900'
                    : ''}"
                onclick={() => {
                    setTab("protocols");
                    searchQuery = "";
                }}
            >
                Protocols
            </button>
            <button
                class="px-5 py-3 text-sm font-medium text-slate-500 bg-transparent border-b-2 border-transparent cursor-pointer transition-all -mb-px hover:text-slate-800 {activeTab ===
                'runs'
                    ? '!text-slate-900 !font-semibold !border-slate-900'
                    : ''}"
                onclick={() => {
                    setTab("runs");
                    searchQuery = "";
                }}
            >
                Runs
            </button>

            <button
                class="px-5 py-3 text-sm font-medium text-slate-500 bg-transparent border-b-2 border-transparent cursor-pointer transition-all -mb-px hover:text-slate-800 {activeTab ===
                'activity'
                    ? '!text-slate-900 !font-semibold !border-slate-900'
                    : ''}"
                onclick={() => {
                    setTab("activity");
                    searchQuery = "";
                }}
            >
                Activity
            </button>
            <button
                class="px-5 py-3 text-sm font-medium text-slate-500 bg-transparent border-b-2 border-transparent cursor-pointer transition-all -mb-px hover:text-slate-800 {activeTab ===
                'settings'
                    ? '!text-slate-900 !font-semibold !border-slate-900'
                    : ''}"
                onclick={() => {
                    setTab("settings");
                    searchQuery = "";
                }}
            >
                Settings
            </button>
        </nav>

        <!-- Tab Content -->
        <div class="min-h-[300px]">
            {#if activeTab === "runs"}
                <!-- Toolbar -->
                <div class="flex justify-between items-center px-8 py-4">
                    <div class="relative w-60">
                        <svg
                            class="absolute left-2.5 top-1/2 -translate-y-1/2 w-[15px] h-[15px] text-slate-400 pointer-events-none"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="2"
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            ><circle cx="11" cy="11" r="8" /><path
                                d="m21 21-4.3-4.3"
                            /></svg
                        >
                        <input
                            type="text"
                            bind:value={searchQuery}
                            placeholder="Filter runs..."
                            class="w-full py-1.5 pl-8 pr-2.5 border border-slate-200 rounded-lg text-[13px] text-slate-800 bg-white placeholder:text-slate-400 focus:outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-400/15"
                        />
                    </div>
                    <div class="flex items-center gap-4">
                        {#if selectedRunIds.size > 0}
                            <button
                                class="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                                onclick={() => goto(`/export?runs=${[...selectedRunIds].join(',')}`)}
                            >
                                <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
                                </svg>
                                Export {selectedRunIds.size} Run{selectedRunIds.size !== 1 ? 's' : ''}
                            </button>
                        {/if}
                        <span class="text-[13px] text-slate-400 font-medium">
                            {filteredRuns().length} of {runs.length} run{runs.length !==
                            1
                                ? "s"
                                : ""}
                        </span>
                    </div>
                </div>

                {#if filteredRuns().length === 0}
                    <div
                        class="flex flex-col items-center justify-center py-16 px-8 text-center gap-2"
                    >
                        {#if runs.length === 0}
                            <div class="w-12 h-12 text-slate-300 mb-2">
                                <svg
                                    class="w-full h-full"
                                    viewBox="0 0 24 24"
                                    fill="none"
                                    stroke="currentColor"
                                    stroke-width="1.5"
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                    ><path
                                        d="M9.75 3.104v5.714a2.25 2.25 0 0 1-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 0 1 4.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0 1 12 15a9.065 9.065 0 0 0-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0 1 12 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5"
                                    /></svg
                                >
                            </div>
                            <p class="text-[15px] font-semibold text-slate-600">
                                No runs yet
                            </p>
                            <p class="text-[13px] text-slate-400">
                                Create your first run to get started.
                            </p>
                        {:else}
                            <p class="text-[15px] font-semibold text-slate-600">
                                No matching runs
                            </p>
                            <p class="text-[13px] text-slate-400">
                                Try a different search term.
                            </p>
                        {/if}
                    </div>
                {:else}
                    <table class="w-full border-collapse">
                        <thead>
                            <tr class="border-t border-b border-slate-100">
                                <th class="w-[40px] py-2.5 px-2 pl-6">
                                    <input
                                        type="checkbox"
                                        class="w-3.5 h-3.5 rounded border-slate-300 text-blue-600 focus:ring-blue-500 cursor-pointer"
                                        checked={exportableRuns.length > 0 && exportableRuns.every((r) => selectedRunIds.has(r.id))}
                                        onclick={(e) => { e.stopPropagation(); toggleAllExportable(); }}
                                        title="Select all exportable runs (Completed/Edited)"
                                    />
                                </th>
                                <th
                                    class="w-[80px] text-left py-2.5 px-4 text-[11px] font-bold text-slate-400 uppercase tracking-wide"
                                    >ID</th
                                >
                                <th
                                    class="text-left py-2.5 px-4 text-[11px] font-bold uppercase tracking-wide cursor-pointer select-none hover:text-slate-600 {runSortKey === 'name' ? 'text-slate-700' : 'text-slate-400'}"
                                    onclick={() => toggleSort("runs", "name")}
                                    >Run Name{sortIndicator("runs", "name")}</th
                                >
                                <th
                                    class="w-[150px] text-left py-2.5 px-4 text-[11px] font-bold text-slate-400 uppercase tracking-wide"
                                    >Protocol</th
                                >
                                <th
                                    class="w-[100px] text-left py-2.5 px-4 text-[11px] font-bold uppercase tracking-wide cursor-pointer select-none hover:text-slate-600 {runSortKey === 'status' ? 'text-slate-700' : 'text-slate-400'}"
                                    onclick={() => toggleSort("runs", "status")}
                                    >Status{sortIndicator("runs", "status")}</th
                                >
                                <th
                                    class="w-[130px] text-right py-2.5 px-4 pr-8 text-[11px] font-bold uppercase tracking-wide cursor-pointer select-none hover:text-slate-600 {runSortKey === 'updated_at' ? 'text-slate-700' : 'text-slate-400'}"
                                    onclick={() => toggleSort("runs", "updated_at")}
                                    >Last Modified{sortIndicator("runs", "updated_at")}</th
                                >
                            </tr>
                        </thead>
                        <tbody>
                            {#each paginatedRuns() as r}
                                <tr
                                    class="border-b border-slate-50 cursor-pointer transition-colors hover:bg-slate-50 {selectedRunIds.has(r.id) ? 'bg-blue-50/50' : ''}"
                                    onclick={() => goto(`/runs/${r.id}`)}
                                >
                                    <td class="py-3.5 px-2 pl-6">
                                        {#if r.status === 'COMPLETED' || r.status === 'EDITED'}
                                            <input
                                                type="checkbox"
                                                class="w-3.5 h-3.5 rounded border-slate-300 text-blue-600 focus:ring-blue-500 cursor-pointer"
                                                checked={selectedRunIds.has(r.id)}
                                                onclick={(e) => { e.stopPropagation(); toggleRunSelection(r.id); }}
                                            />
                                        {:else}
                                            <span class="block w-3.5 h-3.5"></span>
                                        {/if}
                                    </td>
                                    <td
                                        class="py-3.5 px-4 text-xs text-slate-400 font-mono font-medium whitespace-nowrap"
                                        >{shortId(r.id)}</td
                                    >
                                    <td
                                        class="py-3.5 px-4 text-sm font-semibold text-slate-800"
                                        >{r.name}</td
                                    >
                                    <td
                                        class="py-3.5 px-4 text-[13px] text-slate-500 whitespace-nowrap"
                                    >
                                        {#if r.protocol_id}
                                            {#each protocols.filter((p: any) => p.id === r.protocol_id) as proto}
                                                <span
                                                    class="text-slate-600 font-medium"
                                                    >{proto.name}</span
                                                >
                                            {/each}
                                        {:else}
                                            <span class="text-slate-400"
                                                >--</span
                                            >
                                        {/if}
                                    </td>
                                    <td class="py-3.5 px-4 whitespace-nowrap">
                                        <span
                                            class="inline-block text-xs font-semibold px-3 py-0.5 rounded-full {statusClasses(
                                                r.status,
                                            )}"
                                        >
                                            {statusLabel(r.status)}
                                        </span>
                                    </td>
                                    <td
                                        class="py-3.5 px-4 pr-8 text-[13px] text-slate-400 font-medium whitespace-nowrap text-right"
                                        >{formatDate(
                                            r.updated_at || r.created_at,
                                        )}</td
                                    >
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                    <!-- Pagination -->
                    <div
                        class="flex justify-between items-center px-8 py-3.5 border-t border-slate-100"
                    >
                        <div class="flex items-center gap-2">
                            <span class="text-[13px] text-slate-400 font-medium">
                                Showing {Math.min((runPage - 1) * runPageSize + 1, runTotalFiltered)}–{Math.min(runPage * runPageSize, runTotalFiltered)} of {runTotalFiltered}
                            </span>
                            {#if runTotalFiltered > 25}
                                <select
                                    class="ml-2 text-[12px] border border-slate-200 rounded px-1.5 py-0.5 text-slate-600 bg-white"
                                    bind:value={runPageSize}
                                    onchange={() => { runPage = 1; }}
                                >
                                    <option value={25}>25 / page</option>
                                    <option value={50}>50 / page</option>
                                    <option value={100}>100 / page</option>
                                </select>
                            {/if}
                        </div>
                        {#if runTotalPages > 1}
                            <div class="flex items-center gap-1">
                                <button
                                    class="px-2.5 py-1 text-[12px] font-medium rounded border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                                    disabled={runPage <= 1}
                                    onclick={() => { runPage = runPage - 1; }}
                                >Prev</button>
                                <span class="text-[12px] text-slate-500 px-2">
                                    {runPage} / {runTotalPages}
                                </span>
                                <button
                                    class="px-2.5 py-1 text-[12px] font-medium rounded border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                                    disabled={runPage >= runTotalPages}
                                    onclick={() => { runPage = runPage + 1; }}
                                >Next</button>
                            </div>
                        {/if}
                    </div>
                {/if}
            {:else if activeTab === "protocols"}
                <!-- Toolbar -->
                <div class="flex justify-between items-center px-8 py-4">
                    <div class="relative w-60">
                        <svg
                            class="absolute left-2.5 top-1/2 -translate-y-1/2 w-[15px] h-[15px] text-slate-400 pointer-events-none"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="2"
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            ><circle cx="11" cy="11" r="8" /><path
                                d="m21 21-4.3-4.3"
                            /></svg
                        >
                        <input
                            type="text"
                            bind:value={searchQuery}
                            placeholder="Filter protocols..."
                            class="w-full py-1.5 pl-8 pr-2.5 border border-slate-200 rounded-lg text-[13px] text-slate-800 bg-white placeholder:text-slate-400 focus:outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-400/15"
                        />
                    </div>
                    <span class="text-[13px] text-slate-400 font-medium">
                        {filteredProtocols().length} of {protocols.length} protocol{protocols.length !==
                        1
                            ? "s"
                            : ""}
                    </span>
                </div>

                {#if filteredProtocols().length === 0}
                    <div
                        class="flex flex-col items-center justify-center py-16 px-8 text-center gap-2"
                    >
                        {#if protocols.length === 0}
                            <div class="w-12 h-12 text-slate-300 mb-2">
                                <svg
                                    class="w-full h-full"
                                    viewBox="0 0 24 24"
                                    fill="none"
                                    stroke="currentColor"
                                    stroke-width="1.5"
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                    ><path
                                        d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
                                    /></svg
                                >
                            </div>
                            <p class="text-[15px] font-semibold text-slate-600">
                                No protocols yet
                            </p>
                            <p class="text-[13px] text-slate-400 mb-4">
                                Create your first protocol to define a workflow.
                            </p>
                            <button
                                class="px-4.5 py-2 bg-slate-800 text-white rounded-lg text-[13px] font-semibold cursor-pointer whitespace-nowrap transition-colors hover:bg-slate-900"
                                onclick={createProtocol}
                            >
                                + New Protocol
                            </button>
                        {:else}
                            <p class="text-[15px] font-semibold text-slate-600">
                                No matching protocols
                            </p>
                            <p class="text-[13px] text-slate-400">
                                Try a different search term.
                            </p>
                        {/if}
                    </div>
                {:else}
                    <table class="w-full border-collapse">
                        <thead>
                            <tr class="border-t border-b border-slate-100">
                                <th
                                    class="w-[100px] text-left py-2.5 px-4 pl-8 text-[11px] font-bold text-slate-400 uppercase tracking-wide"
                                    >ID</th
                                >
                                <th
                                    class="text-left py-2.5 px-4 text-[11px] font-bold uppercase tracking-wide cursor-pointer select-none hover:text-slate-600 {protoSortKey === 'name' ? 'text-slate-700' : 'text-slate-400'}"
                                    onclick={() => toggleSort("protocols", "name")}
                                    >Protocol Name{sortIndicator("protocols", "name")}</th
                                >
                                <th
                                    class="text-left py-2.5 px-4 text-[11px] font-bold text-slate-400 uppercase tracking-wide"
                                    >Description</th
                                >
                                <th
                                    class="w-[80px] text-left py-2.5 px-4 text-[11px] font-bold uppercase tracking-wide cursor-pointer select-none hover:text-slate-600 {protoSortKey === 'version_number' ? 'text-slate-700' : 'text-slate-400'}"
                                    onclick={() => toggleSort("protocols", "version_number")}
                                    >Version{sortIndicator("protocols", "version_number")}</th
                                >
                                {#if showProtocolStatus}
                                    <th
                                        class="w-[110px] text-left py-2.5 px-4 text-[11px] font-bold uppercase tracking-wide cursor-pointer select-none hover:text-slate-600 {protoSortKey === 'status' ? 'text-slate-700' : 'text-slate-400'}"
                                        onclick={() => toggleSort("protocols", "status")}
                                        >Status{sortIndicator("protocols", "status")}</th
                                    >
                                {/if}
                                <th
                                    class="w-[130px] text-right py-2.5 px-4 pr-8 text-[11px] font-bold uppercase tracking-wide cursor-pointer select-none hover:text-slate-600 {protoSortKey === 'updated_at' ? 'text-slate-700' : 'text-slate-400'}"
                                    onclick={() => toggleSort("protocols", "updated_at")}
                                    >Last Modified{sortIndicator("protocols", "updated_at")}</th
                                >
                            </tr>
                        </thead>
                        <tbody>
                            {#each paginatedProtocols() as proto}
                                <tr
                                    class="border-b border-slate-50 cursor-pointer transition-colors hover:bg-slate-50"
                                    onclick={() =>
                                        goto(`/protocols/${proto.id}`)}
                                >
                                    <td
                                        class="py-3.5 px-4 pl-8 text-xs text-slate-400 font-mono font-medium whitespace-nowrap"
                                        >{shortId(proto.id)}</td
                                    >
                                    <td
                                        class="py-3.5 px-4 text-sm font-semibold text-slate-800"
                                        >{proto.name}</td
                                    >
                                    <td
                                        class="py-3.5 px-4 text-[13px] text-slate-500 max-w-[300px] whitespace-nowrap overflow-hidden text-ellipsis"
                                        >{proto.description || "--"}</td
                                    >
                                    <td
                                        class="py-3.5 px-4 text-xs text-slate-400 font-mono font-medium whitespace-nowrap"
                                        >{proto.version_number
                                            ? `v${proto.version_number}`
                                            : "--"}</td
                                    >
                                    {#if showProtocolStatus}
                                        <td
                                            class="py-3.5 px-4 whitespace-nowrap"
                                        >
                                            <span
                                                class="inline-block text-xs font-semibold px-3 py-0.5 rounded-full {protocolStatusClasses(
                                                    proto.status,
                                                )}"
                                            >
                                                {protocolStatusLabel(
                                                    proto.status,
                                                )}
                                            </span>
                                        </td>
                                    {/if}
                                    <td
                                        class="py-3.5 px-4 pr-8 text-[13px] text-slate-400 font-medium whitespace-nowrap text-right"
                                        >{formatDate(
                                            proto.updated_at ||
                                                proto.created_at,
                                        )}</td
                                    >
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                    <!-- Pagination -->
                    <div
                        class="flex justify-between items-center px-8 py-3.5 border-t border-slate-100"
                    >
                        <div class="flex items-center gap-2">
                            <span class="text-[13px] text-slate-400 font-medium">
                                Showing {Math.min((protoPage - 1) * protoPageSize + 1, protoTotalFiltered)}–{Math.min(protoPage * protoPageSize, protoTotalFiltered)} of {protoTotalFiltered}
                            </span>
                            {#if protoTotalFiltered > 25}
                                <select
                                    class="ml-2 text-[12px] border border-slate-200 rounded px-1.5 py-0.5 text-slate-600 bg-white"
                                    bind:value={protoPageSize}
                                    onchange={() => { protoPage = 1; }}
                                >
                                    <option value={25}>25 / page</option>
                                    <option value={50}>50 / page</option>
                                    <option value={100}>100 / page</option>
                                </select>
                            {/if}
                        </div>
                        {#if protoTotalPages > 1}
                            <div class="flex items-center gap-1">
                                <button
                                    class="px-2.5 py-1 text-[12px] font-medium rounded border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                                    disabled={protoPage <= 1}
                                    onclick={() => { protoPage = protoPage - 1; }}
                                >Prev</button>
                                <span class="text-[12px] text-slate-500 px-2">
                                    {protoPage} / {protoTotalPages}
                                </span>
                                <button
                                    class="px-2.5 py-1 text-[12px] font-medium rounded border border-slate-200 text-slate-500 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                                    disabled={protoPage >= protoTotalPages}
                                    onclick={() => { protoPage = protoPage + 1; }}
                                >Next</button>
                            </div>
                        {/if}
                    </div>
                {/if}
            {:else if activeTab === "activity"}
                <div class="p-8">
                    <!-- Filter Bar -->
                    <div class="mb-6 space-y-3">
                        <!-- Row 1: Entity type pills + search -->
                        <div class="flex flex-wrap items-center gap-3">
                            <div class="flex items-center gap-1.5">
                                {#each allEntityTypes as et}
                                    <button
                                        class="px-2.5 py-1 text-xs font-medium rounded-full border transition-colors {activityEntityFilter.includes(et)
                                            ? entityBadgeClasses(et) + ' ring-1 ring-offset-1'
                                            : 'bg-white text-slate-400 border-slate-200 hover:text-slate-600 hover:border-slate-300'}"
                                        onclick={() => toggleEntityFilter(et)}
                                    >
                                        {et}
                                    </button>
                                {/each}
                            </div>

                            <div class="h-5 w-px bg-slate-200"></div>

                            <div class="flex items-center gap-1.5 flex-wrap">
                                {#each allActionTypes as at}
                                    <button
                                        class="px-2.5 py-1 text-xs font-medium rounded-full border transition-colors {activityActionFilter.includes(at.value)
                                            ? 'bg-slate-800 text-white border-slate-800'
                                            : 'bg-white text-slate-400 border-slate-200 hover:text-slate-600 hover:border-slate-300'}"
                                        onclick={() => toggleActionFilter(at.value)}
                                    >
                                        {at.label}
                                    </button>
                                {/each}
                            </div>

                            <div class="ml-auto flex items-center gap-2">
                                {#if hasActiveFilters}
                                    <button
                                        class="text-xs text-slate-400 hover:text-slate-600 underline"
                                        onclick={clearActivityFilters}
                                    >
                                        Clear filters
                                    </button>
                                {/if}
                                <div class="relative">
                                    <input
                                        type="text"
                                        placeholder="Search activity..."
                                        class="w-48 pl-8 pr-3 py-1.5 text-xs border border-slate-200 rounded-md focus:outline-none focus:ring-1 focus:ring-slate-400 focus:border-slate-400"
                                        bind:value={activitySearch}
                                        oninput={() => {
                                            if (activitySearchDebounce) clearTimeout(activitySearchDebounce);
                                            activitySearchDebounce = setTimeout(() => {
                                                activityLoaded = false;
                                                loadActivity(0);
                                            }, 400);
                                        }}
                                    />
                                    <svg class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                        <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
                                    </svg>
                                </div>
                            </div>
                        </div>
                    </div>

                    {#if activityLoading && !activityLoaded}
                        <div
                            class="flex items-center justify-center py-16 text-sm text-slate-400"
                        >
                            Loading activity...
                        </div>
                    {:else if activityItems.length === 0}
                        <div
                            class="flex flex-col items-center justify-center py-16 text-center gap-2"
                        >
                            <div class="w-12 h-12 text-slate-300 mb-2">
                                <svg
                                    class="w-full h-full"
                                    viewBox="0 0 24 24"
                                    fill="none"
                                    stroke="currentColor"
                                    stroke-width="1.5"
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                    ><path
                                        d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
                                    /></svg
                                >
                            </div>
                            {#if hasActiveFilters}
                                <p class="text-[15px] font-semibold text-slate-600">
                                    No matching activity
                                </p>
                                <p class="text-[13px] text-slate-400">
                                    Try adjusting your filters or search term.
                                </p>
                                <button
                                    class="mt-2 text-xs text-slate-500 hover:text-slate-700 underline"
                                    onclick={clearActivityFilters}
                                >
                                    Clear all filters
                                </button>
                            {:else}
                                <p class="text-[15px] font-semibold text-slate-600">
                                    No activity yet
                                </p>
                                <p class="text-[13px] text-slate-400">
                                    Changes to this project and its protocols and
                                    runs will appear here.
                                </p>
                            {/if}
                        </div>
                    {:else}
                        <!-- Timeline -->
                        <div class="relative pl-7">
                            <!-- Vertical line -->
                            <div
                                class="absolute left-[9px] top-2 bottom-2 w-px bg-slate-200"
                            ></div>

                            {#each activityItems as item}
                                <div class="relative pb-6 last:pb-0">
                                    <!-- Dot -->
                                    <div
                                        class="absolute -left-7 top-1 w-[18px] h-[18px] rounded-full border-2 border-white {actionColor(
                                            item.action,
                                        )} shadow-sm"
                                    ></div>

                                    <!-- Content -->
                                    <div
                                        class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5"
                                    >
                                        <span
                                            class="text-sm font-semibold text-slate-800"
                                        >
                                            {item.actor_name ||
                                                item.actor_email ||
                                                "System"}
                                        </span>
                                        <span class="text-sm text-slate-500">
                                            {actionVerb(item.action)}
                                        </span>
                                        <span
                                            class="inline-flex items-center text-xs font-medium px-2 py-0.5 rounded-full border {entityBadgeClasses(
                                                item.entity_type,
                                            )}"
                                        >
                                            {item.entity_type}
                                        </span>
                                        {#if item.entity_name}
                                            <span
                                                class="text-sm font-medium text-slate-700"
                                            >
                                                {item.entity_name}
                                            </span>
                                        {/if}
                                        <span
                                            class="text-xs text-slate-400 font-medium"
                                        >
                                            {formatDate(item.created_at)}
                                        </span>
                                    </div>

                                    <!-- Version info + changed fields -->
                                    {#if versionSummary(item)}
                                        <p
                                            class="mt-1 text-xs font-medium text-teal-600"
                                        >
                                            {versionSummary(item)}
                                        </p>
                                    {/if}
                                    {#if item.action === "STEP_EDIT" && item.changes}
                                        <p class="mt-1 text-xs text-amber-600">
                                            {stepEditSummary(item.changes) || ""}
                                        </p>
                                    {:else if item.action === "UPDATE" && item.changes && changedKeys(item.changes).length > 0}
                                        <p class="mt-1 text-xs text-slate-400">
                                            Changed: {changedKeys(
                                                item.changes,
                                            ).join(", ")}
                                        </p>
                                    {/if}
                                </div>
                            {/each}
                        </div>

                        <!-- Pagination -->
                        {#if activityTotal > activityLimit}
                            <div
                                class="flex justify-between items-center pt-6 mt-6 border-t border-slate-100"
                            >
                                <span
                                    class="text-[13px] text-slate-400 font-medium"
                                >
                                    Showing {activityOffset + 1}–{Math.min(
                                        activityOffset + activityLimit,
                                        activityTotal,
                                    )} of {activityTotal}
                                </span>
                                <div class="flex gap-2">
                                    <button
                                        class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                                        disabled={activityOffset === 0 ||
                                            activityLoading}
                                        onclick={() =>
                                            loadActivity(
                                                Math.max(
                                                    0,
                                                    activityOffset -
                                                        activityLimit,
                                                ),
                                            )}
                                    >
                                        Previous
                                    </button>
                                    <button
                                        class="px-3 py-1.5 text-xs font-medium rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                                        disabled={activityOffset +
                                            activityLimit >=
                                            activityTotal || activityLoading}
                                        onclick={() =>
                                            loadActivity(
                                                activityOffset + activityLimit,
                                            )}
                                    >
                                        Next
                                    </button>
                                </div>
                            </div>
                        {/if}
                    {/if}
                </div>
            {:else if activeTab === "settings"}
                <div class="p-8 max-w-2xl">
                    <h3 class="text-lg font-bold text-slate-900 mb-1.5">
                        Project Settings
                    </h3>
                    <p class="text-sm text-slate-500 mb-6">
                        Manage project configuration.
                    </p>

                    {#if settingsMessage}
                        <div
                            class="mb-4 text-sm font-medium {settingsMessage.startsWith(
                                'Failed',
                            )
                                ? 'text-red-600'
                                : 'text-emerald-600'}"
                        >
                            {settingsMessage}
                        </div>
                    {/if}

                    <!-- Protocol Approval Section -->
                    <div
                        class="bg-white border border-slate-200 rounded-lg p-6 mb-6"
                    >
                        <h4 class="text-sm font-bold text-slate-800 mb-1">
                            Protocol Approval
                        </h4>
                        <p class="text-xs text-slate-500 mb-4">
                            Require protocols to be approved before they can be
                            used in runs.
                        </p>

                        <label class="flex items-center gap-3 cursor-pointer">
                            <input
                                type="checkbox"
                                bind:checked={requireApproval}
                                class="w-4 h-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500"
                            />
                            <span class="text-sm text-slate-700 font-medium"
                                >Require protocol approval before use</span
                            >
                        </label>
                    </div>

                    <!-- Approvers Section (only visible when approval is enabled) -->
                    {#if requireApproval}
                        <div
                            class="bg-white border border-slate-200 rounded-lg p-6 mb-6"
                        >
                            <h4 class="text-sm font-bold text-slate-800 mb-1">
                                Approvers
                            </h4>
                            <p class="text-xs text-slate-500 mb-4">
                                Users who can approve or reject protocols in
                                this project.
                            </p>

                            <!-- Current approvers -->
                            {#if approvers.length === 0}
                                <p class="text-xs text-slate-400 mb-4">
                                    No approvers assigned yet. Org admins can
                                    always approve.
                                </p>
                            {:else}
                                <div class="space-y-2 mb-4">
                                    {#each approvers as approver}
                                        <div
                                            class="flex items-center justify-between py-2 px-3 bg-slate-50 rounded-lg"
                                        >
                                            <div
                                                class="flex items-center gap-2"
                                            >
                                                <div
                                                    class="w-7 h-7 rounded-full bg-teal-100 text-teal-700 flex items-center justify-center text-xs font-bold"
                                                >
                                                    {(approver.name ||
                                                        "?")[0].toUpperCase()}
                                                </div>
                                                <div>
                                                    <p
                                                        class="text-sm font-medium text-slate-700"
                                                    >
                                                        {approver.name ||
                                                            "Unknown"}
                                                    </p>
                                                    {#if approver.email}
                                                        <p
                                                            class="text-xs text-slate-400"
                                                        >
                                                            {approver.email}
                                                        </p>
                                                    {/if}
                                                </div>
                                            </div>
                                            <button
                                                class="text-xs text-slate-400 hover:text-red-500 transition-colors"
                                                onclick={() =>
                                                    removeApprover(approver.id)}
                                            >
                                                Remove
                                            </button>
                                        </div>
                                    {/each}
                                </div>
                            {/if}

                            <!-- Add approver -->
                            <div class="flex gap-2">
                                <select
                                    bind:value={newApproverUserId}
                                    class="flex-1 px-3 py-2 border border-slate-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
                                >
                                    <option value="">Select a user...</option>
                                    {#each orgMembers.filter((m) => !approvers.some((a) => a.principal_id === m.id)) as member}
                                        <option value={member.id}
                                            >{member.full_name ||
                                                member.email}</option
                                        >
                                    {/each}
                                </select>
                                <button
                                    class="px-4 py-2 text-sm font-semibold text-white bg-teal-600 rounded-lg hover:bg-teal-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                    onclick={addApprover}
                                    disabled={!newApproverUserId}
                                >
                                    Add
                                </button>
                            </div>
                        </div>
                    {/if}

                    <!-- Save Settings -->
                    <button
                        class="px-4 py-2 text-sm font-semibold text-white bg-slate-800 rounded-lg hover:bg-slate-900 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        onclick={saveSettings}
                        disabled={settingsSaving}
                    >
                        {settingsSaving ? "Saving..." : "Save Settings"}
                    </button>
                </div>
            {/if}
        </div>
    </div>
{/if}

<!-- RUN MODAL -->
<Modal bind:open={showRunModal} title="New Run">
    <p class="text-sm text-gray-500 mb-4">Start a new run from a protocol.</p>
    <div class="space-y-3">
        <div>
            <label
                for="exp-name"
                class="block text-sm font-medium text-gray-700 mb-1">Name</label
            >
            <input
                id="exp-name"
                type="text"
                bind:value={newRunName}
                placeholder="e.g. CHO-DG44 Run 1"
                class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
            />
        </div>
        <div>
            <label
                for="protocol-select"
                class="block text-sm font-medium text-gray-700 mb-1"
                >Protocol</label
            >
            <select
                id="protocol-select"
                bind:value={selectedProtocolId}
                class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent bg-white"
            >
                <option value="">Select a protocol</option>
                {#each protocols as proto}
                    <option value={proto.id}>{proto.name}</option>
                {/each}
            </select>
        </div>
        <div class="flex justify-end gap-2 pt-2">
            <button
                onclick={() => {
                    showRunModal = false;
                    selectedProtocolId = null;
                }}
                class="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
            >
                Cancel
            </button>
            <button
                onclick={createRun}
                disabled={!newRunName || !selectedProtocolId}
                class="px-4 py-2 text-sm font-medium text-white bg-teal-600 rounded-lg hover:bg-teal-700 transition-colors disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
                Create
            </button>
        </div>
    </div>
</Modal>

