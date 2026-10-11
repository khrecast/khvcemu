package com.khrecast.recast;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/**
 * Asked once, right after the opening notice the first time the app is opened: how to play. Smartphone style is the touch
 * controls round the picture; flip phone style puts the game in a 2005 clamshell with a keypad (the most authentic way to
 * play a V CAST game), with two choices of its own, graphite instead of silver and a small bezel for a bigger picture. The
 * answer is kept; everything here can be changed later in Options.
 */
public class StyleActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER_HORIZONTAL);

        boolean wide = getResources().getDisplayMetrics().widthPixels > getResources().getDisplayMetrics().heightPixels;
        ImageView logo = new ImageView(this);
        logo.setImageResource(R.drawable.recast_logo);
        logo.setAdjustViewBounds(true);
        logo.setScaleType(ImageView.ScaleType.FIT_CENTER);
        logo.setContentDescription("Kingdom Hearts Re:Cast");
        logo.setMaxHeight(Math.min(dp(140), Math.round(getResources().getDisplayMetrics().heightPixels * (wide ? 0.12f : 0.16f))));
        col.addView(logo, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        ImageView title = Labels.picture(this, R.drawable.menu_style_title, 24, Labels.maxWidth(this), false,
                "How do you want to play?");
        ((LinearLayout.LayoutParams) title.getLayoutParams()).gravity = Gravity.CENTER_HORIZONTAL;
        ((LinearLayout.LayoutParams) title.getLayoutParams()).topMargin = dp(16);
        ((LinearLayout.LayoutParams) title.getLayoutParams()).bottomMargin = dp(4);
        col.addView(title);
        TextView sub = text("You can change this any time in Options.", 14, 0xFF9FB0C3);
        sub.setGravity(Gravity.CENTER);
        sub.setPadding(0, 0, 0, dp(16));
        col.addView(sub);

        col.addView(choice(R.drawable.menu_style_smart, "Smartphone style", false,
                "Touch controls round the picture, and the biggest picture. Turn the phone sideways for a wider view.",
                v -> done(false, 0, false)));

        TextView flipNote = text("Flip phone style, the most authentic 2005 V CAST experience: the game in the screen of a clamshell phone, "
                + "played on its keypad and navigation ring.", 14, 0xFFCFD8DC);
        flipNote.setPadding(0, dp(24), 0, dp(8));
        TextView colorLabel = text("Color", 14, 0xFFCFD8DC);
        android.widget.Spinner colors = new android.widget.Spinner(this);
        colors.setAdapter(new android.widget.ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, Settings.FLIP_COLORS));
        CheckBox bezel = new CheckBox(this);
        bezel.setText("Small bezel (a bigger picture)");
        bezel.setTextColor(0xFFCFD8DC);
        bezel.setButtonTintList(android.content.res.ColorStateList.valueOf(0xFF9CC4F5));
        View flip = Labels.pictureButton(this, R.drawable.menu_style_flip, 24, 64, true, "Play in flip phone style",
                v -> done(true, colors.getSelectedItemPosition(), bezel.isChecked()));
        col.addView(flipNote);                                          // the choices come first: the button below goes on
        col.addView(colorLabel);
        col.addView(colors);
        col.addView(bezel);
        col.addView(flip);

        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(Color.BLACK);
        scroll.setFillViewport(true);
        scroll.addView(col);
        setContentView(scroll);
        Edge.pad(scroll, col, dp(24), dp(16), dp(24), dp(32));
    }

    private View choice(int picture, String label, boolean primary, String note, android.view.View.OnClickListener l) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.addView(Labels.pictureButton(this, picture, 24, 64, primary, label, l));
        TextView t = text(note, 14, 0xFFCFD8DC);
        t.setPadding(0, dp(8), 0, 0);
        box.addView(t);
        return box;
    }

    private void done(boolean flip, int color, boolean smallBezel) {
        Settings.setFlipPhone(this, flip);
        Settings.setFlipColor(this, flip ? color : 0);
        Settings.setFlipSmallBezel(this, flip && smallBezel);
        Settings.setStyleChosen(this, true);
        startActivity(new Intent(this, HomeActivity.class));
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
