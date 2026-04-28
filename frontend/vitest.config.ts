import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vitest/config';

export default defineConfig({
    plugins: [svelte({ hot: false })],
    test: {
        include: ['src/**/*.test.ts'],
        environment: 'jsdom',
        setupFiles: ['./vitest.setup.ts'],
    },
    resolve: {
        alias: {
            $lib: new URL('./src/lib', import.meta.url).pathname,
            '$app/navigation': new URL(
                './src/test-mocks/app-navigation.ts',
                import.meta.url,
            ).pathname,
        },
        conditions: ['browser'],
    },
});
