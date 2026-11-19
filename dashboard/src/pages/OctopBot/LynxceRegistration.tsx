import { useId } from "react";
import { ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";
import styles from "./LynxceRegistration.module.less";

export default function LynxceRegistration() {
  const { t } = useTranslation();
  const hint = useId();
  return (
    <div className={styles.registration}>
      <a
        href="https://admin.lynxce.cn/profile/login"
        target="_blank"
        rel="noopener noreferrer"
        aria-describedby={hint}
      >
        {t("botClient.lynxce.register")}
        <ExternalLink size={14} aria-hidden="true" />
      </a>
      <span id={hint}>{t("botClient.lynxce.registerHint")}</span>
    </div>
  );
}
