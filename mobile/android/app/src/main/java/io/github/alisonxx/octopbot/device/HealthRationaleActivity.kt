package io.github.alisonxx.octopbot.device

import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import io.github.alisonxx.octopbot.ui.theme.OctopTheme

/** Health Connect's "why does this app read health data" screen (required to request its permissions). */
class HealthRationaleActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContent {
            OctopTheme {
                val palette = LocalPalette.current
                Column(
                    Modifier
                        .fillMaxSize()
                        .background(palette.background)
                        .safeDrawingPadding()
                        .verticalScroll(rememberScrollState())
                        .padding(24.dp),
                ) {
                    Text(stringResource(R.string.health_rationale_title), style = MaterialTheme.typography.headlineSmall, color = palette.text)
                    Text(
                        stringResource(R.string.health_rationale_text),
                        style = MaterialTheme.typography.bodyLarge,
                        color = palette.secondary,
                        modifier = Modifier.padding(top = 16.dp),
                    )
                    TextButton(onClick = ::finish, modifier = Modifier.padding(top = 16.dp)) {
                        Text(stringResource(R.string.common_close))
                    }
                }
            }
        }
    }
}
