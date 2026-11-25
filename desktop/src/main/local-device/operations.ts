import { createHash } from "node:crypto";
import { exec } from "node:child_process";
import { constants } from "node:fs";
import { open, opendir, realpath, stat } from "node:fs/promises";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { promisify } from "node:util";

const runCommand = promisify(exec);
const limit = 32_768;
export interface DesktopRequest {
  id: string;
  bot: string;
  action:
    | "list"
    | "read"
    | "write"
    | "run"
    | "send_to_cloud"
    | "fetch_from_cloud";
  cloud_path: string;
  destination: string;
  size: number | null;
  reason: string;
  path: string;
  command: string;
  text: string;
}

export function parseRequest(
  raw: Record<string, unknown>,
): DesktopRequest | null {
  if (
    ![
      "list",
      "read",
      "write",
      "run",
      "send_to_cloud",
      "fetch_from_cloud",
    ].includes(String(raw.action))
  )
    return null;
  for (const [key, max] of Object.entries({
    id: 64,
    bot: 250,
    reason: 500,
    path: 1024,
    cloud_path: 1024,
    destination: 1100,
    command: 4000,
    text: limit,
  })) {
    if (typeof raw[key] !== "string" || raw[key].length > max) return null;
  }
  if (!raw.id || !raw.path || !raw.reason || !raw.bot) return null;
  // Native approval must show the exact single-line command and destination.
  const hidden = /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u;
  if (
    [
      raw.id,
      raw.bot,
      raw.reason,
      raw.path,
      raw.command,
      raw.destination,
      raw.cloud_path,
    ].some((value) => hidden.test(String(value)))
  )
    return null;
  if ((raw.action === "run") !== Boolean(String(raw.command).trim()))
    return null;
  if (
    raw.action === "fetch_from_cloud" &&
    (!raw.cloud_path ||
      !Number.isSafeInteger(raw.size) ||
      Number(raw.size) < 0 ||
      Number(raw.size) > transferLimit)
  )
    return null;
  if (raw.action === "send_to_cloud" && !raw.destination) return null;
  return raw as unknown as DesktopRequest;
}

/** Existing paths and parents are resolved on this device, including links and junctions. */
async function inside(
  root: string,
  path: string,
  writing: boolean,
): Promise<string> {
  if (isAbsolute(path) || path.includes("\0"))
    throw new Error("Choose a relative path.");
  const base = await realpath(root);
  const target = resolve(base, path);
  const resolved = writing
    ? resolve(
        await realpath(dirname(target)),
        relative(dirname(target), target),
      )
    : await realpath(target);
  const rel = relative(base, resolved);
  if (rel === ".." || rel.startsWith(".." + sep) || isAbsolute(rel))
    throw new Error("Outside the selected folder.");
  return resolved;
}

const transferLimit = 1024 * 1024;
type FileIdentity = {
  size: number;
  dev: number;
  ino: number;
  mtimeMs: number;
  ctimeMs: number;
};
export interface Transfer {
  size: number;
  sha256: string;
  content: string;
}

export async function describeUpload(
  root: string,
  path: string,
): Promise<FileIdentity> {
  const info = await stat(await inside(root, path, false));
  if (!info.isFile() || info.size > transferLimit)
    throw new Error("Choose a regular file of at most 1 MiB.");
  return {
    size: info.size,
    dev: info.dev,
    ino: info.ino,
    mtimeMs: info.mtimeMs,
    ctimeMs: info.ctimeMs,
  };
}

export async function approvedUpload(
  root: string,
  path: string,
  expected: FileIdentity,
  signal: AbortSignal,
): Promise<Transfer> {
  signal.throwIfAborted();
  const file = await open(
    await inside(root, path, false),
    constants.O_RDONLY |
      (constants.O_NOFOLLOW ?? 0) |
      (constants.O_NONBLOCK ?? 0),
  );
  try {
    const data = Buffer.alloc(expected.size + 1);
    const verify = async () => {
      const info = await file.stat();
      if (
        !info.isFile() ||
        info.size !== expected.size ||
        info.dev !== expected.dev ||
        info.ino !== expected.ino ||
        info.mtimeMs !== expected.mtimeMs ||
        info.ctimeMs !== expected.ctimeMs
      )
        throw new Error("The selected file changed. Request approval again.");
    };
    await verify();
    let length = 0;
    while (length < data.length) {
      signal.throwIfAborted();
      const part = await file.read(data, length, data.length - length, length);
      if (!part.bytesRead) break;
      length += part.bytesRead;
    }
    await verify();
    signal.throwIfAborted();
    if (length !== expected.size) throw new Error("The selected file changed.");
    const content = data.subarray(0, length);
    return {
      size: length,
      sha256: createHash("sha256").update(content).digest("hex"),
      content: content.toString("base64"),
    };
  } finally {
    await file.close();
  }
}

/** Called only after the native user's one-time approval and a matching live request. */
export async function performApproved(
  root: string,
  r: DesktopRequest,
  signal: AbortSignal,
  transfer?: Transfer,
): Promise<string> {
  signal.throwIfAborted();
  const target = await inside(
    root,
    r.path,
    r.action === "write" || r.action === "fetch_from_cloud",
  );
  signal.throwIfAborted();
  if (r.action === "send_to_cloud")
    throw new Error("Local upload needs its approved file identity.");
  if (r.action === "fetch_from_cloud") {
    if (
      !transfer ||
      transfer.size !== r.size ||
      typeof transfer.content !== "string" ||
      transfer.content.length > Math.ceil(transferLimit / 3) * 4
    )
      throw new Error("Incomplete file transfer.");
    const data = Buffer.from(transfer.content, "base64");
    if (
      data.length !== r.size ||
      createHash("sha256").update(data).digest("hex") !== transfer.sha256
    )
      throw new Error("File transfer verification failed.");
    const file = await open(target, "wx", 0o600);
    try {
      await file.writeFile(data);
    } finally {
      await file.close();
    }
    return "Created the downloaded file on the desktop.";
  }
  if (r.action === "run") {
    const { stdout, stderr } = await runCommand(r.command, {
      cwd: target,
      env: Object.fromEntries(
        [
          "PATH",
          "HOME",
          "USERPROFILE",
          "SystemRoot",
          "TEMP",
          "TMP",
          "LANG",
        ].flatMap((key) =>
          process.env[key] === undefined ? [] : [[key, process.env[key]]],
        ),
      ),
      signal,
      timeout: 30_000,
      maxBuffer: limit,
      windowsHide: true,
    });
    return (stdout + stderr).slice(0, limit) || "Command exited successfully.";
  }
  if (r.action === "list") {
    const entries: { name: string; directory: boolean }[] = [];
    for await (const entry of await opendir(target)) {
      signal.throwIfAborted();
      entries.push({ name: entry.name, directory: entry.isDirectory() });
      if (entries.length === 200) break;
    }
    return JSON.stringify(entries).slice(0, limit);
  }
  // New files only: a symlink, hard link or concurrently created file cannot redirect a write.
  if (r.action === "write") {
    const file = await open(target, "wx", 0o600);
    try {
      await file.writeFile(r.text, "utf8");
    } finally {
      await file.close();
    }
    return "Created the file on the desktop.";
  }
  const file = await open(
    target,
    constants.O_RDONLY |
      (constants.O_NOFOLLOW ?? 0) |
      (constants.O_NONBLOCK ?? 0),
  );
  try {
    const stat = await file.stat();
    if (!stat.isFile() || stat.size > limit)
      throw new Error("Select a text file of at most 32 KiB.");
    const buffer = Buffer.alloc(limit + 1);
    const { bytesRead } = await file.read(buffer, 0, buffer.length, 0);
    if (bytesRead > limit) throw new Error("File exceeds 32 KiB.");
    return new TextDecoder("utf-8", { fatal: true }).decode(
      buffer.subarray(0, bytesRead),
    );
  } finally {
    await file.close();
  }
}
