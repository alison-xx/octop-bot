const sitePreferences = (() => {
  const darkSystem = window.matchMedia("(prefers-color-scheme: dark)");
  const choices = { language: ["auto", "zh", "en"], theme: ["auto", "light", "dark"] };
  const values = { language: "auto", theme: "auto" };
  for (const key of Object.keys(choices)) {
    try {
      const saved = localStorage.getItem("octop-site-" + key);
      if (choices[key].includes(saved)) values[key] = saved;
    } catch {}
  }
  function resolve() {
    const languages = navigator.languages?.length ? navigator.languages : [navigator.language];
    const matched = languages.map(tag => tag.toLowerCase().split("-")[0]).find(code => code === "zh" || code === "en");
    const language = values.language === "auto" ? (matched || "en") : values.language;
    const theme = values.theme === "auto" ? (darkSystem.matches ? "dark" : "light") : values.theme;
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
    document.documentElement.dataset.theme = theme;
    return { language, theme };
  }
  function set(key, value) {
    if (!choices[key]?.includes(value)) return;
    values[key] = value;
    try { localStorage.setItem("octop-site-" + key, value); } catch {}
    window.dispatchEvent(new Event("sitepreferenceschange"));
  }
  function changed() { window.dispatchEvent(new Event("sitepreferenceschange")); }
  darkSystem.addEventListener("change", changed);
  window.addEventListener("languagechange", changed);
  resolve();
  return { resolve, set, values };
})();
