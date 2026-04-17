// html5-qrcode is loaded lazily via dynamic import to avoid side effects
// (the library injects DOM elements when loaded eagerly)

export const SCANNER_CONFIG = {
    fps: 10,
    qrbox: { width: 250, height: 250 },
    aspectRatio: 1.0,
};

// Scanner instance type — avoids importing the type at module level
type Scanner = {
    start: (
        cameraId: { facingMode: string },
        config: typeof SCANNER_CONFIG,
        onSuccess: (text: string) => void,
        onError: () => void,
    ) => Promise<void>;
    stop: () => Promise<void>;
    clear: () => void;
    getState: () => number;
};

export async function createScanner(
    elementId: string,
    onScan: (decodedText: string) => void,
    onError: (error: string) => void,
): Promise<Scanner> {
    const {
        Html5Qrcode,
        Html5QrcodeSupportedFormats,
    } = await import('html5-qrcode');

    const formats = [
        Html5QrcodeSupportedFormats.CODE_128,
        Html5QrcodeSupportedFormats.CODE_39,
        Html5QrcodeSupportedFormats.QR_CODE,
        Html5QrcodeSupportedFormats.DATA_MATRIX,
    ];

    const scanner = new Html5Qrcode(elementId, {
        formatsToSupport: formats,
        verbose: false,
    });

    await scanner.start(
        { facingMode: 'environment' },
        SCANNER_CONFIG,
        onScan,
        // html5-qrcode fires this continuously when no code is detected — not a real error
        () => {},
    );

    return scanner as unknown as Scanner;
}

export async function stopScanner(scanner: Scanner | null): Promise<void> {
    if (!scanner) return;
    try {
        const { Html5QrcodeScannerState } = await import('html5-qrcode');
        if (scanner.getState() === Html5QrcodeScannerState.SCANNING) {
            await scanner.stop();
        }
        scanner.clear();
    } catch {
        // Scanner may already be stopped
    }
}

export function playBeep(): void {
    try {
        if (typeof AudioContext === 'undefined') return;
        const ctx = new AudioContext();
        const oscillator = ctx.createOscillator();
        const gain = ctx.createGain();

        oscillator.type = 'sine';
        oscillator.frequency.setValueAtTime(1200, ctx.currentTime);
        gain.gain.setValueAtTime(0.3, ctx.currentTime);

        oscillator.connect(gain);
        gain.connect(ctx.destination);

        oscillator.start(ctx.currentTime);
        oscillator.stop(ctx.currentTime + 0.15);
    } catch {
        // Audio not available — silent fallback
    }
}

export function triggerHaptic(): void {
    try {
        if (navigator?.vibrate) {
            navigator.vibrate(50);
        }
    } catch {
        // Haptic not available
    }
}
