/** Poll quickly while a group turn is live, slowly once the room goes quiet. */
export const ACTIVE_POLL_MS = 2500;
export const IDLE_POLL_MS = 10000;
/** Quiet polls to keep the fast cadence for, so a reply that is about to start is not missed. */
export const ACTIVE_GRACE_POLLS = 4;

export function groupPollDelay(busy: boolean, quietPolls: number): number {
  return busy || quietPolls < ACTIVE_GRACE_POLLS
    ? ACTIVE_POLL_MS
    : IDLE_POLL_MS;
}
