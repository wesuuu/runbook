/**
 * Duration values are entered through plain number inputs whose `min`
 * attribute is only a soft hint — typed or pasted negatives, zero, and blank
 * values still bind to the bound variable. Clamp them to a sane minimum
 * before they are applied to a protocol step (QA issue #8).
 */

/** Smallest duration (minutes) allowed for a unit-op step. */
export const MIN_DURATION_MIN = 1;

/** Smallest duration (minutes) when the protocol timeline grid is enabled. */
export const MIN_DURATION_MIN_TIMELINE = 5;

/**
 * Coerce a user-entered duration to a valid positive number of minutes.
 *
 * @param value Raw bound value — may be NaN, null, undefined, negative, or
 *     zero when the number input is cleared or contains invalid text.
 * @param timelineEnabled Whether the protocol timeline grid is enabled, which
 *     raises the floor to a 5-minute step.
 * @returns A finite duration greater than or equal to the applicable minimum.
 */
export function clampDuration(
    value: number | null | undefined,
    timelineEnabled: boolean,
): number {
    const min = timelineEnabled
        ? MIN_DURATION_MIN_TIMELINE
        : MIN_DURATION_MIN;
    if (typeof value !== 'number' || !Number.isFinite(value) || value < min) {
        return min;
    }
    return value;
}
