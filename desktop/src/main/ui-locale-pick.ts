/**
 * The language for native menus and dialogs: the system's first preferred language.
 *
 * `app.getLocale()` alone is not enough on macOS: it only reports a language the
 * bundle declares, and the build ships `zh_CN.lproj` while macOS prefers "zh-Hans",
 * so a Chinese Mac gets "en".
 */
export function pickUiLocale(preferred: readonly string[], fallback: string): string {
  return preferred.find((lang) => lang.trim() !== "") ?? fallback;
}
