# 📣 Outreach plan — getting this in front of Red Sox media

## The thing to internalise first

**Nobody wants another Red Sox stats site.** Every beat writer already has
Baseball Reference, FanGraphs and Savant open. A link that says "I built a Sox
analytics app" gets a polite nothing, because it asks the recipient to do the
work of finding the story in it.

What this project actually has is **three findings**, and a finding is
pitchable. Lead with the finding, let the site be the evidence. The correct
first sentence of any outreach is a claim someone could argue with — never a
description of the software.

---

## 0. Preconditions — roughly a week, and do not skip them

You get one shot per person. If someone with an audience clicks through and the
site is stale or wrong, that is the impression, and there is no second pitch.

1. **Prove the pipeline.** On 2026-08-23 the deploy broke and Render silently
   kept serving a build from before `556b463` — the site returned 200s the
   whole time and simply stopped updating. It was found by accident a day
   later. Before any push, get **7 consecutive days of clean automated builds**,
   and add something that fails loudly rather than quietly: a staleness check
   that compares the newest `game_date` in the cache against today, wired to
   fail the Action.

2. **Add analytics.** There is none — I checked. Without it you cannot tell a
   successful push from a failed one, which makes the whole exercise
   unfalsifiable, and this is a project whose entire premise is measuring
   things. Plausible or GoatCounter, one script tag, no cookie banner needed.

3. **Audit the site for anything that reads as a pick.** The board printed
   `OVER (-5.9% EV) 🔥` on 2026-08-24 — a flame on a bet the same code had
   computed to lose money. That is fixed, but it is exactly the screenshot that
   would circulate. Read every page as a hostile reader would.

4. **Pick the canonical link per audience.** Not the homepage for everyone.
   Sox media → `/matchup` or `/streak_records`. Analytics people →
   `/track_record`. Never open with `/tonights_board`.

---

## 1. The three stories, and who each is for

### Story A — "Sorting by game ID says the streak was 14"
**For: Sox fan media, podcasts, r/redsox.**

A rained-out makeup game carries a *lower* `gamePk` than the nightcap it
precedes, so ordering the July 3–22 run by primary key reads a 15-game streak
as 14. Everything here orders by `(game_date, game_number)` instead.

This is the wedge, and it is the only one of the three that is genuinely
*local*. Sox media covered that streak heavily — it tied the franchise record.
It is a story about a thing they already care about, it has a concrete
surprise, and it takes twenty seconds to tell. It also implicitly makes the
case for the rest of the site without you having to.

### Story B — "I built betting models and published proof they don't work"
**For: betting media, and cynics anywhere.**

164 graded player-games, neither model beats the market, both Brier gaps
contain zero, and the Track Record page says so in those words. As of
2026-08-24 there is also a market-movement read over 160 player-games: mean
−0.05 points, CI [−0.33, +0.23].

This is counter-positioning, and it is strong precisely because that space is
wall-to-wall with people selling picks. You are not selling anything. Do not
oversell this either — the honest framing *is* the pitch, and dressing it up
destroys the only thing that makes it interesting.

### Story C — the selection effect
**For: FanGraphs/BP community, stats Twitter, Hacker News. Not Sox radio.**

Same total-bases model, same 1.5 line, two populations:

| Population | n | AUC | Slope |
|---|---|---|---|
| All hitter-starts | 935 | **0.564** | **+0.710** |
| Only those a book priced | 140 | 0.495 | −0.014 |

The skill is real; the market has already priced out the actionable part. This
generalises well past baseball — any model evaluated on a non-random subsample
chosen by an informed party is measuring something other than what it thinks.
It is the most intellectually interesting of the three and the **worst** fit
for a Sox audience. Do not mix it into Story A.

---

## 2. The ladder — start at the bottom

The instinct is to email the biggest name first. That is the fastest way to
burn the biggest name. A cold pitch from an account with no traction reads as
spam; the same pitch two weeks later reading *"this got picked up by X and Y"*
reads as a tip.

**Tier 1 — community, no gatekeeper (week 1–2).**
r/redsox, r/Sabermetrics, r/baseball. Sons of Sam Horn. Over the Monster's
FanPosts (SB Nation lets anyone post; a good FanPost gets promoted). The
Fangraphs Community Blog accepts submissions and is the natural home for
Story C.

Goal: three credible mentions and a real referral-traffic number.

**Tier 2 — independent Sox podcasts and newsletters (week 3–4).**
Smaller Sox pods and Substacks. They have real audiences, they publish
constantly, and they are *hungry for segments* in a way a radio show is not.
This is where Story A actually lands. A pod will happily spend five minutes on
"the streak was almost recorded wrong."

**Tier 3 — established outlets (week 5+, only with Tier 1–2 receipts).**
Over the Monster (staff), NBC Sports Boston, WEEI, NESN, The Athletic's Boston
staff, Boston Globe, MassLive, Baseball Prospectus.

⚠️ **Verify every name and handle yourself before sending.** Boston sports
media personnel churn constantly and my information is not current. Check who
currently covers the Sox at each outlet, and check whether they have said
anything about analytics or betting — someone who has written about neither is
the wrong target regardless of audience size.

---

## 3. Pitch templates

Rules: one claim, one link, under 120 words, no attachment, no "would love to
hop on a call." Make it trivially easy to use the thing without replying to
you.

**Tier 1, Reddit / forum post — Story A**

> **The Sox' 15-game streak is recorded as 14 if you sort the games wrong**
>
> A rained-out makeup game gets a lower gamePk than the nightcap it comes
> before, so ordering by game ID splits the July 3–22 run. You have to order by
> (date, game number). I found this building a Sox tracker and it cost me a
> real day.
>
> The streak page is here if it's useful: [link]. Whole thing is open source.

**Tier 2, podcast/newsletter DM — Story A**

> Hi — I build [dirtywater.corygarms.com], a Red Sox analytics site.
>
> One thing that might make a segment: sorting games by MLB's own game ID reads
> the July 3–22 streak as 14, not 15, because a rained-out makeup game carries
> a lower ID than the game it precedes. Small thing, but it means a lot of
> quick analyses of that run were probably wrong.
>
> Streak page: [link]. Happy for you to use any of it, credit or not.

**Tier 3, journalist email — Story B**

> Subject: I built Red Sox betting models and published the proof they don't work
>
> I run [dirtywater.corygarms.com]. It publishes strikeout and total-bases
> projections, and it also publishes a page scoring every one of them against
> what happened and against the market price. Over 164 graded player-games
> neither model beats the market, and the page says exactly that.
>
> I'm not selling picks and there's nothing to buy. If a site that grades
> itself in public is of interest: [link to /track_record].

---

## 4. Timing

- **Now → end of season (~30 games).** Peak attention, peak noise. Good for
  Tier 1. Beat writers are busiest and least reachable now.
- **Postseason, if they make it.** Do not pitch. You will not be read.
- **November–February.** The real window for Tier 3. Sox media is starved for
  content and a self-grading analytics project is exactly the kind of thing
  that fills an offseason column or episode. By then you will also have a full
  season of track record instead of a month.

The counterintuitive call: **the best pitching window is the offseason**, and
between now and then your job is to accumulate evidence and fix the pipeline.

---

## 5. How you will know it worked

Define this before you send anything, or you will rationalise afterwards —
which is the exact failure this project exists to avoid everywhere else.

- Referral traffic by source, per push.
- Did anyone link back? A mention with no link is worth much less.
- Return visitors — the only real signal. A traffic spike that never comes back
  means the story travelled and the site did not.

Set a threshold in advance. If three Tier 1 posts produce no returning users,
the problem is the site, not the outreach, and more pitching will not fix it.

---

## 6. What not to do

- **Don't mass-DM.** Ten personalised notes beat two hundred copied ones.
- **Don't lead with "I built an app."** Lead with the claim.
- **Don't pitch Story C to Sox media** or Story A to statisticians.
- **Don't oversell the betting angle.** "My models don't beat the market" is
  the interesting version. "I found an edge" is both less interesting and, per
  your own Track Record page, false.
- **Don't ask for a share.** Offer a fact and let them decide.
- **Don't pitch while the pipeline is unproven.** See §0.
