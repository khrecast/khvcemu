package com.khrecast.recast;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RadialGradient;
import android.graphics.RectF;
import android.graphics.Shader;
import android.graphics.Typeface;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * "Flip phone mode": the game on the screen of a clamshell phone drawn round it, in the gray and silver plastic of a 2005
 * handset. Under the screen, in the lower half of the shell, sit the two softkeys, a navigation ring with a center button, a
 * green Call key and a red End key, and the twelve keys of a phone keypad. The keys press the phone keys the game was written
 * for: 2, 4, 6 and 8 move, 5 selects, the ring does the same, * casts magic, 0 is Status. Call sends the phone's Send key (the
 * game does not use it) and End is the phone's Clear key (Back). Portrait only; GameView draws the layout in landscape as usual.
 */
final class FlipPhone {
    private static final class Key {
        final String key, label, sub;
        final int kind;                         // 0 keypad, 1 softkey, 2 call, 3 end
        final RectF r = new RectF();
        Shader up, down;                        // the key's face, normal and held (built when the phone is laid out)

        Key(String key, String label, String sub, int kind) {
            this.key = key;
            this.label = label;
            this.sub = sub;
            this.kind = kind;
        }
    }

    private boolean graphite;                    // the dark gray body instead of silver
    private int outline() { return graphite ? 0xFF1F2226 : 0xFF6B7078; }
    private int edgeLight() { return graphite ? 0xFF7C828C : 0xFFF7F8FA; }
    private int ink() { return graphite ? 0xFFEEF0F3 : 0xFF2A2E34; }
    private int inkSub() { return graphite ? 0xFFB4BAC3 : 0xFF5B616A; }

    /** A silver colour as the graphite body shows it: the same light and shade, much darker. */
    private int tone(int c) {
        if (!graphite) {
            return c;
        }
        return (c & 0xFF000000) | (((c >> 16 & 0xFF) * 38 / 100) << 16) | (((c >> 8 & 0xFF) * 40 / 100) << 8) | ((c & 0xFF) * 44 / 100);
    }

    private int[] tones(int... colors) {
        int[] out = new int[colors.length];
        for (int i = 0; i < colors.length; i++) {
            out[i] = tone(colors[i]);
        }
        return out;
    }

    /** Silver or graphite; takes effect at once. */
    void setGraphite(boolean on) {
        if (on != graphite) {
            graphite = on;
            if (upper.width() > 0) {
                buildShaders();
            }
        }
    }

    private final float density;
    private final List<Key> keys = new ArrayList<>();
    private final RectF upper = new RectF(), lower = new RectF(), hinge = new RectF(), bezel = new RectF();
    private final RectF screen = new RectF(), slot = new RectF(), antenna = new RectF();
    private final Path arrowPath = new Path();
    private final RectF plate = new RectF(), logoDst = new RectF();
    private final Paint bitmapPaint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
    private final android.graphics.Bitmap vcast;
    private float navX, navY, navR;
    private Shader antennaShade, shellUpper, shellLower, hingeShade, ringShade, hubUp, hubDown;
    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint stroke = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint text = new Paint(Paint.ANTI_ALIAS_FLAG);

    FlipPhone(Context context) {
        density = context.getResources().getDisplayMetrics().density;
        vcast = android.graphics.BitmapFactory.decodeResource(context.getResources(), R.drawable.vcast_logo);
        stroke.setStyle(Paint.Style.STROKE);
        text.setTextAlign(Paint.Align.CENTER);
        text.setTypeface(Typeface.DEFAULT_BOLD);
        keys.add(new Key("SOFT1", "", "", 1));
        keys.add(new Key("SOFT2", "", "", 1));
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

    private static Shader vertical(RectF r, int... colors) {
        return new LinearGradient(0, r.top, 0, r.bottom, colors, null, Shader.TileMode.CLAMP);
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
        upper.set(shellL, top + free * 0.005f + dp(14), shellR, 0);          // room above for the antenna stub
        picture.set(cx - sw / 2f, upper.top + dp(28), cx + sw / 2f, upper.top + dp(28) + sh);
        screen.set(picture);
        upper.bottom = picture.bottom + dp(34);                              // the strip under the screen holds the name
        bezel.set(picture.left - dp(8), picture.top - dp(8), picture.right + dp(8), picture.bottom + dp(8));
        slot.set(cx - dp(32), upper.top + dp(10), cx + dp(32), upper.top + dp(17));
        antenna.set(shellR - dp(74), upper.top - dp(15), shellR - dp(62), upper.top + dp(12));
        hinge.set(shellL + shellW * 0.04f, upper.bottom + dp(2), shellR - shellW * 0.04f, upper.bottom + dp(10));
        lower.set(shellL, hinge.bottom - dp(2), shellR, bottom - free * 0.02f);

        float lowerH = lower.height();
        float pad = lowerH * 0.035f;
        float rowTop = lower.top + pad, rowH = lowerH * 0.26f;
        navR = Math.max(1f, Math.min(rowH * 0.5f, shellW * 0.16f));      // never zero: the gradients need a radius
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
        buildShaders();
    }

    /** The gradients that give the plastic its look: they depend on where things are, so they are made once per layout. */
    private void buildShaders() {
        antennaShade = new LinearGradient(antenna.left, 0, antenna.right, 0,
                tones(0xFF5E636B, 0xFFD9DCE0, 0xFF6F747C), null, Shader.TileMode.CLAMP);
        shellUpper = vertical(upper, tones(0xFFEEF0F3, 0xFFC9CDD3, 0xFFA9AEB6));
        shellLower = vertical(lower, tones(0xFFC4C8CE, 0xFFB3B8BF, 0xFF989DA5));
        hingeShade = vertical(hinge, tones(0xFFE9EBEE, 0xFF8F949C, 0xFF5E636B));
        ringShade = new RadialGradient(navX - navR * 0.25f, navY - navR * 0.3f, navR * 1.4f,
                tones(0xFFF4F5F7, 0xFFC5C9CF, 0xFF8D929A), null, Shader.TileMode.CLAMP);
        float hr = navR * 0.34f;
        hubUp = new RadialGradient(navX - hr * 0.3f, navY - hr * 0.35f, hr * 1.5f,
                tones(0xFFD7DADF, 0xFF9CA1A9, 0xFF70757D), null, Shader.TileMode.CLAMP);
        hubDown = new RadialGradient(navX, navY, hr * 1.3f,
                new int[]{0xFF8BB6F2, 0xFF5B8FDA, 0xFF3D6DB5}, null, Shader.TileMode.CLAMP);
        for (Key k : keys) {
            switch (k.kind) {
                case 2:
                    k.up = vertical(k.r, 0xFF7FE59B, 0xFF2FAE58, 0xFF1F8140);
                    k.down = vertical(k.r, 0xFF4FB86F, 0xFF1F8140, 0xFF176A33);
                    break;
                case 3:
                    k.up = vertical(k.r, 0xFFFF8E80, 0xFFD2402F, 0xFF9C2A1E);
                    k.down = vertical(k.r, 0xFFD2685B, 0xFF9C2A1E, 0xFF7E2017);
                    break;
                case 1:
                    k.up = vertical(k.r, tones(0xFFDDE0E4, 0xFFAEB3BA, 0xFF8D929A));
                    k.down = vertical(k.r, 0xFFA8C6F0, 0xFF7FA6DE, 0xFF5E86C2);
                    break;
                default:
                    k.up = vertical(k.r, tones(0xFFF9FAFB, 0xFFDCDFE3, 0xFFB6BBC2));
                    k.down = vertical(k.r, 0xFFBBD2F2, 0xFF98B8E6, 0xFF7A9ACD);
            }
        }
    }

    /** The shell: two silver halves, the hinge barrel, the speaker slot and the dark frame round the screen (drawn before the picture). */
    void drawBody(Canvas c) {
        fill.setStyle(Paint.Style.FILL);
        float cr = dp(34);
        fill.setColor(Color.BLACK);                                             // the stub antenna, behind the shell
        fill.setShader(antennaShade);
        c.drawRoundRect(antenna, dp(6), dp(6), fill);
        fill.setShader(null);
        stroke.setStrokeWidth(dp(1.2f));
        stroke.setColor(outline());
        c.drawRoundRect(antenna, dp(6), dp(6), stroke);
        fill.setShader(shellUpper);
        c.drawRoundRect(upper, cr, cr, fill);
        fill.setShader(shellLower);
        c.drawRoundRect(lower, cr, cr, fill);
        fill.setShader(null);
        for (int h = 0; h < 2; h++) {
            RectF half = h == 0 ? upper : lower;
            stroke.setStrokeWidth(dp(2));
            stroke.setColor(outline());
            c.drawRoundRect(half, cr, cr, stroke);
            stroke.setStrokeWidth(dp(1.2f));                                    // the lit edge inside the outline
            stroke.setColor(edgeLight());
            c.drawRoundRect(half.left + dp(3), half.top + dp(3), half.right - dp(3), half.bottom - dp(3), cr - dp(3), cr - dp(3), stroke);
        }
        fill.setShader(hingeShade);
        c.drawRoundRect(hinge, dp(5), dp(5), fill);
        fill.setShader(null);
        stroke.setStrokeWidth(dp(1.2f));
        stroke.setColor(outline());
        c.drawRoundRect(hinge, dp(5), dp(5), stroke);
        // the speaker: a dark slot over a row of small holes
        fill.setColor(0xFF4A4F57);
        c.drawRoundRect(slot, dp(4), dp(4), fill);
        fill.setColor(0xFF7C828B);
        for (int i = 0; i < 7; i++) {
            c.drawCircle(slot.left + dp(8) + i * (slot.width() - dp(16)) / 6f, slot.centerY(), dp(1.1f), fill);
        }
        // a small camera lens left of the speaker
        float lx = slot.left - dp(18), ly = slot.centerY();
        fill.setColor(0xFF2C3036);
        c.drawCircle(lx, ly, dp(5.5f), fill);
        fill.setColor(0xFF0B0C10);
        c.drawCircle(lx, ly, dp(3.6f), fill);
        fill.setColor(0xAA6E7DE0);
        c.drawCircle(lx - dp(1), ly - dp(1), dp(1.2f), fill);
        // a small status light by the speaker, and the name in a printed strip under the screen
        fill.setColor(0xFF3F8F5A);
        c.drawCircle(slot.right + dp(14), slot.centerY(), dp(2.4f), fill);
        fill.setColor(0x66FFFFFF);
        c.drawCircle(slot.right + dp(13.2f), slot.centerY() - dp(0.8f), dp(0.9f), fill);
        text.setTextSize(dp(12));
        text.setLetterSpacing(0.25f);
        text.setColor(graphite ? 0xFF14161A : 0xFFF4F5F7);                      // a lit edge under the print: a pressed-in logo
        c.drawText("Re:Cast", (upper.left + upper.right) / 2f + dp(1.5f), upper.bottom - dp(10) + dp(0.8f), text);
        text.setColor(inkSub());
        c.drawText("Re:Cast", (upper.left + upper.right) / 2f + dp(1.5f), upper.bottom - dp(10), text);   // the spacing leaves a gap after the last letter
        if (vcast != null) {                                                    // the V CAST logo on a small light plate, left of the name
            float ph = dp(17), pw = (ph - dp(4)) * vcast.getWidth() / vcast.getHeight() + dp(8);   // the logo keeps its shape inside the plate
            plate.set(upper.left + dp(34), upper.bottom - dp(23.5f), upper.left + dp(34) + pw, upper.bottom - dp(23.5f) + ph);
            fill.setColor(0xFFF1F2F4);
            c.drawRoundRect(plate, dp(4), dp(4), fill);
            stroke.setStrokeWidth(dp(1));
            stroke.setColor(outline());
            c.drawRoundRect(plate, dp(4), dp(4), stroke);
            logoDst.set(plate.left + dp(4), plate.top + dp(2), plate.right - dp(4), plate.bottom - dp(2));
            c.drawBitmap(vcast, null, logoDst, bitmapPaint);
        }
        text.setLetterSpacing(0f);
        // the dark frame round the screen, with a thin rim
        fill.setColor(0xFF1B1E23);
        c.drawRoundRect(bezel, dp(10), dp(10), fill);
        stroke.setColor(0xFF5B616A);
        stroke.setStrokeWidth(dp(1.5f));
        c.drawRoundRect(bezel, dp(10), dp(10), stroke);
        fill.setColor(Color.BLACK);
        c.drawRect(screen.left - dp(2), screen.top - dp(2), screen.right + dp(2), screen.bottom + dp(2), fill);
    }

    /** The keys, with the ones that are held lit (drawn after the picture). */
    void drawKeys(Canvas c, Set<String> down) {
        for (Key k : keys) {
            boolean on = down.contains(k.key);
            fill.setStyle(Paint.Style.FILL);
            float radius = Math.min(k.r.width(), k.r.height()) / (k.kind == 0 ? 3.2f : 2f);
            if (!on) {                                                          // a soft shadow under a raised key
                fill.setColor(0x44000000);
                c.drawRoundRect(k.r.left, k.r.top + dp(2), k.r.right, k.r.bottom + dp(2), radius, radius, fill);
            }
            fill.setColor(Color.BLACK);                                         // opaque: a shader is faded by the paint's alpha
            fill.setShader(on ? k.down : k.up);
            c.drawRoundRect(k.r, radius, radius, fill);
            fill.setShader(null);
            stroke.setStrokeWidth(dp(1.2f));
            stroke.setColor(outline());
            c.drawRoundRect(k.r, radius, radius, stroke);
            if (k.kind <= 1) {                                                  // a bright line just inside the edge of a plastic key
                stroke.setStrokeWidth(dp(1));
                stroke.setColor(0xAAFFFFFF);
                c.drawRoundRect(k.r.left + dp(2), k.r.top + dp(2), k.r.right - dp(2), k.r.bottom - dp(2),
                        radius - dp(2), radius - dp(2), stroke);
            }
            text.setColor(k.kind >= 2 ? Color.WHITE : ink());
            if (k.label.isEmpty()) {
                continue;                                                       // the softkeys carry no print
            } else if (k.kind == 0) {
                boolean hasSub = !k.sub.isEmpty();
                text.setTextSize(k.r.height() * (hasSub ? 0.46f : 0.58f));
                c.drawText(k.label, k.r.centerX(), k.r.centerY() + (hasSub ? -k.r.height() * 0.02f : k.r.height() * 0.2f), text);
                if (hasSub) {
                    text.setTextSize(k.r.height() * 0.2f);
                    text.setColor(inkSub());
                    c.drawText(k.sub, k.r.centerX(), k.r.bottom - k.r.height() * 0.14f, text);
                }
            } else {
                text.setTextSize(Math.min(k.r.height() * 0.5f, k.r.width() * 0.2f));
                c.drawText(k.label, k.r.centerX(), k.r.centerY() + text.getTextSize() * 0.35f, text);
            }
        }
        // the navigation ring: a metal disc with four arrows printed on it round a center button
        fill.setStyle(Paint.Style.FILL);
        fill.setColor(0x44000000);
        c.drawCircle(navX, navY + dp(2), navR, fill);
        fill.setColor(Color.BLACK);
        fill.setShader(ringShade);
        c.drawCircle(navX, navY, navR, fill);
        fill.setShader(null);
        stroke.setColor(outline());
        stroke.setStrokeWidth(dp(1.6f));
        c.drawCircle(navX, navY, navR, stroke);
        arrow(c, "UP", down, navX, navY - navR * 0.68f, 0);
        arrow(c, "DOWN", down, navX, navY + navR * 0.68f, 180);
        arrow(c, "LEFT", down, navX - navR * 0.68f, navY, 270);
        arrow(c, "RIGHT", down, navX + navR * 0.68f, navY, 90);
        fill.setShader(down.contains("SELECT") ? hubDown : hubUp);
        c.drawCircle(navX, navY, navR * 0.34f, fill);
        fill.setShader(null);
        stroke.setStrokeWidth(dp(1.2f));
        c.drawCircle(navX, navY, navR * 0.34f, stroke);
    }

    private void arrow(Canvas c, String key, Set<String> down, float x, float y, float deg) {
        float s = navR * 0.17f;
        fill.setColor(down.contains(key) ? (graphite ? 0xFF8DB8F5 : 0xFF2F66C4) : (graphite ? 0xFFD5D9DF : 0xFF3A3F47));
        c.save();
        c.rotate(deg, x, y);
        arrowPath.rewind();
        arrowPath.moveTo(x, y - s);
        arrowPath.lineTo(x + s, y + s * 0.8f);
        arrowPath.lineTo(x - s, y + s * 0.8f);
        arrowPath.close();
        c.drawPath(arrowPath, fill);
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
