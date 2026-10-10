package com.khrecast.recast;

import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;

/**
 * Game controllers (and keyboards with a D-pad): which phone key each button stands for. The D-pad and the left stick move,
 * A is Action, B is Back, X is Magic, Y is Status, the shoulder buttons are the two softkeys, Start opens the menu.
 * Pure mapping: GameView and MainActivity do the pressing.
 */
final class GamePad {
    /** Where an event came from: the bits of GameView.padKey's `source` argument. */
    static final int FROM_BUTTONS = 1, FROM_STICK = 2;

    private GamePad() {
    }

    /** The phone key a controller button stands for (the names of khvcemu.keys.AVK), or null when it is not one of ours. */
    static String keyFor(int keyCode) {
        switch (keyCode) {
            case KeyEvent.KEYCODE_DPAD_UP:
                return "UP";
            case KeyEvent.KEYCODE_DPAD_DOWN:
                return "DOWN";
            case KeyEvent.KEYCODE_DPAD_LEFT:
                return "LEFT";
            case KeyEvent.KEYCODE_DPAD_RIGHT:
                return "RIGHT";
            case KeyEvent.KEYCODE_BUTTON_A:
            case KeyEvent.KEYCODE_DPAD_CENTER:
                return "SELECT";
            case KeyEvent.KEYCODE_BUTTON_B:
                return "CLR";
            case KeyEvent.KEYCODE_BUTTON_X:
                return "STAR";
            case KeyEvent.KEYCODE_BUTTON_Y:
                return "0";
            case KeyEvent.KEYCODE_BUTTON_L1:
            case KeyEvent.KEYCODE_BUTTON_L2:
                return "SOFT1";
            case KeyEvent.KEYCODE_BUTTON_R1:
            case KeyEvent.KEYCODE_BUTTON_R2:
                return "SOFT2";
            default:
                return null;
        }
    }

    /** True for the controller's Start button (it opens the game's menu). */
    static boolean isMenu(int keyCode) {
        return keyCode == KeyEvent.KEYCODE_BUTTON_START;
    }

    /** True when the event comes from a controller or a D-pad rather than the phone's own keys. */
    static boolean fromPad(KeyEvent e) {
        int src = e.getSource();
        return (src & InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD
                || (src & InputDevice.SOURCE_DPAD) == InputDevice.SOURCE_DPAD
                || (src & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK;
    }

    /** The four directions a stick (or a hat) position stands for: {left, right, up, down}, with a dead zone in the middle. */
    static boolean[] directions(float x, float y) {
        final float zone = 0.5f;
        return new boolean[]{x < -zone, x > zone, y < -zone, y > zone};
    }

    /** The stick or hat position of a motion event: the larger of the left stick and the hat on each axis. */
    static float[] position(MotionEvent e) {
        float x = e.getAxisValue(MotionEvent.AXIS_X), y = e.getAxisValue(MotionEvent.AXIS_Y);
        float hx = e.getAxisValue(MotionEvent.AXIS_HAT_X), hy = e.getAxisValue(MotionEvent.AXIS_HAT_Y);
        return new float[]{Math.abs(hx) > Math.abs(x) ? hx : x, Math.abs(hy) > Math.abs(y) ? hy : y};
    }
}
