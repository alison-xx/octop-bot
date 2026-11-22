package io.github.alisonxx.octopbot.net

/**
 * Resolve @mentions in a group message the same way the backend does
 * (`octop.infra.bot_groups.turns.mentions`): every member is addressable by agent id or display name,
 * the longest handle wins (so names with spaces work), and a name shared by several members only
 * resolves through @agent_id.
 */
object Mentions {
    data class Member(val agentId: String, val name: String)

    fun resolve(text: String, members: List<Member>): List<String> {
        val handles = linkedMapOf<String, MutableList<String>>()
        for (member in members) {
            for (label in setOf(member.agentId, member.name)) {
                if (label.isNotEmpty()) handles.getOrPut(label) { mutableListOf() } += member.agentId
            }
        }
        if (handles.isEmpty()) return emptyList()
        val alternatives = handles.keys.sortedByDescending { it.length }.joinToString("|") { Regex.escape(it) }
        val pattern = Regex("(?<![a-zA-Z0-9_@])@($alternatives)(?![a-zA-Z0-9_-])")
        val found = mutableListOf<String>()
        for (match in pattern.findAll(text)) {
            val owners = handles.getValue(match.groupValues[1])
            if (owners.size == 1 && owners[0] !in found) found += owners[0]
        }
        return found
    }

    /** The `@query` being typed at the end of [text], or null when the caret is not in a mention. */
    fun activeQuery(text: String): String? {
        val at = text.lastIndexOf('@')
        if (at < 0) return null
        if (at > 0 && (text[at - 1].isLetterOrDigit() || text[at - 1] == '_')) return null
        val query = text.substring(at + 1)
        return query.takeIf { '\n' !in it && it.length <= 32 }
    }
}
