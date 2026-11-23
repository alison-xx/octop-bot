# Review — Octop Bot intro film (zh / en)

Checked with `hyperframes check` (ok), snapshots and frames pulled from the renders.

- Hook (0–4.6 s): title on screen from frame 0; three task cards pile onto the lone user, then gather into a black pill that lands exactly on the message bubble (4.72 s frame matches the bubble rect in both languages).
- App shots use the real demo conversation and the real sidebar from the screenshots; chat text is 31–38 px on screen. Framing keeps the window edges off-screen until the pull-back (fixed: English bubble was cropped; window top band showed at 5.5 s and 9.2 s).
- Cloud: iris opens from the sidebar cloud icon (fixed: a full-white scene background hid the dive). Marker sits on "电脑关机后照常执行" / "even when your computer is off" in the real screenshot; English push-in lowered to 1.6x so the line start is not cropped.
- End card: crew drops on beats 26.0–27.0, icon + wordmark at 27.25–27.9, CTA held 3.5 s.
- Audio (measured, not heard): integrated −14.9 LUFS, true peak −1.0 dBFS; voice tracks normalised to −17 LUFS, music bed at 0.2 rising to ~0.6 under the end card; zh and en renders carry different voice tracks.
- Known: `font_face_local_only` (PingFang SC via `local()`), so renders must run on a Mac; pull-back frame text is below the 28 px floor on purpose (context view).
