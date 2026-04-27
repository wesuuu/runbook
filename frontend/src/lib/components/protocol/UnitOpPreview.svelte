<script lang="ts">
    import { fade } from "svelte/transition";
    import { cubicOut } from "svelte/easing";
    import { X, Lock } from "lucide-svelte";
    import { getCategoryColor } from "$lib/categoryColors";

    interface UnitOpProp {
        id: string;
        name: string;
        category: string;
        description?: string | null;
        param_schema?: Record<string, any>;
        library_slug?: string | null;
    }

    interface Props {
        op: UnitOpProp;
        libraryDisplayName?: string | null;
        libraryVersion?: string | null;
        onClose: () => void;
    }

    let { op, libraryDisplayName = null, libraryVersion = null, onClose }: Props = $props();

    // Extract param entries: [{ key, title, default, type }]
    const params = $derived.by(() => {
        const props = op.param_schema?.properties ?? {};
        const out: Array<{ key: string; title: string; def: any; type: string }> = [];
        for (const [k, v] of Object.entries(props as Record<string, any>)) {
            out.push({
                key: k,
                title: v?.title ?? humanize(k),
                def: v?.default,
                type: v?.type ?? "string",
            });
        }
        return out;
    });

    function humanize(slug: string): string {
        return slug
            .replace(/_/g, " ")
            .replace(/\b\w/g, (c) => c.toUpperCase());
    }

    // Render description with {{token}} pills
    function descSegments(desc: string): Array<{ kind: "text" | "token"; value: string }> {
        const re = /\{\{\s*([^}]+?)\s*\}\}/g;
        const out: Array<{ kind: "text" | "token"; value: string }> = [];
        let last = 0;
        let m: RegExpExecArray | null;
        while ((m = re.exec(desc)) !== null) {
            if (m.index > last) out.push({ kind: "text", value: desc.slice(last, m.index) });
            out.push({ kind: "token", value: m[1] });
            last = m.index + m[0].length;
        }
        if (last < desc.length) out.push({ kind: "text", value: desc.slice(last) });
        return out;
    }

    function formatDefault(def: any, type: string): string {
        if (def === undefined || def === null) return "—";
        if (typeof def === "boolean") return def ? "true" : "false";
        if (typeof def === "string" && def === "") return '""';
        return String(def);
    }
</script>

<aside
    class="preview-panel"
    style:--cat-color={getCategoryColor(op.category)}
    in:fade={{ duration: 140, easing: cubicOut }}
>
    <button class="close-btn" onclick={onClose} aria-label="Close preview">
        <X size={16} />
    </button>

    <header class="preview-header">
        <div class="kicker">{op.category}</div>
        <h2 class="op-name">{op.name}</h2>
    </header>

    <div class="warning-banner" role="status">
        <Lock size={13} />
        <span>Preview — drag onto the canvas to add this step.</span>
    </div>

    {#if op.description}
        <section class="block">
            <div class="block-label">Description</div>
            <p class="description">
                {#each descSegments(op.description) as seg}
                    {#if seg.kind === "token"}
                        <span class="token">{seg.value}</span>
                    {:else}
                        {seg.value}
                    {/if}
                {/each}
            </p>
        </section>
    {/if}

    {#if params.length > 0}
        <section class="block">
            <div class="block-label">Parameters</div>
            <dl class="param-grid">
                {#each params as p}
                    <dt>{p.title}</dt>
                    <dd>{formatDefault(p.def, p.type)}</dd>
                {/each}
            </dl>
        </section>
    {/if}

    <section class="block source-block">
        <div class="block-label">Source</div>
        <p class="source">
            {libraryDisplayName ?? op.library_slug ?? "Custom"}{#if libraryVersion} · v{libraryVersion}{/if}
        </p>
    </section>

    <footer class="preview-footer">
        <span class="hint">Drag this op onto the canvas to add it to your protocol.</span>
    </footer>
</aside>

<style>
    .preview-panel {
        position: relative;
        width: 320px;
        flex-shrink: 0;
        background: #fdfdfb;
        border-left: 1px solid hsl(240, 5.9%, 90%);
        padding: 20px 22px 16px;
        overflow-y: auto;
        font-family: inherit;
        color: #0f172a;
    }

    .preview-panel::before {
        content: "";
        position: absolute;
        top: 0;
        left: 0;
        bottom: 0;
        width: 3px;
        background: var(--cat-color, hsl(173, 58%, 39%));
    }

    .close-btn {
        position: absolute;
        top: 12px;
        right: 12px;
        background: transparent;
        border: none;
        color: #94a3b8;
        cursor: pointer;
        padding: 4px;
        border-radius: 4px;
        line-height: 0;
    }
    .close-btn:hover {
        color: #0f172a;
        background: #f1f5f9;
    }

    .preview-header {
        margin-bottom: 14px;
        padding-right: 24px;
    }
    .kicker {
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.12em;
        color: var(--cat-color, hsl(173, 58%, 39%));
        text-transform: uppercase;
        margin-bottom: 4px;
    }
    .op-name {
        font-size: 20px;
        font-weight: 600;
        line-height: 1.25;
        letter-spacing: -0.01em;
        margin: 0;
    }

    .warning-banner {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 9px 12px;
        background: hsl(40, 95%, 96%);
        border: 1px solid hsl(40, 80%, 85%);
        border-radius: 6px;
        font-size: 12px;
        color: hsl(28, 70%, 30%);
        font-weight: 500;
        margin-bottom: 18px;
    }

    .block {
        margin-bottom: 18px;
    }
    .block-label {
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.1em;
        color: #94a3b8;
        text-transform: uppercase;
        margin-bottom: 8px;
    }

    .description {
        font-size: 13px;
        line-height: 1.55;
        color: #334155;
        margin: 0;
    }

    .token {
        display: inline-block;
        padding: 0 5px;
        margin: 0 1px;
        font-family: 'JetBrains Mono', 'SF Mono', ui-monospace, monospace;
        font-size: 11px;
        background: hsl(173, 58%, 96%);
        color: hsl(173, 58%, 30%);
        border-radius: 3px;
        font-weight: 500;
    }

    .param-grid {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        column-gap: 16px;
        row-gap: 6px;
        margin: 0;
        padding: 12px 14px;
        background: white;
        border: 1px solid hsl(240, 5.9%, 92%);
        border-radius: 6px;
    }
    .param-grid dt {
        font-size: 12px;
        color: #64748b;
        font-weight: 500;
    }
    .param-grid dd {
        margin: 0;
        font-family: 'JetBrains Mono', 'SF Mono', ui-monospace, monospace;
        font-size: 12px;
        color: #0f172a;
        text-align: right;
        word-break: break-word;
    }

    .source-block {
        margin-bottom: 12px;
    }
    .source {
        font-size: 12px;
        color: #64748b;
        font-style: italic;
        margin: 0;
    }

    .preview-footer {
        padding-top: 12px;
        border-top: 1px dashed hsl(240, 5.9%, 90%);
    }
    .hint {
        font-size: 11px;
        color: #94a3b8;
        line-height: 1.45;
    }
</style>
