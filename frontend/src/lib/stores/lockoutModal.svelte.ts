let open = $state(false);
let message = $state<string>(
    'Your subscription is not active. Reads remain available, but new changes are blocked.'
);

export const lockoutModal = {
    get open() { return open; },
    get message() { return message; },
};

export function showLockout(msg?: string) {
    if (msg) message = msg;
    open = true;
}

export function dismissLockout() {
    open = false;
}
