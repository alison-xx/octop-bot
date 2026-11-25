import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import {
  approvedUpload,
  describeUpload,
  parseRequest,
  performApproved,
} from "./operations";

test("one approved file round trips with the displayed size and contents", async () => {
  const root = await mkdtemp(join(tmpdir(), "octop-local-files-"));
  try {
    const data = Buffer.from("实际内容\n");
    await writeFile(join(root, "source.txt"), data);
    const identity = await describeUpload(root, "source.txt");
    assert.equal(identity.size, data.length);
    const signal = new AbortController().signal;
    const file = await approvedUpload(root, "source.txt", identity, signal);
    const request = parseRequest({
      id: "request1",
      bot: "Clerk",
      reason: "Copy the finished report",
      action: "fetch_from_cloud",
      path: "copy.txt",
      cloud_path: "outbound/report.txt",
      destination: "",
      size: data.length,
      command: "",
      text: "",
    });
    assert.ok(request);
    await performApproved(root, request, signal, file);
    assert.deepEqual(await readFile(join(root, "copy.txt")), data);
    await assert.rejects(performApproved(root, request, signal, file), {
      code: "EEXIST",
    });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
