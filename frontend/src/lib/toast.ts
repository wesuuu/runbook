import { toast as sonnerToast } from 'svelte-sonner';

/**
 * Global toast notification API.
 *
 * Usage:
 *   import { toast } from '$lib/toast';
 *   toast.success('Saved');
 *   toast.error('Something went wrong');
 */

export type ToastLevel = 'success' | 'error' | 'warning' | 'info';

/** Last-resort body text per level when a caller supplies no message. */
const FALLBACK_MESSAGE: Record<ToastLevel, string> = {
	success: 'Done',
	error: 'Something went wrong',
	warning: 'Warning',
	info: 'Notice',
};

/**
 * Resolve the text a toast will actually render.
 *
 * A toast must never show an empty body (QA issue #14). When the caller
 * passes a blank message we promote the description into the message slot,
 * and if that is blank too we fall back to a generic per-level label.
 */
export function resolveToast(
	level: ToastLevel,
	message: string | null | undefined,
	description: string | null | undefined,
): { message: string; description?: string } {
	const msg = (message ?? '').trim();
	if (msg) {
		const desc = (description ?? '').trim();
		return desc ? { message: msg, description: desc } : { message: msg };
	}
	const desc = (description ?? '').trim();
	if (desc) return { message: desc };
	return { message: FALLBACK_MESSAGE[level] };
}

function show(
	level: ToastLevel,
	message: string | null | undefined,
	description: string | undefined,
	duration: number,
): void {
	const resolved = resolveToast(level, message, description);
	sonnerToast[level](resolved.message, {
		description: resolved.description,
		duration,
	});
}

export const toast = {
	success(message: string, description?: string) {
		show('success', message, description, 4000);
	},
	error(message: string, description?: string) {
		show('error', message, description, 6000);
	},
	warning(message: string, description?: string) {
		show('warning', message, description, 6000);
	},
	info(message: string, description?: string) {
		show('info', message, description, 4000);
	},
};
