# Home, feed and profile redesign

Findings from an audit of the three pages (October 2026) and the direction we are taking.
Mockups live in `debug/home_designs/`.

## What is wrong today

**Home page.** It is a table of contents, not a page. A tagline hero with three vanity
counters, an intro paragraph that says the same thing again, then five sections whose
real job is to hold a "view all" link. Nothing on it knows what day it is: no sense of
what races this weekend or what just happened. The four champion cards are hard-coded
athlete ids and show the same faces to every visitor until someone edits the router. Six
tall event cards carry only six events and print date and venue twice each. The Compare
block is a fixed Brownlee vs Gomez button. The page is identical whether you are logged
in or not, so a returning user never sees their own athletes and a new visitor is given
no reason to sign up. On a phone the first real data is a screen and a half down.
Analytics back this up: event pages take 160 to 170 visits a week, the home page about
40. People land on race pages and reach the home page by tapping the logo or coming back
directly. Both groups want to know what is happening now.

**Feed page.** Empty because it is three filtered lists, not a feed. With one followed
athlete it shows one start, three results and an empty comments box, under a hero that
spends its space counting your own follows. Each section ends by linking you away to a
generic site page. There is no "new since you were last here", no rating or rank
movement, no milestones, and nothing that acknowledges the weekly rebuild rhythm, so
between race weekends it is static and in the off-season it is blank. The upcoming card
shows the model's podium but not where your athlete is expected to finish, which is the
one number a follower wants. There is no way to find more things to follow from inside
the page. On a phone the Feed link is inside the hamburger, two taps away.

**Profile page.** The hero puts two competing groups side by side: unlabeled reaction
badges under the name, and a cluster of small social icons, a follow button and three
counters on the right. Below that is a bio box and a flat wall of comments, with replies
shown without the comment they answered. For a stats site the profile has no stats about
the person and nothing that changes week to week. Your own profile has no edit button
and the header chip goes to the account page, so people cannot easily find their public
page. Profiles are noindex and only reachable from comment author links, so they cost a
header slot and bring little back.

**Across all three.** The user system takes four surfaces (feed, profile, account, bell)
and three header slots. Everything personal is kept behind session-gated pages instead
of layered onto the pages people already visit. The growth plan says the retention play
is follows plus race-weekend emails, but the feed does not mirror the emails and the home
page has no follow hooks at all.

## Direction

**Home becomes the feed.** One page, built around the week. Logged out it answers "what is
happening in triathlon right now": this weekend's races with their status (start list,
predicted podium, results in), the latest results as dense rows rather than cards, the
week's biggest rating movers, one compact rankings table, and the latest blog post.
Logged in, a personal layer is injected above the general sections: your athletes racing
this weekend with their expected finish, their results since your last visit, and
suggestions while someone has few follows. The anonymous HTML stays identical for
everyone; the personal part is a partial fetched by the existing hydration script, the
same way race comments load. The separate feed page and its header link go.

**Feed items are a typed stream.** Start-list entry, race this weekend, result, rating
milestone (new peak, top-10 entry, rank change), comment or reply on something you
follow, blog post. Milestones come from a table built with the weekly rebuild, so the
page has something to say in weeks with no starts. Items are grouped by week.

**Profile absorbs account.** A hero in the athlete-page style: photo, name, flag, club,
bio, socials, Follow or Edit profile, and a stat row. Below it: who they follow (athlete
follows become public, they are not sensitive), personal bests, and comments grouped by
race with the parent quoted for replies. The account form and danger zone sit behind
Edit on your own profile, or on a settings page reached only from the avatar menu.

**Header.** Athletes, Races, About, search, bell, then an avatar menu with Profile,
Settings and Log out. Logged out, a single Log in link. On phones the avatar sits outside
the hamburger.

## Engagement ideas that are ours

Podium picks are out: a competitor runs them and it would read as copying. These fit the
data we already have and nobody else publishes:

- **Model accountability.** Each week, the biggest over- and under-performances against
  the pre-race prediction, and the model's public record. Honest, unfakeable, and it
  invites argument in the comments.
- **Rivalries.** Follow a head-to-head (the rivals query already exists). The feed shows
  every shared race and the running score.
- **Milestones.** New peak rating, first top 10, first win, first elite start, surfaced
  for followed athletes and in the weekly digest.
- **Share from the feed.** Every result row can produce the share card that already
  exists on main.

## Mockup notes

- No cards, pills or gradients. Rules, type and tables do the work, in the existing palette.
- Men left, women right wherever the two sit side by side.
- Must hold up at phone, tablet, laptop and wide desktop widths.
- The animated hero counters move to a single line of small type above the footer.

## Quick fixes done on this branch

- About subtitle typo (FAG to FAQ).
- Scotland, England, Wales and Northern Ireland flags copied from main.
- Uppercase country names for the home nations come from World Triathlon data; left.

Note: `feature/users` is 101 commits behind `main`, which has since gained predictions,
share cards, relay pages and an odometer version of the home counters. Merging main in
is the first implementation step.
