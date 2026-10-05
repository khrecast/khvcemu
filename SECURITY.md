# Security

khvcemu runs code from the game files you point it at, inside an emulated ARM
CPU. It never executes that code on your real CPU, but treat game dumps from
sources you don't trust with the usual care.

**Save states are Python pickles.** Loading a `.khs` file runs whatever is
inside it. Only load save states you made yourself, never ones from someone
else. (khvcemu's own `states/` folder is safe.)

To report a vulnerability, email **khrecast@gmail.com**. Please don't open a
public issue for it. This is a small volunteer project, so expect a reply in
days rather than hours.
