const { dirname, join } = require("node:path");
// Info.plist usage strings, shared with electron-builder.config.ts. Loaded only
// on macOS so the Windows build does not need TypeScript support in Node.
const macPrivacy = process.platform === "darwin" ? require("./mac-privacy-plist.ts") : null;

const staging = process.env.OCTOP_BOT_STAGING;
const version = process.env.OCTOP_BOT_PACKAGE_VERSION;
const certificateSha1 = process.env.OCTOP_BOT_SIGN_CERT_SHA1?.trim();
// package-bot-mac.py sets this unless --unsigned. Signing uses the Developer ID
// Application identity from the keychain (or CSC_LINK in CI); notarization reads
// APPLE_KEYCHAIN_PROFILE or APPLE_API_KEY / APPLE_API_KEY_ID / APPLE_API_ISSUER.
const macSign = process.env.OCTOP_BOT_MAC_SIGN === "1";
if (!staging || !version) throw new Error("Run the package:bot:win or package:bot:mac script.");
// osx-sign signs every file that looks binary. In the Python runtime only the
// Mach-O files need a signature, so skip its data files (botocore .json.gz,
// images, fonts, Windows DLLs, static archives).
const MAC_DATA_FILES =
  "/Contents/Resources/sidecar/.+\\.(gz|png|gif|jpe?g|webp|ico|emf|ttf|pickle|whl|pptx|docx|a|o|obj|dll|pyc)$";

module.exports = {
  forceCodeSigning: Boolean(certificateSha1) || macSign,
  appId: "com.tencent.octop.bot",
  productName: "Octop Bot",
  extraMetadata: {
    name: "octop-bot",
    productName: "Octop Bot",
    description: "Octop Bot desktop client",
    version,
    octopBotClient: true,
  },
  directories: { output: "release/octop-bot", buildResources: "resources" },
  // octop-bot://market/<slug> from the website's Bot market (Info.plist / NSIS registry).
  protocols: [{ name: "Octop Bot", schemes: ["octop-bot"] }],
  // require("electron") is dist/electron.exe on Windows but a path inside
  // Electron.app on macOS; electron-builder wants the dist directory itself.
  // Electron 45 has no postinstall; requiring it downloads the binary on first use.
  electronDist: (require("electron"), join(dirname(require.resolve("electron/package.json")), "dist")),
  npmRebuild: false,
  toolsets: { winCodeSign: "1.1.0", nsis: "1.2.1" },
  asar: true,
  electronLanguages: ["en", "zh_CN"],
  files: ["out/**/*", "package.json"],
  extraResources: [
    { from: join(staging, "portable"), to: "sidecar", filter: ["**/*", "!**/__pycache__/**", "!**/*.pyc"] },
    ...(process.platform === "darwin" ? [] : [{ from: join(staging, "bot-icon.ico"), to: "bot-icon.ico" }]),
    ...(process.platform === "win32" ? [{ from: join(__dirname, "resources/bot-tray.ico"), to: "bot-tray.ico" }] : []),
    { from: join(staging, "bot-icon.png"), to: "bot-icon.png" },
  ],
  win: {
    icon: join(staging, "bot-icon.ico"),
    executableName: "Octop Bot",
    target: ["nsis"],
    ...(certificateSha1 && {
      // Keep vendor signatures on the bundled Python runtime and third-party executables.
      signExts: ["Octop Bot.exe", ".__uninstaller.exe", `Octop-Bot-Setup-${version}-x64.exe`, "!.exe"],
      signtoolOptions: {
        certificateSha1,
        signingHashAlgorithms: ["sha256"],
        rfc3161TimeStampServer: "http://time.certum.pl",
      },
    }),
  },
  mac: {
    icon: join(staging, "bot-icon.png"),
    target: ["dmg"],
    category: "public.app-category.productivity",
    artifactName: "Octop-Bot-${version}-mac-${arch}.${ext}",
    extendInfo: macPrivacy?.macPrivacyExtendInfo(),
    ...(macSign
      ? {
          hardenedRuntime: true,
          entitlements: "build/entitlements.bot.mac.plist",
          entitlementsInherit: "build/entitlements.bot.mac.plist",
          // Every Mach-O file in the Python runtime is signed; data files are not.
          signIgnore: [MAC_DATA_FILES],
          notarize: true,
        }
      : { identity: null, notarize: false }),
  },
  dmg: {
    // package-bot-mac.py notarizes and staples the signed DMG afterwards.
    sign: macSign,
    background: "resources/dmg-background.png",
    iconSize: 128,
    contents: [
      { x: 154, y: 237, type: "file" },
      { x: 454, y: 237, type: "link", path: "/Applications" },
    ],
  },
  afterPack(context) {
    if (context.electronPlatformName !== "darwin") return;
    macPrivacy.writeMacPrivacyLocalizations(
      join(context.appOutDir, "Octop Bot.app", "Contents", "Resources"),
    );
  },
  nsis: {
    artifactName: "Octop-Bot-Setup-${version}-${arch}.${ext}",
    oneClick: false,
    perMachine: false,
    allowToChangeInstallationDirectory: true,
    createDesktopShortcut: true,
    deleteAppDataOnUninstall: false,
    shortcutName: "Octop Bot",
  },
  publish: null,
};
