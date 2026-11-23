package io.github.alisonxx.octopbot.net

/**
 * The Lynxce wallet of whoever is signed in: straight with Lynxce ([LynxceBackend]), or through
 * Octop Bot cloud, which keeps the Lynxce session on the user's behalf ([ServerBackend.isCloud]).
 */
interface CreditAccount {
    suspend fun balance(): String?

    /** A signed-in link to Lynxce's recharge page, valid for 15 minutes. */
    suspend fun checkoutUrl(): String

    /** Delete the Lynxce account; it is signed out everywhere and erased after a cooling-off period. */
    suspend fun requestDeletion()
}
