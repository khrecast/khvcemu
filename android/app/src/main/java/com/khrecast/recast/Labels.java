package com.khrecast.recast;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.drawable.BitmapDrawable;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;

/**
 * The menu and heading names drawn in the Kingdom Hearts menu font (the same look as the desktop launcher's tab names;
 * made by tools/make_tab_labels.py, which also copies them into res/drawable-nodpi/menu_*.png). They are small pictures,
 * enlarged by a whole number so the hard pixel edges stay crisp.
 */
final class Labels {
    private Labels() {
    }

    /** A picture label about `targetDp` tall (rounded to a whole-number scale, and not wider than `maxWidthPx`). */
    static ImageView picture(Context context, int resId, int targetDp, int maxWidthPx, boolean centeredInFrame,
                             String description) {
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inScaled = false;                              // the pixels as drawn
        Bitmap bm = BitmapFactory.decodeResource(context.getResources(), resId, options);
        float density = context.getResources().getDisplayMetrics().density;
        int scale = Math.max(1, Math.round(targetDp * density / bm.getHeight()));
        while (scale > 1 && bm.getWidth() * scale > maxWidthPx) {
            scale--;
        }
        BitmapDrawable drawable = new BitmapDrawable(context.getResources(), bm);
        drawable.setFilterBitmap(false);                       // crisp pixels
        ImageView view = new ImageView(context);
        view.setImageDrawable(drawable);
        view.setScaleType(ImageView.ScaleType.FIT_XY);
        view.setContentDescription(description);
        int w = bm.getWidth() * scale, h = bm.getHeight() * scale;
        if (w > maxWidthPx && maxWidthPx > 0) {                // even 1x is too wide (a long label, a narrow screen): shrink it to fit
            h = Math.max(1, Math.round(h * (float) maxWidthPx / w));
            w = maxWidthPx;
            drawable.setFilterBitmap(true);
        }
        if (centeredInFrame) {
            view.setLayoutParams(new FrameLayout.LayoutParams(w, h, Gravity.CENTER));
        } else {
            view.setLayoutParams(new LinearLayout.LayoutParams(w, h));
        }
        return view;
    }

    /** A section heading in the menu font: a smaller picture label with room above and below it. */
    static ImageView heading(Context context, int resId, String description) {
        ImageView v = picture(context, resId, 20, maxWidth(context), false, description);
        float density = context.getResources().getDisplayMetrics().density;
        LinearLayout.LayoutParams lp = (LinearLayout.LayoutParams) v.getLayoutParams();
        lp.topMargin = Math.round(22 * density);
        lp.bottomMargin = Math.round(8 * density);
        if (android.os.Build.VERSION.SDK_INT >= 28) {
            v.setAccessibilityHeading(true);                   // TalkBack can jump from heading to heading
        }
        return v;
    }

    /** Enables or greys a picture button (the picture dims with it). */
    static void enable(FrameLayout pictureButton, boolean on) {
        pictureButton.getChildAt(0).setEnabled(on);
        pictureButton.getChildAt(1).setAlpha(on ? 1f : 0.4f);
    }

    /** The width a label may use on this screen: the screen minus the screen padding and a little room inside a button. */
    static int maxWidth(Context context) {
        return context.getResources().getDisplayMetrics().widthPixels
                - 2 * Math.round(26 * context.getResources().getDisplayMetrics().density);
    }

    private static Drawable shape(Context context, int top, int bottom, int stroke) {
        float density = context.getResources().getDisplayMetrics().density;
        GradientDrawable g = new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, new int[]{top, bottom});
        g.setCornerRadius(10 * density);
        g.setStroke(Math.round(2 * density), stroke);
        return g;
    }

    /**
     * The look of a button, from the launcher's palette and the logo's blue: the main button is a bright blue gradient
     * with a silver outline (like the selected tab); the others are dark navy with a blue-silver outline. Both brighten
     * while pressed.
     */
    static Drawable buttonBackground(Context context, boolean primary) {
        StateListDrawable states = new StateListDrawable();
        states.addState(new int[]{-android.R.attr.state_enabled}, shape(context, 0xFF3A4452, 0xFF262E3A, 0xFF566275));   // greyed out
        Drawable pressed = primary ? shape(context, 0xFF7DC0FF, 0xFF3A82EE, 0xFFFFFFFF)
                : shape(context, 0xFF2C5282, 0xFF173158, 0xFFA9C4EA);
        states.addState(new int[]{android.R.attr.state_pressed}, pressed);
        states.addState(new int[]{android.R.attr.state_focused}, pressed);           // keyboard / D-pad focus looks pressed
        states.addState(new int[]{}, primary ? shape(context, 0xFF3E95F5, 0xFF1C5FD1, 0xFFE6EEFB)
                : shape(context, 0xFF1E3A5F, 0xFF0F2038, 0xFF6F93C4));
        return states;
    }

    /** Gives an ordinary text Button the themed look (white text, no raised shadow). */
    static void theme(android.widget.Button button, boolean primary) {
        button.setBackground(buttonBackground(button.getContext(), primary));
        button.setStateListAnimator(null);
        button.setTextColor(new android.content.res.ColorStateList(
                new int[][]{{-android.R.attr.state_enabled}, {}}, new int[]{0xFF8A97A8, 0xFFFFFFFF}));
        button.setAllCaps(false);
    }

    private static ImageView face(Context context, int resId, int targetDp, int maxWidthPx, String description) {
        ImageView pic = picture(context, resId, targetDp, maxWidthPx, true, description);
        pic.setClickable(false);
        pic.setImportantForAccessibility(android.view.View.IMPORTANT_FOR_ACCESSIBILITY_NO);   // the Button already says it
        pic.setElevation(12 * context.getResources().getDisplayMetrics().density);            // a Button is raised: the picture sits above it
        return pic;
    }

    /** Puts another picture on a picture button (for a button that changes what it says, such as Play and Stop). */
    static void setFace(Context context, FrameLayout pictureButton, int resId, int targetDp, int maxWidthPx, String description) {
        boolean enabled = pictureButton.getChildAt(0).isEnabled();
        pictureButton.removeViewAt(1);
        ImageView pic = face(context, resId, targetDp, maxWidthPx, description);
        pic.setAlpha(enabled ? 1f : 0.4f);
        pictureButton.addView(pic);
        pictureButton.getChildAt(0).setContentDescription(description);
    }

    /** A button face made of a picture label: a normal Button with the picture centered on top (touches go to the button). */
    static FrameLayout pictureButton(Context context, int resId, int targetDp, int heightDp, boolean primary,
                                     String description, android.view.View.OnClickListener listener) {
        return pictureButton(context, resId, targetDp, heightDp, primary, description, maxWidth(context), listener);
    }

    /** Same, with the widest the picture may be (for a button that is not the full width). The caller sets the layout. */
    static FrameLayout pictureButton(Context context, int resId, int targetDp, int heightDp, boolean primary,
                                     String description, int maxWidthPx, android.view.View.OnClickListener listener) {
        FrameLayout box = new FrameLayout(context);
        android.widget.Button button = new android.widget.Button(context);
        theme(button, primary);
        button.setOnClickListener(listener);
        button.setContentDescription(description);
        box.addView(button, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
        box.addView(face(context, resId, targetDp, maxWidthPx, description));
        float density = context.getResources().getDisplayMetrics().density;
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                Math.round(heightDp * density));
        lp.topMargin = Math.round(8 * density);
        box.setLayoutParams(lp);
        return box;
    }
}
