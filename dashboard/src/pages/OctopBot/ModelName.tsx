import anthropicLogo from "../../assets/providers/anthropic.png";
import dashscopeLogo from "../../assets/providers/dashscope.png";
import deepseekLogo from "../../assets/providers/deepseek.png";
import geminiLogo from "../../assets/providers/gemini.png";
import hunyuanLogo from "../../assets/providers/hunyuan.svg";
import mimoLogo from "../../assets/providers/mimo.svg";
import minimaxLogo from "../../assets/providers/minimax.png";
import moonshotLogo from "../../assets/providers/moonshot.webp";
import openaiLogo from "../../assets/providers/openai.png";
import volcesLogo from "../../assets/providers/volces.svg";
import zhipuLogo from "../../assets/providers/zhipu.png";
import styles from "./modelName.module.less";

/**
 * Models are labelled by the vendor that made them, not by the channel that
 * serves them: `relay::deepseek-flash` and `deepseek::deepseek-ai/DeepSeek-V4-Pro`
 * both show the DeepSeek mark and only the model name.
 */
const VENDORS: [RegExp, string, string][] = [
  [/deepseek/, "deepseek", deepseekLogo],
  [/qwen|qwq|tongyi/, "qwen", dashscopeLogo],
  [/glm|zhipu|chatglm/, "glm", zhipuLogo],
  [/kimi|moonshot/, "kimi", moonshotLogo],
  [/doubao|volc/, "doubao", volcesLogo],
  [/hunyuan/, "hunyuan", hunyuanLogo],
  [/minimax|abab/, "minimax", minimaxLogo],
  [/gemini|gemma/, "gemini", geminiLogo],
  [/claude/, "claude", anthropicLogo],
  [/gpt|(^|[^a-z])o[1-9]([^a-z]|$)|openai/, "openai", openaiLogo],
  [/mimo/, "mimo", mimoLogo],
];

const WORDS: Record<string, string> = {
  deepseek: "DeepSeek",
  glm: "GLM",
  gpt: "GPT",
  kimi: "Kimi",
  qwen: "Qwen",
  qwq: "QwQ",
  minimax: "MiniMax",
  hunyuan: "Hunyuan",
  doubao: "Doubao",
  gemini: "Gemini",
  claude: "Claude",
  mimo: "MiMo",
  vl: "VL",
  ai: "AI",
};

/** The model part of an id: no `channel::` and no `org/` prefix. */
function bareModel(id: string): string {
  const afterChannel = id.includes("::")
    ? id.slice(id.lastIndexOf("::") + 2)
    : id;
  return afterChannel.slice(afterChannel.lastIndexOf("/") + 1);
}

/** "deepseek-ai/DeepSeek-V4-Pro" → "DeepSeek V4 Pro", "qwen3.8-flash" → "Qwen3.8 Flash". */
export function modelDisplayName(id: string, name?: string | null): string {
  // A catalog name that is not just the id again is already human-readable.
  const given = name?.trim();
  if (given && given !== id && !given.includes("::") && !given.includes("/"))
    return given;
  return bareModel(given || id)
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((word) => {
      const lower = word.toLowerCase();
      const known = Object.keys(WORDS).find(
        (key) => lower === key || new RegExp(`^${key}\\d`).test(lower),
      );
      if (known) return WORDS[known] + word.slice(known.length);
      if (/^[a-z]\d/i.test(word)) return word.toUpperCase();
      return word === lower ? word[0].toUpperCase() + word.slice(1) : word;
    })
    .join(" ");
}

/** The model's maker (key for `octopBot.modelVendor.*`) and its mark. */
export function modelVendor(
  id: string,
): { key: string; logo: string } | undefined {
  const text = (
    id.includes("::") ? id.slice(id.indexOf("::") + 2) : id
  ).toLowerCase();
  const hit = VENDORS.find(([pattern]) => pattern.test(text));
  return hit && { key: hit[1], logo: hit[2] };
}

export function modelVendorLogo(id: string): string | undefined {
  return modelVendor(id)?.logo;
}

/** The id without its serving channel, shown as secondary text. */
export function modelBareId(id: string): string {
  return id.includes("::") ? id.slice(id.lastIndexOf("::") + 2) : id;
}

/** Vendor mark (or a letter tile) plus the friendly model name. */
export default function ModelName({
  id,
  name,
  size = 16,
}: {
  id: string;
  name?: string | null;
  size?: number;
}) {
  const label = modelDisplayName(id, name);
  const logo = modelVendorLogo(`${id} ${name ?? ""}`);
  return (
    <span className={styles.model} title={id}>
      {logo ? (
        <img
          className={styles.logo}
          src={logo}
          alt=""
          width={size}
          height={size}
        />
      ) : (
        <span
          className={styles.letter}
          style={{ width: size, height: size, fontSize: size * 0.62 }}
          aria-hidden
        >
          {label.charAt(0).toUpperCase()}
        </span>
      )}
      <span className={styles.name}>{label}</span>
    </span>
  );
}
