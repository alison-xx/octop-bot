package io.github.alisonxx.octopbot.ui

import io.github.alisonxx.octopbot.ui.onboarding.LynxceSignInState
import io.github.alisonxx.octopbot.ui.settings.AccountSummary
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SignInAndAccountTest {
    @Test
    fun signInPointsAtTheAccountFirstThenTheCode() {
        val form = LynxceSignInState()
        assertTrue(form.accountMissing)
        form.account = "   "
        assertTrue(form.accountMissing)
        form.account = "138 0013 8000"
        assertFalse(form.accountMissing)
        assertFalse(form.canSubmit)
        form.code = "123456"
        assertTrue(form.canSubmit)
        form.account = "a@b.cn"
        assertFalse(form.accountMissing)
    }

    @Test
    fun passwordSignInOnlyNeedsSomeAccountText() {
        val form = LynxceSignInState(useCode = false)
        assertTrue(form.accountMissing)
        form.account = "alice"
        assertFalse(form.accountMissing)
        assertFalse(form.canSubmit)
        form.password = "secret"
        assertTrue(form.canSubmit)
    }

    @Test
    fun aRealAccountShowsOnlyTheTotalUntilTheMemberProfileComes() {
        val card = AccountSummary("alice", credits = 120.0)
        assertFalse(card.member)
        assertNull(card.accountHint)
        assertNull(card.expiring)
        assertNull(card.permanent)
        assertEquals(120.0, card.credits!!, 0.0)
        assertTrue(card.copy(tier = "Plus").member)
    }
}
