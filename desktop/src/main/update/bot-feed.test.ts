import { generateKeyPairSync, sign } from "node:crypto";
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  BOT_FEED_PUBLIC_KEY,
  botDownloadManifest,
  inRollout,
  minimumSupported,
  releaseNotes,
  rolloutBucket,
  verifyBotManifest,
  type BotManifest,
} from "./bot-feed";
import { isValidAssetUrl, selectRelease } from "./update-coordinator";

const { publicKey, privateKey } = generateKeyPairSync("ed25519");
const pem = publicKey.export({ type: "spki", format: "pem" }).toString();

function signed(manifest: unknown): { body: string; signature: string } {
  const body = JSON.stringify(manifest, null, 2) + "\n";
  return { body, signature: sign(null, Buffer.from(body), privateKey).toString("base64") + "\n" };
}

const base = "https://dl.lynxce.cn/releases/octop-bot/1.0.4b1";
const sample: BotManifest = {
  schema: 1,
  product: "octop-bot",
  channels: {
    stable: {
      version: "1.0.3",
      min_supported: "1.0.2",
      assets: { win_x64: { name: "Octop-Bot-Setup-1.0.3-x64.exe", url: "https://dl.lynxce.cn/releases/octop-bot/1.0.3/Octop-Bot-Setup-1.0.3-x64.exe", sha256: "AB".repeat(32), size: 3 } },
    },
    beta: {
      version: "1.0.4b1",
      rollout: 100,
      notes: { zh: "自动更新", en: "Auto update" },
      assets: {
        win_x64: { name: "Octop-Bot-Setup-1.0.4b1-x64.exe", url: `${base}/Octop-Bot-Setup-1.0.4b1-x64.exe`, sha256: "cd".repeat(32) },
        mac_arm: { name: "Octop-Bot-1.0.4b1-mac-arm64.dmg", url: `${base}/Octop-Bot-1.0.4b1-mac-arm64.dmg` },
        android: { url: `${base}/octop-bot-1.0.4b1.apk` },
      },
    },
  },
};

test("verifyBotManifest accepts only our signature over the exact bytes", () => {
  const { body, signature } = signed(sample);
  assert.equal(verifyBotManifest(body, signature, pem).channels.beta?.version, "1.0.4b1");
  assert.throws(() => verifyBotManifest(body.replace("1.0.4b1", "9.9.9"), signature, pem), /signature/);
  assert.throws(() => verifyBotManifest(body, signature, BOT_FEED_PUBLIC_KEY), /signature/);
  assert.throws(() => verifyBotManifest(body, "not-base64", pem), /signature/);
  const wrongProduct = signed({ ...sample, product: "octop" });
  assert.throws(() => verifyBotManifest(wrongProduct.body, wrongProduct.signature, pem), /shape/);
});

test("the Bot manifest feeds the shared release selection", () => {
  const manifest = botDownloadManifest(sample, "install-1");
  const beta = selectRelease(manifest, "1.0.3b8", "win_x64", false);
  assert.equal(beta?.tag, "1.0.4b1");
  assert.equal(beta?.asset.sha256, "cd".repeat(32));
  assert.equal(beta?.asset.ext, "exe");
  assert.equal(selectRelease(manifest, "1.0.3b8", "win_x64", true)?.tag, "1.0.3");
  assert.equal(selectRelease(manifest, "1.0.4b1", "win_x64", false), null);
  assert.equal(selectRelease(manifest, "1.0.3", "mac_intel", false), null);
  assert.equal(manifest.client.stable?.assets.win_x64?.sha256, "ab".repeat(32));
  assert.ok(isValidAssetUrl(`${base}/x.exe`));
  assert.ok(!isValidAssetUrl("http://dl.lynxce.cn/x.exe"));
});

test("rollout buckets are stable per install and version", () => {
  assert.equal(rolloutBucket("a", "1.0.4"), rolloutBucket("a", "1.0.4"));
  const share = 30;
  const ids = Array.from({ length: 2000 }, (_, i) => `install-${i}`);
  const inside = ids.filter((id) => inRollout({ version: "1.0.4", rollout: share, assets: {} }, id)).length;
  assert.ok(inside > 450 && inside < 750, `about 30 % expected, got ${inside}`);
  assert.equal(inRollout({ version: "1.0.4", rollout: 0, assets: {} }, "x"), false);
  const held = botDownloadManifest(
    { ...sample, channels: { beta: { ...sample.channels.beta!, rollout: 0 } } },
    "install-1",
  );
  assert.equal(selectRelease(held, "1.0.3b8", "win_x64", false), null);
});

test("minimum supported version and release notes", () => {
  assert.equal(minimumSupported(sample), "1.0.2");
  assert.equal(releaseNotes(sample, "1.0.4b1", true), "自动更新");
  assert.equal(releaseNotes(sample, "1.0.4b1", false), "Auto update");
  assert.equal(releaseNotes(sample, "0.0.1", true), "");
});
