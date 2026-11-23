package io.github.alisonxx.octopbot.ui.voice

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ArrowUpward
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Mic
import androidx.compose.material.icons.rounded.Stop
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.AppViewModel
import io.github.alisonxx.octopbot.app.SessionState
import io.github.alisonxx.octopbot.app.describe
import io.github.alisonxx.octopbot.character.BotCharacter
import io.github.alisonxx.octopbot.model.BotMotion
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.model.MessageRole
import io.github.alisonxx.octopbot.model.MessageStatus
import io.github.alisonxx.octopbot.ui.common.accentOf
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import io.github.alisonxx.octopbot.ui.theme.OctopTheme
import io.github.alisonxx.octopbot.voice.VoiceInput
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

enum class VoicePhase { Idle, Listening, Transcribing, Thinking, Speaking }

/** Full-screen voice: tap to talk, tap again to send; the reply streams in and is read aloud. */
@Composable
fun VoiceScreen(model: AppViewModel, botId: String, onClose: () -> Unit) {
    val session by model.session.collectAsStateWithLifecycle()
    val backend = (session as? SessionState.Ready)?.backend ?: return
    val bots by model.bots.collectAsStateWithLifecycle()
    val bot = bots.firstOrNull { it.id == botId } ?: return
    val chat = remember(botId) { model.chat(botId) }
    val state by chat.state.collectAsStateWithLifecycle()
    val level by model.voiceInput.level.collectAsStateWithLifecycle()
    val partial by model.voiceInput.partial.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val resources = LocalResources.current
    val scope = rememberCoroutineScope()
    var phase by remember { mutableStateOf(VoicePhase.Idle) }
    var transcript by remember { mutableStateOf("") }
    var notice by remember { mutableStateOf<String?>(null) }
    var turn by remember { mutableStateOf<Job?>(null) }

    DisposableEffect(botId) {
        model.voiceBotId = botId
        onDispose {
            model.voiceBotId = null
            model.voiceInput.cancel()
            model.speaker.stop()
        }
    }

    fun listen() {
        notice = null
        scope.launch {
            runCatching { model.voiceInput.start(backend) }
                .onSuccess {
                    transcript = ""
                    phase = VoicePhase.Listening
                }
                .onFailure {
                    notice = resources.getString(if (it is VoiceInput.Unavailable) R.string.voice_unavailable else R.string.voice_mic_denied)
                }
        }
    }

    /** Transcribe, send, wait for the reply, read it aloud. */
    fun sendTurn() {
        phase = VoicePhase.Transcribing
        turn = scope.launch {
            val heard = runCatching { model.voiceInput.finish(backend) }
                .onFailure { notice = resources.describe(it) }
                .getOrDefault("")
            if (heard.isEmpty()) {
                if (notice == null) notice = resources.getString(R.string.voice_not_heard)
                phase = VoicePhase.Idle
                return@launch
            }
            transcript = heard
            phase = VoicePhase.Thinking
            chat.send(heard, emptyList())
            snapshotFlow { chat.state.value.streaming }.first { !it }
            val reply = chat.state.value.messages.lastOrNull()?.takeIf { it.role == MessageRole.Assistant }
            val failed = reply?.status as? MessageStatus.Failed
            if (failed != null) {
                notice = failed.message ?: resources.getString(R.string.chat_failed)
            } else if (!reply?.text.isNullOrBlank()) {
                phase = VoicePhase.Speaking
                model.speaker.speak(reply.text, backend)
            }
            phase = VoicePhase.Idle
        }
    }

    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) listen() else notice = resources.getString(R.string.voice_mic_denied)
    }

    fun tap() {
        when (phase) {
            VoicePhase.Idle -> if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED
            ) listen() else permission.launch(Manifest.permission.RECORD_AUDIO)
            VoicePhase.Listening -> sendTurn()
            VoicePhase.Transcribing -> Unit
            VoicePhase.Thinking -> chat.stop()
            VoicePhase.Speaking -> {
                model.speaker.stop()
                turn?.cancel()
                phase = VoicePhase.Idle
            }
        }
    }

    val reply = state.messages.lastOrNull()?.takeIf { it.role == MessageRole.Assistant && phase >= VoicePhase.Thinking }?.text
    OctopTheme(accent = accentOf(bot.look)) {
        VoiceContent(
            bot = bot,
            phase = phase,
            motion = when (phase) {
                VoicePhase.Listening, VoicePhase.Transcribing -> BotMotion.Searching
                VoicePhase.Thinking -> if (state.motion == BotMotion.Thinking) BotMotion.Thinking else BotMotion.Working
                VoicePhase.Speaking -> BotMotion.Working
                VoicePhase.Idle -> BotMotion.Idle
            },
            transcript = if (phase == VoicePhase.Listening) partial else transcript,
            reply = reply.orEmpty(),
            notice = notice,
            level = level,
            onTap = ::tap,
            onClose = onClose,
        )
    }
}

@Composable
fun VoiceContent(
    bot: BotProfile,
    phase: VoicePhase,
    motion: BotMotion,
    transcript: String,
    reply: String,
    notice: String?,
    level: Float,
    onTap: () -> Unit,
    onClose: () -> Unit,
) {
    val palette = LocalPalette.current
    val pulse by animateFloatAsState(1f + level * 0.35f, label = "level")
    Box(Modifier.fillMaxSize().background(palette.background)) {
        IconButton(onClick = onClose, modifier = Modifier.statusBarsPadding().padding(8.dp)) {
            Icon(Icons.Rounded.Close, contentDescription = stringResource(R.string.common_close))
        }
        Column(
            Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(top = 56.dp, bottom = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(bot.name, style = MaterialTheme.typography.titleMedium, color = palette.secondary)
            Spacer(Modifier.weight(1f))
            BotCharacter(bot.look, 200.dp, motion = motion, seed = bot.id)
            Spacer(Modifier.height(28.dp))
            Column(
                Modifier
                    .fillMaxWidth()
                    .heightIn(max = 220.dp)
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 28.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                if (transcript.isNotBlank()) {
                    Text(transcript, style = MaterialTheme.typography.titleMedium, textAlign = TextAlign.Center)
                }
                if (reply.isNotBlank()) {
                    Text(reply.take(600), style = MaterialTheme.typography.bodyLarge, color = palette.secondary, textAlign = TextAlign.Center)
                }
                notice?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.error, textAlign = TextAlign.Center) }
            }
            Spacer(Modifier.weight(1f))
            Text(
                stringResource(
                    when (phase) {
                        VoicePhase.Idle -> R.string.voice_tap_to_talk
                        VoicePhase.Listening -> R.string.voice_listening
                        VoicePhase.Transcribing -> R.string.voice_transcribing
                        VoicePhase.Thinking -> R.string.voice_thinking
                        VoicePhase.Speaking -> R.string.voice_speaking
                    },
                ),
                style = MaterialTheme.typography.bodyMedium,
                color = palette.secondary,
            )
            Spacer(Modifier.height(16.dp))
            Box(contentAlignment = Alignment.Center) {
                if (phase == VoicePhase.Listening) {
                    Box(Modifier.size(96.dp).scale(pulse).clip(CircleShape).background(MaterialTheme.colorScheme.primary.copy(alpha = 0.25f)))
                }
                IconButton(
                    onClick = onTap,
                    enabled = phase != VoicePhase.Transcribing,
                    modifier = Modifier
                        .size(84.dp)
                        .clip(CircleShape)
                        .background(if (phase == VoicePhase.Listening) MaterialTheme.colorScheme.primary else palette.text),
                ) {
                    Icon(
                        when (phase) {
                            VoicePhase.Idle -> Icons.Rounded.Mic
                            VoicePhase.Listening -> Icons.Rounded.ArrowUpward
                            else -> Icons.Rounded.Stop
                        },
                        contentDescription = stringResource(
                            when (phase) {
                                VoicePhase.Idle -> R.string.voice_tap_to_talk
                                VoicePhase.Listening -> R.string.chat_send
                                else -> R.string.chat_stop
                            },
                        ),
                        tint = if (phase == VoicePhase.Listening) MaterialTheme.colorScheme.onPrimary else palette.background,
                        modifier = Modifier.size(36.dp),
                    )
                }
            }
        }
    }
}

@Preview(showBackground = true, backgroundColor = 0xFF000000, heightDp = 800)
@Composable
private fun VoicePreview() {
    OctopTheme(dark = true) {
        VoiceContent(
            bot = BotProfile("chief", "Chief", look = Look.chief, isChief = true),
            phase = VoicePhase.Listening,
            motion = BotMotion.Searching,
            transcript = "What's the weather like for a walk later?",
            reply = "",
            notice = null,
            level = 0.4f,
            onTap = {},
            onClose = {},
        )
    }
}
