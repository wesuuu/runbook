/**
 * Single source of truth for RunProgressBar segment colors + labels (F-0093).
 * Color alone is not accessible — every segment also carries runSegmentLabel
 * as its title / aria-label.
 */

export function runSegmentClass(
  status: string,
  outcome: string | null | undefined,
): string {
  const s = (status ?? '').toUpperCase();
  const o = (outcome ?? '').toUpperCase();
  if (s === 'COMPLETED') {
    if (o === 'COMPLETED_WITH_DEVIATIONS') return 'bg-amber-400 dark:bg-amber-500';
    if (o === 'ABORTED') return 'bg-destructive';
    return 'bg-accent'; // COMPLETED_NORMAL or legacy null outcome
  }
  if (s === 'ACTIVE' || s === 'EDITED') return 'bg-primary';
  if (s === 'ARCHIVED') return 'bg-muted-foreground/30';
  return 'bg-muted'; // PLANNED and anything unrecognized
}

export function runSegmentLabel(
  status: string,
  outcome: string | null | undefined,
): string {
  const s = (status ?? '').toUpperCase();
  const o = (outcome ?? '').toUpperCase();
  if (s === 'COMPLETED') {
    if (o === 'COMPLETED_WITH_DEVIATIONS') return 'Completed (with deviations)';
    if (o === 'ABORTED') return 'Completed (aborted)';
    return 'Completed';
  }
  if (s === 'ACTIVE') return 'Active';
  if (s === 'EDITED') return 'Edited';
  if (s === 'PLANNED') return 'Planned';
  if (s === 'ARCHIVED') return 'Archived';
  return status || 'Unknown';
}

export function isPulsing(status: string): boolean {
  return (status ?? '').toUpperCase() === 'ACTIVE';
}
