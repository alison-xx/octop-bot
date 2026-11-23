/** What a self-hosted server's page may use: notifications, the microphone for voice input, copying. */
const REMOTE_PERMISSIONS = new Set(["notifications", "media", "clipboard-sanitized-write", "fullscreen"]);

/**
 * Should a permission request from a self-hosted server's page be granted?
 * Only pages on that server's origin ask, and "media" covers the microphone
 * alone: a request that names the camera (or no device at all) is refused.
 */
export function allowRemotePermission(input: {
  origin: string;
  requestingUrl: string;
  permission: string;
  mediaTypes?: readonly string[];
}): boolean {
  let requestingOrigin = "";
  try {
    requestingOrigin = new URL(input.requestingUrl).origin;
  } catch {
    return false;
  }
  if (requestingOrigin !== input.origin || !REMOTE_PERMISSIONS.has(input.permission)) return false;
  if (input.permission !== "media") return true;
  const types = input.mediaTypes ?? [];
  return types.length > 0 && types.every((type) => type === "audio");
}
