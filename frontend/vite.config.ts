import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig(({ mode }) => {
	const host = process.env.VITE_API_HOST;

	return {
		plugins: [sveltekit()],
		server: host
			? {
					host,
					hmr: {
						host,
					},
				}
			: undefined,
	};
});
