package io.github.alisonxx.octopbot.voice

import android.content.Context
import android.content.Intent
import android.media.MediaRecorder
import android.os.Build
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import io.github.alisonxx.octopbot.app.AppLocale
import io.github.alisonxx.octopbot.net.ChatBackend
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.io.File

/**
 * Captures one utterance. With backend STT it records AAC audio and uploads it on [finish]; otherwise it
 * uses the on-device SpeechRecognizer. Must be driven from the main thread. Needs RECORD_AUDIO.
 */
class VoiceInput(private val context: Context) {
    class Unavailable : Exception()

    private val _level = MutableStateFlow(0f)
    /** Input loudness 0..1 for the listening animation. */
    val level: StateFlow<Float> = _level
    private val _partial = MutableStateFlow("")
    val partial: StateFlow<String> = _partial

    private var recorder: MediaRecorder? = null
    private var file: File? = null
    private var meter: Job? = null
    private var recognizer: SpeechRecognizer? = null
    private var result: CompletableDeferred<String>? = null

    val listening: Boolean get() = recorder != null || recognizer != null

    suspend fun start(backend: ChatBackend) {
        cancel()
        _partial.value = ""
        if (backend.voiceSupport().stt) startRecording() else startRecognizer()
    }

    /** Stop listening and return the transcript (empty when nothing was heard). */
    suspend fun finish(backend: ChatBackend): String {
        recorder?.let { active ->
            runCatching { active.stop() }
            active.release()
            recorder = null
            stopMeter()
            val audio = file?.let { withContext(Dispatchers.IO) { it.readBytes().also { _ -> it.delete() } } } ?: return ""
            if (audio.size < 2048) return ""
            return backend.transcribe(audio).trim()
        }
        val pending = result ?: return ""
        recognizer?.stopListening()
        val text = withTimeoutOrNull(8_000) { pending.await() } ?: _partial.value
        releaseRecognizer()
        return text.trim()
    }

    fun cancel() {
        recorder?.run { runCatching { stop() }; release() }
        recorder = null
        file?.delete()
        stopMeter()
        releaseRecognizer()
    }

    private fun startRecording() {
        val target = File(context.cacheDir, "voice.m4a")
        val media = if (Build.VERSION.SDK_INT >= 31) MediaRecorder(context) else @Suppress("DEPRECATION") MediaRecorder()
        media.setAudioSource(MediaRecorder.AudioSource.MIC)
        media.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
        media.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
        media.setAudioSamplingRate(16_000)
        media.setAudioEncodingBitRate(64_000)
        media.setOutputFile(target.path)
        media.prepare()
        media.start()
        recorder = media
        file = target
        meter = MainScope().launch {
            while (isActive) {
                _level.value = (media.maxAmplitude / 20_000f).coerceIn(0f, 1f)
                delay(80)
            }
        }
    }

    private fun stopMeter() {
        meter?.cancel()
        meter = null
        _level.value = 0f
    }

    private fun startRecognizer() {
        if (!SpeechRecognizer.isRecognitionAvailable(context)) throw Unavailable()
        val deferred = CompletableDeferred<String>()
        result = deferred
        val engine = SpeechRecognizer.createSpeechRecognizer(context)
        recognizer = engine
        engine.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) = Unit
            override fun onBeginningOfSpeech() = Unit
            override fun onRmsChanged(rmsdB: Float) {
                _level.value = ((rmsdB + 2f) / 12f).coerceIn(0f, 1f)
            }
            override fun onBufferReceived(buffer: ByteArray?) = Unit
            override fun onEndOfSpeech() {
                _level.value = 0f
            }
            override fun onError(error: Int) {
                deferred.complete(_partial.value)
            }
            override fun onResults(results: Bundle?) {
                deferred.complete(results.best() ?: _partial.value)
            }
            override fun onPartialResults(partialResults: Bundle?) {
                partialResults.best()?.let { _partial.value = it }
            }
            override fun onEvent(eventType: Int, params: Bundle?) = Unit
        })
        engine.startListening(
            Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE, AppLocale.current().toLanguageTag())
                .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                // Keep listening through pauses; the user taps to finish.
                .putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 10_000L)
                .putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 10_000L),
        )
    }

    private fun releaseRecognizer() {
        recognizer?.destroy()
        recognizer = null
        result?.cancel()
        result = null
        _level.value = 0f
    }

    private fun Bundle?.best(): String? =
        this?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.takeIf { it.isNotBlank() }
}
