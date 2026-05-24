import { describe, it, expect, beforeEach, vi } from 'vitest';
import { focusStep } from './stepDeepLink';

describe('focusStep', () => {
    beforeEach(() => {
        document.body.innerHTML = '';
        document.head
            .querySelectorAll('style[data-step-deeplink]')
            .forEach((el) => el.remove());
        vi.restoreAllMocks();
    });

    it('scrolls and highlights the matching element', async () => {
        const el = document.createElement('div');
        el.setAttribute('data-step-id', 'abc-123');
        const scrollSpy = vi.fn();
        el.scrollIntoView = scrollSpy;
        document.body.appendChild(el);

        await focusStep('abc-123');

        expect(scrollSpy).toHaveBeenCalledWith(
            expect.objectContaining({
                behavior: 'auto',
                block: 'center',
            }),
        );
        expect(el.classList.contains('step-deeplink-target')).toBe(true);
    });

    it('is a silent no-op when the element is absent', async () => {
        vi.useFakeTimers();
        const p = focusStep('missing');
        // advance past the 3s wait-for-element budget
        await vi.advanceTimersByTimeAsync(3500);
        vi.useRealTimers();
        await expect(p).resolves.toBeUndefined();
    });

    it('waits for the element to appear (handles render race)', async () => {
        const scrollSpy = vi.fn();
        const p = focusStep('late-render');
        // Mount the element 200ms later — focusStep should still find it.
        setTimeout(() => {
            const el = document.createElement('div');
            el.setAttribute('data-step-id', 'late-render');
            el.scrollIntoView = scrollSpy;
            document.body.appendChild(el);
        }, 200);
        await p;
        expect(scrollSpy).toHaveBeenCalled();
    });

    it('honors prefers-reduced-motion (instant scroll, no highlight)', async () => {
        const el = document.createElement('div');
        el.setAttribute('data-step-id', 'abc');
        const scrollSpy = vi.fn();
        el.scrollIntoView = scrollSpy;
        document.body.appendChild(el);

        vi.spyOn(window, 'matchMedia').mockImplementation(
            (q: string) =>
                ({
                    matches: q.includes('reduce'),
                    media: q,
                    onchange: null,
                    addEventListener: () => {},
                    removeEventListener: () => {},
                    addListener: () => {},
                    removeListener: () => {},
                    dispatchEvent: () => false,
                }) as MediaQueryList,
        );

        await focusStep('abc');

        expect(scrollSpy).toHaveBeenCalledWith(
            expect.objectContaining({ behavior: 'auto' }),
        );
        expect(el.classList.contains('step-deeplink-target')).toBe(false);
    });

    it('injects its <style> exactly once across multiple imports', async () => {
        const el = document.createElement('div');
        el.setAttribute('data-step-id', 'a');
        el.scrollIntoView = () => {};
        document.body.appendChild(el);

        await focusStep('a');
        await focusStep('a');
        await focusStep('a');

        const styles = document.head.querySelectorAll(
            'style[data-step-deeplink]',
        );
        expect(styles.length).toBe(1);
    });

    it('escapes selector input', async () => {
        const el = document.createElement('div');
        el.setAttribute('data-step-id', 'safe-id');
        const scrollSpy = vi.fn();
        el.scrollIntoView = scrollSpy;
        document.body.appendChild(el);

        await focusStep('safe-id');
        expect(scrollSpy).toHaveBeenCalled();
    });
});
