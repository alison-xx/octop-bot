package io.github.alisonxx.octopbot.model

/** A paused server turn waiting for the user (human in the loop): questions to answer or actions to approve. */
data class HitlRequest(val pendingId: String?, val actions: List<HitlAction>) {
    /** Every action is an `ask_user_question`: a question card. Otherwise an approval card. */
    val isQuestion: Boolean get() = actions.isNotEmpty() && actions.all { it.questions != null }
}

data class HitlAction(
    val name: String,
    /** The tool name in the app language (`/api/i18n/tools`), else [name]. */
    val label: String,
    val description: String?,
    /** Key arguments worth showing for an approval (`command`, `url`, `path`, `query`), in that order. */
    val details: List<Pair<String, String>>,
    /** Non-null for `ask_user_question`. */
    val questions: List<HitlQuestion>?,
    /** From `review_configs`; null when the server didn't say (both allowed). */
    val allowedDecisions: Set<String>? = null,
) {
    fun allows(decision: String): Boolean = allowedDecisions?.contains(decision) ?: true
}

data class HitlQuestion(
    val text: String,
    val header: String?,
    val options: List<HitlOption>,
    val multiSelect: Boolean,
)

data class HitlOption(val label: String, val description: String?)

/** Fixed HITL replies and captions, in the app language. */
class HitlTexts(
    /** "You decide — pick the best default and tell me what you assumed." */
    val youDecide: String,
    /** "The user closed these questions without answering. …" */
    val closed: String,
    /** Caption "Approved: {actions}". */
    val approved: (String) -> String,
    /** Caption "Declined: {actions}". */
    val declined: (String) -> String,
)

/** One decision per action, sent to `chat/hitl/resume`. */
sealed interface HitlDecision {
    data class Respond(val message: String) : HitlDecision
    data object Approve : HitlDecision
    data class Reject(val message: String = REJECTED) : HitlDecision

    companion object {
        const val REJECTED = "Rejected by user"
    }
}

/** What the user picked for one question: option indices and the "Something else" text. */
data class HitlAnswer(val selected: Set<Int> = emptySet(), val other: String = "") {
    val isEmpty: Boolean get() = selected.isEmpty() && other.isBlank()
}

/** Pure answer formatting for the question card (shared by the card, the composer and tests). */
object HitlAnswers {
    /** One line per answered question: `"{header or question}: {answer}"`, several choices joined with `"; "`. */
    fun format(questions: List<HitlQuestion>, answers: List<HitlAnswer>): String =
        questions.mapIndexedNotNull { index, question ->
            val answer = answers.getOrNull(index) ?: return@mapIndexedNotNull null
            val parts = answer.selected.sorted().mapNotNull { question.options.getOrNull(it)?.label } +
                listOfNotNull(answer.other.trim().takeIf { it.isNotEmpty() })
            if (parts.isEmpty()) null else "${question.header?.takeIf { it.isNotBlank() } ?: question.text}: ${parts.joinToString("; ")}"
        }.joinToString("\n")

    /**
     * Text typed into the composer while a question is open answers it: it fills the first question without an
     * answer (or adds to the last one). With nothing picked in the card and several questions, it goes as typed.
     */
    fun withComposerText(questions: List<HitlQuestion>, answers: List<HitlAnswer>, text: String): String {
        val typed = text.trim()
        if (typed.isEmpty()) return format(questions, answers)
        val current = questions.indices.map { answers.getOrNull(it) ?: HitlAnswer() }
        if (questions.size != 1 && current.all { it.isEmpty }) return typed
        val target = current.indexOfFirst { it.isEmpty }.takeIf { it >= 0 } ?: questions.lastIndex
        if (target < 0) return typed
        val filled = current.toMutableList()
        filled[target] = filled[target].let { it.copy(other = listOf(it.other.trim(), typed).filter(String::isNotEmpty).joinToString("; ")) }
        return format(questions, filled)
    }

    /** Question card: each `ask_user_question` action answered with its own lines. */
    fun respond(request: HitlRequest, answers: List<List<HitlAnswer>>): List<HitlDecision> =
        request.actions.mapIndexed { index, action ->
            HitlDecision.Respond(format(action.questions.orEmpty(), answers.getOrNull(index).orEmpty()))
        }

    /**
     * A message typed in the composer while a card is open. Question: it answers (the first question action
     * gets the text, see [withComposerText]). Approval: it declines, with the text as the reason.
     */
    fun fromComposer(request: HitlRequest, text: String, answers: List<List<HitlAnswer>>): List<HitlDecision> {
        if (!request.isQuestion) {
            return request.actions.map { if (it.questions != null) HitlDecision.Respond(text) else HitlDecision.Reject(text) }
        }
        return request.actions.mapIndexed { index, action ->
            val questions = action.questions.orEmpty()
            val picked = answers.getOrNull(index).orEmpty()
            HitlDecision.Respond(if (index == 0) withComposerText(questions, picked, text) else format(questions, picked))
        }
    }

    /** The same fixed message for every action ("You decide…" or "closed without answering"). */
    fun respondAll(request: HitlRequest, message: String): List<HitlDecision> = request.actions.map { HitlDecision.Respond(message) }

    /**
     * Approval card: approve or reject every action. A question mixed into an approval is answered with
     * [questionReply] ("You decide…" on approve, "closed" on reject).
     */
    fun review(request: HitlRequest, approve: Boolean, questionReply: String): List<HitlDecision> = request.actions.map { action ->
        when {
            action.questions != null -> HitlDecision.Respond(questionReply)
            approve -> HitlDecision.Approve
            else -> HitlDecision.Reject()
        }
    }
}
