package io.github.alisonxx.octopbot.app

import android.content.Context
import android.content.res.Configuration
import android.content.res.Resources
import android.os.LocaleList
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.os.LocaleListCompat
import java.util.Locale

/** The in-app language ("Follow system" / 简体中文 / English), via AppCompat per-app locales. */
object AppLocale {
    const val SYSTEM = ""
    const val CHINESE = "zh-CN"
    const val ENGLISH = "en"

    /** The chosen tag, or [SYSTEM]. */
    fun tag(): String = AppCompatDelegate.getApplicationLocales().toLanguageTags()

    fun set(tag: String) = AppCompatDelegate.setApplicationLocales(LocaleListCompat.forLanguageTags(tag))

    /** The language the app speaks right now (drives Accept-Language and speech languages). */
    fun current(): Locale = AppCompatDelegate.getApplicationLocales()[0] ?: Locale.getDefault()

    /** Resources in the in-app language, for code outside an activity (AppCompat only localizes activities below Android 13). */
    fun resources(context: Context): Resources {
        val locales = AppCompatDelegate.getApplicationLocales()
        if (locales.isEmpty) return context.resources
        val config = Configuration(context.resources.configuration)
        config.setLocales(LocaleList.forLanguageTags(locales.toLanguageTags()))
        return context.createConfigurationContext(config).resources
    }
}
