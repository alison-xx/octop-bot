package io.github.alisonxx.octopbot.net

import kotlinx.serialization.json.JsonObject
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

data class AccountPhoto(val name: String?, val url: String?) {
    companion object {
        fun direct(profile: JsonObject, accountId: String): AccountPhoto? {
            if (profile.str("id") != accountId) return null
            return parse(profile.str("displayName")?.takeUnless { it == accountId }, profile.str("avatarUrl"))
        }

        fun cloud(profile: JsonObject): AccountPhoto {
            if (profile.bool("connected") != true) return AccountPhoto(null, null)
            return parse(profile.str("display_name"), profile.str("avatar_url"))
        }

        private fun parse(name: String?, url: String?): AccountPhoto {
            val image = url?.toHttpUrlOrNull()?.takeIf { it.isHttps && it.username.isEmpty() && it.password.isEmpty() }
            return AccountPhoto(name?.trim()?.takeIf { it.isNotEmpty() }, image?.toString())
        }
    }
}
