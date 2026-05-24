<script lang="ts">
import { Input } from '$lib/components/ui/input';

interface Props {
    label: string | null | undefined;
    value: number | null | undefined;
    unit: string | null | undefined;
    onChange: (next: { label: string | null; value: number | null; unit: string | null }) => void;
}
let { label, value, unit, onChange }: Props = $props();

let localLabel = $state(label ?? '');
let localValue = $state(value?.toString() ?? '');
let localUnit = $state(unit ?? '');

function emit() {
    const parsed = localValue.trim() === '' ? null : Number(localValue);
    onChange({
        label: localLabel.trim() === '' ? null : localLabel.trim(),
        value: parsed != null && Number.isFinite(parsed) ? parsed : null,
        unit: localUnit.trim() === '' ? null : localUnit.trim(),
    });
}
</script>

<div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
    <label class="text-sm">
        Label
        <Input bind:value={localLabel} onblur={emit} placeholder="e.g. Titer" />
    </label>
    <label class="text-sm">
        Value
        <Input type="number" step="any" bind:value={localValue} onblur={emit} />
    </label>
    <label class="text-sm">
        Unit
        <Input bind:value={localUnit} onblur={emit} placeholder="g/L" />
    </label>
</div>
