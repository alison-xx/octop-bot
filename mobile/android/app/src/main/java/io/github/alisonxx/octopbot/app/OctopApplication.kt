package io.github.alisonxx.octopbot.app

import android.app.Application
import androidx.appcompat.app.AppCompatDelegate
import io.github.alisonxx.octopbot.net.Http
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import io.github.alisonxx.octopbot.notify.ReplyNotifier
import io.github.alisonxx.octopbot.store.AppStore
import io.github.alisonxx.octopbot.store.LocalBots
import io.github.alisonxx.octopbot.update.Updater
import kotlinx.coroutines.MainScope

class OctopApplication : Application() {
    lateinit var store: AppStore
        private set
    lateinit var localBots: LocalBots
        private set
    lateinit var notifier: ReplyNotifier
        private set
    lateinit var updater: Updater
        private set

    override fun onCreate() {
        super.onCreate()
        store = AppStore(this)
        localBots = LocalBots(this, store)
        notifier = ReplyNotifier(this)
        updater = Updater(this, store, MainScope()).also { it.watchForeground() }
        Http.locale = AppLocale::current
        // Apply the saved appearance before the first activity draws (a tiny DataStore read).
        AppCompatDelegate.setDefaultNightMode(runBlocking { store.settings.first() }.appearance.nightMode)
    }
}
