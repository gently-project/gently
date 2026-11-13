# Operate as a workspace

The Devices tab's Operate view is one workspace, **Scope**, with Acquisition
as the surface beside it. This is why, what it is, and how it was checked.
The mockups in this folder are the drawings it was built from.

Calibration was a third surface when this was written. It is on Scope now: a
Fit row in the Sheet panel and Fit as the fifth entry of the strip above the
picture (`calibration-and-acquisition.md`). Where the text below says
"Calibration" as a surface, read that.

| | |
|---|---|
| `mockup-v1.html` | the first drawing: three zones, group boxes, dense rows |
| `mockup-v2.html` | after the audit below: number boxes, a real small-window layout, both themes |
| `calibration-and-acquisition.md` | the study of the two surfaces beside Scope, what was proposed for them, and what of it is built ("What is built" lists the steps and what is left) |
| `mockup-run-v1.html` | that proposal drawn: calibration on Scope, Acquisition before a run and during one, the Calibration tab as the archive of raw exposures |
| `sessions.md` | the study of the Sessions tab: what was measured, the loading work that is built, and the redesign that is proposed and not built |
| `mockup-sessions-v1.html` | that proposal drawn: the sessions as a log-book table, and a session opened in the same three zones as Scope |

Open any of the mockups in a browser. The controls move; nothing reaches a
microscope.

## The problem

> "there is still no good way to place the panels on the screen. what is the
> fundamental problem? something wrong with our design philosophy? frontend
> architecture? the way we layout css? why is this gui not as good as the
> microscope guis traditionally made"

Nothing had a place. The bottom camera and the SPIM head were two panes, and
each assembled its own copy of the instrument around its own frame:

- The same control was in a different place, or missing, depending on which
  camera was up. The stage pad and the LED's brightness were only beside the
  bottom camera; the head and the laser only beside the light sheet. Moving
  the stage while looking through the SPIM camera meant leaving the view.
- Panels flowed into "as many columns as fit", so a panel's position depended
  on the window's width and on which of its neighbours were folded.
- What did not fit scrolled, and to make it fit every card on the rail had
  been given a Show/Hide. A panel that can be folded away is a panel that is
  somewhere else the next time.
- Three rows of chrome sat above the panes (a strip, a title with the view
  switcher, the pane switcher) and one below (the water's strip). In a
  1920×889 window the picture was 373 px tall.

A traditional microscope GUI is dull in exactly the way that matters: the
laser is top right today because it was top right yesterday.

## The workspace

Three zones in one row. Every panel has one place and keeps it.

```
┌ Scope | Calibration | Acquisition │ Map | Details | 3D | Manual ─── status · HALT ┐
├──────────────┬───────────────────────────────┬─────────────────────────────────────┤
│ THE DISH     │ WHAT THE RIG SEES             │ THE INSTRUMENT                      │
│              │ [Bottom cam|SPIM A|SPIM B|Multi] Start · Exposure                   │
│ Detect       │ ┌───────────────────────────┐ │ Light          Head                 │
│ Embryos      │ │                           │ │   LED            height, floor      │
│ Fields       │ │        the frame          │ │   Laser presets  steps              │
│ Overview     │ │                           │ │   405…637        go to, raise       │
│   frames     │ └───────────────────────────┘ │   Beam, status                      │
│              │ caption            fps · size │ Sheet          Stage                │
│              │ Display                       │   galvo, piezo   XY, jog, focus     │
└──────────────┴───────────────────────────────┴─────────────────────────────────────┘
```

**The dish** (280 px) is what is on the coverslip: finding embryos, the embryo
list, the fields the overview is taken from, and the overview frames'
settings. It is the same rail on Calibration, less the two boxes that act on
the bottom camera's picture.

**What the rig sees** is one frame. A strip above it chooses the camera: the
bottom camera, or the light sheet from side A, side B or both. Only the
camera's own things change with the camera: its frame, its live-view button,
its exposure, its caption and its display range. Choosing another camera stops
the one that was live and starts nothing; a live view is on because someone
pressed Start.

**The instrument** is four panels in two columns whose order never changes:
Light and Sheet, Head and Stage. A wide window shows the columns side by side;
a narrower one stacks the second under the first. Nothing here depends on the
camera chosen, and nothing is switched off by it: the LED lights either
camera, and the head and the stage are the same head and stage.

The frame takes the height there is and its width from its aspect. The
instrument takes the width that is left. No script measures anything: the
pane is a CSS size container, and the frame's height is the container's
height less the fixed heights of what sits above and below it
(`operate.css`, "Scope — the workspace").

## What changed on the page

| Before | Now |
|---|---|
| Bottom cam and SPIM head: two panes | one surface, Scope; the camera is a choice in a strip |
| three rows of chrome above the panes, one below | one toolbar row: the surfaces, the other views, the readings, HALT |
| HALT inside the SPIM head's gauge | in the toolbar, on every view of the tab |
| the left navigation at 212 px | starts as a 56 px icon strip on this tab (the choice is remembered) |
| the water's strip under every view | one reading in the toolbar; its chart opens over the foot of the page |
| the Detect strip under the frame | a box in the dish rail |
| an LED card beside the bottom camera, the whole Light panel beside the SPIM head | the whole Light panel, always |
| every rail card folds | the instrument panels do not fold; Overview frames, set once a night, still does |
| a slider with a read-only number | a slider and a number to type, one control |
| the head to 1000 µm, or up, by button | those, and a typed height (1000 µm or more) |

## Numbers can be typed

> "the adjustable parameters like laser power can also have a way to enter
> numbers into a text box -- as sometimes biologists love that"

Every adjustable value is a line to drag and a box to type in: each laser
line's power, the LED's brightness, the sheet's galvo and piezo
(`panels/numrow.js`). The rules are the same everywhere:

- The limits are the slider's, which the panel sets from what the server says.
- A typed value is a draft, drawn as one, until Enter or leaving the box.
  Nothing is sent while typing: "12" on the way to "120" is not a power.
- A value outside the limits is pulled inside and the box flashes, so the
  number on screen is the number sent.
- Not a number, or Esc, puts back what was there.
- ↑ and ↓ step by the slider's step, Shift by ten.
- A value read back from the hardware does not land under a drag or a
  half-typed number.

The head's typed height has a floor of 1000 µm, held by the server
(`FDRIVE_GOTO_MIN_UM`) and read by the page with the head's position. The rig
images about 85 µm above the F-drive's own floor, so a typed 100 for 1000
would put the objectives on the sample in one move. Below 1000 µm the head
comes down by the steps, as before.

There is deliberately **no typed XY position**. The route that moves the
stage to an absolute position checks that x and y are numbers and nothing
else; until it is fenced by the XY envelope a typed coordinate is a slipped
digit away from the edge of the dish. The jog pad, centring on an embryo and
going to a field cover what the page needs. The second mockup drew a typed XY
row before this was looked at; it has been taken out of the drawing.

## The Light panel

One place for each control, always there: the LED (Closed | Open, and its
brightness), the Laser config group's presets as buttons, a row for every
line the rig has, the beam on each side, and one status line.

The status line is always present and says, in order of what matters:
`EMITTING · 488 nm · side A`; that the emission state is unknown; that both
sources are open; that lines are routed but will not emit, and why; that the
beam is armed with nothing routed; the LED alone; or `Dark — nothing emits`.
It is derived from what is read back (a beam armed, a line routed, its power
above zero), never from what was pressed. The toolbar's `LASER EMITTING` is
the same derivation.

Two things the redesign found on the way:

- A preset named "ALL ON" carries no wavelength, and the rule "no digits in
  the name, no lines routed" read it as dark: all four lines on, armed and
  powered came out as *not emitting*. A name that cannot be read for lines,
  and is not an off, now counts as every line.
- A line's power could not be seen or set until the line was routed. Every
  line's power is read and shown now, routed or not.

## How it was checked

There was no microscope: the rig was powered down for this work. Everything
was exercised on the simulated rig (`tools/sim_rig.py`: the real device layer
and the real page on a stand-in for the Micro-Manager core) in a real browser
window, and **nothing here has been driven on hardware yet**.

Measured in the browser:

| Window | The picture | The instrument | Scrolls |
|---|---|---|---|
| 1920×889 (a maximized browser on this rig's monitor) | 583 px (was 373) | two columns | nothing |
| 1440×920 (the desktop app's window) | 614 px | one column, all four panels | nothing |
| 1366×768 | 462 px | one column | the instrument column, by 105 px |
| 1280×800 | 494 px | one column | the instrument column, by 122 px |
| 1100×700 and 900×600 (the app's minimum) | the width there is | under the frame | the page; nothing is clipped, HALT stays in the window |

Exercised by hand on the simulated rig, in both themes: the camera strip
(bottom camera, SPIM A, B, Multi, and back), starting and stopping each view,
marking three embryos by clicking and registering them (they landed within
2 µm of where the simulation puts them), adding a field, centring on an
embryo, jogging with the head at imaging height, typing a galvo angle and a
laser power inside and outside their limits, the laser presets, arming a
side, opening the LED over a routed line, a typed head height below the
floor (refused, nothing sent), and switching to and from Calibration,
Acquisition, Map, Details, 3D and Manual.

## Where the drawing and the page differ

- No typed XY position (above).
- The mockup greyed the Sheet panel while the bottom camera was up. On the
  page it stays live: `operate.js` forbids switching a control off by which
  surface is on screen, and a sheet can be posed without looking at it.
- The source strip does not carry the live view across cameras. The mockup
  implied it did; on the rig a view that restarted by itself once began
  streaming under a timelapse, and the rule since is that only Start starts.
- The head keeps its two named heights as buttons (To 1000 µm, Raise head)
  beside the typed one; the mockup had one "Load" button.

## Not done here

- The frame is still fetched by snap, one exposure at a time. Micro-Manager's
  sequence acquisition would be faster, and if each snap is cycling the
  shutter through the Tiger (it appears to, and has not been measured) would
  stop that too.
- The Light panel reads the hardware every ten seconds, so a change made by
  the agent or a run shows up to ten seconds late. A change made on the panel
  is read back at once.
- Manual mode still has its own laser controls.
- Nothing checks the page's scripts for a name that is never defined. One
  such slip (a variable left behind when the XY lock was removed) broke
  click-to-mark for five days and was found only by clicking. An ESLint
  `no-undef` pass over `static/js` in CI would have caught it.
