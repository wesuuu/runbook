import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock html5-qrcode module
const mockStart = vi.fn().mockResolvedValue(undefined);
const mockStop = vi.fn().mockResolvedValue(undefined);
const mockClear = vi.fn();
const mockGetState = vi.fn().mockReturnValue(1);

vi.mock('html5-qrcode', () => {
    return {
        Html5Qrcode: vi.fn().mockImplementation(() => ({
            start: mockStart,
            stop: mockStop,
            clear: mockClear,
            getState: mockGetState,
        })),
        Html5QrcodeScannerState: {
            NOT_STARTED: 1,
            SCANNING: 2,
            PAUSED: 3,
        },
        Html5QrcodeSupportedFormats: {
            QR_CODE: 0,
            CODE_128: 2,
            CODE_39: 3,
            DATA_MATRIX: 16,
        },
    };
});

import {
    createScanner,
    stopScanner,
    SCANNER_CONFIG,
    playBeep,
    triggerHaptic,
} from './barcodeScannerUtils';

describe('barcodeScannerUtils', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    describe('SCANNER_CONFIG', () => {
        it('has a reasonable fps setting', () => {
            expect(SCANNER_CONFIG.fps).toBeGreaterThanOrEqual(5);
            expect(SCANNER_CONFIG.fps).toBeLessThanOrEqual(30);
        });

        it('has a scan region defined', () => {
            expect(SCANNER_CONFIG.qrbox).toBeDefined();
        });
    });

    describe('createScanner', () => {
        it('creates an Html5Qrcode instance with the given element ID', async () => {
            const { Html5Qrcode } = await import('html5-qrcode');
            const onScan = vi.fn();
            const onError = vi.fn();

            await createScanner('test-reader', onScan, onError);

            expect(Html5Qrcode).toHaveBeenCalledWith('test-reader', expect.any(Object));
        });

        it('starts scanning with the back camera by default', async () => {
            const onScan = vi.fn();
            const onError = vi.fn();

            await createScanner('test-reader', onScan, onError);

            expect(mockStart).toHaveBeenCalledWith(
                { facingMode: 'environment' },
                expect.any(Object),
                expect.any(Function),
                expect.any(Function),
            );
        });

        it('passes the onScan callback to the scanner start', async () => {
            const onScan = vi.fn();
            const onError = vi.fn();

            await createScanner('test-reader', onScan, onError);

            // Get the success callback that was passed to start()
            const successCallback = mockStart.mock.calls[0][2];
            successCallback('LOT-55291');

            expect(onScan).toHaveBeenCalledWith('LOT-55291');
        });

        it('configures Code 128, Code 39, QR Code, and DataMatrix formats', async () => {
            const { Html5Qrcode } = await import('html5-qrcode');
            await createScanner('test-reader', vi.fn(), vi.fn());

            const constructorCall = (Html5Qrcode as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
            const config = constructorCall[1];
            expect(config.formatsToSupport).toHaveLength(4);
        });

        it('returns the scanner instance for cleanup', async () => {
            const scanner = await createScanner('test-reader', vi.fn(), vi.fn());
            expect(scanner).toBeDefined();
            expect(scanner.stop).toBeDefined();
        });
    });

    describe('stopScanner', () => {
        it('stops a scanning scanner', async () => {
            mockGetState.mockReturnValue(2); // SCANNING
            const scanner = await createScanner('test-reader', vi.fn(), vi.fn());

            await stopScanner(scanner);

            expect(mockStop).toHaveBeenCalled();
            expect(mockClear).toHaveBeenCalled();
        });

        it('only clears a non-scanning scanner', async () => {
            mockGetState.mockReturnValue(1); // NOT_STARTED
            const scanner = await createScanner('test-reader', vi.fn(), vi.fn());

            await stopScanner(scanner);

            expect(mockStop).not.toHaveBeenCalled();
            expect(mockClear).toHaveBeenCalled();
        });

        it('handles null scanner gracefully', async () => {
            await expect(stopScanner(null)).resolves.toBeUndefined();
        });
    });

    describe('playBeep', () => {
        it('creates an AudioContext and plays a tone', () => {
            const mockOscillator = {
                type: '',
                frequency: { setValueAtTime: vi.fn() },
                connect: vi.fn(),
                start: vi.fn(),
                stop: vi.fn(),
            };
            const mockGain = {
                gain: { setValueAtTime: vi.fn() },
                connect: vi.fn(),
            };
            const mockAudioCtx = {
                createOscillator: vi.fn().mockReturnValue(mockOscillator),
                createGain: vi.fn().mockReturnValue(mockGain),
                destination: {},
                currentTime: 0,
            };
            vi.stubGlobal('AudioContext', vi.fn().mockImplementation(() => mockAudioCtx));

            playBeep();

            expect(mockAudioCtx.createOscillator).toHaveBeenCalled();
            expect(mockOscillator.start).toHaveBeenCalled();
            expect(mockOscillator.stop).toHaveBeenCalled();

            vi.unstubAllGlobals();
        });

        it('does not throw if AudioContext is unavailable', () => {
            vi.stubGlobal('AudioContext', undefined);
            expect(() => playBeep()).not.toThrow();
            vi.unstubAllGlobals();
        });
    });

    describe('triggerHaptic', () => {
        it('calls navigator.vibrate when available', () => {
            const vibrateMock = vi.fn();
            vi.stubGlobal('navigator', { vibrate: vibrateMock });

            triggerHaptic();

            expect(vibrateMock).toHaveBeenCalledWith(50);
            vi.unstubAllGlobals();
        });

        it('does not throw if vibrate is unavailable', () => {
            vi.stubGlobal('navigator', {});
            expect(() => triggerHaptic()).not.toThrow();
            vi.unstubAllGlobals();
        });
    });
});
