package io.github.alisonxx.octopbot.ui.chat

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.material.icons.rounded.KeyboardArrowDown
import androidx.compose.runtime.derivedStateOf
import androidx.compose.ui.res.stringArrayResource
import androidx.compose.ui.unit.Dp
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Chat
import androidx.compose.material.icons.rounded.EditNote
import androidx.compose.material.icons.rounded.GraphicEq
import androidx.compose.material.icons.rounded.History
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.net.toUri
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.AppViewModel
import io.github.alisonxx.octopbot.app.ChatState
import io.github.alisonxx.octopbot.app.SessionState
import io.github.alisonxx.octopbot.character.BotCharacter
import io.github.alisonxx.octopbot.media.Photos
import io.github.alisonxx.octopbot.model.BotMotion
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.ImageAttachment
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.model.MessageRole
import io.github.alisonxx.octopbot.model.MessageStatus
import io.github.alisonxx.octopbot.model.ToolStep
import io.github.alisonxx.octopbot.net.ChatBackend
import io.github.alisonxx.octopbot.ui.common.BackButton
import io.github.alisonxx.octopbot.ui.common.BottomFade
import io.github.alisonxx.octopbot.ui.common.TopBar
import io.github.alisonxx.octopbot.ui.common.accentOf
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import io.github.alisonxx.octopbot.ui.theme.OctopTheme
import io.github.alisonxx.octopbot.voice.VoiceInput
import kotlinx.coroutines.launch
import java.io.File

@Composable
fun ChatScreen(model: AppViewModel, botId: String, onBack: () -> Unit, onEditBot: () -> Unit, onVoice: () -> Unit) {
    val session by model.session.collectAsStateWithLifecycle()
    val backend = (session as? SessionState.Ready)?.backend ?: return
    val bots by model.bots.collectAsStateWithLifecycle()
    val bot = bots.firstOrNull { it.id == botId } ?: return
    val chat = remember(botId) { model.chat(botId) }
    val state by chat.state.collectAsStateWithLifecycle()
    LaunchedEffect(botId) {
        model.noteBotOpened(botId)
        chat.openLatest()
    }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var draft by rememberSaveable(botId) { mutableStateOf("") }
    val images = remember(botId) { mutableStateListOf<ImageAttachment>() }
    var history by rememberSaveable { mutableStateOf(false) }
    val dictation = rememberDictation(model.voiceInput, backend) { heard ->
        draft = listOf(draft.trimEnd(), heard).filter { it.isNotEmpty() }.joinToString(" ")
    }
    val photoFailed = stringResource(R.string.chat_photo_failed)
    val copied = stringResource(R.string.common_copied)

    fun addPhotos(uris: List<Uri>) {
        scope.launch {
            for (uri in uris.take(4 - images.size)) {
                val photo = Photos.load(context, uri)
                if (photo == null) Toast.makeText(context, photoFailed, Toast.LENGTH_SHORT).show() else images += photo
            }
        }
    }
    val pickPhotos = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(4)) { addPhotos(it) }
    var cameraTarget by rememberSaveable { mutableStateOf<String?>(null) }
    val takePhoto = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { saved ->
        val target = cameraTarget
        if (saved && target != null) addPhotos(listOf(target.toUri()))
    }

    OctopTheme(accent = accentOf(bot.look)) {
        ChatContent(
            bot = bot,
            state = state,
            draft = draft,
            onDraftChange = { draft = it },
            images = images,
            onRemoveImage = { images.remove(it) },
            dictating = dictation.active,
            onBack = onBack,
            onEditBot = onEditBot,
            onHistory = {
                chat.refreshConversations()
                history = true
            },
            onVoice = onVoice,
            onNewChat = chat::newChat,
            onSuggestion = { suggestion ->
                // "Translate into English…" needs the user's text: put it in the field instead of sending.
                if (suggestion.endsWith("…")) draft = suggestion.removeSuffix("…").trimEnd() + " " else chat.send(suggestion, emptyList())
            },
            onPickPhotos = { pickPhotos.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) },
            onTakePhoto = {
                val uri = cameraUri(context)
                cameraTarget = uri.toString()
                takePhoto.launch(uri)
            },
            onSend = {
                chat.send(draft, images.toList())
                draft = ""
                images.clear()
            },
            onStop = chat::stop,
            onDictate = dictation.toggle,
            actionsFor = { message, isLastReply ->
                MessageActions(
                    readAloud = model::readAloud,
                    copied = { model.notice(copied) },
                    retry = if (isLastReply && message.role == MessageRole.Assistant) chat::retry else null,
                )
            },
        )
        if (history) {
            HistorySheet(
                conversations = state.conversations,
                currentId = state.conversationId,
                onNewChat = {
                    chat.newChat()
                    history = false
                },
                onOpen = {
                    chat.open(it)
                    history = false
                },
                onDelete = chat::delete,
                onDismiss = { history = false },
            )
        }
    }
}

private fun cameraUri(context: Context): Uri {
    val folder = File(context.cacheDir, "camera").apply { mkdirs() }
    val file = File(folder, "photo-${System.currentTimeMillis()}.jpg")
    return FileProvider.getUriForFile(context, context.packageName + ".photos", file)
}

/** Composer dictation: tap mic to listen, tap again to put the transcript in the field. */
class Dictation(val active: Boolean, val toggle: () -> Unit)

@Composable
fun rememberDictation(input: VoiceInput, backend: ChatBackend, onHeard: (String) -> Unit): Dictation {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var active by remember { mutableStateOf(false) }
    val denied = stringResource(R.string.voice_mic_denied)
    val unavailable = stringResource(R.string.voice_unavailable)

    fun start() {
        scope.launch {
            runCatching { input.start(backend) }
                .onSuccess { active = true }
                .onFailure {
                    val message = if (it is VoiceInput.Unavailable) unavailable else denied
                    Toast.makeText(context, message, Toast.LENGTH_SHORT).show()
                }
        }
    }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) start() else Toast.makeText(context, denied, Toast.LENGTH_LONG).show()
    }
    return Dictation(active) {
        if (active) {
            active = false
            scope.launch {
                runCatching { input.finish(backend) }
                    .onSuccess { if (it.isNotEmpty()) onHeard(it) }
                    .onFailure { Toast.makeText(context, it.message ?: unavailable, Toast.LENGTH_SHORT).show() }
            }
        } else if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            start()
        } else {
            permission.launch(Manifest.permission.RECORD_AUDIO)
        }
    }
}

@Composable
fun ChatContent(
    bot: BotProfile,
    state: ChatState,
    draft: String,
    onDraftChange: (String) -> Unit,
    images: List<ImageAttachment>,
    onRemoveImage: (ImageAttachment) -> Unit,
    dictating: Boolean,
    onBack: () -> Unit,
    onEditBot: () -> Unit,
    onHistory: () -> Unit,
    onVoice: () -> Unit,
    onNewChat: () -> Unit,
    onSuggestion: (String) -> Unit,
    onPickPhotos: () -> Unit,
    onTakePhoto: () -> Unit,
    onSend: () -> Unit,
    onStop: () -> Unit,
    onDictate: () -> Unit,
    actionsFor: (ChatMessage, Boolean) -> MessageActions,
) {
    val density = LocalDensity.current
    var composerHeight by remember { mutableStateOf(96.dp) }
    Box(Modifier.fillMaxSize().imePadding()) {
        Column(Modifier.fillMaxSize()) {
            ChatTopBar(bot, state, onBack, onEditBot, onHistory, onVoice, onNewChat)
            Box(Modifier.weight(1f).fillMaxWidth()) {
                when {
                    state.loading && state.messages.isEmpty() ->
                        CircularProgressIndicator(Modifier.align(Alignment.Center).size(28.dp), strokeWidth = 2.dp)
                    state.messages.isEmpty() -> EmptyState(bot, Modifier.padding(bottom = composerHeight), onSuggestion)
                    else -> MessageList(bot, state, composerHeight, actionsFor)
                }
            }
        }
        BottomFade(composerHeight + 16.dp, Modifier.align(Alignment.BottomCenter))
        Composer(
            text = draft,
            onTextChange = onDraftChange,
            images = images,
            onRemoveImage = onRemoveImage,
            streaming = state.streaming,
            dictating = dictating,
            placeholder = stringResource(R.string.chat_placeholder),
            onPickPhotos = onPickPhotos,
            onTakePhoto = onTakePhoto,
            onSend = onSend,
            onStop = onStop,
            onDictate = onDictate,
            // Measured outside the insets so the list clears the composer and the navigation bar.
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .onSizeChanged { composerHeight = with(density) { it.height.toDp() } }
                .navigationBarsPadding()
                .padding(horizontal = 12.dp, vertical = 8.dp),
        )
    }
}

@Composable
private fun ChatTopBar(
    bot: BotProfile,
    state: ChatState,
    onBack: () -> Unit,
    onEditBot: () -> Unit,
    onHistory: () -> Unit,
    onVoice: () -> Unit,
    onNewChat: () -> Unit,
) {
    TopBar(
        titleInset = 132.dp,
        leading = { BackButton(onBack) },
        trailing = {
            IconButton(onClick = onHistory, modifier = Modifier.size(44.dp)) {
                Icon(Icons.Rounded.History, contentDescription = stringResource(R.string.chat_history))
            }
            IconButton(onClick = onVoice, modifier = Modifier.size(44.dp)) {
                Icon(Icons.Rounded.GraphicEq, contentDescription = stringResource(R.string.chat_voice))
            }
            IconButton(onClick = onNewChat, enabled = !state.streaming, modifier = Modifier.size(44.dp)) {
                Icon(Icons.Rounded.EditNote, contentDescription = stringResource(R.string.chat_new))
            }
        },
    ) {
        Row(
            Modifier.clip(CircleShape).clickable(onClick = onEditBot).padding(horizontal = 8.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            BotCharacter(bot.look, 28.dp, motion = if (state.streaming) state.motion else BotMotion.Idle, seed = bot.id)
            Spacer(Modifier.width(8.dp))
            Text(bot.name, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}

/** Starter prompts that fit the Bot: built-in roles have their own, everyone else gets general ones. */
private fun suggestionsFor(bot: BotProfile): Int = when (bot.id) {
    "researcher" -> R.array.suggestions_researcher
    "engineer" -> R.array.suggestions_engineer
    "translator" -> R.array.suggestions_translator
    "writer" -> R.array.suggestions_writer
    "companion" -> R.array.suggestions_companion
    else -> R.array.suggestions_default
}

@Composable
private fun EmptyState(bot: BotProfile, modifier: Modifier, onSuggestion: (String) -> Unit) {
    val palette = LocalPalette.current
    val suggestions = stringArrayResource(suggestionsFor(bot))
    Column(
        modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        BotCharacter(bot.look, 168.dp, seed = bot.id)
        Spacer(Modifier.height(20.dp))
        Text(stringResource(R.string.chat_greeting, bot.name), style = MaterialTheme.typography.headlineSmall, textAlign = TextAlign.Center)
        bot.subtitle?.let {
            Spacer(Modifier.height(6.dp))
            Text(
                it,
                style = MaterialTheme.typography.bodyLarge,
                color = palette.secondary,
                textAlign = TextAlign.Center,
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(Modifier.height(28.dp))
        Column(verticalArrangement = Arrangement.spacedBy(10.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            suggestions.forEach { suggestion ->
                Row(
                    Modifier
                        .clip(RoundedCornerShape(20.dp))
                        .background(palette.surface)
                        .clickable { onSuggestion(suggestion) }
                        .padding(horizontal = 16.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.AutoMirrored.Rounded.Chat, null, tint = palette.secondary, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(suggestion, style = MaterialTheme.typography.bodyMedium)
                }
            }
        }
    }
}

@Composable
private fun MessageList(bot: BotProfile, state: ChatState, composerHeight: Dp, actionsFor: (ChatMessage, Boolean) -> MessageActions) {
    val palette = LocalPalette.current
    val list = rememberLazyListState()
    val scope = rememberCoroutineScope()
    val reversed = state.messages.asReversed()
    // Newest at the bottom: a reversed layout stays pinned to the end while a reply streams in.
    LaunchedEffect(state.messages.size) { list.animateScrollToItem(0) }
    val scrolledUp by remember { derivedStateOf { list.firstVisibleItemIndex > 0 || list.firstVisibleItemScrollOffset > 240 } }
    Box(Modifier.fillMaxSize()) {
        LazyColumn(
            state = list,
            reverseLayout = true,
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = composerHeight + 12.dp),
            verticalArrangement = Arrangement.spacedBy(18.dp, Alignment.Bottom),
            modifier = Modifier.fillMaxSize(),
        ) {
            itemsIndexed(reversed, key = { _, message -> message.id }) { index, message ->
                MessageRow(
                    message = message,
                    bot = bot,
                    motion = state.motion,
                    actions = actionsFor(message, index == 0 && !state.streaming),
                    modifier = MessageMaxWidth,
                )
            }
        }
        AnimatedVisibility(
            visible = scrolledUp,
            enter = fadeIn(),
            exit = fadeOut(),
            modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = composerHeight + 12.dp),
        ) {
            IconButton(
                onClick = { scope.launch { list.animateScrollToItem(0) } },
                modifier = Modifier
                    .size(40.dp)
                    .clip(CircleShape)
                    .background(palette.raised),
            ) {
                Icon(Icons.Rounded.KeyboardArrowDown, contentDescription = stringResource(R.string.chat_jump_latest))
            }
        }
    }
}

private val previewBot = BotProfile("engineer", "Engineer", "Code and debugging", Look("beacon", "cobalt"))

@Preview(showBackground = true, backgroundColor = 0xFF000000, heightDp = 800)
@Composable
private fun ChatEmptyPreview() {
    OctopTheme(accent = androidx.compose.ui.graphics.Color(0xFF082DFF), dark = true) {
        ChatContent(
            bot = previewBot, state = ChatState(), draft = "", onDraftChange = {}, images = emptyList(), onRemoveImage = {},
            dictating = false, onBack = {}, onEditBot = {}, onHistory = {}, onVoice = {}, onNewChat = {}, onSuggestion = {},
            onPickPhotos = {}, onTakePhoto = {}, onSend = {}, onStop = {}, onDictate = {},
            actionsFor = { _, _ -> MessageActions({}, {}, null) },
        )
    }
}

@Preview(showBackground = true, backgroundColor = 0xFF000000, heightDp = 800)
@Composable
private fun ChatConversationPreview() {
    val messages = listOf(
        ChatMessage(id = "1", role = MessageRole.User, text = "Why does my RecyclerView crash after rotation?"),
        ChatMessage(
            id = "2",
            role = MessageRole.Assistant,
            text = "The adapter is created in `onResume()`, so after rotation the old one is still attached.\n\n" +
                "1. Create the adapter once in `onCreate()`\n2. Keep data in a `ViewModel`\n\n```kotlin\nrecycler.adapter = adapter\n```",
            thinking = "The user rotates; Activity is recreated…",
            tools = listOf(ToolStep("t1", "web_search", done = true)),
        ),
        ChatMessage(id = "3", role = MessageRole.User, text = "Can you show the ViewModel part?"),
        ChatMessage(
            id = "4",
            role = MessageRole.Assistant,
            text = "Sure — here is a minimal",
            tools = listOf(ToolStep("t2", "read_file", done = false)),
            status = MessageStatus.Streaming,
        ),
    )
    OctopTheme(accent = androidx.compose.ui.graphics.Color(0xFF082DFF), dark = true) {
        ChatContent(
            bot = previewBot, state = ChatState(conversationId = "c", messages = messages, streaming = true, motion = BotMotion.Working),
            draft = "", onDraftChange = {}, images = emptyList(), onRemoveImage = {}, dictating = false, onBack = {}, onEditBot = {},
            onHistory = {}, onVoice = {}, onNewChat = {}, onSuggestion = {}, onPickPhotos = {}, onTakePhoto = {}, onSend = {},
            onStop = {}, onDictate = {}, actionsFor = { _, _ -> MessageActions({}, {}, null) },
        )
    }
}
