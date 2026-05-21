import { render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import Logo from './Logo.svelte';
import LogoMark from './LogoMark.svelte';

describe('LogoMark', () => {
	it('renders an inline svg for the full variant', () => {
		const { container } = render(LogoMark, { props: { variant: 'full' } });
		const svg = container.querySelector('svg');
		expect(svg).not.toBeNull();
		expect(svg?.getAttribute('data-variant')).toBe('full');
	});

	it('renders an inline svg for the simple variant', () => {
		const { container } = render(LogoMark, { props: { variant: 'simple' } });
		expect(
			container.querySelector('svg')?.getAttribute('data-variant'),
		).toBe('simple');
	});

	it('sets svg width and height from the size prop', () => {
		const { container } = render(LogoMark, {
			props: { variant: 'simple', size: 48 },
		});
		const svg = container.querySelector('svg');
		expect(svg?.getAttribute('width')).toBe('48');
		expect(svg?.getAttribute('height')).toBe('48');
	});

	it('crops the full variant viewBox to the flask art', () => {
		const { container } = render(LogoMark, { props: { variant: 'full' } });
		expect(container.querySelector('svg')?.getAttribute('viewBox')).toBe(
			'22 9 56 80',
		);
	});

	it('renders the full variant non-square (taller than wide)', () => {
		// `size` is the mark height; width follows the cropped 56:80 ratio.
		const { container } = render(LogoMark, {
			props: { variant: 'full', size: 80 },
		});
		const svg = container.querySelector('svg');
		expect(svg?.getAttribute('height')).toBe('80');
		expect(svg?.getAttribute('width')).toBe('56');
	});

	it('omits SMIL animation nodes when not animated', () => {
		const { container } = render(LogoMark, {
			props: { variant: 'full', animated: false },
		});
		expect(container.querySelectorAll('animate')).toHaveLength(0);
		expect(container.querySelectorAll('animateMotion')).toHaveLength(0);
	});

	it('includes SMIL animation nodes for an animated full mark', () => {
		const { container } = render(LogoMark, {
			props: { variant: 'full', animated: true },
		});
		expect(container.querySelectorAll('animate').length).toBeGreaterThan(0);
		expect(
			container.querySelectorAll('animateMotion').length,
		).toBeGreaterThan(0);
	});

	it('never animates the simple variant', () => {
		const { container } = render(LogoMark, {
			props: { variant: 'simple', animated: true },
		});
		expect(container.querySelectorAll('animate')).toHaveLength(0);
		expect(container.querySelectorAll('animateMotion')).toHaveLength(0);
	});

	it('gives each instance a unique clipPath id', () => {
		const a = render(LogoMark, { props: { variant: 'full' } });
		const b = render(LogoMark, { props: { variant: 'full' } });
		const idA = a.container.querySelector('clipPath')?.id;
		const idB = b.container.querySelector('clipPath')?.id;
		expect(idA).toBeTruthy();
		expect(idB).toBeTruthy();
		expect(idA).not.toBe(idB);
	});
});

describe('Logo', () => {
	it('renders an inline svg mark, not an img', () => {
		const { container } = render(Logo, { props: {} });
		expect(container.querySelector('svg')).not.toBeNull();
		expect(container.querySelector('img')).toBeNull();
	});

	it('renders exactly one batchrite wordmark', () => {
		const { container } = render(Logo, { props: {} });
		const wordmarks = container.querySelectorAll('.batchrite-wordmark');
		expect(wordmarks).toHaveLength(1);
		expect(wordmarks[0].textContent).toBe('batchrite');
	});

	it('defaults to the static simple mark', () => {
		const { container } = render(Logo, { props: {} });
		expect(
			container.querySelector('svg')?.getAttribute('data-variant'),
		).toBe('simple');
		expect(container.querySelectorAll('animate')).toHaveLength(0);
	});

	it('forwards variant and animated to the mark', () => {
		const { container } = render(Logo, {
			props: { variant: 'full', animated: true },
		});
		expect(
			container.querySelector('svg')?.getAttribute('data-variant'),
		).toBe('full');
		expect(container.querySelectorAll('animate').length).toBeGreaterThan(0);
	});

	it('applies a passed class to the lockup', () => {
		const { container } = render(Logo, { props: { class: 'mb-4' } });
		const lockup = container.querySelector('.batchrite-lockup');
		expect(lockup?.classList.contains('mb-4')).toBe(true);
	});

	it('lays out horizontally by default', () => {
		const { container } = render(Logo, { props: {} });
		const lockup = container.querySelector('.batchrite-lockup');
		expect(lockup?.classList.contains('stacked')).toBe(false);
	});

	it('stacks the mark above the wordmark when orientation is stacked', () => {
		const { container } = render(Logo, {
			props: { orientation: 'stacked' },
		});
		const lockup = container.querySelector('.batchrite-lockup');
		expect(lockup?.classList.contains('stacked')).toBe(true);
	});
});
