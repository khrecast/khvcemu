package com.khrecast.recast;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.drawable.BitmapDrawable;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.text.DateFormat;
import java.util.Date;

/**
 * The front door: a Continue card with the picture and date of the newest save, "Play from the title screen", the saved
 * games, Options and the game files. Without game files it asks for them first.
 */
public class HomeActivity extends Activity {
    static final String EXTRA_LOAD = "load";          // for MainActivity: a slot to load as soon as the game is up
    static final String EXTRA_START_WORLD = "start_world";   // for MainActivity: seed the game save from this world's start
    private static final int REQ_SAVES = 1;

    private LinearLayout col;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER_HORIZONTAL);
        int pad = dp(16);
        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(Color.BLACK);
        scroll.setFillViewport(true);
        scroll.addView(col);
        setContentView(scroll);
        Edge.pad(scroll, col, pad, dp(16), pad, dp(32));
    }

    @Override
    protected void onResume() {
        super.onResume();
        build();                                       // saves, settings or the game files may have changed
    }

    private void build() {
        col.removeAllViews();
        ImageView logo = new ImageView(this);                  // the Kingdom Hearts Re:Cast logo (wordmark included)
        logo.setImageResource(R.drawable.recast_logo);
        logo.setAdjustViewBounds(true);
        logo.setMaxHeight(Math.min(dp(220), Math.round(getResources().getDisplayMetrics().heightPixels * 0.2f)));   // leaves room for the buttons, in landscape too
        logo.setScaleType(ImageView.ScaleType.FIT_CENTER);
        logo.setContentDescription("Kingdom Hearts Re:Cast");
        LinearLayout.LayoutParams logoParams = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        logoParams.topMargin = dp(8);
        col.addView(logo, logoParams);

        if (!GameInstaller.isInstalled(this)
                && !new java.io.File(new java.io.File(getFilesDir(), "game"), "mod").isDirectory()) {
            TextView need = text("Re:Cast needs the game's own files, which are not part of this app. Choose the folder "
                    + "that holds them to get started.", 16, 0xFFCFD8DC);
            need.setPadding(0, dp(16), 0, dp(20));
            col.addView(need);
            col.addView(Labels.pictureButton(this, R.drawable.menu_set_up, 30, 76, true, "Set up the game files",
                    v -> startActivity(new Intent(this, SetupActivity.class))));
            return;
        }

        SaveSlots.Slot newest = SaveSlots.newest(this);
        if (newest != null) {
            col.addView(continueCard(newest));
        }
        col.addView(Labels.pictureButton(this, R.drawable.menu_play_title, 30, newest == null ? 76 : 68,
                newest == null, "Play from the title screen",
                v -> startActivity(new Intent(this, MainActivity.class))));
        col.addView(Labels.pictureButton(this, R.drawable.menu_saved_games, 30, 68, false, "Saved games",
                v -> startActivityForResult(new Intent(this, SavesActivity.class)
                        .putExtra(SavesActivity.EXTRA_MODE, "load").putExtra(SavesActivity.EXTRA_IMPORT, true), REQ_SAVES)));
        if (!worldSaves().isEmpty()) {
            col.addView(Labels.pictureButton(this, R.drawable.menu_start_world, 30, 68, false, "Start at a world",
                    v -> chooseWorld()));
        }
        // Options and Game files share a row (their names are short), so everything fits on one screen
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        int half = (getResources().getDisplayMetrics().widthPixels - 2 * dp(16) - dp(10)) / 2 - dp(12);   // the picture's room
        android.widget.FrameLayout options = Labels.pictureButton(this, R.drawable.menu_options, 30, 68, false, "Options",
                half, v -> startActivity(new Intent(this, OptionsActivity.class)));
        android.widget.FrameLayout files = Labels.pictureButton(this, R.drawable.menu_game_files, 30, 68, false, "Game files",
                half, v -> startActivity(new Intent(this, SetupActivity.class)));
        for (android.widget.FrameLayout b : new android.widget.FrameLayout[]{options, files}) {
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, dp(68), 1f);   // equal halves
            lp.topMargin = 0;
            lp.leftMargin = b == files ? dp(5) : 0;
            lp.rightMargin = b == options ? dp(5) : 0;
            b.setLayoutParams(lp);
            row.addView(b);
        }
        LinearLayout.LayoutParams rowParams = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        rowParams.topMargin = dp(8);
        col.addView(row, rowParams);
        TextView hint = text("In the game, the phone's Back button opens its menu.", 13, 0xFF8EA4BF);
        hint.setPadding(0, dp(20), 0, 0);
        col.addView(hint);
    }

    /** The worlds the game folder came with a starting save for (savegame(world).dat): {core name, title}. */
    private java.util.List<String[]> worldSaves() {
        java.util.List<String[]> out = new java.util.ArrayList<>();
        String[][] known = {{"training", "The Obstacle Course"}, {"island", "Swashbuckler's Island"},
                {"wonderland", "Wonderland"}, {"agrabah", "Agrabah"}, {"castle", "Maleficent's Castle"}};
        java.io.File[] files = new java.io.File(getFilesDir(), "game").listFiles();
        java.util.Set<String> found = new java.util.HashSet<>();
        if (files != null) {
            for (java.io.File f : files) {
                String low = f.getName().toLowerCase(java.util.Locale.ROOT);
                if (low.startsWith("savegame(") && low.endsWith(").dat")) {
                    String w = low.substring("savegame(".length(), low.length() - ").dat".length());
                    found.add(w.startsWith("malefic") || w.equals("castle") ? "castle" : w);     // "maleficient" is how the files spell it
                }
            }
        }
        for (String[] k : known) {
            if (found.contains(k[0])) {
                out.add(k);
            }
        }
        return out;
    }

    private void chooseWorld() {
        java.util.List<String[]> worlds = worldSaves();
        String[] titles = new String[worlds.size()];
        for (int i = 0; i < titles.length; i++) {
            titles[i] = worlds.get(i)[1];
        }
        new android.app.AlertDialog.Builder(this).setTitle("Start at a world").setItems(titles, (d, which) -> {
            String[] w = worlds.get(which);
            new android.app.AlertDialog.Builder(this).setTitle("Start at " + w[1] + "?")
                    .setMessage("This replaces your current game save with the starting " + w[1] + " save. Then choose "
                            + "Load Game on the title screen.\n\nYour current save is backed up first. To keep playing your "
                            + "own game, use Continue or Play from the title screen instead.")
                    .setPositiveButton("Start", (d2, w2) -> startActivity(new Intent(this, MainActivity.class)
                            .putExtra(EXTRA_START_WORLD, w[0])))
                    .setNegativeButton("Cancel", null).show();
        }).setNegativeButton("Cancel", null).show();
    }

    private View continueCard(SaveSlots.Slot s) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.HORIZONTAL);
        card.setGravity(Gravity.CENTER_VERTICAL);
        card.setBackground(Labels.buttonBackground(this, false));
        card.setPadding(dp(12), dp(12), dp(12), dp(12));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(20);
        lp.bottomMargin = dp(12);
        card.setLayoutParams(lp);

        ImageView pic = new ImageView(this);
        pic.setScaleType(ImageView.ScaleType.FIT_CENTER);
        pic.setBackgroundColor(Color.BLACK);
        pic.setLayoutParams(new LinearLayout.LayoutParams(dp(84), dp(105)));
        if (s.hasThumb()) {
            Bitmap bm = BitmapFactory.decodeFile(s.thumb.getAbsolutePath());
            if (bm != null) {
                BitmapDrawable d = new BitmapDrawable(getResources(), bm);
                d.setFilterBitmap(false);
                pic.setImageDrawable(d);
            }
        }
        card.addView(pic);

        LinearLayout words = new LinearLayout(this);
        words.setOrientation(LinearLayout.VERTICAL);
        words.setPadding(dp(14), 0, 0, 0);
        ImageView continueLabel = Labels.picture(this, R.drawable.menu_continue, 34, Labels.maxWidth(this), false, "Continue");
        words.addView(continueLabel);
        words.addView(text(s.label, 15, 0xFFCFD8DC));
        words.addView(text(DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT)
                .format(new Date(s.created)), 13, 0xFF8EA4BF));
        card.addView(words);
        card.setOnClickListener(v -> {
            SaveSlots.Slot now = SaveSlots.newest(this);       // the newest at the moment of the tap (an autosave may have landed)
            startActivity(new Intent(this, MainActivity.class)
                    .putExtra(EXTRA_LOAD, now != null ? now.name : s.name));
        });
        return card;
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_SAVES && resultCode == RESULT_OK && data != null) {
            startActivity(new Intent(this, MainActivity.class)
                    .putExtra(EXTRA_LOAD, data.getStringExtra(SavesActivity.EXTRA_SLOT)));
        }
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
