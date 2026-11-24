/** The part of noVNC's RFB client the shortcuts drive. */
export interface KeySender {
  sendKey(keysym: number, code: string | null, down?: boolean): void;
}

const XK_CONTROL_L = 0xffe3;

export const isApplePlatform = (
  platform = navigator.platform || navigator.userAgent,
) => /Mac|iPhone|iPad|iPod/.test(platform);

/**
 * On a Mac, the cloud desktop (Ubuntu) expects Ctrl where the Mac hand reaches for ⌘. While
 * the user has taken over, ⌘+key goes to the desktop as Ctrl+key and ⌘ alone is never sent (a
 * lone Super tap opens Ubuntu's overview; noVNC would otherwise send ⌘ as Alt). With a screen
 * session, the clipboard follows the shortcuts too: ⌘V pastes this Mac's clipboard into the
 * desktop and ⌘C / ⌘X copy what was selected there back to this Mac.
 *
 * Listens in the capture phase on `host` (noVNC's canvas lives inside it) so noVNC never sees
 * the ⌘ events; returns the cleanup.
 */
export function installMacShortcuts(
  host: HTMLElement,
  client: () => KeySender | null,
  clipboard: {
    paste: (text: string) => void;
    copyBack: () => void;
  } | null,
): () => void {
  // ⌘V leaves the keydown alone so the browser fires `paste` with this Mac's clipboard; if it
  // does not come, ask the clipboard API instead.
  let awaitingPaste = false;
  let pasteTimer: ReturnType<typeof setTimeout> | undefined;

  const onKeyDown = (e: KeyboardEvent) => {
    const rfb = client();
    if (!rfb) return;
    if (e.key === "Meta") {
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    if (!e.metaKey) return;
    e.stopPropagation();
    const key = e.key.length === 1 ? e.key.toLowerCase() : "";
    const keysym = key.charCodeAt(0);
    if (key === "v" && clipboard) {
      awaitingPaste = true;
      clearTimeout(pasteTimer);
      pasteTimer = setTimeout(() => {
        if (!awaitingPaste) return;
        awaitingPaste = false;
        void navigator.clipboard
          ?.readText()
          .then((text) => text && clipboard.paste(text))
          .catch(() => undefined);
      }, 300);
      return;
    }
    e.preventDefault();
    // Printable ASCII keys are their own X keysyms.
    if (!key || keysym < 0x20 || keysym > 0x7e) return;
    rfb.sendKey(XK_CONTROL_L, "ControlLeft", true);
    rfb.sendKey(keysym, e.code || null);
    rfb.sendKey(XK_CONTROL_L, "ControlLeft", false);
    if ((key === "c" || key === "x") && clipboard) clipboard.copyBack();
  };

  const onKeyUp = (e: KeyboardEvent) => {
    if (e.key === "Meta" || e.metaKey) {
      e.preventDefault();
      e.stopPropagation();
    }
  };

  const onPaste = (e: ClipboardEvent) => {
    if (!awaitingPaste || !clipboard) return;
    awaitingPaste = false;
    clearTimeout(pasteTimer);
    e.preventDefault();
    const text = e.clipboardData?.getData("text/plain") ?? "";
    if (text) clipboard.paste(text);
  };

  host.addEventListener("keydown", onKeyDown, true);
  host.addEventListener("keyup", onKeyUp, true);
  document.addEventListener("paste", onPaste, true);
  return () => {
    clearTimeout(pasteTimer);
    host.removeEventListener("keydown", onKeyDown, true);
    host.removeEventListener("keyup", onKeyUp, true);
    document.removeEventListener("paste", onPaste, true);
  };
}

/**
 * Write text that is still on its way to this device's clipboard. Call it inside the user's
 * gesture: the pending ClipboardItem keeps Safari's permission while the text arrives.
 * Resolves false when the browser refuses (the caller then shows the text instead).
 */
export async function copyToThisDevice(
  pending: Promise<string>,
): Promise<boolean> {
  if (navigator.clipboard?.write && typeof ClipboardItem !== "undefined") {
    const item = new ClipboardItem({
      "text/plain": pending.then(
        (value) => new Blob([value], { type: "text/plain" }),
      ),
    });
    if (
      await navigator.clipboard.write([item]).then(
        () => true,
        () => false,
      )
    ) {
      return true;
    }
  }
  if (!navigator.clipboard?.writeText) return false;
  const value = await pending;
  return navigator.clipboard.writeText(value).then(
    () => true,
    () => false,
  );
}
