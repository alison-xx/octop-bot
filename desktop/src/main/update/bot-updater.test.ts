import assert from "node:assert/strict";
import { test } from "node:test";
import { BotUpdater, CHECK_INTERVAL_MS, FIRST_CHECK_DELAY_MS, type BotUpdaterDeps, type BotUpdateState } from "./bot-updater";
import type { SelectedRelease } from "./update-coordinator";

const release = (tag: string): SelectedRelease => ({
  tag,
  releasesUrl: "https://octop-bot.lynxce.cn/download.html",
  asset: { name: `Octop-Bot-Setup-${tag}-x64.exe`, ext: "exe", url: `https://dl.lynxce.cn/releases/octop-bot/${tag}/x.exe` },
});

function harness(overrides: Partial<BotUpdaterDeps> = {}) {
  const states: BotUpdateState["kind"][] = [];
  const notified: string[] = [];
  const timers: { run: () => void; ms: number }[] = [];
  const downloads: string[] = [];
  let next: SelectedRelease | null = release("1.0.4");
  const deps: BotUpdaterDeps = {
    select: async () => next,
    download: async (r) => {
      downloads.push(r.tag);
      return `/tmp/${r.tag}.exe`;
    },
    verify: async () => true,
    notifyReady: (r) => notified.push(r.tag),
    onChange: (s) => states.push(s.kind),
    log: () => {},
    setTimer: (run, ms) => {
      timers.push({ run, ms });
      return timers.length;
    },
    clearTimer: () => {},
    ...overrides,
  };
  return {
    updater: new BotUpdater(deps),
    states,
    notified,
    timers,
    downloads,
    setNext: (r: SelectedRelease | null) => {
      next = r;
    },
  };
}

test("a newer release is downloaded, verified and announced once", async () => {
  const h = harness();
  const state = await h.updater.check();
  assert.equal(state.kind, "ready");
  assert.deepEqual(h.states, ["checking", "downloading", "ready"]);
  assert.deepEqual(h.notified, ["1.0.4"]);
  await h.updater.check();
  assert.deepEqual(h.downloads, ["1.0.4"], "the waiting package is kept, not downloaded again");
  assert.deepEqual(h.notified, ["1.0.4"]);
  h.setNext(release("1.0.5"));
  await h.updater.check();
  assert.deepEqual(h.downloads, ["1.0.4", "1.0.5"]);
  assert.deepEqual(h.notified, ["1.0.4", "1.0.5"]);
});

test("nothing newer means idle and no notice", async () => {
  const h = harness();
  h.setNext(null);
  assert.equal((await h.updater.check()).kind, "idle");
  assert.deepEqual(h.notified, []);
});

test("a bad checksum is an error and nothing is offered", async () => {
  const h = harness({ verify: async () => false });
  const state = await h.updater.check();
  assert.equal(state.kind, "error");
  assert.deepEqual(h.notified, []);
});

test("a failed check keeps a package that is already waiting", async () => {
  let fail = false;
  const h = harness({
    select: async () => {
      if (fail) throw new Error("offline");
      return release("1.0.4");
    },
  });
  await h.updater.check();
  fail = true;
  assert.equal((await h.updater.check()).kind, "ready");
});

test("concurrent checks share one run", async () => {
  const h = harness();
  const [a, b] = await Promise.all([h.updater.check(), h.updater.check()]);
  assert.equal(a, b);
  assert.deepEqual(h.downloads, ["1.0.4"]);
});

test("the schedule checks soon after launch, then every few hours", async () => {
  const h = harness();
  h.updater.start();
  assert.equal(h.timers[0]?.ms, FIRST_CHECK_DELAY_MS);
  h.timers[0]!.run();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(h.timers[1]?.ms, CHECK_INTERVAL_MS);
});
