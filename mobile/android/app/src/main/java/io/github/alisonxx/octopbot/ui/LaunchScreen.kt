package io.github.alisonxx.octopbot.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import io.github.alisonxx.octopbot.ui.theme.OctopTheme

/** The system splash icon canvas: the art sits in the same place as on the system splash. */
private val ArtSize = 288.dp

/**
 * The first Compose screen: the launch art centered in the whole window (where the system splash drew it),
 * with "Octop Bot" and the tagline fading in below while the session and directory load.
 */
@Composable
fun LaunchScreen() {
    val palette = LocalPalette.current
    val fade = remember { Animatable(0f) }
    LaunchedEffect(Unit) { fade.animateTo(1f, tween(durationMillis = 450, delayMillis = 120)) }
    BoxWithConstraints(Modifier.fillMaxSize().background(palette.background)) {
        Image(
            painter = painterResource(R.drawable.splash_art),
            contentDescription = null,
            modifier = Modifier.align(Alignment.Center).size(ArtSize),
        )
        // The art fills the 192 dp circle inside the 288 dp canvas: the text starts just under it.
        Column(
            Modifier
                .align(Alignment.TopCenter)
                .offset(y = maxHeight / 2 + 104.dp)
                .padding(horizontal = 32.dp)
                .graphicsLayer {
                    alpha = fade.value
                    translationY = (1f - fade.value) * 8.dp.toPx()
                },
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                "Octop Bot",
                style = MaterialTheme.typography.headlineMedium.copy(fontSize = 30.sp, fontWeight = FontWeight.ExtraBold),
                color = palette.text,
            )
            Spacer(Modifier.height(6.dp))
            Text(
                stringResource(R.string.onboarding_tagline),
                style = MaterialTheme.typography.bodyLarge,
                color = palette.secondary,
                textAlign = TextAlign.Center,
            )
        }
    }
}

@Preview(showBackground = true, backgroundColor = 0xFF000000, heightDp = 800)
@Composable
private fun LaunchPreview() {
    OctopTheme(dark = true) { Box { LaunchScreen() } }
}
