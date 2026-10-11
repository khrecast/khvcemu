package com.khrecast.recast;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.drawable.BitmapDrawable;
import android.net.Uri;
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
import android.widget.Toast;



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
    static final String EXTRA_IMPORT = "import";      // offer Import (only when the game is not running)

    private static final int REQ_IMPORT = 10, REQ_EXPORT = 11;

    private String mode = "load";
    private LinearLayout list;
    private String exportSlot;                        // the slot waiting for the player to choose where to write it

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        mode = "save".equals(getIntent().getStringExtra(EXTRA_MODE)) ? "save" : "load";
        int pad = dp(16);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.addView(Labels.picture(this, "save".equals(mode) ? R.drawable.menu_save_slot : R.drawable.menu_load_saved, 32,
                Labels.maxWidth(this), false, "save".equals(mode) ? "Save to a slot" : "Load a saved game"));
        TextView hint = text("save".equals(mode)
                ? "Tap a slot to save the game there. The autosaves can only be loaded."
                : "Tap a slot to load it. Press and hold a slot to export or delete it.", 14, 0xFF8EA4BF);
        hint.setPadding(0, dp(4), 0, dp(12));
        col.addView(hint);
        android.widget.FrameLayout importButton = Labels.pictureButton(this, R.drawable.menu_b_import, 20, 52, false,
                "Import a state file", v -> startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT)
                        .addCategory(Intent.CATEGORY_OPENABLE).setType("*/*"), REQ_IMPORT));
        ((LinearLayout.LayoutParams) importButton.getLayoutParams()).bottomMargin = dp(12);
        if (getIntent().getBooleanExtra(EXTRA_IMPORT, false)) {      // not while the game is running: it owns the slots
            col.addView(importButton);
        }
        if (savedInstanceState != null) {
            exportSlot = savedInstanceState.getString("exportSlot");
        }
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

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        out.putString("exportSlot", exportSlot);                       // the picker may outlive this screen
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
                new AlertDialog.Builder(this).setTitle(s.label)
                        .setItems(new String[]{"Export to a file...", "Delete..."}, (d, which) -> {
                            if (which == 0) {
                                exportSlot = name;
                                startActivityForResult(new Intent(Intent.ACTION_CREATE_DOCUMENT)
                                        .addCategory(Intent.CATEGORY_OPENABLE).setType("application/octet-stream")
                                        .putExtra(Intent.EXTRA_TITLE, "recast_" + (s.isAuto() ? name : "slot" + name) + ".khs"),
                                        REQ_EXPORT);
                            } else {
                                new AlertDialog.Builder(this).setTitle("Delete " + s.label + "?")
                                        .setMessage("This cannot be undone.")
                                        .setPositiveButton("Delete", (d2, w) -> {
                                            SaveSlots.delete(this, name);
                                            fill();
                                        })
                                        .setNegativeButton("Cancel", null).show();
                            }
                        }).show();
                return true;
            });
        }
        return row;
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null || data.getData() == null) {
            return;
        }
        Uri uri = data.getData();
        if (requestCode == REQ_EXPORT) {
            boolean found = false;
            for (SaveSlots.Slot s : SaveSlots.all(this)) {
                if (s.name.equals(exportSlot)) {
                    found = true;
                    try {
                        SaveSlots.exportTo(this, s, uri);
                        Toast.makeText(this, "Saved to the file you chose", Toast.LENGTH_SHORT).show();
                    } catch (Exception e) {
                        Toast.makeText(this, "Could not write the file: " + e.getMessage(), Toast.LENGTH_LONG).show();
                    }
                }
            }
            if (!found) {
                Toast.makeText(this, "Could not tell which save to export, try again", Toast.LENGTH_LONG).show();
            }
        } else if (requestCode == REQ_IMPORT) {
            chooseSlotForImport(uri);
        }
    }

    /** The picked file goes into a slot from 1 to 9: the player chooses which (filled ones say so). */
    private void chooseSlotForImport(Uri uri) {
        try (java.io.InputStream in = getContentResolver().openInputStream(uri)) {
            if (in == null || !SaveSlots.looksLikeState(in)) {
                Toast.makeText(this, "That is not a Re:Cast state file (.khs)", Toast.LENGTH_LONG).show();
                return;
            }
        } catch (Exception e) {
            Toast.makeText(this, "Could not read that file: " + e.getMessage(), Toast.LENGTH_LONG).show();
            return;
        }
        java.util.List<SaveSlots.Slot> slots = SaveSlots.all(this);
        String[] items = new String[9];
        for (int i = 0; i < 9; i++) {
            items[i] = slots.get(i).label + (slots.get(i).exists ? " (replace)" : " (empty)");
        }
        new AlertDialog.Builder(this).setTitle("Import into which slot?").setItems(items, (d, which) -> {
            try {
                if (SaveSlots.importInto(this, uri, String.valueOf(which + 1))) {
                    Toast.makeText(this, "Imported into " + slots.get(which).label, Toast.LENGTH_SHORT).show();
                    fill();
                } else {
                    Toast.makeText(this, "That is not a Re:Cast state file (.khs)", Toast.LENGTH_LONG).show();
                }
            } catch (Exception e) {
                Toast.makeText(this, "Could not import: " + e.getMessage(), Toast.LENGTH_LONG).show();
            }
        }).setNegativeButton("Cancel", null).show();
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
