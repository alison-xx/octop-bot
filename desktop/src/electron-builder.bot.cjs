const { dirname, join } = require("node:path");

const staging = process.env.OCTOP_BOT_STAGING;
const version = process.env.OCTOP_BOT_PACKAGE_VERSION;
const certificateSha1 = process.env.OCTOP_BOT_SIGN_CERT_SHA1?.trim();
if (!staging || !version) throw new Error("Run the package:bot:win script.");

module.exports = {
  forceCodeSigning: Boolean(certificateSha1),
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
  electronDist: dirname(require("electron")),
  npmRebuild: false,
  toolsets: { winCodeSign: "1.1.0", nsis: "1.2.1" },
  asar: true,
  electronLanguages: ["en", "zh_CN"],
  files: ["out/**/*", "package.json"],
  extraResources: [
    { from: join(staging, "portable"), to: "sidecar", filter: ["**/*", "!**/__pycache__/**", "!**/*.pyc"] },
    { from: join(staging, "bot-icon.ico"), to: "bot-icon.ico" },
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
