package com.khrecast.recast;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.LinearGradient;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RadialGradient;
import android.graphics.RectF;
import android.graphics.Shader;

import java.util.HashMap;
import java.util.Map;
import java.util.Set;

/**
 * How the touch controls look: round glass-like buttons with a bright rim and a soft shadow (blue for Action, violet for Magic,
 * gold for Status), a d-pad on a dark disc with a cross and glowing arrows, and navy softkey pills. A held control lights up and
 * glows. The names are the menu-font pictures also used on the buttons in the menus (tools/make_tab_labels.py). No Java objects
 * are made while drawing: the gradients are made once at a unit size and moved and scaled with a matrix.
 */
final class ControlSkin {
    static final int NAVY = 0, BLUE = 1, VIOLET = 2, GOLD = 3;

    private static final int[][] STOPS = {              // light, middle, dark
            {0xFF4F678C, 0xFF2D4263, 0xFF182740},
            {0xFF6FB2FF, 0xFF2F72E0, 0xFF1A458F},
            {0xFFB39BFF, 0xFF6A4FD0, 0xFF3C2A8A},
            {0xFFFFE493, 0xFFE0A42A, 0xFF9A6A12}};
    private static final int RIM = 0xFFC9D6E8, RIM_HELD = 0xFFFFFFFF, GLOW = 0xFF8FC2FF;

    private final float density;
    private final Shader[] idle = new Shader[4], held = new Shader[4];       // round buttons (unit radial gradients)
    private final Shader pillIdle, pillHeld;                                  // pills (unit vertical gradients)
    private final Shader padBase;
    private final Matrix matrix = new Matrix();
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pic = new Paint(Paint.FILTER_BITMAP_FLAG);
    private final Paint crisp = new Paint();
    private final Paint words = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final MenuFont menuFont;
    private final Path arrow = new Path();
    private final RectF box = new RectF();
    private final Map<String, Bitmap> names = new HashMap<>();

    ControlSkin(Context context) {
        density = context.getResources().getDisplayMetrics().density;
        crisp.setFilterBitmap(false);
        menuFont = new MenuFont(context);
        words.setColor(0xFFFFFFFF);
        words.setTextAlign(Paint.Align.CENTER);
        words.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        for (int i = 0; i < 4; i++) {
            idle[i] = new RadialGradient(-0.3f, -0.4f, 1.5f, STOPS[i], new float[]{0f, 0.55f, 1f}, Shader.TileMode.CLAMP);
            held[i] = new RadialGradient(-0.3f, -0.4f, 1.5f, new int[]{lighter(STOPS[i][0]), lighter(STOPS[i][1]), STOPS[i][1]},
                    new float[]{0f, 0.55f, 1f}, Shader.TileMode.CLAMP);
        }
        pillIdle = new LinearGradient(0, 0, 0, 1, new int[]{0xFF3E557A, 0xFF22344F}, null, Shader.TileMode.CLAMP);
        pillHeld = new LinearGradient(0, 0, 0, 1, new int[]{0xFF6FB2FF, 0xFF2F72E0}, null, Shader.TileMode.CLAMP);
        padBase = new RadialGradient(0f, -0.15f, 1f, new int[]{0xFF2A3D5C, 0xFF16233A, 0xFF0E1625}, new float[]{0f, 0.7f, 1f},
                Shader.TileMode.CLAMP);
        String[][] files = {{"Action", "c_action"}, {"Magic", "c_magic"}, {"Status", "c_status"}, {"Soft 1", "c_soft1"},
                {"Back", "c_back"}, {"Soft 2", "c_soft2"}};
        int[] ids = {R.drawable.menu_c_action, R.drawable.menu_c_magic, R.drawable.menu_c_status, R.drawable.menu_c_soft1,
                R.drawable.menu_c_back, R.drawable.menu_c_soft2};
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inScaled = false;                                              // the pixels as drawn
        for (int i = 0; i < ids.length; i++) {
            Bitmap b = BitmapFactory.decodeResource(context.getResources(), ids[i], options);
            if (b != null) {
                names.put(files[i][0], b);
            }
        }
        Bitmap slash = BitmapFactory.decodeResource(context.getResources(), R.drawable.menu_c_action_slash, options);
        if (slash != null) {
            names.put("Action/", slash);
        }
        String[] banner = {"Open", "Attack", "Grab", "Jump", "Talk", "Interact", "Use"};
        int[] bannerIds = {R.drawable.menu_w_open, R.drawable.menu_w_attack, R.drawable.menu_w_grab, R.drawable.menu_w_jump,
                R.drawable.menu_w_talk, R.drawable.menu_w_interact, R.drawable.menu_w_use};
        for (int i = 0; i < banner.length; i++) {
            Bitmap b = BitmapFactory.decodeResource(context.getResources(), bannerIds[i], options);
            if (b != null) {
                names.put(banner[i], b);
            }
        }
    }

    private static int lighter(int c) {
        int r = (c >> 16 & 0xFF), g = (c >> 8 & 0xFF), b = (c & 0xFF);
        return 0xFF000000 | ((r + (255 - r) / 4) << 16) | ((g + (255 - g) / 4) << 8) | (b + (255 - b) / 4);
    }

    private float dp(float v) {
        return v * density;
    }

    /** The direction pad: a dark disc with a lit rim, a cross, and four arrows that glow while held. */
    void drawPad(Canvas c, float x, float y, float r, Set<String> down) {
        paint.setShader(null);
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(0x66000000);
        c.drawCircle(x, y + r * 0.05f, r * 1.02f, paint);                      // shadow
        matrix.setScale(r, r);
        matrix.postTranslate(x, y);
        padBase.setLocalMatrix(matrix);
        paint.setShader(padBase);
        c.drawCircle(x, y, r, paint);
        paint.setShader(null);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(Math.max(dp(1.5f), r * 0.04f));
        paint.setColor(0xCC8FA9CC);
        c.drawCircle(x, y, r - paint.getStrokeWidth() / 2f, paint);
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(0xFF1F3049);                                            // the cross
        float arm = r * 0.30f, len = r * 0.80f;
        box.set(x - len, y - arm, x + len, y + arm);
        c.drawRoundRect(box, arm * 0.7f, arm * 0.7f, paint);
        box.set(x - arm, y - len, x + arm, y + len);
        c.drawRoundRect(box, arm * 0.7f, arm * 0.7f, paint);
        paint.setColor(0xFF2B4163);
        c.drawCircle(x, y, arm * 0.55f, paint);                                // the middle
        arrow(c, "UP", down, x, y - r * 0.60f, 0, r);
        arrow(c, "DOWN", down, x, y + r * 0.60f, 180, r);
        arrow(c, "LEFT", down, x - r * 0.60f, y, 270, r);
        arrow(c, "RIGHT", down, x + r * 0.60f, y, 90, r);
    }

    private void arrow(Canvas c, String key, Set<String> down, float x, float y, float deg, float padR) {
        boolean on = down.contains(key);
        float s = padR * 0.20f;
        if (on) {
            paint.setColor(0x338FC2FF);
            c.drawCircle(x, y, s * 2.3f, paint);                               // glow
            paint.setColor(0x558FC2FF);
            c.drawCircle(x, y, s * 1.6f, paint);
        }
        paint.setColor(on ? 0xFFFFFFFF : 0xFFAFC2DD);
        c.save();
        c.rotate(deg, x, y);
        arrow.rewind();
        arrow.moveTo(x, y - s);
        arrow.lineTo(x + s * 1.05f, y + s * 0.8f);
        arrow.lineTo(x - s * 1.05f, y + s * 0.8f);
        arrow.close();
        c.drawPath(arrow, paint);
        c.restore();
    }

    /** A round button (Action, Magic, Status) in the area `r`; `accent` is BLUE, VIOLET or GOLD. */
    void drawBall(Canvas c, RectF r, String label, String word, int accent, boolean pressed) {
        float cx = r.centerX(), cy = r.centerY(), rad = r.width() / 2f * (pressed ? 0.96f : 1f);
        paint.setShader(null);
        paint.setStyle(Paint.Style.FILL);
        if (pressed) {
            paint.setColor(0x338FC2FF);
            c.drawCircle(cx, cy, rad * 1.22f, paint);                          // glow
            paint.setColor(0x558FC2FF);
            c.drawCircle(cx, cy, rad * 1.1f, paint);
        } else {
            paint.setColor(0x66000000);
            c.drawCircle(cx, cy + rad * 0.07f, rad * 1.02f, paint);            // shadow
        }
        Shader s = pressed ? held[accent] : idle[accent];
        matrix.setScale(rad, rad);
        matrix.postTranslate(cx, cy);
        s.setLocalMatrix(matrix);
        paint.setShader(s);
        c.drawCircle(cx, cy, rad, paint);
        paint.setShader(null);
        paint.setStyle(Paint.Style.STROKE);                                    // the rim, and a soft highlight just inside it
        paint.setStrokeWidth(Math.max(dp(1.5f), rad * 0.05f));
        paint.setColor(pressed ? RIM_HELD : RIM);
        c.drawCircle(cx, cy, rad - paint.getStrokeWidth() / 2f, paint);
        paint.setStrokeWidth(Math.max(dp(1f), rad * 0.025f));
        paint.setColor(0x33FFFFFF);
        c.drawCircle(cx, cy, rad - paint.getStrokeWidth() * 3f, paint);
        paint.setStyle(Paint.Style.FILL);
        if (word != null) {                                                    // what Action does right now, from the game's own banner
            Bitmap known = names.get(word.substring(0, 1).toUpperCase(java.util.Locale.US) + word.substring(1).toLowerCase(java.util.Locale.US));   // (Open, Attack, Grab...)
            if (known != null) {
                name(c, known, cx, cy, rad * 1.6f, rad * 0.8f);
            } else if (!menuFont.draw(c, word, cx, cy, rad * 1.6f, rad * 0.8f)) {
                words.setTextSize(rad * 0.5f);
                while (words.measureText(word) > rad * 1.6f && words.getTextSize() > dp(9)) {
                    words.setTextSize(words.getTextSize() - 1f);
                }
                c.drawText(word, cx, cy + words.getTextSize() * 0.35f, words);
            }
        } else if (label.equals("Action") && names.get("Jump") != null) {
            // nothing to act on: the key still jumps, so it says both, Action above and to the left, Jump below and to the right
            name(c, names.containsKey("Action/") ? "Action/" : label, cx - rad * 0.16f, cy - rad * 0.12f, rad * 1.5f, rad * 0.6f);
            name(c, names.get("Jump"), cx + rad * 0.2f, cy + rad * 0.28f, rad * 1.3f, rad * 0.5f);
        } else {
            name(c, label, cx, cy, rad * 1.6f, rad * 0.8f);
        }
    }

    /** A softkey or Back: a rounded bar in the area `r`. */
    void drawPill(Canvas c, RectF r, String label, String word, boolean pressed) {
        float rad = r.height() / 2.4f;
        paint.setShader(null);
        paint.setStyle(Paint.Style.FILL);
        if (pressed) {
            paint.setColor(0x338FC2FF);
            box.set(r.left - dp(4), r.top - dp(4), r.right + dp(4), r.bottom + dp(4));
            c.drawRoundRect(box, rad + dp(4), rad + dp(4), paint);
        } else {
            paint.setColor(0x66000000);
            box.set(r.left, r.top + dp(2), r.right, r.bottom + dp(2));
            c.drawRoundRect(box, rad, rad, paint);
        }
        Shader s = pressed ? pillHeld : pillIdle;
        matrix.setScale(1f, r.height());
        matrix.postTranslate(0f, r.top);
        s.setLocalMatrix(matrix);
        paint.setShader(s);
        c.drawRoundRect(r, rad, rad, paint);
        paint.setShader(null);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(dp(1.5f));
        paint.setColor(pressed ? RIM_HELD : 0xCC8FA9CC);
        box.set(r.left + dp(0.75f), r.top + dp(0.75f), r.right - dp(0.75f), r.bottom - dp(0.75f));
        c.drawRoundRect(box, rad, rad, paint);
        paint.setStyle(Paint.Style.FILL);
        if (word != null) {                                                    // the game's own word for what this key does now
            if (!menuFont.draw(c, word, r.centerX(), r.centerY(), r.width() * 0.8f, r.height() * 0.62f)) {
                words.setTextSize(r.height() * 0.46f);                         // (a word the menu font has no letters for)
                while (words.measureText(word) > r.width() * 0.84f && words.getTextSize() > dp(9)) {
                    words.setTextSize(words.getTextSize() - 1f);
                }
                c.drawText(word, r.centerX(), r.centerY() + words.getTextSize() * 0.35f, words);
            }
        } else if (label.startsWith("Soft")) {
            // a softkey with nothing to say stays blank
        } else {
            name(c, label, r.centerX(), r.centerY(), r.width() * 0.8f, r.height() * 0.62f);
        }
    }

    /** The control's name, in the menu font, as large as fits the control (a whole number when that is nearly exact, else smoothed). */
    private void name(Canvas c, String label, float cx, float cy, float maxW, float maxH) {
        name(c, names.get(label), cx, cy, maxW, maxH);
    }

    private void name(Canvas c, Bitmap b, float cx, float cy, float maxW, float maxH) {
        if (b == null) {
            return;
        }
        float f = Math.min(maxW / b.getWidth(), maxH / b.getHeight());
        float whole = (float) Math.floor(f);
        boolean crispFit = whole >= 1 && f - whole < 0.2f;            // (near a whole number: keep the hard pixel edges)
        float scale = crispFit ? whole : f;
        float w = b.getWidth() * scale, h = b.getHeight() * scale;
        Paint p = crispFit ? crisp : pic;
        box.set(cx - w / 2f, cy - h / 2f, cx + w / 2f, cy + h / 2f);
        c.drawBitmap(b, null, box, p);
    }
}
