import { sveltekit } from '@sveltejs/kit/vite';
import { SvelteKitPWA } from '@vite-pwa/sveltekit';
import { defineConfig } from 'vite';

export default defineConfig(({ mode }) => {
	const host = process.env.VITE_API_HOST;

	return {
		plugins: [
			sveltekit(),
			SvelteKitPWA({
				registerType: 'autoUpdate',
				manifest: {
					name: 'Trellis Runbook',
					short_name: 'Runbook',
					description: 'Digital Lab Notebook for Process Development',
					theme_color: '#2b4678',
					background_color: '#f7f5f0',
					display: 'standalone',
					scope: '/',
					start_url: '/',
					icons: [
						{
							src: '/icons/icon-192.svg',
							sizes: '192x192',
							type: 'image/svg+xml',
						},
						{
							src: '/icons/icon-512.svg',
							sizes: '512x512',
							type: 'image/svg+xml',
						},
						{
							src: '/icons/icon-maskable.svg',
							sizes: '512x512',
							type: 'image/svg+xml',
							purpose: 'maskable',
						},
					],
				},
				workbox: {
					// Static assets: cache-first
					globPatterns: ['**/*.{js,css,html,svg,png,ico,woff,woff2}'],
					// Offline fallback
					navigateFallback: null,
					runtimeCaching: [
						{
							// API calls (non-auth): network-first with 3s timeout
							urlPattern: ({ url }) =>
								url.pathname.startsWith('/api/') ||
								(url.port === '8000' && !url.pathname.startsWith('/auth/')),
							handler: 'NetworkFirst',
							options: {
								cacheName: 'api-cache',
								networkTimeoutSeconds: 3,
								cacheableResponse: {
									statuses: [0, 200],
								},
								expiration: {
									maxEntries: 100,
									maxAgeSeconds: 60 * 60, // 1 hour
								},
							},
						},
						{
							// Auth endpoints: network-only (never cache tokens)
							urlPattern: ({ url }) =>
								url.pathname.startsWith('/auth/') ||
								(url.port === '8000' && url.pathname.startsWith('/auth/')),
							handler: 'NetworkOnly',
						},
						{
							// Google Fonts stylesheets: stale-while-revalidate
							urlPattern: /^https:\/\/fonts\.googleapis\.com\/.*/,
							handler: 'StaleWhileRevalidate',
							options: {
								cacheName: 'google-fonts-stylesheets',
							},
						},
						{
							// Google Fonts files: cache-first (long-lived)
							urlPattern: /^https:\/\/fonts\.gstatic\.com\/.*/,
							handler: 'CacheFirst',
							options: {
								cacheName: 'google-fonts-webfonts',
								cacheableResponse: {
									statuses: [0, 200],
								},
								expiration: {
									maxEntries: 30,
									maxAgeSeconds: 60 * 60 * 24 * 365, // 1 year
								},
							},
						},
					],
				},
				devOptions: {
					enabled: false,
				},
			}),
		],
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
