package io.github.alisonxx.octopbot.store

import android.content.Context
import io.github.alisonxx.octopbot.app.AppLocale
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.Look

/**
 * Bots that live on this phone when signed in with a Lynxce account: Chief, the built-in roles
 * (same shape/ink mapping as the desktop) and the user's own. Built-ins keep their persona; only
 * their look can be changed.
 */
class LocalBots(private val context: Context, private val store: AppStore) {
    private val resources get() = AppLocale.resources(context)

    suspend fun all(): List<BotProfile> {
        val looks = store.lookOverrides()
        return builtIns().map { bot -> looks[bot.id]?.let { bot.copy(look = it) } ?: bot } + store.customBots()
    }

    suspend fun save(bot: BotProfile) {
        if (builtIns().any { it.id == bot.id }) {
            store.setLookOverrides(store.lookOverrides() + (bot.id to bot.look))
            return
        }
        val custom = store.customBots()
        val saved = bot.copy(isLocal = true)
        val index = custom.indexOfFirst { it.id == bot.id }
        store.setCustomBots(if (index >= 0) custom.toMutableList().also { it[index] = saved } else custom + saved)
    }

    suspend fun delete(id: String) = store.setCustomBots(store.customBots().filterNot { it.id == id })

    fun builtIns(): List<BotProfile> = listOf(
        BotProfile(
            id = CHIEF_ID,
            name = "Chief",
            subtitle = resources.getString(R.string.bot_chief_subtitle),
            look = Look.chief,
            isChief = true,
            systemPrompt = resources.getString(R.string.bot_chief_prompt),
        ),
        role("researcher", "acorn", "green", R.string.bot_researcher_name, R.string.bot_researcher_subtitle, R.string.bot_researcher_prompt),
        role("engineer", "beacon", "cobalt", R.string.bot_engineer_name, R.string.bot_engineer_subtitle, R.string.bot_engineer_prompt),
        role("translator", "wave", "sky", R.string.bot_translator_name, R.string.bot_translator_subtitle, R.string.bot_translator_prompt),
        role("writer", "cushion", "violet", R.string.bot_writer_name, R.string.bot_writer_subtitle, R.string.bot_writer_prompt),
        role("companion", "bunny", "tangerine", R.string.bot_companion_name, R.string.bot_companion_subtitle, R.string.bot_companion_prompt),
    )

    private fun role(id: String, shape: String, color: String, name: Int, subtitle: Int, prompt: Int) = BotProfile(
        id = id,
        name = resources.getString(name),
        subtitle = resources.getString(subtitle),
        look = Look(shape, color),
        systemPrompt = resources.getString(prompt),
    )

    companion object {
        const val CHIEF_ID = "chief"
    }
}
