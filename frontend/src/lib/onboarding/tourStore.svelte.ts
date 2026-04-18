import { api } from '$lib/api';

export type TourSegment = 'project' | 'protocol' | 'run';
export type TourStatus = 'completed' | 'dismissed';

interface TourStateData {
    completed: TourSegment[];
    dismissed: TourSegment[];
}

let state = $state<TourStateData>({ completed: [], dismissed: [] });
let hydrated = $state(false);

export function resetTourState(): void {
    state = { completed: [], dismissed: [] };
    hydrated = false;
}

export async function hydrateTourState(): Promise<void> {
    const res = await api.get<TourStateData>('/onboarding/state');
    state = {
        completed: res.completed || [],
        dismissed: res.dismissed || [],
    };
    hydrated = true;
}

export function isHydrated(): boolean {
    return hydrated;
}

export function isCompleted(segment: TourSegment): boolean {
    return state.completed.includes(segment);
}

export function isDismissed(segment: TourSegment): boolean {
    return state.dismissed.includes(segment);
}

export function shouldShowDot(segment: TourSegment): boolean {
    return hydrated && !isCompleted(segment) && !isDismissed(segment);
}

export function isWelcomeEmpty(): boolean {
    return (
        hydrated &&
        state.completed.length === 0 &&
        state.dismissed.length === 0
    );
}

async function patchState(segment: TourSegment, status: TourStatus): Promise<void> {
    const res = await api.patch<TourStateData>('/onboarding/state', {
        segment,
        status,
    });
    state = {
        completed: res.completed || [],
        dismissed: res.dismissed || [],
    };
}

export async function markCompleted(segment: TourSegment): Promise<void> {
    await patchState(segment, 'completed');
}

export async function markDismissed(segment: TourSegment): Promise<void> {
    await patchState(segment, 'dismissed');
}

export async function markAllDismissed(): Promise<void> {
    await markDismissed('project');
    await markDismissed('protocol');
    await markDismissed('run');
}
