package io.github.alisonxx.octopbot.app

import android.content.res.Resources
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.net.ApiException

/** A failure as one localized sentence for the user. */
fun Resources.describe(error: Throwable): String {
    val api = error as? ApiException ?: return getString(R.string.error_network)
    api.message?.takeIf { it.isNotBlank() }?.let { return it }
    return when (api.kind) {
        ApiException.Kind.Unauthorized -> getString(R.string.error_unauthorized)
        ApiException.Kind.Credits -> getString(R.string.error_credits)
        ApiException.Kind.Rejected -> getString(R.string.error_rejected, api.status)
        ApiException.Kind.Network -> getString(R.string.error_network)
        ApiException.Kind.Server -> getString(R.string.error_server, api.status)
    }
}
