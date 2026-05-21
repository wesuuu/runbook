import { render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

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
