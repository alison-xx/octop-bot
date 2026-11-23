// Octop Bot for Apple silicon: Developer ID signed, hardened runtime, notarized.
// Run scripts/package-bot-mac.sh, which stages the runtime and sets these variables.
const { join } = require("node:path");

const staging = process.env.OCTOP_BOT_STAGING;
const version = process.env.OCTOP_BOT_PACKAGE_VERSION;
if (!staging || !version) throw new Error("Run scripts/package-bot-mac.sh.");
const entitlements = join(__dirname, "build", "entitlements.bot.mac.plist");

module.exports = {
  appId: "com.tencent.octop.bot",
  productName: "Octop Bot",
  extraMetadata: {
    name: "octop-bot",
    productName: "Octop Bot",
    description: "Octop Bot desktop client",
    version,
    octopBotClient: true,
  },
  directories: { output: "release/octop-bot-mac", buildResources: "resources" },
  npmRebuild: false,
  asar: true,
  electronLanguages: ["en", "zh_CN"],
  files: ["out/**/*", "package.json"],
  // The shell finds the expanded runtime at Contents/Resources/portable.
  extraResources: [
    { from: join(staging, "portable"), to: "portable", filter: ["**/*", "!**/__pycache__/**", "!**/*.pyc"] },
    { from: join(staging, "bot-icon.png"), to: "bot-icon.png" },
  ],
  mac: {
    target: ["dmg", "zip"],
    artifactName: "Octop-Bot-${version}-mac-${arch}.${ext}",
    category: "public.app-category.productivity",
    icon: join(staging, "bot-icon.icns"),
    identity: "Lynxce Technologies Pty Ltd (F7URANQHX7)",
    hardenedRuntime: true,
    gatekeeperAssess: false,
    entitlements,
    entitlementsInherit: entitlements,
    // Uses the notarytool keychain profile named in APPLE_KEYCHAIN_PROFILE.
    notarize: true,
    extendInfo: {
      NSMicrophoneUsageDescription: "Octop Bot uses the microphone to turn your speech into text.",
      NSSpeechRecognitionUsageDescription: "Octop Bot uses speech recognition to transcribe what you say.",
      NSScreenCaptureUsageDescription: "Octop Bot records the screen so it can show and control this computer's desktop.",
      NSLocalNetworkUsageDescription: "Octop Bot connects to services on your local network, such as a local model or your NAS.",
    },
  },
  dmg: {
    background: "resources/dmg-background.png",
    iconSize: 128,
    contents: [
      { x: 154, y: 237, type: "file" },
      { x: 454, y: 237, type: "link", path: "/Applications" },
    ],
  },
  publish: null,
};
