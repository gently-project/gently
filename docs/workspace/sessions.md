# The Sessions tab: a study

What the tab is for, what is wrong with it today, what was fixed along the
way, and what it should become. `mockup-sessions-v1.html` in this folder draws
the proposal. The loading work and one naming fix are built; **the redesign is
not**, it is here to be agreed or changed first.

## The short version

1. **The list could not say which session was which.** 381 of the rig's 384
   sessions have no name, and each was listed as eight hex digits. Fixed: an
   unnamed session is called by what it holds, on every page that lists them.
2. **It is a log book drawn as a column of cards.** Five sessions of 47 fit on
   screen, in a column 339 px wide, beside 1,320 px that are blank until one
   is opened. Nothing can be compared down a column, because there are no
   columns. The proposal is a table that has the page.
3. **An opened session shows its pictures last.** They start 633 px down an
   889 px window, under a header, an export row, an empty notes box and the
   plan. With eleven embryos the pane is 1,751 px tall. The proposal is
   Scope's three zones: the log, the pictures, the record.
4. **Loading is done.** The list answers in 60 ms where it took 680, its first
   rows are on screen 80 ms after the tab is pressed where it took 280, and
   the sizes arrive with the list where they took four seconds and sixteen
   requests.

## How it was studied

- The rig's sessions were copied without their image stacks (385 sessions,
  47 with data, everything but the TIFFs) to a folder of their own, and the
  real routes and the real page were run on the copy in a browser at
  1920×889. The rig's own folder was only read.
- Route timings were taken in-process on that copy, cold and warm. Time to the
  first row was taken in the browser with a mutation observer, since the
  window throttles animation frames when it is not in front.
- What a card's picture costs was timed on the rig's own files, read-only,
  the way the route reads them, because the copy has no volumes to read.
- The page's markup, script and styles were read in full.

Limits. Sizes on the copy are the copy's, so the mockup's sizes are worked out
(timepoints × 105 MB), not read. Nothing here needs a microscope and nothing
was run on one. The mockup was looked at in a browser at 1920×889 and at the
desktop app's 1440×920, in both themes.

## What the tab is for

Five jobs, in the order they come up:

1. **Find a session.** By when, by what it holds, by project.
2. **See what it holds** before doing anything with it: the embryos, how the
   run went, what it was asked to do.
3. **Compare.** Which night kept its cadence, which dish hatched, which run
   was cut short.
4. **Act on one.** Carry on with it at the rig, name it, file it under a
   project, export it for Fiji, make a movie of it, open its folder.
5. **Keep house.** 338 of 385 sessions have nothing in them; someone should be
   able to see that without scrolling past them.

## What is wrong

**S1. A session was listed by its id.** The list route sent the id in a name's
place, which stopped the page's own fallback (the name, else what the session
holds, else the id) at the first word. The detail route has always sent no
name, so an opened session read "11 embryos · every 10 min · Oct 12 overnight
· complete" over a row that said `b269eb0d`. Home's recent sessions and both
session pickers in Projects had the same column of hex. *Fixed.*

**S2. Five rows.** A row is a card 105 to 127 px tall in a 339 px column. At
1920×889, five of the 47 sessions with data are wholly on screen. Open the
filters and it is two and a half.

**S3. The rest of the page is blank.** Until a session is opened, 1,320 px of
a 1,660 px page hold a document icon and "Select a session to review".

**S4. A card says everything twice and lines nothing up.** The name line reads
"3 embryos · every 30 s · Oct 26 overnight · complete"; the line under it
reads "Oct 26, 5:26 PM · 3 embryos · 1680 brightfield · 83 MB · complete". The
facts are running text, so the eye cannot go down the timepoints or the sizes,
and the only orders on offer are three chips inside the folded filters
(newest, most timepoints, largest).

**S5. The name line showed twenty characters of fifty.** It kept 140 px free
for two buttons that appear on hover. *Fixed* for the cards as they are (the
corner is kept free only while the buttons are in it); a table does not have
the problem.

**S6. The filters are a second page.** Six groups and the sort, 370 px tall in
the 307 px column, above the list they filter.

**S7. The pictures come last.** In an opened session, top to bottom: a
five-line header (141 px), the notes box (150 px, "Nothing written on this
session yet"), the plan (129 px: four short lines with 1,100 px of nothing to
their right), a tab strip (40 px), and then the embryos, from 633 px down.
One row of four cards shows, cut off at the middle.

**S8. A card is 396 px for a 201 px picture.** Eleven embryos make three rows
and a 1,751 px pane in a 778 px window. The embryo that hatched is on the
second screen.

**S9. Each picture scrubs on its own.** Moving across a thumbnail runs that
embryo through its timepoints. There is no way to put the whole dish at one
moment, which is the question after a night: what did the dish look like at
3 am.

**S10. A row cannot be reached from the keyboard.** A row is a `div` with a
click handler: no tab stop, no role, no arrow keys. The two buttons inside it
can be reached; the session cannot be opened.

**S11. Three typefaces and twelve sizes.** The system face, a monospace, and
Arial on every button that does not inherit its font (54 of them on screen);
sizes at 10, 11, 11.5, 12, 12.5, 12.8, 13, 13.5, 13.6, 14, 15 and 21 px.

**S12. Nobody is written on a session.** None of the 47 sessions with data
records an operator, two have a description, eighteen are filed under a
project. The launch gate now asks who is at the rig, so new sessions can
carry a name; the column is worth having for that.

**S13. Looking at an old session writes into it.** A card's picture is the
camera's counts at thumbnail size, read from a small file written beside the
JPEG when the volume was taken. 158 of the rig's 169 embryos with volumes
predate that file, so the first look reads the whole 105 MB volume (50 ms),
projects it (46 ms) and keeps the result, 2.2 MB, in the session's
`projections` folder. A tenth of a second per card, once, is not a loading
problem. It is a thing to know: scrubbing an old night end to end adds a file
per timepoint crossed. Not changed.

## What was done

Built on this branch, with tests. Timings are on the copy of the rig's
sessions.

| | Before | Now | How |
|---|---|---|---|
| The list, cold | 682 ms | 64 ms | what the list read of a session is kept (`sessions/_list_cache.json`) and trusted while the session's two YAML files are unchanged: two `stat` calls a session, not a walk of its folder |
| The list, warm | 411 ms | 49 ms | the same |
| A project's sessions, and the unfiled ones | 645 ms | 50 to 70 ms | the same rows, filtered |
| Every session's size | 3,985 ms in 16 requests after the list | with the list | a size once counted is kept with the row; the live session is counted afresh |
| The projects | 240 ms | 160 ms | what each planned item waits on is read once, not once per dependency (it was about a thousand YAML reads to list six projects) |
| First rows on screen | 280 ms | 80 ms | the rows are drawn when the list arrives and redrawn when the projects do; they used to wait for both |
| Opening a session | 60 ms, 28 requests | unchanged | already quick |

The live session is never read from the cache, a session is forgotten when it
leaves the index, and the cache file is safe to delete. Along the way a stale
read was found and fixed in the store itself: a YAML file rewritten at the
same size within one tick of the clock was answered from memory as it had
been. It showed as a test that failed one run in six.

What is left in the projects' 160 ms: 40 ms walking every session to count
each project's, the rest reading plan items again for every node of the tree.
It no longer holds up a row, so it was left.

## The proposal

### Nothing opened: the log

A table with the whole page. One session a line, 26 px a line, so about 28
on screen where there are 5.

```
┌ Find…  │ With data · Empty · All │ SPIM  Brightfield │ Complete  Cut short  Never ran │ any time ▾ │ any project ▾ │ 47 of 385 · + New ┐
├───────────────┬─────┬───────┬───────┬────────┬───────┬───────────┬───────┬──────────┬──────┬───────────────────────┤
│ WHEN        ▾ │ EMB │ TIMEP │ EVERY │ LASTED │ BF    │ ENDED     │ SIZE  │ PROJECT  │ BY   │ NAME OR NOTE          │
│ Oct 26 17:26  │   3 │       │ 30 s  │ 14.0 h │ 1,680 │ complete  │ 111 MB│ hatching │      │ not named             │
│ Oct 12 17:21  │  11 │    85 │ 10 min│ 14.1 h │       │ complete  │ 98 GB │ unfiled  │      │ not named             │
│ Oct 7 18:33   │   4 │       │ 30 s  │ 11.4 h │ 2,726 │ complete  │ 180 MB│ hatching │      │ Four embryos, overnight│
│ …                                                                                                                  │
├────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 338 sessions with nothing in them · Show                                                                           │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

- **A heading sorts.** Pressing a column's heading orders by it; pressing
  again turns it round. The three sort chips go.
- **Timepoints are how far the run got**, the most any one embryo has, as the
  list has defined them since #328. Eleven embryos imaged 85 times are 85
  timepoints and 935 volumes; the volumes are what the size is.
- **What a session holds is the row.** The derived name was the row's facts in
  a sentence because there was nowhere else to say them. In a table they are
  the columns, beside the date. What a person wrote is the last column, with
  the room that is left: the name, or the first line of the description, or
  "not named" in the dim. Three of the rig's 384 sessions have a name, so a
  name column put second left a gap a third of the page wide between the
  date and the numbers.
- **The filters are one bar** above the table. The same six questions as
  today: what it holds, which channel, how the run ended, when, which project,
  and the two "has" marks. The count beside them says how many of how many
  are showing, so a filter never hides sessions silently, as now.
- **The empties are one line** at the foot, with their number. Showing them
  puts them in the table like any other row.
- **The live session** is the first row, marked, whatever the order.
- **Keys.** The table is a list to the keyboard: up and down move, Enter
  opens, Esc closes the opened session, `/` goes to Find.

### A session opened: the same three zones as Scope

```
┌ Find… │ filters ──────────────────────────────────────────────────────────────── 47 of 385 ┐
├────────────────────┬──────────────────────────────────────────────┬────────────────────────┤
│ THE LOG            │ WHAT IT HOLDS                                │ THE RECORD             │
│ when · what · end  │ [Embryos 11|Brightfield|Conversation|Tools]  │ This session           │
│                    │ t 85 of 85 · Oct 13 07:31  ◀━━━━━━━━━━━●▶    │   name, project, when  │
│ Oct 26  3 · 30 s   │ ┌────┐ ┌────┐ ┌────┐ ┌────┐                  │   by, on disk, folder  │
│ Oct 24  3 · 30 s   │ │ 1  │ │ 2  │ │ 3  │ │ 4  │                  │ The run                │
│▌Oct 12 11 · 10 min │ └────┘ └────┘ └────┘ └────┘                  │   as started           │
│ Oct 9   4 · 30 s   │ ┌────┐ ┌────┐ ┌────┐ ┌────┐                  │   how it went          │
│ …                  │ │ 5  │ │ 6  │ │ 7  │ │ 8  │                  │ Notes                  │
│                    │ └────┘ └────┘ └────┘ └────┘                  │ Take out               │
│                    │ ┌────┐ ┌────┐ ┌────┐                         │   Fiji, movies, crops  │
│                    │ │ 9  │ │ 10 │ │ 11 │                         │ ─────────────────────  │
│                    │ └────┘ └────┘ └────┘                         │ [ Carry on at the rig ]│
└────────────────────┴──────────────────────────────────────────────┴────────────────────────┘
```

**The log** stays, narrowed to the columns that tell sessions apart (when,
how many embryos at what cadence, how it ended), so the next session is one
arrow key away and the place in the list is never lost.

**What it holds** is the pictures, first and all at once. The tiles are sized
to the room there is, so eleven embryos are on one screen with nothing to
scroll (the rule Acquisition's watch state already uses). Under each: its
name and role, the stage it reached, and its night as a thin bar of stages.
**One scrubber moves every tile together**, so the dish can be put at any
moment of the run. Pressing a tile opens it large, with its planes, as now.
Brightfield frames, the conversation and the tools are the other entries of
the same strip.

**The record** is what was a header, a box and a row of buttons, as four
panels that keep their places:

- *This session.* Its name (typed in place), its projects, when, who, its
  size and its folder.
- *The run.* As started: cadence, volume, laser, overview, which embryos. How
  it went: timepoints, volumes, how it ended, and the cadence it kept beside
  the one it was asked for.
- *Notes.* The stream, one line to write in.
- *Take out.* Export for Fiji, the two movies, the crops.

And one verb at the foot, where Start is on Acquisition: **Carry on at the
rig**, which is today's "Make live". It asks first, as now.

### What does not change

The routes, the store, the filters' meaning, the export and movie forms, the
viewer a picture opens in, and what "Make live" does. This is the same data
and the same verbs in a different arrangement, which is why it can be built
without touching the server beyond one field (the cadence kept).

## Order of work

1. The table, with headings that sort and the filters as one bar. The opened
   session stays as it is, to the right. *This alone takes the list from 5
   rows to 28.*
2. Keys: a row is a tab stop, arrows, Enter, Esc.
3. The empties as one line.
4. The record column: the header, the plan and the export row re-homed as
   four panels.
5. The pictures: fitted tiles and the strip.
6. The one scrubber.
7. The cadence kept, from the route.

Each step leaves the tab working. Steps 1 to 3 are the list and can go in
without the rest.

## Decisions that are the owner's

- **Whether to build it.** Nothing above is built except the fixes in "What
  was done".
- **What the last column says for an unnamed session.** "not named", or
  the derived sentence again. The drawing has "not named", since every word
  of the sentence is in a column beside it.
- **Whether old sessions should get their small pictures in one pass** (S13)
  and not as they are looked at. About 27 GB for the rig's 12,474 volumes,
  against 1.3 TB of volumes.
- **The 161 folders the index does not list.** 157 are empty folders from
  July; four are not. They are invisible to this tab today and were left
  alone.
