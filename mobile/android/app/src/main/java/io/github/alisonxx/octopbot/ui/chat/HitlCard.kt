package io.github.alisonxx.octopbot.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Circle
import androidx.compose.material.icons.rounded.CheckBox
import androidx.compose.material.icons.rounded.CheckBoxOutlineBlank
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.automirrored.rounded.KeyboardArrowLeft
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.ExpandLess
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material.icons.automirrored.rounded.HelpOutline
import androidx.compose.material.icons.rounded.Shield
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.model.HitlAction
import io.github.alisonxx.octopbot.model.HitlAnswer
import io.github.alisonxx.octopbot.model.HitlQuestion
import io.github.alisonxx.octopbot.model.HitlRequest
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** What the user has picked on an open question card; kept by the chat screen so the composer can answer too. */
@Stable
class HitlCardState(val request: HitlRequest) {
    private var answers by mutableStateOf(mapOf<Pair<Int, Int>, HitlAnswer>())

    fun answer(action: Int, question: Int): HitlAnswer = answers[action to question] ?: HitlAnswer()

    fun toggle(action: Int, question: Int, option: Int, multiSelect: Boolean) {
        val current = answer(action, question)
        val selected = when {
            option in current.selected -> current.selected - option
            multiSelect -> current.selected + option
            else -> setOf(option)
        }
        answers = answers + ((action to question) to current.copy(selected = selected))
    }

    fun setOther(action: Int, question: Int, text: String) {
        answers = answers + ((action to question) to answer(action, question).copy(other = text))
    }

    /** Per action, per question. */
    fun answerLists(): List<List<HitlAnswer>> = request.actions.mapIndexed { a, action ->
        action.questions.orEmpty().indices.map { q -> answer(a, q) }
    }

    val hasAnswer: Boolean get() = answers.values.any { !it.isEmpty }

    /** Every question of every question action, shown one at a time: (action index, question index). */
    val pages: List<Pair<Int, Int>> = request.actions.flatMapIndexed { a, action ->
        action.questions.orEmpty().indices.map { q -> a to q }
    }
    var page by mutableIntStateOf(0)
        private set

    /** Collapsed to one line so the card never covers the conversation. */
    var collapsed by mutableStateOf(false)

    val isLastPage: Boolean get() = page >= pages.lastIndex
    val pageAnswered: Boolean get() = pages.getOrNull(page)?.let { (a, q) -> !answer(a, q).isEmpty } ?: false

    fun next() {
        if (page < pages.lastIndex) page++
    }

    fun previous() {
        if (page > 0) page--
    }
}

class HitlCardActions(
    val onSend: () -> Unit,
    val onYouDecide: () -> Unit,
    val onClose: () -> Unit,
    val onApprove: () -> Unit,
    val onReject: () -> Unit,
)

/**
 * The open question or approval, docked above the composer. Questions come one at a time ("1/3"): Back, You
 * decide, Next (Send on the last). Tapping the header collapses the card to one line and expands it again.
 */
@Composable
fun HitlCard(botName: String, card: HitlCardState, actions: HitlCardActions, modifier: Modifier = Modifier) {
    val palette = LocalPalette.current
    val request = card.request
    val scope = rememberCoroutineScope()
    var advance by remember { mutableStateOf<Job?>(null) }
    val current = card.pages.getOrNull(card.page)
    val currentQuestion = current?.let { (a, q) -> request.actions[a].questions?.getOrNull(q) }
    Column(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(24.dp))
            .background(palette.surface)
            .border(1.dp, palette.hairline, RoundedCornerShape(24.dp))
            .padding(bottom = if (card.collapsed) 0.dp else 12.dp),
    ) {
        Row(
            Modifier
                .fillMaxWidth()
                .clickable { card.collapsed = !card.collapsed }
                .padding(start = 16.dp, end = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                if (request.isQuestion) Icons.AutoMirrored.Rounded.HelpOutline else Icons.Rounded.Shield,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(8.dp))
            Column(Modifier.weight(1f).padding(vertical = if (card.collapsed) 10.dp else 14.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        if (request.isQuestion) stringResource(R.string.hitl_question_title, botName) else stringResource(R.string.hitl_approval_title),
                        style = MaterialTheme.typography.titleSmall,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f, fill = false),
                    )
                    if (request.isQuestion && card.pages.size > 1) {
                        Spacer(Modifier.width(8.dp))
                        Text("${card.page + 1}/${card.pages.size}", style = MaterialTheme.typography.labelMedium, color = palette.secondary)
                    }
                }
                if (card.collapsed) {
                    Text(
                        currentQuestion?.text ?: request.actions.joinToString(", ") { it.label },
                        style = MaterialTheme.typography.bodySmall,
                        color = palette.secondary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            Icon(
                if (card.collapsed) Icons.Rounded.ExpandLess else Icons.Rounded.ExpandMore,
                contentDescription = stringResource(if (card.collapsed) R.string.hitl_expand else R.string.hitl_collapse),
                tint = palette.secondary,
                modifier = Modifier.size(22.dp),
            )
            if (request.isQuestion) {
                IconButton(onClick = actions.onClose, modifier = Modifier.size(40.dp)) {
                    Icon(Icons.Rounded.Close, contentDescription = stringResource(R.string.common_close), tint = palette.secondary)
                }
            } else {
                Spacer(Modifier.width(10.dp))
            }
        }
        if (card.collapsed) return@Column
        Column(
            Modifier
                .heightIn(max = 300.dp)
                .verticalScroll(rememberScrollState())
                .padding(start = 16.dp, end = 16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            if (request.isQuestion) {
                if (current != null && currentQuestion != null) {
                    // Keyed by page so each question starts at its own top.
                    key(card.page) {
                        QuestionBlock(currentQuestion, card, current.first, current.second) { picked ->
                            // A single choice moves on by itself.
                            advance?.cancel()
                            if (picked && !currentQuestion.multiSelect && !card.isLastPage) {
                                advance = scope.launch {
                                    delay(280)
                                    card.next()
                                }
                            }
                        }
                    }
                }
            } else {
                request.actions.forEach { action -> if (action.questions == null) ApprovalBlock(action) }
            }
        }
        Spacer(Modifier.size(12.dp))
        Row(
            Modifier.padding(horizontal = 16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (request.isQuestion) {
                if (card.page > 0) {
                    IconButton(
                        onClick = { advance?.cancel(); card.previous() },
                        modifier = Modifier.size(38.dp).clip(CircleShape).background(palette.raised),
                    ) {
                        Icon(Icons.AutoMirrored.Rounded.KeyboardArrowLeft, contentDescription = stringResource(R.string.common_back))
                    }
                }
                Pill(stringResource(R.string.hitl_you_decide), filled = false, onClick = actions.onYouDecide)
                Spacer(Modifier.weight(1f))
                if (card.isLastPage) {
                    Pill(stringResource(R.string.chat_send), filled = true, enabled = card.hasAnswer, onClick = actions.onSend)
                } else {
                    Pill(stringResource(R.string.hitl_next), filled = true, enabled = card.pageAnswered) {
                        advance?.cancel()
                        card.next()
                    }
                }
            } else {
                Spacer(Modifier.weight(1f))
                if (request.actions.all { it.questions != null || it.allows("reject") }) {
                    Pill(stringResource(R.string.hitl_reject), filled = false, onClick = actions.onReject)
                }
                Pill(stringResource(R.string.hitl_approve), filled = true, onClick = actions.onApprove)
            }
        }
    }
}

@Composable
private fun QuestionBlock(question: HitlQuestion, card: HitlCardState, action: Int, index: Int, onPick: (selected: Boolean) -> Unit) {
    val palette = LocalPalette.current
    val answer = card.answer(action, index)
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        question.header?.let {
            Text(it.uppercase(), style = MaterialTheme.typography.labelSmall, color = palette.secondary)
        }
        Text(question.text, style = MaterialTheme.typography.bodyLarge)
        question.options.forEachIndexed { o, option ->
            val selected = o in answer.selected
            Row(
                Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(14.dp))
                    .background(if (selected) palette.raised else palette.background.copy(alpha = 0.0f))
                    .border(1.dp, if (selected) MaterialTheme.colorScheme.primary else palette.hairline, RoundedCornerShape(14.dp))
                    .clickable {
                        card.toggle(action, index, o, question.multiSelect)
                        onPick(o in card.answer(action, index).selected)
                    }
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    when {
                        question.multiSelect && selected -> Icons.Rounded.CheckBox
                        question.multiSelect -> Icons.Rounded.CheckBoxOutlineBlank
                        selected -> Icons.Rounded.CheckCircle
                        else -> Icons.Outlined.Circle
                    },
                    contentDescription = null,
                    tint = if (selected) MaterialTheme.colorScheme.primary else palette.secondary,
                    modifier = Modifier.size(20.dp),
                )
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(option.label, style = MaterialTheme.typography.bodyMedium)
                    option.description?.let {
                        Text(it, style = MaterialTheme.typography.bodySmall, color = palette.secondary)
                    }
                }
            }
        }
        // "Something else": free text, the only answer for a question without options.
        Box(
            Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(14.dp))
                .background(palette.raised)
                .padding(horizontal = 12.dp, vertical = 11.dp),
        ) {
            if (answer.other.isEmpty()) {
                Text(
                    stringResource(if (question.options.isEmpty()) R.string.hitl_your_answer else R.string.hitl_something_else),
                    style = MaterialTheme.typography.bodyMedium,
                    color = palette.secondary,
                )
            }
            BasicTextField(
                value = answer.other,
                onValueChange = { card.setOther(action, index, it) },
                textStyle = MaterialTheme.typography.bodyMedium.copy(color = palette.text),
                cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                maxLines = 4,
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun ApprovalBlock(action: HitlAction) {
    val palette = LocalPalette.current
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(action.label, style = MaterialTheme.typography.titleSmall)
        action.description?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = palette.secondary) }
        for ((key, value) in action.details) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .background(palette.raised)
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                Text(key, style = MaterialTheme.typography.labelSmall, color = palette.secondary)
                Text(
                    value,
                    style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
                    maxLines = 6,
                )
            }
        }
    }
}

@Composable
private fun Pill(label: String, filled: Boolean, enabled: Boolean = true, onClick: () -> Unit) {
    val palette = LocalPalette.current
    Text(
        label,
        style = MaterialTheme.typography.labelLarge,
        color = if (filled) palette.background else palette.text,
        modifier = Modifier
            .alpha(if (enabled) 1f else 0.4f)
            .clip(CircleShape)
            .background(if (filled) palette.text else palette.raised)
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 9.dp),
    )
}
