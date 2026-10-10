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
import android.widget.Button;
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
        ImageView heart = new ImageView(this);
        heart.setImageResource(R.mipmap.ic_launcher_foreground);
        heart.setLayoutParams(new LinearLayout.LayoutParams(dp(110), dp(110)));
        col.addView(heart);
        TextView title = text("Re:Cast", 30, Color.WHITE);
        title.setTypeface(null, android.graphics.Typeface.BOLD);
        col.addView(title);

        if (!GameInstaller.isInstalled(this)
                && !new java.io.File(new java.io.File(getFilesDir(), "game"), "mod").isDirectory()) {
            TextView need = text("Re:Cast needs the game's own files, which are not part of this app. Choose the folder "
                    + "that holds them to get started.", 16, 0xFFCFD8DC);
            need.setPadding(0, dp(16), 0, dp(20));
            col.addView(need);
            col.addView(button("Set up the game files", true, v -> startActivity(new Intent(this, SetupActivity.class))));
            return;
        }

        SaveSlots.Slot newest = SaveSlots.newest(this);
        if (newest != null) {
            col.addView(continueCard(newest));
        }
        col.addView(button("Play from the title screen", newest == null,
                v -> startActivity(new Intent(this, MainActivity.class))));
        col.addView(button("Saved games", false, v -> startActivityForResult(
                new Intent(this, SavesActivity.class).putExtra(SavesActivity.EXTRA_MODE, "load")
                        .putExtra(SavesActivity.EXTRA_IMPORT, true), REQ_SAVES)));
        col.addView(button("Options", false, v -> startActivity(new Intent(this, OptionsActivity.class))));
        col.addView(button("Game files", false, v -> startActivity(new Intent(this, SetupActivity.class))));
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
        words.addView(text("Continue", 22, Color.WHITE));
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

    private Button button(String label, boolean main, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        b.setTextSize(TypedValue.COMPLEX_UNIT_SP, main ? 18 : 16);
        b.setOnClickListener(l);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(main ? 64 : 54));
        lp.topMargin = dp(8);
        b.setLayoutParams(lp);
        return b;
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
