package io.github.alisonxx.octopbot.store

import io.github.alisonxx.octopbot.model.BotProfile

/** Directory bookkeeping: last-reply previews, unread marks and the order they give the Bot list. */
object Previews {
    /** The first non-empty line of a reply without Markdown marks, as shown under the Bot's name. */
    fun snippet(text: String): String = text.lineSequence()
        .filterNot { it.trim().startsWith("```") }
        .map { line ->
            line.trim()
                .replace(Regex("^(#{1,6}|>|[-*+]|\\d+\\.)\\s+"), "")
                .replace(Regex("\\*\\*|__|`+"), "")
                .trim()
        }
        .firstOrNull { it.isNotEmpty() }
        .orEmpty()
        .take(200)

    /** A reply finished: it becomes the preview, unread unless that Bot's chat was on screen. */
    fun replyFinished(previews: Map<String, BotPreview>, botId: String, text: String, at: Long, onScreen: Boolean): Map<String, BotPreview> =
        previews + (botId to BotPreview(snippet(text), at, unread = !onScreen))

    /** Opening a chat clears its unread mark; the preview stays. */
    fun markRead(previews: Map<String, BotPreview>, botId: String): Map<String, BotPreview> {
        val preview = previews[botId]?.takeIf { it.unread } ?: return previews
        return previews + (botId to preview.copy(unread = false))
    }

    /** Chief stays pinned; the other Bots by their last reply (newest first), then in directory order. */
    fun directoryOrder(bots: List<BotProfile>, previews: Map<String, BotPreview>): List<BotProfile> {
        val (pinned, others) = bots.partition { it.isChief }
        // sortedByDescending is stable, so Bots without a reply keep their directory order.
        return pinned + others.sortedByDescending { previews[it.id]?.at ?: Long.MIN_VALUE }
    }
}
