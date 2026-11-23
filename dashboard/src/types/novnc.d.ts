declare module "@novnc/novnc" {
  /** The parts of noVNC's RFB client Octop Bot uses. */
  export default class RFB extends EventTarget {
    constructor(
      target: HTMLElement,
      url: string,
      options?: { wsProtocols?: string[]; shared?: boolean },
    );
    viewOnly: boolean;
    scaleViewport: boolean;
    resizeSession: boolean;
    background: string;
    disconnect(): void;
    sendKey(keysym: number, code: string | null, down?: boolean): void;
  }
}
