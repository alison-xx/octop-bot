package io.github.alisonxx.octopbot.net

import java.io.IOException

/**
 * The Lynxce wallet of whoever is signed in: straight with Lynxce ([LynxceBackend]), or through
 * Octop Bot cloud, which keeps the Lynxce session on the user's behalf ([ServerBackend.isCloud]).
 */
interface CreditAccount {
    /** Credits left; throws when the wallet can't be read. */
    suspend fun balance(): Double

    /** Identifies this wallet across launches (e.g. for a dismissed low-balance banner); null until known. */
    val walletKey: String?

    /** A signed-in link to Lynxce's recharge page, valid for 15 minutes. Throws [CheckoutRefused] for a bad link. */
    suspend fun checkoutUrl(scenario: CreditScenario? = null): String

    /** Delete the Lynxce account; it is signed out everywhere and erased after a cooling-off period. */
    suspend fun requestDeletion()
}

/** The recharge link the server returned is not Lynxce's own recharge page with a fresh ticket; it is never opened. */
class CheckoutRefused : IOException()
