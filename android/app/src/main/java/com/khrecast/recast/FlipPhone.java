package com.khrecast.recast;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.Typeface;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * "Flip phone mode": the game on the screen of a clamshell phone drawn around it. Under the screen, in the lower half of
 * the shell, sit the two softkeys, a navigation ring with a center button, a green Call key and a red End key, and the
 * twelve keys of a phone keypad. The keys press the phone keys the game was written for: 2, 4, 6 and 8 move, 5 selects, the
 * ring does the same, * casts magic, 0 is Status. Call sends the phone's Send key (the game does not use it) and End is the phone's Clear key (Back).
 * Portrait only; GameView draws the layout in landscape as usual.
 */
final class FlipPhone {
    private static final class Key {
        final String key, label, sub;
        final int kind;                         // 0 keypad, 1 softkey, 2 call, 3 end
        final RectF r = new RectF();

        Key(String key, String label, String sub, int kind) {
            this.key = key;
            this.label = label;
            this.sub = sub;
            this.kind = kind;
        }
    }

    private final float density;
    private final List<Key> keys = new ArrayList<>();
    private final RectF upper = new RectF(), lower = new RectF(), hinge = new RectF(), bezel = new RectF();
    private final RectF screen = new RectF();
    private float navX, navY, navR;
    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint stroke = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint text = new Paint(Paint.ANTI_ALIAS_FLAG);

    FlipPhone(Context context) {
        density = context.getResources().getDisplayMetrics().density;
        stroke.setStyle(Paint.Style.STROKE);
        text.setTextAlign(Paint.Align.CENTER);
        text.setTypeface(Typeface.DEFAULT_BOLD);
        keys.add(new Key("SOFT1", "Soft 1", "", 1));
        keys.add(new Key("SOFT2", "Soft 2", "", 1));
        keys.add(new Key("SEND", "Call", "", 2));
        keys.add(new Key("CLR", "End", "", 3));
        // The game is steered with the direction keys and Select (the desktop's arrows and Enter send those; its digit keys send
        // digits), so 2, 4, 6, 8 and 5 send the directions and Select (the digit stays on the face of the key).
        String[][] pad = {{"1", "1", ""}, {"UP", "2", "ABC"}, {"3", "3", "DEF"}, {"LEFT", "4", "GHI"}, {"SELECT", "5", "JKL"},
                {"RIGHT", "6", "MNO"}, {"7", "7", "PQRS"}, {"DOWN", "8", "TUV"}, {"9", "9", "WXYZ"},
                {"STAR", "*", "Magic"}, {"0", "0", "Status"}, {"POUND", "#", ""}};
        for (String[] p : pad) {
            keys.add(new Key(p[0], p[1], p[2], 0));
        }
    }

    private float dp(float v) {
        return v * density;
    }

    /** Lays the phone out inside the free area (pixels) and sets `screen` to where the game's picture goes. */
    void layout(float left, float top, float right, float bottom, RectF picture) {
        float width = right - left, free = bottom - top;
        float shellL = left + width * 0.03f, shellR = right - width * 0.03f, shellW = shellR - shellL;
        float sh = free * 0.36f, sw = sh * GameView.W / GameView.H;
        if (sw > shellW * 0.72f) {
            sw = shellW * 0.72f;
            sh = sw * GameView.H / GameView.W;
        }
        float cx = (left + right) / 2f;
        upper.set(shellL, top + free * 0.005f, shellR, 0);
        picture.set(cx - sw / 2f, upper.top + dp(28), cx + sw / 2f, upper.top + dp(28) + sh);
        screen.set(picture);
        upper.bottom = picture.bottom + dp(24);
        bezel.set(picture.left - dp(8), picture.top - dp(8), picture.right + dp(8), picture.bottom + dp(8));
        hinge.set(shellL + shellW * 0.04f, upper.bottom + dp(2), shellR - shellW * 0.04f, upper.bottom + dp(10));
        lower.set(shellL, hinge.bottom - dp(2), shellR, bottom - free * 0.02f);

        float lowerH = lower.height();
        float pad = lowerH * 0.035f;
        float rowTop = lower.top + pad, rowH = lowerH * 0.26f;
        navR = Math.min(rowH * 0.5f, shellW * 0.16f);
        navX = cx;
        navY = rowTop + rowH * 0.5f;
        float pillW = shellW * 0.28f, pillH = rowH * 0.30f;
        float lx = shellL + shellW * 0.05f, rx = shellR - shellW * 0.05f - pillW;
        keys.get(0).r.set(lx, rowTop + rowH * 0.08f, lx + pillW, rowTop + rowH * 0.08f + pillH);        // Soft 1
        keys.get(1).r.set(rx, rowTop + rowH * 0.08f, rx + pillW, rowTop + rowH * 0.08f + pillH);        // Soft 2
        keys.get(2).r.set(lx, rowTop + rowH * 0.60f, lx + pillW, rowTop + rowH * 0.60f + pillH);        // Call
        keys.get(3).r.set(rx, rowTop + rowH * 0.60f, rx + pillW, rowTop + rowH * 0.60f + pillH);        // End

        float padTop = rowTop + rowH + pad * 0.6f, padBottom = lower.bottom - pad;
        float gapY = lowerH * 0.015f, gapX = shellW * 0.03f;
        float keyH = (padBottom - padTop - 3 * gapY) / 4f;
        float keyW = Math.min((shellW * 0.92f - 2 * gapX) / 3f, keyH * 2.1f);
        float x0 = cx - (3 * keyW + 2 * gapX) / 2f;
        for (int i = 0; i < 12; i++) {
            int row = i / 3, col = i % 3;
            float x = x0 + col * (keyW + gapX), y = padTop + row * (keyH + gapY);
            keys.get(4 + i).r.set(x, y, x + keyW, y + keyH);
        }
    }

    /** The shell: two halves, the hinge, the speaker slot and the black frame round the screen (drawn before the picture). */
    void drawBody(Canvas c) {
        fill.setStyle(Paint.Style.FILL);
        stroke.setStrokeWidth(dp(2));
        for (RectF half : new RectF[]{upper, lower}) {
            fill.setColor(0xFF1B2330);
            c.drawRoundRect(half, dp(34), dp(34), fill);
            stroke.setColor(0xFF8EA4BF);
            c.drawRoundRect(half, dp(34), dp(34), stroke);
        }
        fill.setColor(0xFF0D131B);
        c.drawRoundRect(hinge, dp(5), dp(5), fill);
        stroke.setColor(0xFF4A5B73);
        c.drawRoundRect(hinge, dp(5), dp(5), stroke);
        float cx = (upper.left + upper.right) / 2f;
        fill.setColor(0xFF0B0F14);
        c.drawRoundRect(new RectF(cx - dp(32), upper.top + dp(10), cx + dp(32), upper.top + dp(17)), dp(4), dp(4), fill);
        fill.setColor(Color.BLACK);
        c.drawRoundRect(bezel, dp(10), dp(10), fill);
        stroke.setColor(0xFF4A5B73);
        stroke.setStrokeWidth(dp(1.5f));
        c.drawRoundRect(bezel, dp(10), dp(10), stroke);
    }

    /** The keys, with the ones that are held lit (drawn after the picture). */
    void drawKeys(Canvas c, Set<String> down) {
        for (Key k : keys) {
            boolean on = down.contains(k.key);
            int color = k.kind == 2 ? (on ? 0xFF58D87C : 0xFF2E9E4F)
                    : k.kind == 3 ? (on ? 0xFFFF6B5B : 0xFFC0392B)
                    : (on ? 0xFF5B9DFF : k.kind == 1 ? 0xFF2C3A50 : 0xFF3A465A);
            fill.setStyle(Paint.Style.FILL);
            fill.setColor(color);
            float radius = Math.min(k.r.width(), k.r.height()) / (k.kind == 0 ? 3.2f : 2f);
            c.drawRoundRect(k.r, radius, radius, fill);
            stroke.setStrokeWidth(dp(1.5f));
            stroke.setColor(0xFF8EA4BF);
            c.drawRoundRect(k.r, radius, radius, stroke);
            text.setColor(Color.WHITE);
            if (k.kind == 0) {
                boolean hasSub = !k.sub.isEmpty();
                text.setTextSize(k.r.height() * (hasSub ? 0.46f : 0.58f));
                c.drawText(k.label, k.r.centerX(), k.r.centerY() + (hasSub ? -k.r.height() * 0.02f : k.r.height() * 0.2f), text);
                if (hasSub) {
                    text.setTextSize(k.r.height() * 0.2f);
                    text.setColor(0xFFB8C7DB);
                    c.drawText(k.sub, k.r.centerX(), k.r.bottom - k.r.height() * 0.14f, text);
                }
            } else {
                text.setTextSize(Math.min(k.r.height() * 0.5f, k.r.width() * 0.2f));
                c.drawText(k.label, k.r.centerX(), k.r.centerY() + text.getTextSize() * 0.35f, text);
            }
        }
        // the navigation ring: four arrows round a center button
        fill.setStyle(Paint.Style.FILL);
        fill.setColor(0xFF2A3342);
        c.drawCircle(navX, navY, navR, fill);
        stroke.setColor(0xFF8EA4BF);
        stroke.setStrokeWidth(dp(2));
        c.drawCircle(navX, navY, navR, stroke);
        arrow(c, "UP", down, navX, navY - navR * 0.68f, 0);
        arrow(c, "DOWN", down, navX, navY + navR * 0.68f, 180);
        arrow(c, "LEFT", down, navX - navR * 0.68f, navY, 270);
        arrow(c, "RIGHT", down, navX + navR * 0.68f, navY, 90);
        fill.setColor(down.contains("SELECT") ? 0xFF5B9DFF : 0xFF3F4D63);
        c.drawCircle(navX, navY, navR * 0.34f, fill);
        stroke.setStrokeWidth(dp(1.5f));
        c.drawCircle(navX, navY, navR * 0.34f, stroke);
    }

    private void arrow(Canvas c, String key, Set<String> down, float x, float y, float deg) {
        float s = navR * 0.17f;
        fill.setColor(down.contains(key) ? 0xFF5B9DFF : 0xFFB8C7DB);
        c.save();
        c.rotate(deg, x, y);
        Path p = new Path();
        p.moveTo(x, y - s);
        p.lineTo(x + s, y + s * 0.8f);
        p.lineTo(x - s, y + s * 0.8f);
        p.close();
        c.drawPath(p, fill);
        c.restore();
    }

    /** The phone keys under a finger: a keypad key or button, or the ring (center = select, else the nearest direction). */
    void keysAt(float x, float y, Set<String> out) {
        for (Key k : keys) {
            if (k.r.contains(x, y)) {
                out.add(k.key);
            }
        }
        float dx = x - navX, dy = y - navY, dist = (float) Math.hypot(dx, dy);
        if (dist <= navR * 1.08f) {
            if (dist < navR * 0.36f) {
                out.add("SELECT");
            } else if (Math.abs(dx) > Math.abs(dy)) {
                out.add(dx < 0 ? "LEFT" : "RIGHT");
            } else {
                out.add(dy < 0 ? "UP" : "DOWN");
            }
        }
    }
}
