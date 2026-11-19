/** Group composer state outlives the route, so an upload or send can finish after switching chats. */
export interface RoomRequest {
  id: string;
  text: string;
  mentions: string[];
  paths: string[];
  fromComposer: boolean;
  error?: string;
}
interface SavedDraft {
  text: string;
  attachments: string[];
  outbox: RoomRequest[];
}
const empty: SavedDraft = { text: "", attachments: [], outbox: [] };
interface DraftState extends SavedDraft {
  sending: string | null;
  uploading: string | null;
  uploadError: string;
}
function readDraft(key: string): SavedDraft {
  try {
    const raw = sessionStorage.getItem(key);
    if (raw) {
      const data = JSON.parse(raw) as SavedDraft;
      if (
        typeof data.text === "string" &&
        Array.isArray(data.attachments) &&
        Array.isArray(data.outbox)
      )
        return data;
    }
  } catch {
    /* Storage can be unavailable on a locked-down device. */
  }
  return empty;
}
class RoomDraft {
  private listeners = new Set<() => void>();
  private state: DraftState;
  private readonly key: string;
  constructor(key: string) {
    this.key = key;
    this.state = {
      ...readDraft(key),
      sending: null,
      uploading: null,
      uploadError: "",
    };
  }
  read = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  patch = (patch: Partial<DraftState>) => {
    this.state = { ...this.state, ...patch };
    if ("text" in patch || "attachments" in patch || "outbox" in patch) {
      const { text, attachments, outbox } = this.state;
      try {
        if (text || attachments.length || outbox.length)
          sessionStorage.setItem(
            this.key,
            JSON.stringify({ text, attachments, outbox }),
          );
        else sessionStorage.removeItem(this.key);
      } catch {
        /* The live draft still supports switching chats. */
      }
    }
    this.listeners.forEach((listener) => listener());
  };
}
const rooms = new Map<string, RoomDraft>();
export function roomDraft(userId: number | null, groupId: string) {
  const key = "octop.bot.group-draft.v1:" + JSON.stringify([userId, groupId]);
  let draft = rooms.get(key);
  if (!draft) {
    draft = new RoomDraft(key);
    rooms.set(key, draft);
  }
  return draft;
}
