import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
    THEMES,
    DEFAULT_THEME,
    isTheme,
    getTheme,
    setTheme,
    applyThemeFromCache,
} from './theme.svelte';

describe('theme', () => {
    beforeEach(() => {
        localStorage.clear();
        document.documentElement.removeAttribute('data-theme');
    });

    it('exposes the three theme ids', () => {
        expect(THEMES).toEqual(['lab-glass', 'blueprint', 'apothecary']);
        expect(DEFAULT_THEME).toBe('lab-glass');
    });

    it('isTheme accepts only known ids', () => {
        expect(isTheme('lab-glass')).toBe(true);
        expect(isTheme('apothecary')).toBe(true);
        expect(isTheme('instrument')).toBe(false);
        expect(isTheme('nope')).toBe(false);
        expect(isTheme(null)).toBe(false);
    });

    it('applyThemeFromCache reads localStorage and sets data-theme', () => {
        localStorage.setItem('batchrite.theme', 'apothecary');
        applyThemeFromCache();
        expect(document.documentElement.dataset.theme).toBe('apothecary');
        expect(getTheme()).toBe('apothecary');
    });

    it('applyThemeFromCache falls back to default for invalid value', () => {
        localStorage.setItem('batchrite.theme', 'garbage');
        applyThemeFromCache();
        expect(document.documentElement.dataset.theme).toBe('lab-glass');
        expect(getTheme()).toBe('lab-glass');
    });

    it('setTheme updates DOM, localStorage, and module state', async () => {
        const persistFn = vi.fn().mockResolvedValue(undefined);
        await setTheme('blueprint', persistFn);
        expect(document.documentElement.dataset.theme).toBe('blueprint');
        expect(localStorage.getItem('batchrite.theme')).toBe('blueprint');
        expect(getTheme()).toBe('blueprint');
        expect(persistFn).toHaveBeenCalledWith('blueprint');
    });

    it('setTheme rejects invalid theme ids', async () => {
        await expect(setTheme('nope' as never)).rejects.toThrow();
    });
});
