package io.github.alisonxx.octopbot.app

import android.content.res.Resources
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.net.ApiException
import io.github.alisonxx.octopbot.net.ModelSourceException
import io.github.alisonxx.octopbot.net.ModelSourceException.Reason

/** A failure as one localized sentence for the user. */
fun Resources.describe(error: Throwable): String {
    (error as? ModelSourceException)?.let { return describeModelSource(it) }
    val api = error as? ApiException ?: return getString(R.string.error_network)
    // The server's out-of-credits text carries a URL a snackbar can't open; the chat card links it instead.
    if (api.kind == ApiException.Kind.Credits) return getString(R.string.error_credits)
    if (api.kind == ApiException.Kind.DailyLimit) return getString(R.string.error_daily_limit)
    api.message?.takeIf { it.isNotBlank() }?.let { return it }
    return when (api.kind) {
        ApiException.Kind.Unauthorized -> getString(R.string.error_unauthorized)
        ApiException.Kind.Credits -> getString(R.string.error_credits)
        ApiException.Kind.DailyLimit -> getString(R.string.error_daily_limit)
        ApiException.Kind.Rejected -> getString(R.string.error_rejected, api.status)
        ApiException.Kind.Network -> getString(R.string.error_network)
        ApiException.Kind.Server -> getString(R.string.error_server, api.status)
    }
}

/** Why the phone refused a model key or address, or a vendor refused a chat. */
fun Resources.describeModelSource(error: ModelSourceException): String = when (error.reason) {
    Reason.InvalidKey -> getString(R.string.models_error_invalid_key)
    Reason.Limit -> getString(R.string.models_error_limit)
    Reason.BadUrl -> getString(R.string.models_error_url)
    Reason.UnknownVendor -> getString(R.string.models_error_unknown_vendor)
    Reason.Vendor -> getString(R.string.models_error_vendor, error.status)
    Reason.Unreachable -> getString(R.string.models_error_unreachable)
    Reason.NoModels -> getString(R.string.models_local_no_models)
    Reason.NoModel -> getString(R.string.models_error_no_model)
    Reason.KeyRejected -> getString(R.string.models_error_key_rejected)
    Reason.Quota -> listOfNotNull(getString(R.string.models_error_quota), error.detail).joinToString(" ")
}
