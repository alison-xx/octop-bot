import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BOT_PRODUCT_NAME } from "../../shared/product";

/**
 * Every shell page is a static HTML file with a single ``#root``. The pages are
 * permanently mounted for the life of the window, so nothing here unmounts.
 */
export function mount(node: ReactNode): void {
  if (window.octopDesktop?.botOnly) document.title = document.title.replace(/^Octop\b/, BOT_PRODUCT_NAME);
  const container = document.getElementById("root");
  if (!container) throw new Error("renderer host element #root is missing");
  createRoot(container).render(<StrictMode>{node}</StrictMode>);
}
