import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/svelte';

// jsdom does not implement Element.animate (Web Animations API).
// Svelte 5 transitions like fade/fly call element.animate(); stub it so
// component tests that mount transition-using pages do not crash.
if (typeof Element !== 'undefined' && !Element.prototype.animate) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (Element.prototype as any).animate = function animateStub() {
        return {
            cancel: () => {},
            finish: () => {},
            play: () => {},
            pause: () => {},
            reverse: () => {},
            addEventListener: () => {},
            removeEventListener: () => {},
            finished: Promise.resolve(),
            ready: Promise.resolve(),
            onfinish: null,
            oncancel: null,
            currentTime: 0,
            playbackRate: 1,
            playState: 'finished',
            startTime: 0,
            timeline: null,
            effect: null,
            id: '',
            commitStyles: () => {},
            persist: () => {},
            updatePlaybackRate: () => {},
        };
    };
}

afterEach(() => {
    cleanup();
});
