import type { EarlyShellBridge } from "../preload/early";
import type { OctopDesktopBridge } from "../preload/index";

declare global {
  interface Window {
    botOrb?: import("../preload/orb").OrbBridge;
    /** The "Connect to a server" window: check an address and switch to it. */
    octopServer?: import("../preload/server").ServerBridge;
    octopDesktop?: OctopDesktopBridge;
    /**
     * Bridge for the shell's own pages (splash + fatal error). Those pages are
     * separate documents from the Dashboard and expose one method, not the
     * Dashboard's API.
     */
    octopShell?: EarlyShellBridge;
  }
}

export {};
