package io.github.alisonxx.octopbot

import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import io.github.alisonxx.octopbot.app.AppViewModel
import io.github.alisonxx.octopbot.ui.OctopBotApp
import kotlinx.coroutines.flow.MutableStateFlow

data class NotificationChat(val botId: String, val threadId: String?)

/** AppCompat so per-app language and the appearance setting apply live on every supported Android. */
class MainActivity : AppCompatActivity() {
    private val model: AppViewModel by viewModels()
    /** A Bot to open, from a reply notification. */
    private val openBot = MutableStateFlow<NotificationChat?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        // Shown until the first frame only. The Compose launch screen below draws the same art in the same place,
        // so the system splash goes away at once instead of fading its icon out.
        installSplashScreen().setOnExitAnimationListener { it.remove() }
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        openBot.value = notificationChat(intent)
        setContent { OctopBotApp(model, openBot) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        notificationChat(intent)?.let { openBot.value = it }
    }

    private fun notificationChat(intent: Intent): NotificationChat? =
        intent.getStringExtra(EXTRA_BOT)?.let { NotificationChat(it, intent.getStringExtra(EXTRA_THREAD)) }

    companion object {
        const val EXTRA_THREAD = "io.github.alisonxx.octopbot.THREAD"
        const val EXTRA_BOT = "io.github.alisonxx.octopbot.BOT"
    }
}
