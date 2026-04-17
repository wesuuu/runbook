import { toast as sonnerToast } from 'svelte-sonner';

/**
 * Global toast notification API.
 *
 * Usage:
 *   import { toast } from '$lib/toast';
 *   toast.success('Saved');
 *   toast.error('Something went wrong');
 */
export const toast = {
	success(message: string, description?: string) {
		sonnerToast.success(message, { description, duration: 4000 });
	},
	error(message: string, description?: string) {
		sonnerToast.error(message, { description, duration: 6000 });
	},
	warning(message: string, description?: string) {
		sonnerToast.warning(message, { description, duration: 6000 });
	},
	info(message: string, description?: string) {
		sonnerToast.info(message, { description, duration: 4000 });
	},
};
