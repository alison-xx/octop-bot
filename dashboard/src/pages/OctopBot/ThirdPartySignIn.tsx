import { Button } from "antd";
import { useTranslation } from "react-i18next";
// Unmodified marks from each brand's own website (see the PR for their sources).
import wechatMark from "../../assets/providers/wechat.png";
import workbuddyMark from "../../assets/providers/workbuddy.svg";
import intro from "./BotClientSetup.module.less";

/**
 * "Sign in with …" buttons under the Lynxce form, each with the provider's
 * official mark. A provider is offered only when its handler is given.
 */
export default function ThirdPartySignIn({
  disabled,
  wechatStatus,
  workbuddyStatus,
  onWechat,
  onWorkbuddy,
}: {
  disabled: boolean;
  wechatStatus?: string;
  workbuddyStatus?: string;
  onWechat?: () => void;
  onWorkbuddy?: () => void;
}) {
  const { t } = useTranslation();
  if (!onWechat && !onWorkbuddy) return null;
  // Side by side the labels are short; a lone button says it in full.
  const both = Boolean(onWechat && onWorkbuddy);
  return (
    <>
      <div className={intro.or} role="separator">
        <span>{t("botOnboarding.or")}</span>
      </div>
      <div className={intro.thirdParty}>
        {onWechat && (
          <Button
            size="large"
            disabled={disabled || !!wechatStatus}
            aria-label={[t("botStart.wechatSignIn"), wechatStatus]
              .filter(Boolean)
              .join(" · ")}
            onClick={onWechat}
          >
            <img src={wechatMark} alt="" />
            {t(both ? "botStart.wechat" : "botStart.wechatSignIn")}
            {wechatStatus && <small>{wechatStatus}</small>}
          </Button>
        )}
        {onWorkbuddy && (
          <Button
            size="large"
            disabled={disabled || !!workbuddyStatus}
            aria-label={[t("botCloud.workbuddySignIn"), workbuddyStatus]
              .filter(Boolean)
              .join(" · ")}
            onClick={onWorkbuddy}
          >
            <img src={workbuddyMark} alt="" />
            {both ? "WorkBuddy" : t("botCloud.workbuddySignIn")}
            {workbuddyStatus && <small>{workbuddyStatus}</small>}
          </Button>
        )}
      </div>
    </>
  );
}
