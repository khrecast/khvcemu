package com.khrecast.recast;

import android.app.Activity;
import android.graphics.Color;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.TypedValue;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.Switch;
import android.widget.Spinner;
import android.widget.TextView;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.util.Locale;

/**
 * The Sound screen: a ready-made mix to start from, and a slider for each family of instruments and for how the piano and
 * horns sound (the same settings as the desktop launcher's Sound tab). Every change is saved at once and is heard the next
 * time the game starts (the game renders its music when it starts, and keeps what it has rendered for each setting).
 */
public class SoundActivity extends Activity {
    private static final int STEPS = 600;               // slider resolution

    private final SeekBar[] bars = new SeekBar[SoundSettings.SLIDERS.length];
    private final TextView[] values = new TextView[SoundSettings.SLIDERS.length];
    private Spinner mix;
    private android.widget.FrameLayout favoriteMix, clearCache;
    private TextView cacheNote;
    private android.widget.FrameLayout deleteMix, renameMix;     // picture buttons (the menu font)
    private java.util.List<String> mixNames = new java.util.ArrayList<>();   // ready-made mixes, saved mixes, then "Custom"
    private boolean loading;                            // true while the screen sets the sliders itself
    private Spinner tune;
    private android.widget.FrameLayout playButton;
    private TextView tuneStatus;
    private AudioTrack track;                           // the tune being played (looping), or null
    private boolean wantPlaying;                        // the player pressed Play and has not pressed Stop
    private boolean recMode;                            // what plays is the recording, not the built-in version
    private android.widget.FrameLayout recPlayButton;
    private android.widget.FrameLayout recChoose, recRemove, recMatch;
    private TextView recStatus, recGainText;
    private SeekBar recGainBar;
    private Switch recInGame;
    private boolean recLoading;                         // true while the screen sets the recording controls itself
    private static final int PICK_RECORDING = 41;
    private static final int REC_GAIN_STEPS = 400;      // percent, 0 to 400
    private int renderToken;                            // a newer request makes an older render's result obsolete
    private boolean rendering;                          // one tune is made at a time (the interpreter is shared with the game)
    private boolean renderAgain;                        // asked again while one was being made: make it again when it ends
    private static final Object PYTHON_START = new Object();
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final Runnable restart = this::startTune;   // after the sliders move: make the tune again

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        int pad = dp(20);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.addView(Labels.picture(this, R.drawable.menu_sound, 32, Labels.maxWidth(this), false, "Sound"));

        col.addView(heading("Try the music"));
        tune = new Spinner(this);
        String[] tuneNames = new String[SoundSettings.TUNES.length];
        for (int i = 0; i < tuneNames.length; i++) {
            tuneNames[i] = SoundSettings.TUNES[i][1];
        }
        tune.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, tuneNames));
        col.addView(tune);
        playButton = Labels.pictureButton(this, R.drawable.menu_b_play, 22, 56, true, "Play", v -> {
            if (wantPlaying && !recMode) {
                stopTune();
            } else {
                wantPlaying = true;
                recMode = false;
                startTune();
            }
        });
        col.addView(playButton);
        tuneStatus = note("Plays the tune with the sliders below, over and over. Move a slider and it is made again a moment "
                + "later, so you can tune by ear. Pick another tune while it plays to change over.");
        col.addView(tuneStatus);
        tune.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                refreshRecordingUi();
                if (wantPlaying) {
                    if (recMode && Settings.recFile(SoundActivity.this, currentTune()).isEmpty()) {
                        stopTune();                                  // this tune has no recording to play
                    } else {
                        startTune();
                    }
                }
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
            }
        });

        col.addView(heading("A recording of this tune"));
        recStatus = text("", 14, Color.WHITE);
        col.addView(recStatus);
        LinearLayout recRow = new LinearLayout(this);
        recRow.setOrientation(LinearLayout.HORIZONTAL);
        recChoose = Labels.pictureButton(this, R.drawable.menu_b_choose_file, 18, 48, false, "Choose a file", halfPicture(), v -> {
            Intent pick = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            pick.addCategory(Intent.CATEGORY_OPENABLE);
            pick.setType("audio/*");
            startActivityForResult(pick, PICK_RECORDING);
        });
        recRemove = Labels.pictureButton(this, R.drawable.menu_b_remove_recording, 18, 48, false, "Remove it", halfPicture(),
                v -> removeRecording());
        LinearLayout.LayoutParams rl = new LinearLayout.LayoutParams(0, dp(48), 1f);
        rl.rightMargin = dp(4);
        LinearLayout.LayoutParams rr = new LinearLayout.LayoutParams(0, dp(48), 1f);
        rr.leftMargin = dp(4);
        recRow.addView(recChoose, rl);
        recRow.addView(recRemove, rr);
        LinearLayout.LayoutParams recRowLp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        recRowLp.topMargin = dp(6);
        col.addView(recRow, recRowLp);
        recPlayButton = Labels.pictureButton(this, R.drawable.menu_b_play_recording, 20, 52, true, "Play the recording", v -> {
            if (wantPlaying && recMode) {
                stopTune();
            } else {
                wantPlaying = true;
                recMode = true;
                startTune();
            }
        });
        col.addView(recPlayButton);
        LinearLayout gainHead = new LinearLayout(this);
        gainHead.setOrientation(LinearLayout.HORIZONTAL);
        gainHead.setPadding(0, dp(10), 0, 0);
        TextView gainLabel = text("Recording volume", 16, Color.WHITE);
        gainLabel.setLayoutParams(new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        gainHead.addView(gainLabel);
        recGainText = text("100%", 14, 0xFF8EA4BF);
        gainHead.addView(recGainText);
        col.addView(gainHead);
        recGainBar = new SeekBar(this);
        recGainBar.setMax(REC_GAIN_STEPS);
        recGainBar.setContentDescription("Recording volume");
        recGainBar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar b, int progress, boolean fromUser) {
                recGainText.setText(progress + "%");
                if (fromUser && !recLoading) {
                    Settings.setRecGain(SoundActivity.this, currentTune(), progress / 100f);
                    if (wantPlaying && recMode) {
                        scheduleRestart();
                    }
                }
            }

            @Override
            public void onStartTrackingTouch(SeekBar b) {
            }

            @Override
            public void onStopTrackingTouch(SeekBar b) {
            }
        });
        col.addView(recGainBar);
        recMatch = Labels.pictureButton(this, R.drawable.menu_b_match, 18, 52, false, "Match its loudness to the built-in version",
                v -> matchLevel());
        col.addView(recMatch);
        recInGame = new Switch(this);
        recInGame.setText("Use the recording in the game");
        recInGame.setTextColor(Color.WHITE);
        recInGame.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        recInGame.setPadding(0, dp(12), 0, dp(4));
        recInGame.setOnCheckedChangeListener((b, on) -> {
            if (!recLoading) {
                Settings.setRecInGame(this, currentTune(), on);
            }
        });
        col.addView(recInGame);
        col.addView(note("Your own recording of the tune (FLAC, MP3, M4A, OGG...). Play it, then the built-in version above, to "
                + "compare. \"Use the recording in the game\" plays it in place of this tune the next time the game starts, "
                + "cut or padded to the tune's length so the game's timing does not change. The mix and the sliders do not "
                + "apply to it; the game's Music volume and this volume do."));

        col.addView(heading("Mix"));
        mix = new Spinner(this);
        col.addView(mix);
        LinearLayout mixButtons = new LinearLayout(this);
        mixButtons.setOrientation(LinearLayout.HORIZONTAL);
        android.widget.FrameLayout saveMix = Labels.pictureButton(this, R.drawable.menu_b_save_mix, 18, 48, false, "Save this mix",
                halfPicture(), v -> askMixName());
        deleteMix = Labels.pictureButton(this, R.drawable.menu_b_delete_mix, 18, 48, false, "Delete this mix", halfPicture(),
                v -> confirmDeleteMix());
        LinearLayout.LayoutParams half = new LinearLayout.LayoutParams(0, dp(48), 1f);
        half.rightMargin = dp(4);
        LinearLayout.LayoutParams halfRight = new LinearLayout.LayoutParams(0, dp(48), 1f);
        halfRight.leftMargin = dp(4);
        mixButtons.addView(saveMix, half);
        mixButtons.addView(deleteMix, halfRight);
        LinearLayout.LayoutParams mixRow = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        mixRow.topMargin = dp(6);
        col.addView(mixButtons, mixRow);
        LinearLayout mixButtons2 = new LinearLayout(this);
        mixButtons2.setOrientation(LinearLayout.HORIZONTAL);
        favoriteMix = Labels.pictureButton(this, R.drawable.menu_b_star, 18, 48, false, "Star this mix", halfPicture(),
                v -> toggleFavorite());
        renameMix = Labels.pictureButton(this, R.drawable.menu_b_rename_mix, 18, 48, false, "Rename this mix", halfPicture(),
                v -> askRename());
        LinearLayout.LayoutParams half3 = new LinearLayout.LayoutParams(0, dp(48), 1f);
        half3.rightMargin = dp(4);
        LinearLayout.LayoutParams half4 = new LinearLayout.LayoutParams(0, dp(48), 1f);
        half4.leftMargin = dp(4);
        mixButtons2.addView(favoriteMix, half3);
        mixButtons2.addView(renameMix, half4);
        LinearLayout.LayoutParams mixRow2 = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        mixRow2.topMargin = dp(6);
        col.addView(mixButtons2, mixRow2);
        col.addView(note("Pick a ready-made mix, or move the sliders for your own. Press Play above to hear it now; the game uses it the next time it starts. "
                + "The game's own sound effects are not changed. The first start after a change takes a few seconds longer "
                + "while the music is made."));

        for (int i = 0; i < SoundSettings.SLIDERS.length; i++) {
            if (i == 0) {
                col.addView(heading("How loud"));
            } else if (i == SoundSettings.VOLUME_COUNT) {
                col.addView(heading("How the instruments sound"));
            }
            col.addView(slider(i));
        }

        android.widget.FrameLayout reset = Labels.pictureButton(this, R.drawable.menu_b_back_tuned, 18, 56, false,
                "Back to the sound the game was tuned to", v -> setAll(""));
        ((LinearLayout.LayoutParams) reset.getLayoutParams()).topMargin = dp(20);
        col.addView(reset);
        clearCache = Labels.pictureButton(this, R.drawable.menu_b_clear_cache, 18, 56, false, "Clear the made music",
                v -> confirmClearCache());
        col.addView(clearCache);
        cacheNote = note("");
        col.addView(cacheNote);
        showCacheSize();

        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(Color.BLACK);
        scroll.addView(col);
        setContentView(scroll);
        Edge.pad(scroll, col, pad, dp(16), pad, dp(32));

        rebuildMixList();
        showButtons();
        refreshRecordingUi();
        setAll(Settings.music(this), false);
        mix.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                String chosen = textOfMix(position);
                updateDeleteButton();
                if (loading || chosen == null) {
                    return;                                          // "Custom" is not a mix to apply
                }
                if (SoundSettings.normalize(chosen).equals(SoundSettings.normalize(Settings.music(SoundActivity.this)))) {
                    return;                                          // already this mix (the picker reports its starting choice)
                }
                setAll(chosen);
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
            }
        });
    }

    private View slider(int i) {
        String[] s = SoundSettings.SLIDERS[i];
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setPadding(0, dp(8), 0, 0);
        LinearLayout head = new LinearLayout(this);
        head.setOrientation(LinearLayout.HORIZONTAL);
        TextView label = text(s[1], 16, Color.WHITE);
        label.setLayoutParams(new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        head.addView(label);
        values[i] = text("", 14, 0xFF8EA4BF);
        head.addView(values[i]);
        row.addView(head);
        SeekBar bar = new SeekBar(this);
        bar.setMax(STEPS);
        bar.setContentDescription(s[1]);
        bars[i] = bar;
        bar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar b, int progress, boolean fromUser) {
                values[i].setText(String.format(Locale.US, "%.2f", valueOf(i)));
                if (fromUser) {
                    changed();
                }
            }

            @Override
            public void onStartTrackingTouch(SeekBar b) {
            }

            @Override
            public void onStopTrackingTouch(SeekBar b) {
            }
        });
        row.addView(bar);
        return row;
    }

    private float valueOf(int i) {
        String[] s = SoundSettings.SLIDERS[i];
        float low = SoundSettings.low(s), high = SoundSettings.high(s);
        return low + (high - low) * bars[i].getProgress() / STEPS;
    }

    private void setAll(String text) {
        setAll(text, true);
    }

    /** Puts a whole settings text on the sliders (and saves it, when asked). */
    private void setAll(String text, boolean save) {
        loading = true;
        for (int i = 0; i < bars.length; i++) {
            String[] s = SoundSettings.SLIDERS[i];
            float low = SoundSettings.low(s), high = SoundSettings.high(s);
            float v = Math.min(high, Math.max(low, SoundSettings.value(text, s[0])));
            bars[i].setProgress(Math.round((v - low) / (high - low) * STEPS));
            values[i].setText(String.format(Locale.US, "%.2f", v));
        }
        loading = false;
        if (save) {
            Settings.setMusic(this, normalized(text));                // exactly what was chosen, not re-read from the sliders
            if (!recMode) {
                scheduleRestart();
            }
        }
        showMixName();
    }

    /** The text for a whole set of values: each one clamped to its slider's range (as the module does). */
    private static String normalized(String text) {
        float[] v = new float[SoundSettings.SLIDERS.length];
        for (int i = 0; i < v.length; i++) {
            String[] s = SoundSettings.SLIDERS[i];
            v[i] = Math.min(SoundSettings.high(s), Math.max(SoundSettings.low(s), SoundSettings.value(text, s[0])));
        }
        return SoundSettings.text(v);
    }

    /** A slider moved: save the settings and show which mix they make. */
    private void changed() {
        if (loading) {
            return;
        }
        float[] now = new float[bars.length];
        for (int i = 0; i < now.length; i++) {
            now[i] = valueOf(i);
            String[] s = SoundSettings.SLIDERS[i];
            if (Math.abs(now[i] - 1f) < (SoundSettings.high(s) - SoundSettings.low(s)) / STEPS) {
                now[i] = 1f;                                          // the slider cannot land exactly on 1.0: close counts
            }
        }
        Settings.setMusic(this, SoundSettings.text(now));
        showMixName();
        if (!recMode) {
            scheduleRestart();                                        // (the sliders do not apply to a recording)
        }
    }

    /** While a tune is playing, a changed setting makes it again after the player pauses (a slider sends many changes). */
    private void scheduleRestart() {
        if (wantPlaying) {
            ui.removeCallbacks(restart);
            ui.postDelayed(restart, 700);
        }
    }

    /** Makes the chosen tune with the saved music settings (a few seconds, off the screen's thread) and plays it in a loop. */
    private void startTune() {
        if (!wantPlaying) {
            return;
        }
        ui.removeCallbacks(restart);
        silence();
        showButtons();
        tuneStatus.setText(recMode ? "Reading the recording..." : "Making the music...");
        if (rendering) {
            renderAgain = true;                                     // not two at once: this one starts when the first ends
            return;
        }
        rendering = true;
        final int token = ++renderToken;
        final String name = SoundSettings.TUNES[Math.max(0, tune.getSelectedItemPosition())][0];
        final String settings = Settings.music(this);
        final boolean asRecording = recMode;
        final String recPath = Settings.recFile(this, name);
        final float recGain = Settings.recGain(this, name);
        new Thread(() -> {
            try {
                synchronized (PYTHON_START) {
                    if (!Python.isStarted()) {
                        Python.start(new AndroidPlatform(getApplicationContext()));
                    }
                }
                PyObject app = Python.getInstance().getModule("recast_app");
                byte[] pcm;
                if (asRecording) {
                    pcm = gained(java.nio.file.Files.readAllBytes(new java.io.File(RecordingDecoder.decodedPath(recPath)).toPath()),
                            recGain);
                } else {
                    pcm = app.callAttr("render_tune", GameInstaller.gameDir(this).getAbsolutePath(), name, settings)
                            .toJava(byte[].class);
                }
                runOnUiThread(() -> {
                    rendering = false;
                    if (renderAgain) {
                        renderAgain = false;
                        startTune();                                 // the settings changed meanwhile: this one is out of date
                    } else if (token == renderToken && wantPlaying && !isDestroyed()) {
                        playLoop(pcm);
                    }
                });
            } catch (Throwable e) {
                runOnUiThread(() -> {
                    rendering = false;
                    renderAgain = false;
                    if (token == renderToken && !isDestroyed()) {
                        wantPlaying = false;
                        showButtons();
                        tuneStatus.setText("Could not make that tune: " + (e.getMessage() == null ? e.toString() : e.getMessage()));
                    }
                });
            }
        }, "tune-render").start();
    }

    private void playLoop(byte[] pcm) {
        silence();
        AudioTrack t = null;
        try {
            t = new AudioTrack.Builder()
                    .setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_GAME)
                            .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                    .setAudioFormat(new AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                            .setSampleRate(22050).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
                    .setBufferSizeInBytes(Math.max(pcm.length, 4096))
                    .setTransferMode(AudioTrack.MODE_STATIC)
                    .build();
            if (t.write(pcm, 0, pcm.length) != pcm.length) {
                throw new IllegalStateException("the sound did not fit in the player");
            }
            t.setLoopPoints(0, pcm.length / 2, -1);
            t.play();
            track = t;
            tuneStatus.setText(recMode ? "Playing the recording." : "Playing. Move the sliders to change it.");
        } catch (RuntimeException e) {
            if (t != null) {
                t.release();
            }
            wantPlaying = false;
            showButtons();
            tuneStatus.setText("Could not play it: " + (e.getMessage() == null ? e.toString() : e.getMessage()));
        }
    }

    private void silence() {
        AudioTrack t = track;
        track = null;
        if (t != null) {
            try {
                t.stop();
            } catch (IllegalStateException ignored) {
            }
            t.release();
        }
    }

    /** The two Play buttons say Stop for the one that is playing. */
    private void showButtons() {
        boolean tunePlaying = wantPlaying && !recMode, recPlaying = wantPlaying && recMode;
        Labels.setFace(this, playButton, tunePlaying ? R.drawable.menu_b_stop : R.drawable.menu_b_play, 22, Labels.maxWidth(this),
                tunePlaying ? "Stop" : "Play");
        Labels.setFace(this, recPlayButton, recPlaying ? R.drawable.menu_b_stop_recording : R.drawable.menu_b_play_recording, 20,
                Labels.maxWidth(this), recPlaying ? "Stop the recording" : "Play the recording");
    }

    /** Samples (16-bit little-endian) at another volume, clipped rather than wrapped. */
    private static byte[] gained(byte[] pcm, float gain) {
        if (Math.abs(gain - 1f) < 1e-6f) {
            return pcm;
        }
        byte[] out = new byte[pcm.length];
        for (int i = 0; i + 1 < pcm.length; i += 2) {
            int s = (short) ((pcm[i] & 0xFF) | (pcm[i + 1] << 8));
            int v = Math.max(-32768, Math.min(32767, Math.round(s * gain)));
            out[i] = (byte) v;
            out[i + 1] = (byte) (v >> 8);
        }
        return out;
    }

    private String currentTune() {
        return SoundSettings.TUNES[Math.max(0, tune.getSelectedItemPosition())][0];
    }

    /** Shows the chosen tune's recording: its name, volume and whether the game uses it. */
    private void refreshRecordingUi() {
        String name = currentTune();
        String file = Settings.recFile(this, name);
        recLoading = true;
        boolean has = !file.isEmpty();
        recStatus.setText(has ? "Recording: " + new java.io.File(file).getName() : "No recording chosen for this tune.");
        Labels.enable(recChoose, true);
        Labels.enable(recRemove, has);
        Labels.enable(recPlayButton, has);
        Labels.enable(recMatch, has);
        recGainBar.setEnabled(has);
        recInGame.setEnabled(has);
        recGainBar.setProgress(Math.round(Settings.recGain(this, name) * 100f));
        recGainText.setText(recGainBar.getProgress() + "%");
        recInGame.setChecked(has && Settings.recInGame(this, name));
        recLoading = false;
    }

    private void removeRecording() {
        String name = currentTune();
        String file = Settings.recFile(this, name);
        if (wantPlaying && recMode) {
            stopTune();
        }
        if (!file.isEmpty()) {
            new java.io.File(file).delete();
            new java.io.File(file + ".22050.pcm").delete();
        }
        Settings.setRecFile(this, name, "");
        Settings.setRecInGame(this, name, false);
        Settings.setRecGain(this, name, 1f);
        refreshRecordingUi();
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == PICK_RECORDING && resultCode == RESULT_OK && data != null && data.getData() != null) {
            copyRecording(data.getData(), currentTune());
        }
    }

    /** Keeps a copy of the chosen file in the app's own folder (the picker gives access to it only now), then matches its level. */
    private void copyRecording(Uri uri, String tuneFile) {
        recStatus.setText("Copying the recording...");
        Labels.enable(recChoose, false);                              // one copy at a time
        new Thread(() -> {
            try {
                String display = "recording";
                try (android.database.Cursor c = getContentResolver().query(uri, null, null, null, null)) {
                    if (c != null && c.moveToFirst()) {
                        int i = c.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME);
                        if (i >= 0 && c.getString(i) != null) {
                            display = c.getString(i);
                        }
                    }
                }
                String ext = display.contains(".") ? display.substring(display.lastIndexOf('.')).replaceAll("[^A-Za-z0-9.]", "") : "";
                java.io.File dir = new java.io.File(getFilesDir(), "recordings");
                dir.mkdirs();
                if (ext.length() > 8) {
                    ext = ext.substring(ext.length() - 8);
                }
                java.io.File dest = new java.io.File(dir, tuneFile.replace(".mid", "") + ext);
                java.io.File fresh = new java.io.File(dir, tuneFile.replace(".mid", "") + ".new" + ext);   // the old copy stays until this one works
                java.io.File freshPcm = new java.io.File(fresh.getAbsolutePath() + ".22050.pcm");
                try {
                    try (java.io.InputStream in = getContentResolver().openInputStream(uri);
                         java.io.OutputStream out = new java.io.FileOutputStream(fresh)) {
                        byte[] buf = new byte[1 << 16];
                        int n;
                        while (in != null && (n = in.read(buf)) > 0) {
                            out.write(buf, 0, n);
                        }
                    }
                    freshPcm.delete();
                    RecordingDecoder.decodedPath(fresh.getAbsolutePath());               // fail now, with a message, if it cannot be read
                } catch (Throwable failed) {
                    fresh.delete();
                    freshPcm.delete();
                    throw failed;
                }
                String old = Settings.recFile(this, tuneFile);                           // it works: the new copy takes the old one's place
                if (!old.isEmpty()) {
                    new java.io.File(old).delete();
                    new java.io.File(old + ".22050.pcm").delete();
                }
                new java.io.File(dest.getAbsolutePath() + ".22050.pcm").delete();
                dest.delete();
                if (!fresh.renameTo(dest) || !freshPcm.renameTo(new java.io.File(dest.getAbsolutePath() + ".22050.pcm"))) {
                    throw new java.io.IOException("could not keep the recording");
                }
                Settings.setRecFile(this, tuneFile, dest.getAbsolutePath());          // now, so a closed screen cannot lose the choice
                Settings.setRecInGame(this, tuneFile, false);
                Settings.setRecGain(this, tuneFile, 1f);
                runOnUiThread(() -> {
                    if (isDestroyed()) {
                        return;
                    }
                    refreshRecordingUi();
                    if (tuneFile.equals(currentTune())) {
                        matchLevel();
                    }
                });
            } catch (Throwable e) {
                runOnUiThread(() -> {
                    if (isDestroyed()) {
                        return;
                    }
                    refreshRecordingUi();
                    android.widget.Toast.makeText(this, "Could not use that file: "
                            + (e.getMessage() == null ? e.toString() : e.getMessage()), android.widget.Toast.LENGTH_LONG).show();
                });
            }
        }, "recording-copy").start();
    }

    /** Sets the recording's volume so it is as loud as the built-in version (the launcher's Match level). */
    private void matchLevel() {
        final String name = currentTune();
        final String file = Settings.recFile(this, name);
        if (file.isEmpty()) {
            return;
        }
        Labels.enable(recMatch, false);
        recStatus.setText("Matching the loudness...");
        final String settings = Settings.music(this);
        new Thread(() -> {
            try {
                synchronized (PYTHON_START) {
                    if (!Python.isStarted()) {
                        Python.start(new AndroidPlatform(getApplicationContext()));
                    }
                }
                String pcm = RecordingDecoder.decodedPath(file);
                float gain = Python.getInstance().getModule("recast_app").callAttr("match_gain",
                        GameInstaller.gameDir(this).getAbsolutePath(), name, settings, pcm).toFloat();
                runOnUiThread(() -> {
                    if (isDestroyed()) {
                        return;
                    }
                    Settings.setRecGain(this, name, gain);
                    if (name.equals(currentTune())) {
                        refreshRecordingUi();
                    }
                });
            } catch (Throwable e) {
                runOnUiThread(() -> {
                    refreshRecordingUi();
                    android.widget.Toast.makeText(this, "Could not match the loudness: "
                            + (e.getMessage() == null ? e.toString() : e.getMessage()), android.widget.Toast.LENGTH_LONG).show();
                });
            }
        }, "recording-match").start();
    }

    private void stopTune() {
        wantPlaying = false;
        renderAgain = false;
        renderToken++;
        ui.removeCallbacks(restart);
        silence();
        showButtons();
        tuneStatus.setText("Stopped.");
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (wantPlaying) {
            stopTune();                                             // no music behind another screen
        }
    }

    @Override
    protected void onDestroy() {
        wantPlaying = false;
        renderToken++;
        ui.removeCallbacks(restart);
        silence();
        super.onDestroy();
    }

    /** The settings text of the mix at a position of the Mix list, or null for "Custom". */
    private String textOfMix(int position) {
        if (position < 0 || position >= mixNames.size() - 1) {
            return null;
        }
        if (position < SoundSettings.PRESETS.length) {
            return SoundSettings.PRESETS[position][1];
        }
        return Settings.mixes(this).get(mixNames.get(position));
    }

    /** The Mix list: the ready-made mixes, the player's saved ones, then "Custom". */
    private void rebuildMixList() {
        mixNames = new java.util.ArrayList<>();
        for (String[] p : SoundSettings.PRESETS) {
            mixNames.add(p[0]);
        }
        for (java.util.Map.Entry<String, String> e : Settings.mixes(this).entrySet()) {
            boolean twin = false;                                    // a damaged entry that equals a ready-made mix cannot be told apart
            for (String[] p : SoundSettings.PRESETS) {
                twin |= SoundSettings.normalize(p[1]).equals(SoundSettings.normalize(e.getValue()));
            }
            if (!twin) {
                mixNames.add(e.getKey());
            }
        }
        mixNames.add("Custom");
        // (the picker reports its starting choice after the next layout; the callback ignores a mix that is already in force)
        java.util.Set<String> stars = Settings.mixFavorites(this);
        java.util.List<String> labels = new java.util.ArrayList<>();
        for (String n : mixNames) {
            labels.add(stars.contains(n) ? "\u2605 " + n : n);               // a star marks a favorite
        }
        mix.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, labels));
    }

    /** Which entry of the Mix list the current sliders are: a ready-made mix, a saved one, or "Custom". */
    private void showMixName() {
        String current = SoundSettings.normalize(Settings.music(this));
        int position = mixNames.size() - 1;                          // "Custom"
        for (int i = 0; i < mixNames.size() - 1; i++) {
            String text = textOfMix(i);
            if (text != null && SoundSettings.normalize(text).equals(current)) {
                position = i;
                break;
            }
        }
        if (mix.getSelectedItemPosition() != position) {
            mix.setSelection(position);                              // (the picker's callback ignores a mix that is already saved)
        }
        updateDeleteButton(position);
    }

    private void updateDeleteButton() {
        updateDeleteButton(mix.getSelectedItemPosition());
    }

    /** "Delete this mix" is for the player's own saved mixes only. */
    private void updateDeleteButton(int position) {
        boolean own = position >= SoundSettings.PRESETS.length && position < mixNames.size() - 1;
        boolean real = position >= 0 && position < mixNames.size() - 1;
        Labels.enable(deleteMix, own);
        Labels.enable(renameMix, own);
        Labels.enable(favoriteMix, real);
        boolean starred = real && Settings.mixFavorites(this).contains(mixNames.get(position));
        Labels.setFace(this, favoriteMix, starred ? R.drawable.menu_b_unstar : R.drawable.menu_b_star, 18, halfPicture(),
                starred ? "Unstar this mix" : "Star this mix");
    }

    private void askMixName() {
        android.widget.EditText input = new android.widget.EditText(this);
        input.setHint("Name of this mix");
        input.setSingleLine(true);
        input.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(40)});
        new android.app.AlertDialog.Builder(this).setTitle("Save this mix").setView(input)
                .setPositiveButton("Save", (d, w) -> saveMixAs(Settings.cleanMixName(input.getText().toString())))
                .setNegativeButton("Cancel", null).show();
    }

    private void saveMixAs(String name) {
        if (name.isEmpty()) {
            return;
        }
        if (name.equalsIgnoreCase("Custom")) {
            android.widget.Toast.makeText(this, "Custom is the name of unsaved sliders: pick another",
                    android.widget.Toast.LENGTH_LONG).show();
            return;
        }
        for (String[] p : SoundSettings.PRESETS) {
            if (p[0].equalsIgnoreCase(name)) {
                android.widget.Toast.makeText(this, "That name belongs to a ready-made mix: pick another",
                        android.widget.Toast.LENGTH_LONG).show();
                return;
            }
        }
        String current = SoundSettings.normalize(Settings.music(this));
        for (String[] p : SoundSettings.PRESETS) {                  // two mixes with the same settings could not be told apart
            if (SoundSettings.normalize(p[1]).equals(current)) {
                android.widget.Toast.makeText(this, "These settings are the ready-made mix " + p[0] + ": change a slider first",
                        android.widget.Toast.LENGTH_LONG).show();
                return;
            }
        }
        for (java.util.Map.Entry<String, String> e : Settings.mixes(this).entrySet()) {
            if (!e.getKey().equalsIgnoreCase(name) && SoundSettings.normalize(e.getValue()).equals(current)) {
                android.widget.Toast.makeText(this, "These settings are already saved as " + e.getKey(),
                        android.widget.Toast.LENGTH_LONG).show();
                return;
            }
        }
        boolean exists = false;
        for (String saved : Settings.mixes(this).keySet()) {
            exists |= saved.equalsIgnoreCase(name);
        }
        if (exists) {
            new android.app.AlertDialog.Builder(this).setTitle("Replace " + name + "?")
                    .setMessage("A mix with this name is already saved.")
                    .setPositiveButton("Replace", (d, w) -> writeMix(name))
                    .setNegativeButton("Cancel", null).show();
        } else {
            writeMix(name);
        }
    }

    private void writeMix(String name) {
        Settings.saveMix(this, name, Settings.music(this));
        rebuildMixList();
        showMixName();
        android.widget.Toast.makeText(this, "Saved as " + name, android.widget.Toast.LENGTH_SHORT).show();
    }

    private java.io.File cacheDir() {
        return new java.io.File(new java.io.File(getFilesDir(), "data"), "audio_cache");
    }

    private static long sizeOf(java.io.File f) {
        long n = 0;
        java.io.File[] kids = f.listFiles();
        if (kids == null) {
            return f.isFile() ? f.length() : 0;
        }
        for (java.io.File k : kids) {
            n += sizeOf(k);
        }
        return n;
    }

    private static void deleteTree(java.io.File f, boolean self) {
        java.io.File[] kids = f.listFiles();
        for (java.io.File k : kids == null ? new java.io.File[0] : kids) {
            deleteTree(k, true);
        }
        if (self) {
            f.delete();
        }
    }

    private void showCacheSize() {
        long bytes = sizeOf(cacheDir());
        Labels.setFace(this, clearCache, bytes == 0 ? R.drawable.menu_b_no_cache : R.drawable.menu_b_clear_cache, 18,
                Labels.maxWidth(this), bytes == 0 ? "No made music is kept" : "Clear the made music");
        Labels.enable(clearCache, bytes > 0);
        cacheNote.setText((bytes == 0 ? "Nothing is kept now. " : String.format(Locale.US, "%.1f MB is kept. ", bytes / 1048576.0))
                + "The music the game made for each mix is kept so the game starts faster; clearing it only means the next start "
                + "makes it again.");
    }

    private void confirmClearCache() {
        new android.app.AlertDialog.Builder(this).setTitle("Clear the made music?")
                .setMessage("Your mixes and recordings stay. The next time the game starts it makes the music again, which takes a "
                        + "few seconds longer.")
                .setPositiveButton("Clear", (d, w) -> {
                    deleteTree(cacheDir(), false);
                    showCacheSize();
                })
                .setNegativeButton("Cancel", null).show();
    }

    private void toggleFavorite() {
        int position = mix.getSelectedItemPosition();
        if (position < 0 || position >= mixNames.size() - 1) {
            return;
        }
        Settings.toggleMixFavorite(this, mixNames.get(position));
        rebuildMixList();
        showMixName();
    }

    private void askRename() {
        int position = mix.getSelectedItemPosition();
        if (position < SoundSettings.PRESETS.length || position >= mixNames.size() - 1) {
            return;
        }
        String old = mixNames.get(position);
        android.widget.EditText input = new android.widget.EditText(this);
        input.setText(old);
        input.setSelectAllOnFocus(true);
        input.setSingleLine(true);
        input.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(40)});
        new android.app.AlertDialog.Builder(this).setTitle("Rename " + old).setView(input)
                .setPositiveButton("Rename", (d, w) -> renameTo(old, Settings.cleanMixName(input.getText().toString())))
                .setNegativeButton("Cancel", null).show();
    }

    private void renameTo(String old, String name) {
        if (name.isEmpty() || name.equals(old)) {
            return;
        }
        boolean taken = name.equalsIgnoreCase("Custom");
        for (String[] p : SoundSettings.PRESETS) {
            taken |= p[0].equalsIgnoreCase(name);
        }
        for (String saved : Settings.mixes(this).keySet()) {
            taken |= saved.equalsIgnoreCase(name) && !saved.equals(old);
        }
        if (taken) {
            android.widget.Toast.makeText(this, "That name is already used: pick another", android.widget.Toast.LENGTH_LONG).show();
            return;
        }
        Settings.renameMix(this, old, name);
        rebuildMixList();
        showMixName();
    }

    private void confirmDeleteMix() {
        int position = mix.getSelectedItemPosition();
        if (position < SoundSettings.PRESETS.length || position >= mixNames.size() - 1) {
            return;
        }
        String name = mixNames.get(position);
        new android.app.AlertDialog.Builder(this).setTitle("Delete " + name + "?")
                .setMessage("The sliders stay as they are; only the saved name goes.")
                .setPositiveButton("Delete", (d, w) -> {
                    Settings.deleteMix(this, name);
                    rebuildMixList();
                    showMixName();
                })
                .setNegativeButton("Cancel", null).show();
    }

    /** The widest a picture may be on a button that takes half the row. */
    private int halfPicture() {
        int row = getResources().getDisplayMetrics().widthPixels - 2 * dp(20);
        return (row - dp(8)) / 2 - dp(20);
    }

    /** A heading in the menu font (the pictures are made by tools/make_tab_labels.py). */
    private View heading(String s) {
        int res;
        switch (s) {
            case "Try the music": res = R.drawable.menu_h_try; break;
            case "A recording of this tune": res = R.drawable.menu_h_recording; break;
            case "Mix": res = R.drawable.menu_h_mix; break;
            case "How loud": res = R.drawable.menu_h_loud; break;
            default: res = R.drawable.menu_h_instruments; break;
        }
        return Labels.heading(this, res, s);
    }

    private TextView note(String s) {
        TextView t = text(s, 13, 0xFF8EA4BF);
        t.setPadding(0, dp(4), 0, 0);
        return t;
    }

    private TextView text(String s, int sp, int color) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        return t;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
