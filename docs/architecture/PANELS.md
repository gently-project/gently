# Panels

A **panel** is a standard, reusable control surface that can be mounted in more
than one place and reads its state from one shared source. Panels are how
Gently's UI is meant to be assembled from here on.

This is a policy, not a description: most of the UI does not follow it yet.

## Why

The tabbed UI grew a control at a time, each written where it was needed. So
the same fact is rendered by unrelated code in several places, and the copies
disagree:

- The SPIM head has an LED toggle. Manual mode has a different laser panel.
  Neither knows what the other has done.
- `LASER: ON` in manual mode is set from an HTTP 200 with no hardware read-back
  (#106), so it says ON while the beam is disabled and nothing emits.
- Embryo and image counts disagree across header, footer, panel and agent
  (#129), because four surfaces each count separately.

The cost is not duplicated code. It is that an operator cannot trust the
instrument, and on a microscope with lasers and an objective that can hit a
coverslip, a confident wrong readout is worse than a blank one.

## The rules

**1. One panel per subject, mounted many times.**
A panel owns a subject — light, stage, camera, run state. Every surface that
needs the subject mounts the same panel rather than rendering its own version.

**2. State comes from `SharedState`, never from the caller.**
`status-store.js` is the single store; panels subscribe to a key and re-render.
Two mounted copies cannot disagree because there is only one value. A panel
never takes its reading as a constructor argument.

**3. Read back; never render a command as a fact.**
A value that was sent is not a value that is true. Panels render what the
device reported. A value that has not been read is `—`, not a plausible
default. This is the rule #106 was written by.

**4. Limits come from the server.**
Bounds, options and enumerations are fetched, not hardcoded in JS. Laser power
limits live in `DiSPIMLightSource.POWER_LIMITS_PCT` (488 is `2.0–6.0`, not
`0–100`); a hardcoded slider would offer settings the hardware rejects.

**5. Derived hazards are computed, not commanded.**
"Emitting" is *armed AND routed AND power > 0* — computed from read-back state.
It is never a flag someone remembered to set, because that is the flag someone
will forget to clear.

**6. Presence-driven, not click-driven.**
A panel that reports a transient condition appears when the condition holds and
retires when it stops. No open/close affordance for something the operator did
not ask to see. Someone watching the scope should be able to read the screen
without operating it. See `PREVIEW_IDLE_MS` in `operate.js` for the first
instance.

**7. A panel is a module, not a template fragment.**
Markup, styles and behaviour ship together and mount into a host element, so
adding it to a new surface is one call rather than a copy-paste of markup.

**8. Whoever writes, announces — and a form is derived, not remembered.**
The operator and the agent change the same facts, and each has to see what
the other did. So every change to shared state ends in the broadcast that
puts it on the other party's screen, whether the operator made it (a route),
the agent (a tool) or a rule (the orchestrator). For an embryo's acquisition
parameters that is one door, `ExperimentState.set_params`, which writes,
records who and why, and fires `EMBRYOS_UPDATE`;
`tests/test_every_embryo_write_is_announced.py` fails on any writer that
does not. The GUI's writes always announced themselves, because the GUI
needed the redraw; the agent's did not, because the agent did not — which is
how the Acquisition pane came to show 50 slices over an embryo the agent had
set to 30. The other half is rule 2 applied to a form: the pane's Slices
field is read back from the embryos on every broadcast, says "varies 30–50"
when they disagree, and names who set what when it is not what the field
says. A value the operator has typed and not yet started is the one thing
the broadcast does not overwrite: it is a draft, applied at Start, and a
reload returns the field to what the embryos hold. While a run is going, a
draft that differs is the one case where "at Start" is no answer, and only
then does an Apply button appear beside the line — writing through the same
door as the agent's tool, in effect at the next acquisition. On a vanilla
form there is no button.

## Design language

A panel has to be recognisable as one. An operator scanning the screen for a
control should not have to work out where one grouping ends and the next
begins, and a panel that dissolves into the background is a panel they will not
find under pressure.

### Anatomy

**A box with its name on its top edge.** In the workspace a panel sits in
`.op-panel`: 1px border, 4px radius, panel background, and its name set into
the top border the way a group box carries its caption. The name costs no row
of its own, and a panel reads as one thing from across the room. A shared
panel's own head (`.lp-head`: its title, and what it has to say beside it,
such as how old its reading is) becomes that name when the panel is mounted in
a box. Calibration and Acquisition still use the older card, `.op-block`,
whose heading is a row inside it.

**A heading.** Small, uppercase, letter-spaced, naming the subject. `.lp-title`
shares the `.op-block-head` rule rather than defining its own.

**Rows.** `label — control — value`, 22 px tall. Labels are fixed-width (46 px
in a box) and muted so the values line up down the panel. Values are monospace
and tabular, because they are read by comparison between glances.

**A value that can be set can be typed.** A slider finds a value by looking
at the picture; a number is how a value is written in a notebook and put back
the next day. Every adjustable value is both, bound as one control by
`panels/numrow.js`, with the same rules wherever it appears: the limits are
the server's (rule 4); a typed value is a draft until Enter or leaving the
box, and nothing is sent while typing; a value outside the limits is pulled
inside and the box says so; a value read back never lands under a drag or a
half-typed number (rule 3 still holds: what is shown at rest is what was
read).

**Chosen is not the same as on.** A segmented button is filled in the accent
when the device reports that thing on (a routed line, an open LED, an armed
beam), and in a neutral tone when what is chosen is rest (Closed, Off). A
press is a request; what is filled after it is what was read back.

**An em dash for unknown.** Never a plausible default (rule 3). `—` is a
statement.

**Red only for hazards**, and only when derived from read-back state (rule 5).

### Composition

A panel mounted **standalone** draws its own card and heading. A panel composed
**into an existing card** draws neither — `CameraPanel.mount(host, {titled:
false})` puts exposure inside the block that already names the camera. Two
borders around one subject, or two headings for one device, is the same
duplication as two controls for one LED, just quieter.

### Placement

**Every panel has one place, and keeps it.** This is the rule the first
layouts did not have, and its absence was most of what was wrong with them:
panels flowed into as many columns as fit, each camera's pane assembled its
own set, and cards folded, so where a control was depended on the window, the
camera and what had been folded. The Operate workspace (Scope) is three zones
in one row, and a panel's zone and its position in it do not change
(`docs/workspace/README.md`):

- **the dish**, left: what is on the coverslip — finding, the embryos, the
  fields, the overview frames;
- **what the rig sees**, middle: one frame, the strip that chooses its
  camera, and the camera's own things (its live view, its exposure, its
  display range);
- **the instrument**, right: Light and Sheet, Head and Stage, in two columns
  whose order is fixed. A narrower window stacks the second column under the
  first; it does not reorder them.

Only what belongs to one camera changes with the camera. The instrument is
the same with either, and no control is switched off by which camera is on
screen.

**Panels go where the thing they act on is.** Exposure is in the strip with
its camera. The display range is under the frame it applies to. Finding sits
in the dish, beside the list it fills.

Group by subject, not by widget type. Everything about illumination is in one
panel; exposure is with its camera and not with the light.

**A panel does not fold.** A panel that can be folded away is somewhere else
the next time, and the workspace is sized so that at the desktop app's window
(1440×920) everything is on screen at once. What may fold is a box of
settings made once a night whose closed state still says what is set (the
overview frames); the rig keeps that choice (`/api/ui/rail-cards`).

### Overflow

At the desktop app's window nothing in the workspace scrolls. In a shorter
window the instrument column scrolls, and shows that it does; in a window too
narrow for three zones the workspace becomes one column (the frame, the
instrument, the dish) and the page scrolls. Nothing is clipped at any size:
a control that has left the window does not exist, and that includes HALT.

**Nothing may claim vertical space to say nothing.** The temperature strip
rendered "No temperature data yet" permanently and cost ~60px, which pushed
real panels below the fold; it is hidden until a sample arrives. A widget that
occupies the screen while reporting that nothing has happened is taking space
from one that has something to say — this is rule 6 read as a layout
constraint.

## Status

| Panel | Subject | Mounted in | Notes |
|---|---|---|---|
| Light | the LED and its brightness, the laser presets, every line's power, the beam per side, and one status line | Scope (the instrument) | read-back; derives what is emitting, and says it on a line that is always there; one mount, beside either camera (it had a second, LED-only, on the old Bottom cam pane) |
| ImageView | zoom, pan, contrast, brightness | each camera's frame | view state, stays local |
| Camera | exposure | the camera strip above the frame, one per camera | untitled: the strip already names the camera |
| StagePad | the XY stage: where it is, and a jog by a chosen step | Scope (the Stage panel) | the server keeps the target inside the XY envelope; nothing interlocks it against the head |
| Marking | pending marks vs registered roster, detect/register/clear | the dish rail | renders state, calls operate.js for the verbs |
| Roster | the embryo list | the dish rail + Acquisition | actions declared per mount; `showFit` reads the gate's field |
| Fields | the bottom camera's fields of view for the brightfield overview | the dish rail + Acquisition | the other list of places a run goes back to; kept in the session (`overview_fields.yaml`), read by the plan as "taken from the fields" |
| BrightfieldRefs | the overview frames' dark and flat | the dish rail (Overview frames box) | reads the plan's light, LED and exposure fields, which sit above it in the same box; the flat needs the stage driven clear, and the pad is on the same screen |
| CalProgress | the frames a calibration is judging | Calibration | reads the existing image broadcast; owns no run |

The Roster panel is the clearest case of rule 1 paying off: it replaced
`renderEmbryoRail` and `renderRoster`, which were ~80% the same code with
**arbitrarily** different action sets — delete on one pane, Centre and role on
the other, for no reason either pane justified. Actions are declared per mount
now, so the difference is a decision someone made.

Note what Marking does *not* own: `_markers`, the canvas and the frame
geometry stay in `operate.js`, because marks are placed in stage coordinates
derived from the live frame and that arithmetic belongs with the pixels. A
panel can own a readout and a set of verbs without owning the surface — which
is what lets it mount in the Atrium's EMBRYOS window, where there is no canvas
at all.

ImageView is the exception to rule 2: zoom and contrast are view state, not
instrument state, so they stay per-mount. Two people looking at one microscope
still want their own magnification.

CalProgress is rule 6 at its most literal: it is **absent** until frames
arrive, and an idle Fit view (calibration, on Scope) is 0px taller for its presence. It is
also the panel that owns the least — it starts nothing and stops nothing. It
subscribes to `IMAGE_RECEIVED`, the broadcast every pushed image already rode,
and narrates whatever calibration frames go past. That is why it also shows a
calibration the AGENT started from chat, which the pane itself never knew
about: the panel is watching the instrument, not the button.

Calibration's verbs are worth reading together, because each one answers
"how do I get a fit?" differently and the page shows only the ones that
apply. Calibrate is in Scope's Sheet panel; the rest are under the picture
when Fit is chosen in the strip:

| Verb | When it appears | What it costs |
|---|---|---|
| Calibrate / Recalibrate | always; the word depends on whether a fit exists | ~60–80 exposures |
| Borrow embryo N's fit | another embryo has a **better** fit | nothing |
| Calibrate N uncalibrated | two or more embryos lack a fit | ~70 each |
| Clear fit | this embryo has one | nothing, and it cannot be undone |

Borrow hides rather than offering a downgrade — without that rule it offers
the source embryo a copy of its own fit back the moment one borrow completes
— and it says plainly when the best fit on the slide is below
`LOW_CONFIDENCE_R2`, rather than calling a bad fit "the best".

Next: the calibration tab (#108) mounts Light and Camera. Manual mode's
bespoke laser UI is replaced once the shared one is proven on the rig —
deliberately not in the same change, because it is a surface nobody is testing
this week.
