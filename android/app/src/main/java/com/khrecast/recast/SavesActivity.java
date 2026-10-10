package com.khrecast.recast;

import android.app.Activity;
import android.app.AlertDialog;
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
 * The nine save slots and three autosaves (the same .khs files the desktop makes), each with its picture and date.
 * Started by the game's menu with mode "save" (a tap saves the game into that slot) or "load" (a tap loads it); the
 * choice goes back to the game as the result. A long press on a filled slot offers to delete it.
 */
public class SavesActivity extends Activity {
    static final String EXTRA_MODE = "mode";          // "save" or "load"
    static final String EXTRA_SLOT = "slot";          // the result: "1".."9", "auto", "auto2", "auto3"

    private String mode = "load";
    private LinearLayout list;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        mode = "save".equals(getIntent().getStringExtra(EXTRA_MODE)) ? "save" : "load";
        int pad = dp(16);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        TextView title = text("save".equals(mode) ? "Save to a slot" : "Load a saved game", 24, Color.WHITE);
        title.setTypeface(null, android.graphics.Typeface.BOLD);
        col.addView(title);
        TextView hint = text("save".equals(mode)
                ? "Tap a slot to save the game there. The autosaves can only be loaded."
                : "Tap a slot to load it. Press and hold a slot to delete it.", 14, 0xFF8EA4BF);
        hint.setPadding(0, dp(4), 0, dp(12));
        col.addView(hint);
        list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        col.addView(list);
        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(Color.BLACK);
        scroll.addView(col);
        setContentView(scroll);
        Edge.pad(scroll, col, pad, dp(16), pad, dp(32));
        fill();
    }

    private void fill() {
        list.removeAllViews();
        for (SaveSlots.Slot s : SaveSlots.all(this)) {
            list.addView(row(s));
        }
    }

    private View row(SaveSlots.Slot s) {
        final String name = s.name;
        final boolean exists = s.exists;
        final boolean auto = s.isAuto();
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(8), dp(8), dp(8), dp(8));
        row.setBackgroundColor(0xFF1E2A3C);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.bottomMargin = dp(8);
        row.setLayoutParams(lp);

        ImageView pic = new ImageView(this);
        pic.setScaleType(ImageView.ScaleType.FIT_CENTER);
        pic.setLayoutParams(new LinearLayout.LayoutParams(dp(70), dp(88)));
        pic.setBackgroundColor(Color.BLACK);
        if (exists && s.hasThumb()) {
            Bitmap bm = BitmapFactory.decodeFile(s.thumb.getAbsolutePath());
            if (bm != null) {
                BitmapDrawable d = new BitmapDrawable(getResources(), bm);
                d.setFilterBitmap(false);                      // crisp pixels, as in the game
                pic.setImageDrawable(d);
            }
        }
        row.addView(pic);

        LinearLayout words = new LinearLayout(this);
        words.setOrientation(LinearLayout.VERTICAL);
        words.setPadding(dp(14), 0, 0, 0);
        words.addView(text(s.label, 18, exists ? Color.WHITE : 0xFF6B7A90));
        words.addView(text(exists ? DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT)
                .format(new Date(s.created)) : "Empty", 14, 0xFF8EA4BF));
        row.addView(words);

        boolean tappable = "save".equals(mode) ? !auto : exists;
        row.setAlpha(tappable ? 1f : 0.55f);
        if (tappable) {
            row.setOnClickListener(v -> {
                if ("save".equals(mode) && exists) {
                    new AlertDialog.Builder(this).setTitle("Replace " + s.label + "?")
                            .setMessage("The game saved there will be lost.")
                            .setPositiveButton("Replace", (d, w) -> choose(name))
                            .setNegativeButton("Cancel", null).show();
                } else {
                    choose(name);
                }
            });
        }
        if (exists) {
            row.setOnLongClickListener(v -> {
                new AlertDialog.Builder(this).setTitle("Delete " + s.label + "?")
                        .setMessage("This cannot be undone.")
                        .setPositiveButton("Delete", (d, w) -> {
                            SaveSlots.delete(this, name);
                            fill();
                        })
                        .setNegativeButton("Cancel", null).show();
                return true;
            });
        }
        return row;
    }

    private void choose(String name) {
        setResult(RESULT_OK, new Intent().putExtra(EXTRA_MODE, mode).putExtra(EXTRA_SLOT, name));
        finish();
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
