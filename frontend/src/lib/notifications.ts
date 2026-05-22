import {
    AlertTriangle,
    ArrowLeft,
    ArrowLeftRight,
    ArrowRight,
    BadgeCheck,
    Bell,
    CheckCircle2,
    FileCheck2,
    Mail,
    Play,
    Undo2,
} from 'lucide-svelte';

/** Items fetched into the bell dropdown. */
export const BELL_LIMIT = 20;
/** Items per page on the /notifications history route. */
export const HISTORY_PAGE_SIZE = 25;

// `typeof Bell` is a concrete lucide-svelte icon component type; every
// icon below shares it, so the map and the fallback stay type-aligned.
const EVENT_ICONS: Record<string, typeof Bell> = {
    RUN_STARTED: Play,
    RUN_COMPLETED: CheckCircle2,
    ROLE_ASSIGNED: ArrowRight,
    ROLE_UNASSIGNED: ArrowLeft,
    ROLE_REASSIGNED: ArrowLeftRight,
    PROTOCOL_APPROVED: BadgeCheck,
    PROTOCOL_REVERTED: Undo2,
    PROTOCOL_APPROVAL_REQUESTED: FileCheck2,
    INVITE_SENT: Mail,
    INVITE_ACCEPTED: BadgeCheck,
    STEP_DEVIATION: AlertTriangle,
};

/** Resolve the lucide icon for an event type; `Bell` is the fallback. */
export function eventIcon(eventType: string): typeof Bell {
    return EVENT_ICONS[eventType] ?? Bell;
}

// Tonal chip classes (background + foreground) for the icon, so a
// scientist scanning the list can categorise notifications by colour at a
// glance. Theme/utility tokens only — never a raw `bg-white`.
const EVENT_TONES: Record<string, string> = {
    RUN_STARTED: 'bg-primary/10 text-primary',
    RUN_COMPLETED: 'bg-emerald-500/12 text-emerald-600',
    ROLE_ASSIGNED: 'bg-primary/10 text-primary',
    ROLE_UNASSIGNED: 'bg-primary/10 text-primary',
    ROLE_REASSIGNED: 'bg-primary/10 text-primary',
    PROTOCOL_APPROVED: 'bg-emerald-500/12 text-emerald-600',
    PROTOCOL_REVERTED: 'bg-amber-500/15 text-amber-600',
    PROTOCOL_APPROVAL_REQUESTED: 'bg-primary/10 text-primary',
    INVITE_SENT: 'bg-muted text-muted-foreground',
    INVITE_ACCEPTED: 'bg-emerald-500/12 text-emerald-600',
    STEP_DEVIATION: 'bg-destructive/10 text-destructive',
};

/** Tonal chip classes for an event type; neutral muted fallback. */
export function eventTone(eventType: string): string {
    return EVENT_TONES[eventType] ?? 'bg-muted text-muted-foreground';
}
