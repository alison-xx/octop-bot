/**
 * Background updates for the Octop Bot desktop app.
 *
 * Never interrupts: it checks 30 s after launch and every 6 hours, downloads a
 * newer release in the background, verifies its SHA-256 from the signed
 * manifest, and only then tells the user once ("ready, restart to update").
 * Installing is always the user's click (notification, tray or app menu).
 * Everything with side effects is injected so the schedule and the state
 * machine are unit-tested without Electron.
 */

import type { SelectedRelease } from "./update-coordinator";

export const FIRST_CHECK_DELAY_MS = 30_000;
export const CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000;

export type BotUpdateState =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "downloading"; release: SelectedRelease }
  | { kind: "ready"; release: SelectedRelease; path: string }
  | { kind: "error"; message: string };

export interface BotUpdaterDeps {
  /** The newest installable release for this install, or `null` when current. */
  select(): Promise<SelectedRelease | null>;
  /** Download the release's package to a staging file; resolves to its path. */
  download(release: SelectedRelease): Promise<string>;
  /** Integrity check of a downloaded package against the manifest digest. */
  verify(release: SelectedRelease, path: string): Promise<boolean>;
  /** Tell the user a release is ready (once per version). */
  notifyReady(release: SelectedRelease): void;
  /** Rebuild menus that show the update state. */
  onChange(state: BotUpdateState): void;
  log(message: string): void;
  setTimer(run: () => void, ms: number): unknown;
  clearTimer(handle: unknown): void;
}

export class BotUpdater {
  private state: BotUpdateState = { kind: "idle" };
  private timer: unknown = null;
  private running: Promise<BotUpdateState> | null = null;
  private notified = new Set<string>();
  private readonly deps: BotUpdaterDeps;

  constructor(deps: BotUpdaterDeps) {
    this.deps = deps;
  }

  get current(): BotUpdateState {
    return this.state;
  }

  /** Start the schedule: first check soon after launch, then every few hours. */
  start(): void {
    this.schedule(FIRST_CHECK_DELAY_MS);
  }

  stop(): void {
    if (this.timer !== null) this.deps.clearTimer(this.timer);
    this.timer = null;
  }

  private schedule(ms: number): void {
    this.stop();
    this.timer = this.deps.setTimer(() => {
      void this.check().finally(() => this.schedule(CHECK_INTERVAL_MS));
    }, ms);
  }

  private set(state: BotUpdateState): void {
    this.state = state;
    this.deps.onChange(state);
  }

  /**
   * Check now, download and verify in the background. Concurrent calls share
   * one run; a release that is already downloaded and verified is kept.
   */
  check(): Promise<BotUpdateState> {
    this.running ??= this.run().finally(() => {
      this.running = null;
    });
    return this.running;
  }

  private async run(): Promise<BotUpdateState> {
    const before = this.state;
    if (before.kind !== "ready") this.set({ kind: "checking" });
    let release: SelectedRelease | null;
    try {
      release = await this.deps.select();
    } catch (err) {
      this.deps.log(`update check failed: ${String(err)}`);
      // A failed check keeps a package that is already waiting.
      this.set(before.kind === "ready" ? before : { kind: "error", message: messageOf(err) });
      return this.state;
    }
    if (!release) {
      this.set({ kind: "idle" });
      return this.state;
    }
    if (before.kind === "ready" && before.release.tag === release.tag) {
      this.set(before);
      return this.state;
    }
    this.set({ kind: "downloading", release });
    try {
      const path = await this.deps.download(release);
      if (!(await this.deps.verify(release, path))) throw new Error("package checksum does not match the manifest");
      this.set({ kind: "ready", release, path });
      if (!this.notified.has(release.tag)) {
        this.notified.add(release.tag);
        this.deps.notifyReady(release);
      }
    } catch (err) {
      this.deps.log(`update download failed: ${String(err)}`);
      this.set({ kind: "error", message: messageOf(err) });
    }
    return this.state;
  }
}

function messageOf(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
