package io.github.alisonxx.octopbot.voice

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import io.github.alisonxx.octopbot.app.AppLocale
import io.github.alisonxx.octopbot.net.ChatBackend
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.io.File
import java.util.UUID
import kotlin.coroutines.resume

/**
 * Reads replies aloud: the backend's TTS (MP3 via MediaPlayer) when it has one, else on-device TextToSpeech.
 * [speak] suspends until playback ends; cancelling it stops playback.
 */
class Speaker(private val context: Context) {
    private val _speaking = MutableStateFlow(false)
    val speaking: StateFlow<Boolean> = _speaking

    /** Settings → speaking speed; applies to both the backend voice and the system voice. */
    @Volatile var rate: Float = 1f

    private var player: MediaPlayer? = null
    private var tts: TextToSpeech? = null
    private var ttsReady: CompletableDeferred<Boolean>? = null

    suspend fun speak(text: String, backend: ChatBackend) {
        stop()
        val plain = plainText(text)
        if (plain.isBlank()) return
        _speaking.value = true
        try {
            if (backend.voiceSupport().tts) {
                for (chunk in chunks(plain, 600)) {
                    val audio = runCatching { backend.speech(chunk) }.getOrNull()
                    if (audio == null) {
                        speakOnDevice(chunk)
                    } else {
                        play(audio)
                    }
                }
            } else {
                speakOnDevice(plain)
            }
        } finally {
            stop()
        }
    }

    fun stop() {
        player?.run { runCatching { stop() }; release() }
        player = null
        tts?.stop()
        _speaking.value = false
    }

    fun release() {
        stop()
        tts?.shutdown()
        tts = null
    }

    private suspend fun play(audio: ByteArray) {
        val file = withContext(Dispatchers.IO) {
            File(context.cacheDir, "speech.mp3").apply { writeBytes(audio) }
        }
        suspendCancellableCoroutine { continuation ->
            val media = MediaPlayer()
            player = media
            media.setAudioAttributes(
                AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build(),
            )
            media.setOnCompletionListener { if (continuation.isActive) continuation.resume(Unit) }
            media.setOnErrorListener { _, _, _ -> if (continuation.isActive) continuation.resume(Unit); true }
            continuation.invokeOnCancellation { stop() }
            runCatching {
                media.setDataSource(file.path)
                media.prepare()
                if (rate != 1f) media.playbackParams = media.playbackParams.setSpeed(rate)
                media.start()
            }.onFailure { if (continuation.isActive) continuation.resume(Unit) }
        }
    }

    private suspend fun engine(): TextToSpeech? {
        tts?.let { return if (ttsReady?.await() == true) it else null }
        val ready = CompletableDeferred<Boolean>()
        ttsReady = ready
        tts = TextToSpeech(context) { status -> ready.complete(status == TextToSpeech.SUCCESS) }
        return if (ready.await()) tts else null
    }

    private suspend fun speakOnDevice(text: String) {
        val engine = engine() ?: return
        engine.language = AppLocale.current()
        engine.setSpeechRate(rate)
        for (chunk in chunks(text, TextToSpeech.getMaxSpeechInputLength() - 1)) {
            suspendCancellableCoroutine { continuation ->
                val id = UUID.randomUUID().toString()
                engine.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                    override fun onStart(utteranceId: String?) = Unit
                    override fun onDone(utteranceId: String?) {
                        if (utteranceId == id && continuation.isActive) continuation.resume(Unit)
                    }

                    @Deprecated("Required override on older APIs")
                    override fun onError(utteranceId: String?) {
                        if (utteranceId == id && continuation.isActive) continuation.resume(Unit)
                    }
                })
                continuation.invokeOnCancellation { engine.stop() }
                if (engine.speak(chunk, TextToSpeech.QUEUE_FLUSH, null, id) != TextToSpeech.SUCCESS && continuation.isActive) {
                    continuation.resume(Unit)
                }
            }
        }
    }

    companion object {
        /** Markdown → speakable text: drop code fences, emphasis marks, heading/list markers and link targets. */
        fun plainText(markdown: String): String = markdown
            .replace(Regex("```[\\s\\S]*?```"), " ")
            .replace(Regex("!?\\[([^\\]]*)]\\([^)]*\\)"), "$1")
            .replace(Regex("(?m)^\\s{0,3}(#{1,6}|>|[-*+]|\\d+\\.)\\s+"), "")
            .replace(Regex("[*_`~|]"), "")
            .replace(Regex("[ \\t]+"), " ")
            .trim()

        /** Split at sentence ends so each piece fits a TTS request. */
        fun chunks(text: String, limit: Int): List<String> {
            val pieces = mutableListOf<String>()
            var rest = text.trim()
            while (rest.length > limit) {
                val window = rest.substring(0, limit)
                val cut = window.indexOfLast { it in ".!?。！？\n" }.takeIf { it > limit / 3 } ?: window.lastIndexOf(' ').takeIf { it > 0 } ?: (limit - 1)
                pieces += rest.substring(0, cut + 1).trim()
                rest = rest.substring(cut + 1).trim()
            }
            if (rest.isNotEmpty()) pieces += rest
            return pieces
        }
    }
}
