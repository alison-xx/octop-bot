import { parseActionArgs } from "../../api/types/hitl";
import type { ChatMessage } from "../Chat/hooks/useChat";

/** A subsequent successful edit must apply the same replacement to the same file. */
export function repairedFileEdit(
  failed: ChatMessage,
  next: ChatMessage,
): boolean {
  if (
    next.toolData?.name !== "edit_file" ||
    next.status !== "done" ||
    next.toolData.output === undefined
  )
    return false;
  const args = parseActionArgs(failed.toolData?.arguments);
  const retry = parseActionArgs(next.toolData.arguments);
  if (
    typeof args.file_path !== "string" ||
    retry.file_path !== args.file_path ||
    typeof args.old_string !== "string" ||
    !args.old_string ||
    typeof args.new_string !== "string" ||
    typeof retry.old_string !== "string"
  )
    return false;
  const pos = retry.old_string.indexOf(args.old_string);
  return (
    pos >= 0 &&
    retry.new_string ===
      retry.old_string.slice(0, pos) +
        args.new_string +
        retry.old_string.slice(pos + args.old_string.length)
  );
}
