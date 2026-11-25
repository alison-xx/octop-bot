import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import LynxceSignInForm, { looksLikeEmail } from "./LynxceSignInForm";
import ThirdPartySignIn from "./ThirdPartySignIn";

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

function renderForm() {
  const onCode = vi.fn().mockResolvedValue(undefined);
  const onPassword = vi.fn().mockResolvedValue(undefined);
  const sendCode = vi.fn().mockResolvedValue("phone");
  render(
    <LynxceSignInForm
      idPrefix="t"
      busy={false}
      submitLabel="submit"
      sendCode={sendCode}
      onCode={onCode}
      onPassword={onPassword}
      onError={vi.fn()}
      onClearError={vi.fn()}
    />,
  );
  return { onCode, onPassword, sendCode };
}

describe("Lynxce sign-in form", () => {
  it("tells phone numbers from emails in the one field", () => {
    expect(looksLikeEmail("13800000000")).toBe(false);
    expect(looksLikeEmail("+86 138 0000 0000")).toBe(false);
    expect(looksLikeEmail("a@b.cn")).toBe(true);
    expect(looksLikeEmail("alice")).toBe(true);
  });

  it("keeps the button clickable and points at the empty field", async () => {
    const { onCode, sendCode } = renderForm();
    await userEvent.click(screen.getByRole("button", { name: "submit" }));
    expect(onCode).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "lynxceSignIn.missingTarget",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "lynxceSignIn.send" }),
    );
    expect(sendCode).not.toHaveBeenCalled();
    await userEvent.type(
      screen.getByLabelText("lynxceSignIn.target"),
      "13800000000",
    );
    await userEvent.click(screen.getByRole("button", { name: "submit" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "lynxceSignIn.missingCode",
    );
  });

  it("switches to the password with a link and back", async () => {
    const { onPassword } = renderForm();
    await userEvent.click(
      screen.getByRole("button", { name: "lynxceSignIn.usePassword" }),
    );
    await userEvent.type(
      screen.getByLabelText("lynxceSignIn.account"),
      "a@b.cn",
    );
    await userEvent.click(screen.getByRole("button", { name: "submit" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "lynxceSignIn.missingPassword",
    );
    await userEvent.type(
      screen.getByLabelText("lynxceSignIn.password"),
      "test-secret{Enter}",
    );
    expect(onPassword).toHaveBeenCalledWith("a@b.cn", "test-secret");
    await userEvent.click(
      screen.getByRole("button", { name: "lynxceSignIn.useCode" }),
    );
    expect(screen.getByLabelText("lynxceSignIn.code")).toBeInTheDocument();
  });
});

describe("third-party sign-in", () => {
  it("offers only the providers it is given", async () => {
    const { container, rerender } = render(
      <ThirdPartySignIn disabled={false} />,
    );
    expect(container).toBeEmptyDOMElement();
    const workbuddy = vi.fn();
    rerender(<ThirdPartySignIn disabled={false} onWorkbuddy={workbuddy} />);
    expect(screen.queryByText("botStart.wechat")).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "botCloud.workbuddySignIn" }),
    );
    expect(workbuddy).toHaveBeenCalled();
    rerender(
      <ThirdPartySignIn
        disabled={false}
        onWechat={vi.fn()}
        onWorkbuddy={workbuddy}
      />,
    );
    expect(
      screen.getByRole("button", { name: "botStart.wechatSignIn" }),
    ).toHaveTextContent("botStart.wechat");
    expect(
      screen.getByRole("button", { name: "botCloud.workbuddySignIn" }),
    ).toHaveTextContent("WorkBuddy");
  });
});
