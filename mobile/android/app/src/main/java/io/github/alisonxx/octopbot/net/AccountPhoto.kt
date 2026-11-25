package io.github.alisonxx.octopbot.net

import kotlinx.serialization.json.JsonObject
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

data class AccountPhoto(val name: String?, val url: String?, val localImage: ByteArray? = null) {
    companion object {
        fun direct(profile: JsonObject, accountId: String): AccountPhoto? {
            if (profile.str("id") != accountId) return null
            return parse(profile.str("displayName")?.takeUnless { it == accountId }, profile.str("avatarUrl"))
        }

        fun cloud(profile: JsonObject): AccountPhoto {
            if (profile.bool("connected") != true) return AccountPhoto(null, null)
            return parse(profile.str("display_name"), profile.str("avatar_url"))
        }

        fun localAvatar(me: JsonObject): Pair<String, Map<String, String>>? {
            val id = me.long("id")?.takeIf { it > 0 } ?: return null
            val raw = me.str("avatar_url") ?: return null
            val path = "/api/users/$id/avatar"
            if (raw == path) return path to emptyMap()
            if (!raw.startsWith("$path?")) return null
            val parts = ("https://unused.invalid" + raw).toHttpUrlOrNull() ?: return null
            if (parts.fragment != null || parts.querySize != 1 || parts.queryParameterName(0) != "v") return null
            val version = parts.queryParameterValue(0) ?: return null
            return path to mapOf("v" to version)
        }

        fun owner(profile: JsonObject): AccountPhoto =
            parse(ServerProtocol.personName(profile.str("display_name")), profile.str("avatar_url"))

        private fun parse(name: String?, url: String?): AccountPhoto {
            val image = url?.toHttpUrlOrNull()?.takeIf { it.isHttps && it.username.isEmpty() && it.password.isEmpty() }
            return AccountPhoto(name?.trim()?.takeIf { it.isNotEmpty() }, image?.toString())
        }
    }
}
