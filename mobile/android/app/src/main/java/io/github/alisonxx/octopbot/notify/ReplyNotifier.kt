package io.github.alisonxx.octopbot.notify

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ProcessLifecycleOwner
import io.github.alisonxx.octopbot.MainActivity
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.AppLocale

/** Posts a local notification when a reply finishes while the app is in the background (no remote push in v1). */
class ReplyNotifier(private val context: Context) {
    init {
        updateChannel()
    }

    /** (Re)create the channel so its name follows the in-app language. */
    fun updateChannel() {
        val resources = AppLocale.resources(context)
        val channel = NotificationChannel(CHANNEL, resources.getString(R.string.notify_channel), NotificationManager.IMPORTANCE_DEFAULT)
        channel.description = resources.getString(R.string.notify_channel_description)
        context.getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    val isInForeground: Boolean
        get() = ProcessLifecycleOwner.get().lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)

    fun replyFinished(botId: String, botName: String, text: String) {
        if (isInForeground) return
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) return
        val firstLine = text.lineSequence().map { it.trim().trimStart('#', '>', '-', '*', ' ') }.firstOrNull { it.isNotEmpty() } ?: return
        val open = Intent(context, MainActivity::class.java)
            .setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            .putExtra(MainActivity.EXTRA_BOT, botId)
        val pending = PendingIntent.getActivity(
            context,
            botId.hashCode(),
            open,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(botName)
            .setContentText(firstLine)
            .setStyle(NotificationCompat.BigTextStyle().bigText(firstLine))
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()
        NotificationManagerCompat.from(context).notify(botId.hashCode(), notification)
    }

    private companion object {
        const val CHANNEL = "replies"
    }
}
