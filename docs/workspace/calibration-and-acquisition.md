# Calibration and Acquisition: a study

What the two surfaces beside Scope are for, what was wrong with them, and
what they should become. `mockup-run-v1.html` in this folder draws the
proposal. The owner agreed the drawing ("agreed with the mockup, you can make
them") and it is built: "What is built", near the end, says which parts, how
each was checked, and where the page differs from the drawing. The sections
before it are the study as it was written, so "today" in them is the page
before this work.

## The short version

1. **Calibration should not be a page.** It is an operation on the light
   sheet, for the selected embryo, judged through the light-sheet camera, and
   it needs the laser. The sheet, the embryo list, the camera and the laser are
   all on Scope. None of them is on the Calibration page, which is why the
   first calibration pressed for this study spent eleven exposures on a dark
   laser. The proposal is one row in Scope's Sheet panel and a Fit view in the
   picture's strip, with the Calibration tab in the left navigation as the
   archive of every run and every raw exposure.
2. **Acquisition is two jobs that never happen at the same time**, designing a
   run and watching one, drawn as three columns that are always all there. The
   proposal is one surface with two states, each using the whole page, in
   Scope's three zones: the dish, a picture, the controls.
3. **Start is off the screen, and it refuses in the server's words.** In the
   default timelapse form with three embryos, Start sits 107 px under the fold
   of a maximized browser. The page knew every embryo was uncalibrated and did
   not say so until the press. Start should have one place, and the page
   should say before the press what stands in the way and what the run will
   write.
4. **Watching a run is split across three places.** The pictures are on the
   Embryos tab, which cannot pause or stop. Pause and Stop are on Acquisition,
   which has no picture. HALT is on Devices only.
5. **The cadence asked is not the cadence kept.** Every round runs about 3 s
   longer than the interval. At 5 min that is 1 %. At 30 s it is 12 %, so a
   night at "every 30 s" delivers about 200 fewer timepoints than the form
   implies. This is in the scheduler, not the page, and is a decision.

## How it was studied

- Both pages were read in full (markup, script, styles), then run on the
  simulated rig (`tools/sim_rig.py`) in a real browser at 1920×889 and at the
  desktop app's 1440×920, and pressed: a calibration with the laser dark and
  again with 488 nm routed and armed; a single volume of an uncalibrated
  embryo; a brightfield-only timelapse started, watched, visited from Scope
  while it ran, and stopped.
- The rig's own records were read, and only read: the 12,474 volume records
  in the 38 sessions under `D:\Gently3` that have volumes. They give what a
  volume weighs, what a round costs, the cadence the rig has kept, and the
  fits it has made.
- The scheduler was read for the cause of the cadence (`_reschedule` in
  `gently/app/orchestration/timelapse.py`).
- The built Scope was measured for the room a calibration row would have.
- The tab called Calibration in the left navigation was not in the first
  pass. It was read afterwards, when the owner asked where the raw
  calibration images would go, and it changed the proposal (C9, and "Where
  the raw images go").

Limits. The simulated rig cannot finish a calibration (its camera shows no
nuclei in a hardware-timed scan), so the page after a *successful* calibration
is described from the code, not from the screen. No SPIM timelapse was run on
it, since every simulated embryo was uncalibrated. Nothing was run on hardware.
The mockup was exercised in a browser at both sizes and in both themes; it is
a drawing, and its buttons reach nothing.

## Calibration today

| | Finding | Evidence |
|---|---|---|
| C1 | One card in an otherwise empty page | The card is 229 px of a 759 px page: 28 %. Two buttons and two inputs. |
| C2 | The card changes shape with its state | Calibrate sits at y = 274 before a run and y = 636 after one, because the run's pictures are inserted above the controls. The live progress strip lands under the fold; the page then scrolls by 258 px. |
| C3 | It needs the laser and can neither show nor set it | With the laser dark, Calibrate took 11 exposures and answered "No object visible … nothing lit clears the floor across 101 slices". Nothing on the page said the laser was off. The Light panel is one surface away, and going to it and back stops the view. |
| C4 | No picture before the press | "Is there an embryo here, and is it lit" is the question before a calibration. The operator could answer it by looking, if the light-sheet view were on screen. |
| C5 | One embryo's fit at a time | The rail says only `UNCAL`. Slope, R² and method are a single line for the selected embryo. "Which of my twelve are calibrated, and how well" is twelve clicks. |
| C6 | The evidence is thumbnails | The kept run is a grid of pictures 290 px wide inside the card. The fit itself, a line through two or three points, is the thing to judge, and it is one plot among them behind a click. |
| C7 | Settings come and go | Method, edges, Z buffer, More…, and a bounds row that exists only with edges off: five visibilities for nine fields. |
| C8 | Wide controls, far labels | Calibrate is 596 px wide. "Selected" and "embryo 2" are 1,100 px apart. |
| C9 | Two things are called Calibration, and neither is the archive | The surface on Devices is where a calibration is pressed. The tab in the left navigation (Profile, Gallery) shows the display copies a calibration pushes to the browser: held in memory, so empty after a restart. The record itself is on disk with the embryo, every exposure as it came off the camera (`embryos/{id}/calibration/{when}/frames/*.tif`, 49 runs kept on this rig since late September), and the page reaches only the latest run of the selected embryo, through the strip on the Devices surface. An earlier run, or a refused one, is reached by opening the folder. |

What is right and should stay: the verbs say what they will do (Calibrate or
Recalibrate, "Borrow embryo 1's slope", "Calibrate 3 uncalibrated", the
two-click Clear); the method says what it is before it runs; a refusal comes
with its evidence and a way past it; the frames are shown as they land.

## Acquisition today

| | Finding | Evidence |
|---|---|---|
| A1 | Start is off the screen | The timelapse form is 938 px tall in a 759 px column. Start's top edge is at y = 960; the column ends at 853. Three embryos, both channels on. Every embryo adds a row. At 1440×920 it takes 170 px of scrolling. |
| A2 | Three columns that are always all there | 378, 781 and 605 px. Before a run the right third says "Nothing running." During a run the middle 781 px is a form for a run that has already started, its button reading "A run is going". |
| A3 | Labels are far from their controls | 470 to 500 px, measured on "Every", "Taken from", "The run". |
| A4 | The page does not show what will refuse the run | The roster here has no calibration column. The plan's sentence read "SPIM volumes of 3 embryos" with no problem listed while all three were uncalibrated. Pressing Acquire one volume answered "Start failed (409 — not calibrated: embryo_2 … or pass allow_uncalibrated=true to acquire anyway...)". |
| A5 | Nor what the run will write, or whether a round fits | A volume here is 50 × 512 × 2048 16-bit: 105 MB, and 100 MB at the median of the 12,474 on disk. A new session's form opens at every 30 s for 16 h, which for three embryos is 5,760 volumes and about 576 GB, with 3.4 TB free. One embryo's volume costs 4.0 s (median of 6,919 at 50 slices and 10 ms; the scan itself is 0.5 s of it), so every 30 s holds seven embryos and no more. No line on the page says any of this. |
| A6 | The pictures and the controls of a run are on different tabs | The Embryos tab is the run's monitor: Watch, Table, Film, Vitals, each embryo's latest projection. It has no Pause and no Stop. Acquisition has Pause and Stop and no picture: `embryo 1 · t12 · next 27 s · every 30 s · 50 sl · 10 ms · running`. Neither points at the other. HALT is in the Devices toolbar and nowhere else. |
| A7 | The run is invisible on Scope | With the run going: no word of it, and Start camera, the jog pad, the head's steps and the laser were all live. The status bar under the page said "No run". |
| A8 | The code's words reach the operator | `standing_timelapse`, "Started from the Operate Run step.", "30s · 30s · brightfield", `allow_uncalibrated=true`. |
| A9 | Four modes that are four kinds of thing | A test shot, the run, a saved copy of the run's plan, and a hand-off to the agent, as four peer buttons that swap the form. |
| A10 | Per-embryo things are in three places | Role and Centre in the roster, the ending in the plan, the clock and Stop in the run rows. |
| A11 | Its own typography | Nine font sizes and five families on one page, counting the browser's default on unstyled controls and a serif display face for the sentence. Scope's panels use three sizes and two families. |
| A12 | Laser power is typed twice | Four "as it is" boxes in the plan beside the Light panel's own, without its behaviour at the limits. |
| A13 | The cadence asked is not the cadence kept | From the records: asked 300 s, kept 303.1 s (n = 1,933); 600 s, 603.2 (924); 60 s, 63.5 (417); 30 s, 33.5 (232). An embryo's next volume is scheduled from when its last one finished, not from when it was due (`_reschedule(embryo, from_now=True)`), so every interval is the interval plus one acquisition. |
| A14 | The default is not what is run | Of the 5,501 intervals between consecutive timepoints on disk, 69 % were asked at 5 min, 17 % at 10 min, 8 % at 1 min and 4 % at 30 s. A new session's form opens at 30 s. (A resumed session gets its own last plan back.) |
| A15 | A test volume ends in a toast | Acquire one volume answers "Volume acquired". The picture it took is not shown on the page that took it. |
| A16 | Two stages can end a run, of the eight that are read | "At hatching" and "at comma stage" are offered and no other stage. They are the two detectors the first scheduler had (November 2025). Since February an ending is any set of stages, and perception reads eight (early, bean, comma, 1.5-fold, 2-fold, pretzel, hatching, hatched), but the organism's table still names two sets (`STOP_CONDITIONS` in `gently/organisms/celegans/__init__.py`), the parser accepts only names in that table, and the page keeps its own copy of the list. |

What is right and should stay: the plan is one object said back as one
sentence, and Start sends exactly what was said; "all subjects" is the default
and narrowing is said out loud; a run is derived from the server, so a reload
does not lose it; an embryo can be stopped, or its ending changed, on its own;
a resumed session gets its plan back.

## What the pages are for

**Calibration** answers one question per embryo: at each position of the
sheet, where must the camera's focus be. It is measured by sweeping focus at
two or three sheet positions and fitting a line. Its inputs are the sheet's
two axes, which are the two sliders of Scope's Sheet panel. Its evidence is
light-sheet frames. Its precondition is light. Its result is a property of
the embryo, and a run refuses an embryo without one.

On this rig the line is about 97 µm of piezo per degree of galvo, over a
galvo range of about 0.3 degrees: the median of the 163 fits kept in its
records, of which nine in ten lie between 86 and 99. The slope is close to a
constant of the instrument, and what differs between embryos is mostly where
the line sits. That is why Borrow works, and it is worth knowing when judging
a fit: a slope far from 97 is more likely a bad fit than an unusual embryo.

**Acquisition** has two moments. Before a run it is a decision: which embryos,
how often, with what, until when; and the question an operator leaving for
the night needs answered is *will this run, and will it still be running in
the morning*. During a run it is a watch: is each embryo still in the field,
in focus and alive, when is the next round, how do I stop one.

## Proposal

The rules are Scope's: every panel has one place and keeps it; the picture
takes the height there is; a state is said once, in one place, from what is
read back; a value that can be set can be typed.

### Calibration moves onto Scope

- **The Sheet panel gains one row, Fit**: the selected embryo's fit
  (`97.8 µm/deg · R² 1.00`, or `not calibrated`) and the verb, Calibrate. The
  fit is the relation between the two axes above it, so it reads as the
  panel's third line. One row and no more: the instrument column has 25 px to
  spare in the desktop window (measured on the built page), and a row is
  about 24. The three rows first drawn would have needed about 80.
- **The picture's strip gains a fifth entry, Fit.** The frame shows the
  selected embryo's calibration at the picture's size: the line through its
  points, the focus curve at each sheet position, the frames behind them.
  Calibrate seats it, and the frames are shown as they land with the step
  named under them. Under the frame, where Display sits for a camera, is what
  a calibration is asked (Method, Z buffer, More…) and the other ways to a fit
  (Borrow, Calibrate the rest, Clear). The frame keeps its size.
- **The embryo list carries the fit**: `97.8 · 1.00`, `from 1 · 0.99`, or
  `uncal`. The list is the table C5 is missing.
- **A refused press points at the place that already says why.** What stands
  in the way of a fit is already on this page: the Light panel's line says the
  laser is dark, the Stage says which embryo it is at, the Head says its
  height. Pressing Calibrate with one of those wrong spends no exposure, marks
  that place, and says the reason; a second press goes anyway, as today. The
  fit has no status line of its own.
- **The Calibration entry leaves the toolbar.** What tells an operator the
  next step is on the screen they are already on: an amber `uncal` on each
  row, and "Calibrate 3 uncalibrated" in the Fit view.

### Where the raw images go

Asked by the owner on seeing the drawing: with calibration on Scope, how are
the raw calibration images reached, and do they go to the Calibration page?

They stay where they are, on disk with the embryo, every exposure as it came
off the camera; moving the button changes nothing about what is kept. What
changes is the two ways in:

- **The Fit view is for judging one calibration.** It shows the selected
  embryo's latest run: the line, the focus curves, the frames behind each
  point. A frame opens as it does today, at full size with its counts, with
  Show in folder and Fiji. That is everything the strip on the Devices
  surface does now, drawn larger.
- **The Calibration tab in the left navigation becomes the archive.** Yes:
  that is the right home. Every run of every embryo, the refused and aborted
  ones too; one exposure large with its counts and its file's name; the whole
  run's strip under it in the order taken, each with its score; the run's
  record beside it (what was asked, what came of it, the fit, the curves);
  Show in folder, Open in Fiji, and Recalibrate, which goes to Scope with that
  embryo selected. The Fit view links to it.

The tab already exists and already shows calibration images, but from the
wrong source (C9). Reading the records on disk instead, through the routes
the strip already uses (`/api/calibration/records`, with `.u16` for the
counts), is what makes it an archive: it survives a restart, and it has every
run. Those routes serve the live session; an earlier session's runs are on
disk in the same layout and would need the session named in the request.

The result is one thing called Calibration, where the evidence is kept, and
Scope, where it is made.

That last point reverses a decision. Calibration became a page because, with
the bottom camera and the SPIM head set up, an operator "was not sure what to
do in Gently at this point", and the answer then was a tab in workflow order.
The need was a visible next step. A tab is one way to show it; a mark on the
list in front of the operator is a closer one. If the tab is wanted all the
same, the alternative is a Calibration surface built like Scope (the same
rail, the same Light and Sheet panels in the same places, the evidence in the
middle), which costs a copy of two thirds of Scope and still parts the
Calibrate button from the live view.

### Acquisition: one surface, two states

Both states are Scope's three zones.

**Before a run:**

- *Left, the dish*, as a table: role, fit, and how this embryo ends. The
  per-embryo endings leave the form, which is what pushed Start off the
  screen, and A10's three places become one.
- *Middle, the latest volume of each embryo*, one tile each, as large as the
  room allows. "Test embryo 3" takes one volume with the plan on the right and
  puts its projection on its tile: change the exposure, test, look. This is
  what Single volume is for, and where its picture should have been (A15).
- *Right, the plan*, in boxes of 22 px rows with labels beside their values:
  Cadence, SPIM volume, Brightfield overview, Ends, Watching. Lasers are the
  presets as the Light panel draws them, with each routed line's power shown
  as it is and typed to change it. Nothing in it grows with the roster. An
  ending can be any stage perception reads, not two of them (A16): the
  organism's table names each as "that stage or any later", so a missed call
  cannot run a night long, and the page asks the server for the list instead
  of keeping a copy.
- *Far right, the run before it starts*: the sentence; then what stands in its
  way, each line derived and each with its fix one press away; then Start,
  pinned to the foot of the column and wearing the verdict.

  ```
  ✓  11 embryos in the run; 1 reference left out
  ✕  3 of 11 are not calibrated: 3, 8, 11       [Calibrate 3 ▸ Scope] [Run without them]
  ✓  488 at 3.1 %, 561 at 4.9 %: inside this rig's limits
  ✓  a round takes about 44 s of the 5 min between rounds
  ✓  about 2,079 volumes, 218 GB; 3.4 TB free on D:
  ✓  the head is at 114.6 µm, at the sample
  !  overview: no dark and flat yet                [Set up ▸ Scope]

  [ 1 thing in the way ]
  ```

  A saved plan is a Load beside the plan's name, not a mode. Handing the
  embryos to the agent is a button under Start.

Drawn at twelve embryos, it fits 1440×920 and 1920×889 with nothing scrolling
and Start on screen.

**During a run** the form is put away and the same three zones watch:

- *Left*, the same table with the run's columns: timepoint, next due (or
  "imaging"), ending (still editable), Stop for one embryo.
- *Middle*, the same tiles, now the run's latest volume of each embryo, the
  one being imaged marked as the round sweeps through.
- *Right*, the run's clock: time to the next round, the round, elapsed,
  volumes and gigabytes written, the cadence kept against the cadence asked,
  the last error, Pause and Stop, and the plan as started.

**One deep monitor.** The Embryos tab stays the place for Film, Vitals and
the stage calls, and this page links to it. It should carry Pause and Stop
too, so the tab a run is watched on can hold it.

### The run owns the instrument

- It is said in the Devices toolbar on every view (done, below), and Pause
  sits beside those words.
- On Scope, while a run is going, the verbs that would take the instrument
  from it (Start view, the jog pad, centre on an embryo, the head's steps,
  Calibrate) ask before they act. This is gating from the rig's state, which
  `operate.js` allows, not from which page is up, which it forbids.
- No panel moves when a run starts. A first drawing put a banner across the
  instrument column, and it pushed Light, Sheet, Head and Stage down by its
  own height.
- HALT holds automation as well as motion (see "HALT" below).

## The mockup

`mockup-run-v1.html` opens in a browser from the file. Scope is up first:
select embryo 3 and press Calibrate (refused: the laser is dark), route 488,
arm side A, press ◎ on embryo 3, press Calibrate again and watch the Fit view.
Then Acquisition: change the cadence to 30 s and read the lines, press "Run
without them", press Start, go back to Scope and press something, press HALT.
Then "Ca" in the left rail, or "All runs and exposures" in the Fit view: the
Calibration tab as the archive. Pick a run, step through its exposures with
the arrow keys, look at a refused one.

Its numbers are this rig's: the slopes, the 4.0 s a volume costs, the 105 MB
it weighs, the three seconds a round runs long. Light, Head and Stage are
drawn short and Find and Overview frames are left out; they are as built.

## Order of work

Smallest first. Each step stands on its own.

1. **Say what will refuse, where the press is.** Calibration state in the
   Acquisition roster; "N of M are not calibrated" among the plan's problems
   (`AcquisitionPlan.validate` already lists problems under the sentence) and
   in the refusal, in the operator's words; Calibrate refused by the page when
   the Light panel's own read-back says nothing emits. Text and one column.
2. **Pin Start.** The sentence and Start in a foot that does not scroll. One
   style rule.
3. **The run where it is watched.** Pause and Stop on the Embryos tab; a link
   each way between it and Acquisition; Pause beside the toolbar's run words.
4. **The arithmetic lines**: the round's length, the cadence that will be
   kept, volumes and gigabytes, free disk. All but the last are sums on values
   the page has; free disk is one read on the server.
5. **A test volume shows its picture** instead of a toast.
6. **The plan as a compact grid**; endings into the roster; presets as
   buttons; a saved plan as Load.
7. **Two states**: the form is put away while a run is going, and the tiles
   show the run.
8. **The Calibration tab reads the records on disk**, and becomes the
   archive. It stands on its own and is worth having whatever is decided
   about Scope: today a refused run's exposures can only be seen in a file
   manager.
9. **Calibration onto Scope**: the Fit row, the Fit view, then the toolbar
   entry removed.
10. **Verbs that ask** while a run is going.

Beside these, and small: **every stage as an ending** (A16), which is four
lines in the organism's table (bean, 1.5-fold, 2-fold, pretzel) and the page
asking for the list.

## What is built

The ten steps above, less one part of step 6 (below, "Not built"). Each is a
commit with its tests.

| Step | On the page |
|---|---|
| 1, 2, 4 | Before a run starts, beside Start, in a foot that does not scroll: what stands in the way with the press that puts it right, the round's length, the cadence that will be kept, the volumes and gigabytes against the disk's free room |
| 3 | Pause and Stop on the Embryos tab and Pause beside the toolbar's run words, on every view |
| 5, 6, 7 | Acquisition as one surface in two states, in Scope's three zones: the plan as a grid with each embryo's ending in the dish list and a saved plan as Load; a test volume's picture on its tile; while a run is going, the form is put away and the tiles show the run |
| 8 | The Calibration tab opens on Runs: every run the session kept on disk, one raw exposure large over the run's strip, the run's record |
| 9 | Calibration on Scope: a Fit row in the Sheet panel, Fit as the strip's fifth entry, the Calibration entry gone from the toolbar |
| 10 | On Scope, while a run is running, the stage, the head, starting a live view and a calibration ask first |

### Where the page differs from the drawing

- **The Calibration tab keeps Profile and Gallery** as its second and third
  views. They show what a calibration pushes to the page while it runs, and
  that could not be checked without a calibration that finishes, which the
  simulated rig cannot do. Runs is the first view and the only one with
  anything in it after a restart. Whether the other two go is a decision for
  after a calibration has been watched on the rig.
- **The Fit view is the run's own panels, not a new picture.** The drawing
  had one frame with the focus curves beside it. The page puts the existing
  progress panel (the frames as they land), the refusal and the last run's
  kept strip in the frame's place. Every element kept its id, so none of the
  calibration functions changed. The curves are in the archive, one press
  away ("All runs").
- **The box is square.** The drawing gave Fit the light sheet's wide frame.
  The bottom camera's shape keeps the instrument's columns where they are
  when Fit is chosen from the bottom camera, which is where it is chosen
  from.
- **The question while a run is going is the browser's own**, and one yes
  holds for a minute. The drawing had a line on the page. A paused run asks
  nothing.
- **A refusal points with what the page can read.** The drawing pointed at
  the Light status only. The page reads the laser, the LED, the head's
  height and whether the stage is at the embryo, says which it can see to be
  wrong, and outlines that panel.

### Not built

- **Presets as buttons**, the one part of step 6 not done: the cadence is a
  number and a unit.
- **Every stage as an ending** (A16).
- **The cadence** (A14). The page says the cadence that will be kept; the
  scheduler is unchanged.
- **HALT** is unchanged. It is the owner's decision, below.
- **Scope's sheet pose does not ask during a run.** The galvo and piezo
  lines move the sheet, and a run sets them itself for each volume. They
  were not in the list of verbs agreed and were left.

### How it was checked

On the simulated rig and on a copy of the rig's last session, in a browser at
1920×889 and 1440×920. A calibration pressed from the bottom camera's view
with the laser dark: Fit came up, the run counted, it was refused with its
frames shown, the page said no laser line was emitting and outlined Light.
The archive on the four runs of 8 November with their 157 exposures. The
question while a run is going with every device request intercepted, so
nothing reached even the simulated rig. **Nothing was driven on hardware,
and no calibration was watched to a fit**: what the page shows after one is
from the code and from the rig's kept runs.

## Decisions that are the owner's

- ~~Whether the Calibration entry leaves the Devices toolbar (step 9).~~
  Decided and built: it left.
- Whether Profile and Gallery leave the Calibration tab now that Runs is
  there ("Where the page differs from the drawing").
- What an uncalibrated embryo does to Start: refuse the run (today), or offer
  to run without it.
- The cadence. Either the page says the cadence that will be kept, or the
  scheduler anchors each embryo's next volume on when it was due, which
  `_reschedule` already supports with `from_now=False`. The second makes
  "every 30 s" mean it, and needs the guard its comment describes: a slow
  acquisition must not retrigger at once.
- What a new session's form opens at. The records say 5 min.
- HALT, below.

## HALT

Asked alongside this study: should HALT also turn off live view and the
lasers. Yes, on two conditions.

- **Motion still stops first and alone**, as its own request, so nothing
  added to the button can delay it or make it fail.
- **Everything else it does is free to undo.** Gate the lasers with the
  `ALL OFF` preset and leave the power setpoints alone, so nothing has to be
  typed again. Hold a run rather than stop it. Abort a calibration. Stop the
  live views.

The strongest reason is not the light. Today HALT stops the stages and tells
nobody: `timelapse.py` does not mention it, so as far as the code reads a run
issues its next move seconds later, and a halt during a run does not hold.
(Read from the code; not tried on the rig.) It should hold until Resume.

Two more things follow from A6. HALT is only on the Devices tab, so from the
tab a run is watched on nothing can stop anything; a stop that holds
automation belongs in the header, on every tab. And HALT is deliberately open
to anyone at the page, which is right for a stop, and means anyone can hold a
run.

It should not touch the water's temperature, the laser powers or any
position. One part is a choice: the bottom camera and the LED are how an
operator sees what was just stopped, and neither is a hazard, so they could
be left on.

## Done along the way

Hiding the session strip on the Devices tab (part of the workspace) left the
status bar as the only place that said a run was going, and with a
brightfield timelapse running it said "No run". The run's state is now
written into the Devices toolbar on every view of the tab: `RUNNING · next
27 s · brightfield 1`. Checked on the simulated rig on Scope and on Map, and
that it clears when the run stops.
