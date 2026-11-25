import { request } from "../request";

export type OnboardingStatus = "pending" | "active" | "done" | "skipped";
export type OnboardingStep = "welcome" | "ask" | "team_ready" | "first_message";

export interface OnboardingTeam {
  group_id: string;
  bot_ids: string[];
  section: string | null;
  first_task: string;
}

export type OnboardingKind = "industry" | "role";

/** What the owner picked on the first screen. */
export interface OnboardingChoice {
  kind: OnboardingKind;
  id: string | null;
  label: string;
  note: string;
}

export interface OnboardingOption {
  id: string;
  name: string;
  /** What it covers; shown as a tooltip. */
  hint: string;
}

export interface OnboardingOptions {
  industries: OnboardingOption[];
  roles: OnboardingOption[];
}

export interface OnboardingState {
  show: boolean;
  status: OnboardingStatus;
  step: OnboardingStep;
  choice: OnboardingChoice | null;
  team: OnboardingTeam | null;
  reason: "existing" | "legacy" | null;
}

/** A listed option by id, or the owner's own words; the note is optional. */
export interface OnboardingPick {
  kind: OnboardingKind;
  option?: string;
  custom?: string;
  note?: string;
}

export type OnboardingChange =
  | ({ action: "start" } & OnboardingPick)
  | { action: "complete" | "restart" }
  | { action: "skip"; reason?: "legacy" }
  | { action: "step"; step: "ask" | "first_message" };

const path = "/octop-bot/onboarding";

export const botOnboardingApi = {
  read: () => request<OnboardingState>(path),
  options: () => request<OnboardingOptions>(path + "/options"),
  change: (change: OnboardingChange) =>
    request<OnboardingState>(path, {
      method: "PUT",
      body: JSON.stringify(change),
    }),
};
