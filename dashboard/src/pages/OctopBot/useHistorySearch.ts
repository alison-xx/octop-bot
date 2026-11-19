import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { octopBotApi, type ChatReference } from "../../api/modules/octopBot";
import { apiErrorMessage } from "../../utils/apiError";

export function useHistorySearch(value: string) {
  const { t } = useTranslation();
  const query = value.trim();
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState({
    query: "",
    rows: [] as ChatReference[],
    pending: false,
    error: "",
  });
  useEffect(() => {
    if (!query) return;
    let current = true;
    let timer: ReturnType<typeof setTimeout>;
    const search = async () => {
      try {
        const { matches, indexing } = await octopBotApi.search(query);
        if (!current) return;
        setResult({ query, rows: matches, pending: indexing, error: "" });
        if (indexing) timer = setTimeout(search, 1000);
      } catch (e) {
        if (current)
          setResult({
            query,
            rows: [],
            pending: false,
            error: apiErrorMessage(e, t("octopBot.failed"), t),
          });
      }
    };
    timer = setTimeout(search, 250);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [query, attempt, t]);
  return {
    ...(query && result.query === query
      ? result
      : { rows: [], pending: Boolean(query), error: "" }),
    retry: () => {
      setResult({ query, rows: [], pending: true, error: "" });
      setAttempt((n) => n + 1);
    },
  };
}
