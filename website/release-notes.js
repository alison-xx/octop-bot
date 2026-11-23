(() => {
  const base = "https://dl.lynxce.cn/releases/octop-bot/";
  const packages = {
    installer: {id:"installer", platform:"win32", arch:"x64", ext:"EXE", label:["Windows 安装版","Windows installer"], name:v => "Octop-Bot-Setup-" + v + "-x64.exe"},
    portable: {id:"portable", platform:"win32", arch:"x64", ext:"ZIP", label:["Windows 免安装版","Windows portable edition"], name:v => "Octop-Bot-" + v + "-x64.zip"},
    dmg: {id:"mac-installer", platform:"darwin", arch:"arm64", ext:"DMG", label:["macOS · Apple 芯片","macOS · Apple silicon"], name:v => "Octop-Bot-" + v + "-mac-arm64.dmg"}
  };
  const versionPattern = /^\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)*)?$/;
  let releases = [];
  function validRelease(release) {
    return release && versionPattern.test(release.version) && ["stable","beta"].includes(release.channel)
      && /^\d{4}-\d{2}-\d{2}$/.test(release.date)
      && ["zh","en"].every(lang => Array.isArray(release.notes?.[lang]) && release.notes[lang].every(note => typeof note === "string"))
      && Array.isArray(release.assets) && release.assets.length > 0
      && release.assets.every(asset => {
        const p = Object.hasOwn(packages,asset?.kind) && packages[asset.kind];
        return p && p.platform === asset.platform && p.arch === asset.arch && asset.name === p.name(release.version)
          && Number.isSafeInteger(asset.size) && asset.size > 0 && /^[0-9a-f]{64}$/i.test(asset.sha256);
      });
  }
  function element(tag,text) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function fileLink(release,name,label) {
    const link = element("a",label);
    link.href = base + release.version + "/" + name;
    return link;
  }
  function render() {
    if (!releases.length) return;
    const en = document.documentElement.lang === "en";
    const lang = en ? "en" : "zh";
    const history = releases.map(release => {
      const article = element("article");
      article.className = "release-entry";
      article.id = "release-" + release.version;
      const date = element("time",release.date);
      date.dateTime = release.date;
      const content = element("div");
      const heading = element("h3",release.version);
      heading.append(element("span",release.channel === "beta" ? (en ? "Beta" : "预发布") : (en ? "Stable" : "正式版")));
      const notes = element("ul");
      for (const note of release.notes[lang]) notes.append(element("li",note));
      const links = element("div");
      links.className = "release-files";
      for (const asset of release.assets) links.append(fileLink(release,asset.name,packages[asset.kind].label[Number(en)]));
      links.append(fileLink(release,"SHA256SUMS.txt","SHA-256"));
      content.append(heading,notes,links);
      article.append(date,content);
      return article;
    });
    document.querySelector("#release-history").replaceChildren(...history);
    const versions = new Map();
    for (const [kind,p] of Object.entries(packages)) {
      const link = document.getElementById(p.id);
      // The catalog is published in descending SemVer order. Prefer a stable
      // package for this format even if another platform is still beta-only.
      const available = releases.filter(r => r.assets.some(a => a.kind === kind));
      const release = available.find(r => r.channel === "stable") || available[0];
      link.hidden = !release;
      if (!release) continue;
      const asset = release.assets.find(a => a.kind === kind);
      link.href = base + release.version + "/" + asset.name;
      link.querySelector("small").textContent = [release.version,p.ext,p.arch,(asset.size/1048576).toFixed(1) + " MiB"].join(" · ");
      versions.set(release.version,release);
    }
    const badge = document.querySelector(".package-title .ant-tag");
    badge.hidden = versions.size !== 1;
    badge.textContent = versions.size === 1 ? [...versions.keys()][0] : "";
    let checks = document.querySelector(".release-checks");
    if (!checks) {
      checks = element("div");
      checks.className = "release-checks";
      document.getElementById("checksums").replaceWith(checks);
    }
    checks.replaceChildren(...[...versions.values()].map(r => {
      const a = fileLink(r,"SHA256SUMS.txt",en ? "SHA-256 checksums · " + r.version : "SHA-256 校验值 · " + r.version);
      a.className = "checksum";
      return a;
    }));
  }
  window.addEventListener("sitepreferenceschange",render);
  fetch("releases.json",{cache:"no-store"}).then(response => {
    if (!response.ok) throw Error("Release catalog unavailable");
    return response.json();
  }).then(catalog => {
    if (catalog.product !== "octop-bot" || catalog.schemaVersion !== 1 ||
        !Array.isArray(catalog.releases) || !catalog.releases.length || !catalog.releases.every(validRelease)) throw Error("Invalid release catalog");
    releases = catalog.releases;
    render();
  }).catch(() => {
    // The last published download links and release summary remain usable.
  });
})();
