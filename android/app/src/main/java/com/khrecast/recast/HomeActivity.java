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
    private static final int REQ_SAVES = 1;

    private LinearLayout col;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER_HORIZONTAL);
        int pad = dp(24);
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
        logo.setMaxHeight(Math.min(dp(260), Math.round(getResources().getDisplayMetrics().heightPixels * 0.3f)));   // not the whole screen in landscape
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
            col.addView(Labels.pictureButton(this, R.drawable.menu_set_up, 26, 64, "Set up the game files",
                    v -> startActivity(new Intent(this, SetupActivity.class))));
            return;
        }

        SaveSlots.Slot newest = SaveSlots.newest(this);
        if (newest != null) {
            col.addView(continueCard(newest));
        }
        col.addView(Labels.pictureButton(this, R.drawable.menu_play_title, newest == null ? 26 : 20,
                newest == null ? 64 : 54, "Play from the title screen",
                v -> startActivity(new Intent(this, MainActivity.class))));
        col.addView(Labels.pictureButton(this, R.drawable.menu_saved_games, 20, 54, "Saved games",
                v -> startActivityForResult(new Intent(this, SavesActivity.class)
                        .putExtra(SavesActivity.EXTRA_MODE, "load").putExtra(SavesActivity.EXTRA_IMPORT, true), REQ_SAVES)));
        col.addView(Labels.pictureButton(this, R.drawable.menu_options, 20, 54, "Options",
                v -> startActivity(new Intent(this, OptionsActivity.class))));
        col.addView(Labels.pictureButton(this, R.drawable.menu_game_files, 20, 54, "Game files",
                v -> startActivity(new Intent(this, SetupActivity.class))));
        TextView hint = text("In the game, the phone's Back button opens its menu.", 13, 0xFF8EA4BF);
        hint.setPadding(0, dp(20), 0, 0);
        col.addView(hint);
    }

    private View continueCard(SaveSlots.Slot s) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.HORIZONTAL);
        card.setGravity(Gravity.CENTER_VERTICAL);
        card.setBackgroundColor(0xFF1E2A3C);
        card.setPadding(dp(10), dp(10), dp(10), dp(10));
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
        ImageView continueLabel = Labels.picture(this, R.drawable.menu_continue, 24, Labels.maxWidth(this), false, "Continue");
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
