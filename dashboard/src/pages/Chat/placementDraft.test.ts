import { expect, it } from "vitest";
import {
  choosePlacement,
  clearPlacement,
  readPlacement,
} from "./placementDraft";

it("consumes exactly the choice sent in this Bot's turn", () => {
  choosePlacement("alice", "local");
  const first = readPlacement("alice");
  expect(readPlacement("bob")).toBeNull();
  choosePlacement("alice", "cloud");
  clearPlacement(first);
  expect(readPlacement("alice")?.value).toBe("cloud");
  clearPlacement(readPlacement("alice"));
  expect(readPlacement("alice")).toBeNull();
});
