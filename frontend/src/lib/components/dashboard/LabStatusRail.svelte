<script lang="ts">
    import CalibrationWidget from './CalibrationWidget.svelte';
    import AwaitingSignoffWidget from './AwaitingSignoffWidget.svelte';
    import RecentActivityWidget from './RecentActivityWidget.svelte';

    interface CalibrationItem {
        equipment_id: string;
        name: string;
        site_name: string | null;
        next_calibration_date: string | null;
        state: string;
    }
    interface CalibrationStatus {
        overdue: CalibrationItem[];
        due_soon: CalibrationItem[];
    }
    interface SignoffItem {
        kind: string;
        entity_id: string;
        name: string;
        project_name: string | null;
        detail: string | null;
    }
    interface ActivityItem {
        id: string;
        action: string;
        entity_type: string;
        entity_id: string;
        entity_name: string | null;
        actor_name: string | null;
        changes: Record<string, any>;
        created_at: string;
    }
    interface Props {
        calibration: CalibrationStatus;
        awaitingSignoff: SignoffItem[];
        activity: ActivityItem[];
        onCalibrationViewAll: () => void;
        onSignoffSelect: (item: SignoffItem) => void;
    }
    let {
        calibration,
        awaitingSignoff,
        activity,
        onCalibrationViewAll,
        onSignoffSelect,
    }: Props = $props();
</script>

<div class="space-y-6">
    <CalibrationWidget {calibration} onViewAll={onCalibrationViewAll} />
    <AwaitingSignoffWidget items={awaitingSignoff} onSelect={onSignoffSelect} />
    <RecentActivityWidget {activity} />
</div>
