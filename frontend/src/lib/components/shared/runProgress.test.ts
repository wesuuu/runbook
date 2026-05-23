import { describe, it, expect } from 'vitest';
import { runSegmentClass, runSegmentLabel } from './runProgress';

describe('runSegmentClass', () => {
  it('maps a normal completion to accent green', () => {
    expect(runSegmentClass('COMPLETED', 'COMPLETED_NORMAL')).toBe('bg-accent');
  });
  it('maps a deviated completion to amber', () => {
    expect(runSegmentClass('COMPLETED', 'COMPLETED_WITH_DEVIATIONS')).toBe(
      'bg-amber-400 dark:bg-amber-500',
    );
  });
  it('maps an aborted completion to destructive', () => {
    expect(runSegmentClass('COMPLETED', 'ABORTED')).toBe('bg-destructive');
  });
  it('treats a legacy null-outcome completion as normal', () => {
    expect(runSegmentClass('COMPLETED', null)).toBe('bg-accent');
  });
  it('maps ACTIVE and EDITED to primary', () => {
    expect(runSegmentClass('ACTIVE', null)).toBe('bg-primary');
    expect(runSegmentClass('EDITED', null)).toBe('bg-primary');
  });
  it('maps PLANNED to muted and ARCHIVED to a faded track', () => {
    expect(runSegmentClass('PLANNED', null)).toBe('bg-muted');
    expect(runSegmentClass('ARCHIVED', null)).toBe('bg-muted-foreground/30');
  });
});

describe('runSegmentLabel', () => {
  it('describes status and outcome for the accessible label', () => {
    expect(runSegmentLabel('COMPLETED', 'COMPLETED_WITH_DEVIATIONS')).toBe(
      'Completed (with deviations)',
    );
    expect(runSegmentLabel('PLANNED', null)).toBe('Planned');
  });
});
