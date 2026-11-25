package io.github.alisonxx.octopbot.ui.settings

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.OpenInNew
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.alisonxx.octopbot.BuildConfig
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.ui.common.credits
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/** Pricing (membership and top-ups) and the account centre on the website; opened in the browser. */
const val PRICING_URL = "https://octop-bot.lynxce.cn/pricing.html"
const val ACCOUNT_URL = "https://octop-bot.lynxce.cn/account.html"

/** The website's account centre is not live yet; its link stays hidden until it is. */
const val ACCOUNT_CENTRE_OPEN = false

/**
 * What the account card shows. Only the name is always known; the rest comes with Lynxce's member profile (avatar,
 * tier, masked id, renewal date, and the balance split into expiring and permanent credits) and is left out until then.
 */
data class AccountSummary(
    val name: String,
    val tier: String? = null,
    /** Masked Lynxce id, e.g. "138****0000". */
    val accountHint: String? = null,
    val memberUntil: LocalDate? = null,
    val credits: Double? = null,
    val expiring: Double? = null,
    val expiringOn: LocalDate? = null,
    val signupExpiryDay: String? = null,
    val permanent: Double? = null,
) {
    val member get() = tier != null

    companion object {
        /** Sample data for design screenshots; debug builds only, set in the `octop.debug` preferences. */
        fun demo(context: Context): AccountSummary? {
            if (!BuildConfig.DEBUG || !context.getSharedPreferences("octop.debug", Context.MODE_PRIVATE).getBoolean("demoAccount", false)) return null
            return AccountSummary(
                name = "Octo",
                tier = context.getString(R.string.account_demo_tier),
                accountHint = "138****0000",
                memberUntil = LocalDate.of(2026, 12, 31),
                credits = 4_440_164.0,
                expiring = 2_300.0,
                expiringOn = LocalDate.of(2026, 11, 30),
                permanent = 4_437_864.0,
            )
        }
    }
}

private val day = DateTimeFormatter.ofPattern("MM-dd")

/**
 * The Lynxce account at the top of Settings, like the desktop's card-style account menu: avatar with the Lynxce mark,
 * tier, masked id and renewal date, the balance with what expires and what stays, then membership and top-ups on the
 * website, credits and usage in the app, and the account centre.
 */
@Composable
fun MemberCard(summary: AccountSummary, onCredits: () -> Unit, onOpen: (String) -> Unit) {
    val palette = LocalPalette.current
    val dark = palette.background.luminance() < 0.5f
    val rose = if (dark) Color(0xFFF07C90) else Color(0xFFE85D75)
    val shape = RoundedCornerShape(20.dp)
    Column(Modifier.fillMaxWidth().padding(top = 8.dp)) {
        Column(
            Modifier
                .fillMaxWidth()
                .clip(shape)
                .background(Brush.linearGradient(listOf(rose.copy(alpha = 0.16f), Color(0xFF8E5CF6).copy(alpha = 0.06f))))
                .border(1.dp, rose.copy(alpha = 0.22f), shape)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box {
                    Box(
                        Modifier.size(52.dp).clip(CircleShape).background(Brush.verticalGradient(listOf(Color(0xFFEA5A73), Color(0xFFCF3753)))),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(summary.name.take(1).uppercase(), color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.SemiBold)
                    }
                    Box(Modifier.align(Alignment.BottomEnd).offset(x = 3.dp, y = 3.dp).clip(CircleShape).background(palette.background).padding(2.dp)) {
                        VendorLogo("lynxce", 16.dp)
                    }
                }
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(summary.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        summary.tier?.let {
                            Spacer(Modifier.width(8.dp))
                            Text(
                                it,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                color = Color(0xFF8C5905),
                                modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(Color(0xFFFFDB80)).padding(horizontal = 7.dp, vertical = 2.dp),
                            )
                        }
                    }
                    val line = listOfNotNull(
                        summary.accountHint?.let { stringResource(R.string.account_lynxce_id, it) },
                        summary.memberUntil?.let { stringResource(R.string.account_until, it.format(day)) },
                    ).joinToString(" · ")
                    if (line.isNotEmpty()) Text(line, style = MaterialTheme.typography.bodySmall, color = palette.secondary, maxLines = 1)
                }
            }
            summary.signupExpiryDay?.let {
                Text(stringResource(R.string.signup_credit_expiry, it), style = MaterialTheme.typography.bodySmall, color = palette.secondary)
            }
            summary.credits?.let { total ->
                Column {
                    Row(verticalAlignment = Alignment.Bottom) {
                        Text(credits(total), fontSize = 30.sp, fontWeight = FontWeight.Bold)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.credits_unit), style = MaterialTheme.typography.bodyMedium, color = palette.secondary, modifier = Modifier.padding(bottom = 4.dp))
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                        summary.expiring?.takeIf { it > 0 }?.let { amount ->
                            val text = summary.expiringOn?.let { stringResource(R.string.account_expiring_on, credits(amount), it.format(day)) }
                                ?: stringResource(R.string.account_expiring, credits(amount))
                            Text(text, style = MaterialTheme.typography.bodySmall, color = Color(0xFFE8890C), maxLines = 1)
                        }
                        summary.permanent?.let {
                            Text(stringResource(R.string.account_permanent, credits(it)), style = MaterialTheme.typography.bodySmall, color = palette.secondary, maxLines = 1)
                        }
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(
                    Modifier
                        .weight(1f)
                        .height(44.dp)
                        .clip(RoundedCornerShape(12.dp))
                        .background(Brush.verticalGradient(listOf(Color(0xFFEA5A73), Color(0xFFCF3753))))
                        .clickable { onOpen(PRICING_URL) },
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(stringResource(if (summary.member) R.string.account_renew else R.string.account_join), color = Color.White, fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.width(6.dp))
                    Icon(Icons.AutoMirrored.Rounded.OpenInNew, contentDescription = null, tint = Color.White, modifier = Modifier.size(16.dp))
                }
                Row(
                    Modifier
                        .weight(1f)
                        .height(44.dp)
                        .clip(RoundedCornerShape(12.dp))
                        .background(palette.background)
                        .border(1.dp, palette.hairline, RoundedCornerShape(12.dp))
                        .clickable { onOpen("$PRICING_URL#credits") },
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(stringResource(R.string.account_top_up), color = palette.text, fontWeight = FontWeight.SemiBold)
                }
            }
        }
        CardLink(stringResource(R.string.account_credits_usage), stringResource(R.string.account_credits_usage_detail), external = false, onClick = onCredits)
        if (ACCOUNT_CENTRE_OPEN) {
            CardLink(stringResource(R.string.account_centre), stringResource(R.string.account_centre_detail), external = true) { onOpen(ACCOUNT_URL) }
        }
    }
}

@Composable
private fun CardLink(title: String, detail: String, external: Boolean, onClick: () -> Unit) {
    val palette = LocalPalette.current
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).clickable(onClick = onClick).padding(horizontal = 6.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(detail, style = MaterialTheme.typography.bodySmall, color = palette.secondary)
        }
        Icon(
            if (external) Icons.AutoMirrored.Rounded.OpenInNew else Icons.Rounded.ChevronRight,
            contentDescription = null,
            tint = palette.secondary,
            modifier = Modifier.size(if (external) 18.dp else 22.dp),
        )
    }
}
