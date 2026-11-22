/**
 * Resolve @mentions in a group message the same way the backend does
 * (``octop.infra.bot_groups.turns.mentions``): every member is addressable
 * by agent ID or display name, the longest handle wins (so names with spaces
 * work), and a name shared by several members only resolves through @agent_id.
 */
export interface MentionMember {
  agent_id: string;
  name: string;
}

const escapeRegExp = (value: string) =>
  value.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");

export function resolveMentions(
  text: string,
  members: MentionMember[],
): string[] {
  const handles = new Map<string, string[]>();
  for (const { agent_id, name } of members)
    for (const label of new Set([agent_id, name])) {
      if (!label) continue;
      const owners = handles.get(label) ?? [];
      owners.push(agent_id);
      handles.set(label, owners);
    }
  if (!handles.size) return [];
  const pattern = new RegExp(
    "(?<![a-zA-Z0-9_@])@(" +
      [...handles.keys()]
        .sort((a, b) => b.length - a.length)
        .map(escapeRegExp)
        .join("|") +
      ")(?![a-zA-Z0-9_-])",
    "g",
  );
  const found: string[] = [];
  for (const match of text.matchAll(pattern)) {
    const owners = handles.get(match[1])!;
    if (owners.length === 1 && !found.includes(owners[0]))
      found.push(owners[0]);
  }
  return found;
}
