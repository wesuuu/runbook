<script lang="ts">
    import {
        createScanner,
        stopScanner,
        playBeep,
        triggerHaptic,
    } from './barcodeScannerUtils';
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';

    interface Props {
        open: boolean;
        onScan: (value: string) => void;
        onClose: () => void;
    }

    let { open, onScan, onClose }: Props = $props();

    let scanner: Awaited<ReturnType<typeof createScanner>> | null = $state(null);
    let error: string | null = $state(null);
    let scannedValue: string | null = $state(null);
    let readerElement: HTMLDivElement | undefined = $state();

    const READER_ID = 'barcode-scanner-reader';

    async function startScanning() {
        error = null;
        scannedValue = null;

        // Wait for DOM to render the reader element
        await new Promise((r) => setTimeout(r, 50));

        try {
            scanner = await createScanner(
                READER_ID,
                handleScanSuccess,
                handleScanError,
            );
        } catch (e: unknown) {
            if (e instanceof Error) {
                const msg = e.message.toLowerCase();
                if (msg.includes('permission') || msg.includes('denied') || msg.includes('notallowed')) {
                    error = 'Camera access denied. Please allow camera permissions in your browser settings and try again.';
                } else if (msg.includes('notfound') || msg.includes('no camera')) {
                    error = 'No camera found. Make sure your device has a camera connected.';
                } else {
                    error = `Camera error: ${e.message}`;
                }
            } else {
                error = 'Failed to start camera. Please try again.';
            }
        }
    }

    function handleScanSuccess(decodedText: string) {
        scannedValue = decodedText;
        playBeep();
        triggerHaptic();

        // Brief delay to show the scanned value, then close
        setTimeout(() => {
            onScan(decodedText);
            handleClose();
        }, 600);
    }

    function handleScanError(errorMessage: string) {
        // html5-qrcode fires this continuously — only surface real errors
        if (errorMessage.includes('No MultiFormat Readers')) return;
        console.warn('Scan error:', errorMessage);
    }

    async function handleClose() {
        await stopScanner(scanner);
        scanner = null;
        scannedValue = null;
        error = null;
        onClose();
    }

    $effect(() => {
        if (open) {
            startScanning();
        }
        return () => {
            if (scanner) {
                stopScanner(scanner);
                scanner = null;
            }
        };
    });

    function handleOpenChange(value: boolean) {
        if (!value) handleClose();
    }
</script>

<Dialog.Root {open} onOpenChange={handleOpenChange}>
    <Dialog.Content class="sm:max-w-md p-0 gap-0">
        <!-- Header -->
        <div class="flex items-center gap-2.5 px-5 py-4 border-b border-border">
            <div class="w-8 h-8 rounded-lg bg-teal-100 flex items-center justify-center">
                <svg class="w-4.5 h-4.5 text-teal-700" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 4.875c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5A1.125 1.125 0 013.75 9.375v-4.5zM3.75 14.625c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5a1.125 1.125 0 01-1.125-1.125v-4.5zM13.5 4.875c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5A1.125 1.125 0 0113.5 9.375v-4.5z" />
                    <path stroke-linecap="round" stroke-linejoin="round" d="M6.75 6.75h.75v.75h-.75v-.75zM6.75 16.5h.75v.75h-.75v-.75zM16.5 6.75h.75v.75H16.5v-.75zM13.5 13.5h.75v.75h-.75v-.75zM13.5 19.5h.75v.75h-.75v-.75zM19.5 13.5h.75v.75h-.75v-.75zM19.5 19.5h.75v.75h-.75v-.75zM16.5 16.5h.75v.75H16.5v-.75z" />
                </svg>
            </div>
            <h3 class="text-lg font-semibold text-foreground">Scan Barcode</h3>
        </div>

        <!-- Scanner Area -->
        <div class="px-5 py-4">
            {#if error}
                <div class="rounded-xl bg-red-50 border border-red-200 p-4 text-center">
                    <svg class="w-10 h-10 text-red-400 mx-auto mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z" />
                        <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0zM18.75 10.5h.008v.008h-.008V10.5z" />
                    </svg>
                    <p class="text-sm text-red-700 font-medium">{error}</p>
                </div>
            {:else if scannedValue}
                <div class="rounded-xl bg-teal-50 border border-teal-200 p-6 text-center">
                    <svg class="w-12 h-12 text-teal-500 mx-auto mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <p class="text-xs text-teal-600 font-medium uppercase tracking-wide mb-1">Scanned</p>
                    <p class="text-xl font-mono font-bold text-teal-900 break-all">{scannedValue}</p>
                </div>
            {:else}
                <div
                    data-testid="scanner-viewfinder"
                    class="relative rounded-xl overflow-hidden bg-slate-900"
                >
                    <div id={READER_ID} bind:this={readerElement} class="w-full"></div>
                    <!-- Scan guide overlay -->
                    <div class="absolute inset-0 pointer-events-none flex items-center justify-center">
                        <div class="w-56 h-56 border-2 border-white/30 rounded-lg relative">
                            <!-- Corner accents -->
                            <div class="absolute -top-0.5 -left-0.5 w-6 h-6 border-t-3 border-l-3 border-teal-400 rounded-tl-sm"></div>
                            <div class="absolute -top-0.5 -right-0.5 w-6 h-6 border-t-3 border-r-3 border-teal-400 rounded-tr-sm"></div>
                            <div class="absolute -bottom-0.5 -left-0.5 w-6 h-6 border-b-3 border-l-3 border-teal-400 rounded-bl-sm"></div>
                            <div class="absolute -bottom-0.5 -right-0.5 w-6 h-6 border-b-3 border-r-3 border-teal-400 rounded-br-sm"></div>
                            <!-- Scanning line animation -->
                            <div class="absolute left-2 right-2 h-0.5 bg-teal-400/70 animate-scan"></div>
                        </div>
                    </div>
                </div>
                <p class="text-center text-sm text-muted-foreground mt-3">
                    Point your camera at a barcode or QR code
                </p>
            {/if}
        </div>

        <!-- Footer -->
        <div class="px-5 py-3 border-t border-border flex items-center justify-between">
            <Button
                variant="link"
                size="sm"
                class="h-auto p-0 text-sm font-medium"
                onclick={handleClose}
            >
                Type manually
            </Button>
            <span class="text-xs text-muted-foreground">
                Code 128 / Code 39 / QR / DataMatrix
            </span>
        </div>
    </Dialog.Content>
</Dialog.Root>

<style>
    @keyframes scan {
        0%, 100% { top: 8px; }
        50% { top: calc(100% - 10px); }
    }
    .animate-scan {
        animation: scan 2s ease-in-out infinite;
    }
    /* Hide html5-qrcode default UI elements */
    :global(#barcode-scanner-reader video) {
        border-radius: 0.75rem;
    }
    :global(#barcode-scanner-reader img[alt="Info icon"]) {
        display: none !important;
    }
    :global(#barcode-scanner-reader a[rel="noopener noreferrer"]) {
        display: none !important;
    }
</style>
