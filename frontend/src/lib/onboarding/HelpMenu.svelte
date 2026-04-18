<script lang="ts">
    import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
    import { HelpCircle } from 'lucide-svelte';
    import HintDot from './HintDot.svelte';

    interface Props {
        dotVisible: boolean;
        onTakeTour: () => void;
    }

    let { dotVisible, onTakeTour }: Props = $props();
</script>

<DropdownMenu.Root>
    <DropdownMenu.Trigger
        class="relative inline-flex h-8 w-8 items-center justify-center rounded-full border border-input bg-background text-muted-foreground transition-colors hover:bg-muted"
        aria-label="Help and tours"
    >
        <HelpCircle class="h-4 w-4" />
        <HintDot visible={dotVisible} ariaLabel="tour available" onClick={onTakeTour} />
    </DropdownMenu.Trigger>
    <DropdownMenu.Content align="end">
        <DropdownMenu.Item onclick={onTakeTour}>Take tour</DropdownMenu.Item>
    </DropdownMenu.Content>
</DropdownMenu.Root>
