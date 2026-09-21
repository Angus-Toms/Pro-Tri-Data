"""Detect mechanical anomalies in race results and write auto-correction rows.

Runs between ingest and ratings. All rows inserted here use source='auto'.

Pipeline per result:

    A1. Per-split floor    split < physical floor -> zero (intrinsic, no overall needed)
    A0. Overall recompute  all main splits present and sum >> overall -> recompute
                           (handles dropped-hour / malformed overall times).
                           Skipped when any split is MAD-flagged so a single
                           inflated split (e.g. T1 of 10h) doesn't fake a
                           splits-sum-too-big signal.
    C.  MAD outlier        per-race median/MAD > 6x -> zero (applies to DNFs too)
    A2. Overall cross      split > (corrected) overall -> zero
    B.  Placeholder        finisher split == 0 -> flagged as missing
    D.  Arithmetic recovery exactly one swim/bike/run missing -> recompute from overall
                           (skipped if original is within SPLIT_RESIDUAL tolerance)
    E.  T1/T2 recovery     exactly one transition missing -> attribute shortfall
    F.  Multi-issue track  2+ legs flagged -> counted only; non-zero splits trusted
    G.  DNF pass-through   DNFs keep any splits that pass A+C; they feed partial ELO

Low-data pass-through cases (NOT treated as anomalies):
    - all splits zero, only overall recorded  -> no corrections written
    - both transitions zero, main splits fine -> no corrections written

Mixed relays live in relay_legs, not results, so they get their own pass
(_apply_relay) writing to the same corrections table, keyed on the leg's
athlete_id with 'overall' standing for leg_s:

    R1. Field floor      split < RELAY_FLOOR_FRAC of the field median -> zero
    R2. Transition ceil  T1/T2 over RELAY_T_CEILING -> zero
    R3. MAD slow         main split far above the field median -> zero
    R4. Leg time         leg_s missing -> sum of splits; leg_s short of the
                         splits sum -> blame the one inflated split if there
                         is exactly one, else recompute leg_s

The relay pass ignores team status entirely. Relay statuses are unreliable:
WT labels whole fields 'DNF'/'NC' when only the top three get a classified
time, so teams marked DNF routinely have four complete, valid legs. Validity
is judged from the splits themselves.

Run standalone:
    python -m ptd_data.auto_corrections
"""
import statistics

from tqdm import tqdm

from ptd_data import db


def _leg_name(leg):
    """Pretty discipline name for the notes column."""
    return {'t1': 'T1', 't2': 'T2'}.get(leg, leg.capitalize())


# Hard floors: below these a finisher split must be garbage. Set below the
# observed p0.1 of finisher times (swim 491s, bike 310s, run 539s) with slack
# so super-sprint legs are preserved.
FLOOR = {'swim': 180, 'bike': 300, 'run': 300}

# MAD outlier detection with asymmetric thresholds. Triathlon split distributions
# are skewed — a faster-than-everyone split is almost always a data error
# (missed timing mat, lap shortcut, course-cut), while a slower split has many
# legitimate explanations (dropped from pack, bad day, AG in elite race).
#
#   fast:  v < median - FAST_MULT * effective_MAD   (strict)
#   slow:  v > median + SLOW_MULT * effective_MAD   (permissive)
#
# MAD_FLOOR_FRAC prevents the MAD from collapsing in tight draft-legal fields
# (e.g. a swim pack clustered within 30s), so a "slow but legit" athlete isn't
# flagged as a data error just because the front group swam together.
FAST_MULT      = 6.0    # 6x effective MAD below median -> suspect
SLOW_MULT      = 12.0   # 12x effective MAD above median -> suspect (double the fast side)
MIN_DELTA      = 60.0
MAD_FLOOR_FRAC = 0.05   # 5% of median — 64s for a 21-min swim, 180s for a 60-min one
MIN_GROUP      = 6      # MAD is unreliable below ~6 samples

# Split-sum residual tolerance (seconds). p99 of clean-finisher residual ~29s.
SPLIT_RESIDUAL = 30.0

# Threshold for flagging the overall time itself as wrong (dropped hour, etc.).
# Deliberately much larger than SPLIT_RESIDUAL so ordinary rounding/measurement
# noise never triggers a structural recompute — only errors on the order of
# minutes (typically missing-hour or mis-entered totals).
OVERALL_RECOMPUTE_MIN = 120.0

# Plausible transition duration for T1/T2 recovery.
T_MIN, T_MAX = 5, 300

# Above this a transition is a parse artifact, not a real transition. No
# elite short/middle-course T1/T2 is anywhere near 30 min, so this is a very
# safe ceiling for detecting the H:MM:SS-parsed-as-MM:SS inflation (see the
# de-inflation step in apply()).
TRANSITION_CEILING = 1800

# --- Relay pass ---------------------------------------------------------
# Relay legs are super-sprints whose course length varies wildly by event
# (race-median swims run from 97s to 440s), so every relay threshold is
# relative to the field median for that (leg_num, gender) group.
#
# RELAY_FLOOR_FRAC replaces both the absolute FLOOR and the fast side of the
# MAD: nothing legitimate comes in under half the field median, and the
# observed ratio distribution has a clean gap either side of 0.45 (fastest
# real split 0.60x, next worst error 0.44x).
RELAY_FLOOR_FRAC = 0.45

# Slow side only. The MAD floor is 3x the individual-race one because relay
# fields legitimately span developing-nation athletes 2-3x off the median —
# any tighter and continental-championship legs get deleted as "errors".
RELAY_MAD_FLOOR_FRAC = 0.15
RELAY_MIN_DELTA      = 30.0

# A relay transition is ~30s. Anything past 3 min is a timing-mat failure
# that rolled an adjacent split into the transition, never a real one
# (observed p99: T1 103s, T2 86s).
RELAY_T_CEILING = 180.0

# Gap between the splits sum and leg_s worth reconciling.
RELAY_LEG_RECOMPUTE_MIN = 60.0

# Share of the splits-sum overrun a single split must account for to be
# blamed for it rather than recomputing leg_s.
RELAY_ROLL_IN_SHARE = 0.6

RELAY_MAIN   = ('swim', 'bike', 'run')
RELAY_SPLITS = ('swim', 't1', 'bike', 't2', 'run')


def apply(conn):
    """Recompute auto corrections. Returns a summary dict of counts.

    Wipes all existing correction rows (manual + auto). Callers are expected to
    reload manual rows from corrections.csv via db.load_corrections() after this
    runs so the COALESCE(manual, auto) priority in ratings.py has something to
    pick from.
    """
    conn.execute("DELETE FROM corrections")

    summary = {
        'impossible': 0,
        'placeholders': 0,
        'mad': 0,
        'overall_recomputed': 0,
        't_deinflated': 0,
        'recovered': 0,
        't_recovered': 0,
        'multi_zeroed': 0,
        'dnf_kept': 0,
        'relay_floored': 0,
        'relay_t_ceiling': 0,
        'relay_mad': 0,
        'relay_roll_in': 0,
        'relay_leg_recovered': 0,
        'relay_leg_recomputed': 0,
    }

    race_rows = conn.execute("""
        SELECT race_id FROM races ORDER BY race_date, race_id
    """).fetchall()

    insert_batch = []

    for (race_id,) in tqdm(race_rows, desc="Auto-corrections", unit="race"):
        results = conn.execute("""
            SELECT athlete_id, status, overall_s, swim_s, bike_s, run_s, t1_s, t2_s
            FROM results WHERE race_id = ?
        """, [race_id]).fetchall()
        if not results:
            continue

        # Per-discipline MAD on finishers (Step C precomputation).
        mad_flags = _compute_mad_flags(results)

        for (aid, status, overall, swim, bike, run, t1, t2) in results:
            is_finisher = (status == 'Finished' and overall > 0)
            is_dnf      = (status == 'DNF')

            # Working copy of splits + a tracker of issues on swim/bike/run.
            s = {'overall': overall, 'swim': swim, 'bike': bike,
                 'run': run, 't1': t1, 't2': t2}
            flagged = set()   # subset of {'swim','bike','run'} that are bad/missing

            # Step A1 - per-split impossibility (intrinsic: doesn't depend on overall).
            for leg, floor in FLOOR.items():
                if 0 < s[leg] < floor:
                    reason = f'{_leg_name(leg)} below plausible minimum; removed'
                    insert_batch.append((race_id, aid, leg, 0.0, 'auto', reason))
                    s[leg] = 0
                    if leg in ('swim', 'bike', 'run'):
                        flagged.add(leg)
                    summary['impossible'] += 1

            # Step A1b - de-inflate H:MM:SS-parsed transitions. Some sources
            # render T1/T2 as H:MM:SS but the field is read as MM:SS, inflating
            # the transition by exactly 60x (a 2:46 transition becomes
            # 2:46:00 = 9960s). MAD (Step C) can't catch it because the whole
            # field is inflated by the same factor, so no single value is an
            # outlier; and left alone, Step A0 below would "reconcile" the
            # bloat by folding it into overall. Divide by 60 when the result is
            # a plausible transition and, where overall + main splits exist,
            # reconciles the residual (overall - swim - bike - run). Runs
            # before A0 so the corrected transitions feed the overall check.
            for leg in ('t1', 't2'):
                if s[leg] <= TRANSITION_CEILING:
                    continue
                cand = round(s[leg] / 60.0)
                if not (T_MIN <= cand <= T_MAX):
                    continue
                if (is_finisher and s['overall'] > 0
                        and s['swim'] > 0 and s['bike'] > 0 and s['run'] > 0):
                    other = 't2' if leg == 't1' else 't1'
                    other_val = (s[other] / 60.0 if s[other] > TRANSITION_CEILING
                                 else s[other])
                    residual = s['overall'] - s['swim'] - s['bike'] - s['run']
                    if abs((cand + other_val) - residual) > OVERALL_RECOMPUTE_MIN:
                        continue  # doesn't reconcile - leave it for A0/MAD
                insert_batch.append((race_id, aid, leg, float(cand), 'auto',
                                     f'{_leg_name(leg)} de-inflated from H:MM:SS parse'))
                s[leg] = cand
                # Drop any raw MAD flag so Step C doesn't re-zero the value we
                # just fixed (matters when only some of the field is inflated).
                mad_flags.pop((aid, leg), None)
                summary['t_deinflated'] += 1

            # Step A0 - overall sanity. Two modes:
            #   (a) recompute: all three main splits present and their sum is
            #       meaningfully greater than overall — reconstruct overall
            #       from splits (handles dropped-hour, mis-entered totals).
            #   (b) zero: overall is smaller than at least one main split but
            #       we don't have enough data to recompute (splits missing) —
            #       zero overall so the A2 cross-check below doesn't destroy
            #       the good splits we do have.
            #
            # Skipped if any split is MAD-flagged: a single grossly-inflated
            # split (e.g. mis-entered T1 of 10 hours) would produce a fake
            # "splits sum >> overall" signal here. Let MAD zero the rogue
            # split first and keep the original overall, which is almost
            # always correct in those cases.
            has_mad_flag = any((aid, leg) in mad_flags
                               for leg in ('swim', 'bike', 'run', 't1', 't2'))
            if is_finisher and s['overall'] > 0 and not has_mad_flag:
                biggest_split = max(s['swim'], s['bike'], s['run'])
                if s['swim'] > 0 and s['bike'] > 0 and s['run'] > 0:
                    main_sum = s['swim'] + s['bike'] + s['run'] + s['t1'] + s['t2']
                    if main_sum > s['overall'] + OVERALL_RECOMPUTE_MIN:
                        insert_batch.append((race_id, aid, 'overall', float(main_sum),
                                             'auto', 'Overall recalculated from splits'))
                        s['overall'] = main_sum
                        overall = main_sum
                        summary['overall_recomputed'] += 1
                elif biggest_split > s['overall'] + 5:
                    insert_batch.append((race_id, aid, 'overall', 0.0, 'auto',
                                         'Overall shorter than splits; removed'))
                    s['overall'] = 0
                    overall = 0
                    summary['overall_recomputed'] += 1

            # Step A0b - overall MAD when no splits are available to cross-check.
            # Old races often record only an overall time, so the A0 splits-sum
            # check above can't fire. Fall back to comparing overall against the
            # field's overall distribution and zero implausible values.
            if (is_finisher and s['overall'] > 0
                    and s['swim'] == 0 and s['bike'] == 0 and s['run'] == 0
                    and (aid, 'overall') in mad_flags):
                direction = mad_flags[(aid, 'overall')]
                if direction == 'fast':
                    reason = 'Overall implausibly fast vs field; removed'
                else:
                    reason = 'Overall far off field pace; removed'
                insert_batch.append((race_id, aid, 'overall', 0.0, 'auto', reason))
                s['overall'] = 0
                overall = 0
                summary['overall_recomputed'] += 1

            # Step C - MAD outlier (runs after A0 so its split-zeroing can't
            # mask a broken overall; uses corrected overall for consistency).
            for leg in ('swim', 'bike', 'run', 't1', 't2'):
                if s[leg] > 0 and (aid, leg) in mad_flags:
                    direction = mad_flags[(aid, leg)]
                    if direction == 'fast':
                        reason = f'{_leg_name(leg)} implausibly fast vs field; removed'
                    else:
                        reason = f'{_leg_name(leg)} far off field pace; removed'
                    insert_batch.append((race_id, aid, leg, 0.0, 'auto', reason))
                    s[leg] = 0
                    if leg in ('swim', 'bike', 'run'):
                        flagged.add(leg)
                    summary['mad'] += 1

            # Step A2 - cross-check: split > overall (using possibly corrected overall).
            if s['overall'] > 0:
                for leg in ('swim', 'bike', 'run'):
                    if s[leg] > s['overall'] + 5:
                        reason = f'{_leg_name(leg)} exceeds overall time; removed'
                        insert_batch.append((race_id, aid, leg, 0.0, 'auto', reason))
                        s[leg] = 0
                        flagged.add(leg)
                        summary['impossible'] += 1

            # Step B - placeholder (finishers only; DNFs can legitimately miss splits).
            if is_finisher:
                for leg in ('swim', 'bike', 'run'):
                    if s[leg] == 0 and leg not in flagged:
                        flagged.add(leg)
                        summary['placeholders'] += 1

            # Step D - arithmetic recovery (finishers, exactly one main leg missing,
            # AND both transitions present — otherwise the residual is ambiguous
            # between the missing main and the missing transition).
            if is_finisher and len(flagged) == 1 and s['t1'] > 0 and s['t2'] > 0:
                missing = next(iter(flagged))
                clean_legs = [leg for leg in ('swim', 'bike', 'run') if leg != missing]
                clean_sum = sum(s[leg] for leg in clean_legs)
                if clean_sum > 0 and all(s[leg] > 0 for leg in clean_legs):
                    recovered = overall - clean_sum - s['t1'] - s['t2']
                    if recovered > FLOOR[missing]:
                        orig_val = {'swim': swim, 'bike': bike, 'run': run}[missing]
                        # If the original non-zero value is within arithmetic tolerance
                        # of the recovered value, it was already correct — don't churn
                        # a 2-3s "recovery" on top of a prior speculative flag (MAD).
                        # Drop any earlier auto row for this leg so the original stands.
                        if orig_val > 0 and abs(recovered - orig_val) < SPLIT_RESIDUAL:
                            insert_batch[:] = [
                                row for row in insert_batch
                                if not (row[0] == race_id and row[1] == aid and row[2] == missing)
                            ]
                            s[missing] = orig_val
                            flagged.discard(missing)
                        else:
                            reason = f'{_leg_name(missing)} recalculated from overall and other splits'
                            insert_batch.append((race_id, aid, missing, float(recovered),
                                                 'auto', reason))
                            s[missing] = recovered
                            flagged.discard(missing)
                            summary['recovered'] += 1

            # Step E - transition recovery (finisher, exactly one T missing, main splits clean).
            if is_finisher and not flagged and all(s[leg] > 0 for leg in ('swim', 'bike', 'run')):
                missing_t = None
                if s['t1'] == 0 and s['t2'] > 0:
                    missing_t = 't1'
                elif s['t2'] == 0 and s['t1'] > 0:
                    missing_t = 't2'
                if missing_t:
                    known_t = 't2' if missing_t == 't1' else 't1'
                    residual = overall - s['swim'] - s['bike'] - s['run'] - s[known_t]
                    if T_MIN <= residual <= T_MAX:
                        reason = f'{_leg_name(missing_t)} recalculated from overall and other splits'
                        insert_batch.append((race_id, aid, missing_t, float(residual),
                                             'auto', reason))
                        s[missing_t] = residual
                        summary['t_recovered'] += 1

            # Step F - multi-issue tracking only. The flagged legs are already
            # zeroed by Steps A/B/C individually; we no longer zero clean sibling
            # splits or transitions. If a split is non-zero after A-E, we trust it.
            if len(flagged) >= 2:
                summary['multi_zeroed'] += 1

            # Step G - DNF pass-through accounting (no extra action; A+C already ran).
            if is_dnf and (swim > 0 or bike > 0 or run > 0):
                summary['dnf_kept'] += 1

        # Flush in batches to avoid an enormous single executemany.
        if len(insert_batch) >= 10000:
            _flush(conn, insert_batch)
            insert_batch.clear()

    _apply_relay(conn, insert_batch, summary)

    _flush(conn, insert_batch)

    print(
        "auto-corr: impossible={impossible} placeholders={placeholders} "
        "mad={mad} overall_recomputed={overall_recomputed} "
        "t_deinflated={t_deinflated} recovered={recovered} "
        "t_recovered={t_recovered} multi_zeroed={multi_zeroed} "
        "dnf_kept={dnf_kept}".format(**summary)
    )
    print(
        "auto-corr relay: floored={relay_floored} t_ceiling={relay_t_ceiling} "
        "mad={relay_mad} roll_in={relay_roll_in} "
        "leg_recovered={relay_leg_recovered} "
        "leg_recomputed={relay_leg_recomputed}".format(**summary)
    )
    return summary



def _apply_relay(conn, insert_batch, summary):
    """Relay leg corrections, appended to insert_batch (see module docstring).

    Thresholds are all relative to the field median for the leg's
    (leg_num, gender) group, because relay course lengths vary hugely by event
    and because leg 1 is a mass start while legs 2-4 are chases. Team status is
    deliberately not consulted - see the module docstring.
    """
    race_rows = conn.execute("""
        SELECT race_id FROM races WHERE distance = 'relay'
        ORDER BY race_date, race_id
    """).fetchall()

    for (race_id,) in tqdm(race_rows, desc="Auto-corrections (relay)", unit="race"):
        legs = conn.execute("""
            SELECT l.athlete_id, l.leg_num, a.gender,
                   l.leg_s, l.swim_s, l.t1_s, l.bike_s, l.t2_s, l.run_s
            FROM relay_legs l
            JOIN athletes a USING (athlete_id)
            WHERE l.race_id = ?
        """, [race_id]).fetchall()
        if not legs:
            continue

        # Field median + effective MAD per (leg_num, gender, discipline).
        groups = {}
        for aid, leg_num, gender, *times in legs:
            for disc, value in zip(('overall',) + RELAY_SPLITS, times):
                if value > 0:
                    groups.setdefault((leg_num, gender, disc), []).append(value)
        stats = {}
        for key, values in groups.items():
            if len(values) < MIN_GROUP:
                continue
            med = statistics.median(values)
            mad = statistics.median(abs(v - med) for v in values)
            stats[key] = (med, max(mad, RELAY_MAD_FLOOR_FRAC * med))

        for aid, leg_num, gender, *times in legs:
            s = dict(zip(('overall',) + RELAY_SPLITS, (float(t) for t in times)))
            touched = False

            # R1 - field floor. Catches the 1s/11s placeholder splits and the
            # partial split of an athlete pulled part-way through a leg.
            for disc in RELAY_SPLITS:
                key = (leg_num, gender, disc)
                if s[disc] <= 0 or key not in stats:
                    continue
                med = stats[key][0]
                if s[disc] < RELAY_FLOOR_FRAC * med:
                    insert_batch.append((race_id, aid, disc, 0.0, 'auto',
                                         f'{_leg_name(disc)} under {RELAY_FLOOR_FRAC:.0%} of the relay field; removed'))
                    s[disc] = 0.0
                    touched = True
                    summary['relay_floored'] += 1

            # R2 - transition ceiling. A 30s distribution is far too tight for
            # MAD (its effective MAD collapses to ~1.5s, which would delete
            # every merely-slow transition), so this one is absolute.
            for disc in ('t1', 't2'):
                if s[disc] > RELAY_T_CEILING:
                    insert_batch.append((race_id, aid, disc, 0.0, 'auto',
                                         f'{_leg_name(disc)} too long to be a relay transition; removed'))
                    s[disc] = 0.0
                    touched = True
                    summary['relay_t_ceiling'] += 1

            # R3 - MAD, slow side only. The fast side is R1's job.
            for disc in RELAY_MAIN:
                key = (leg_num, gender, disc)
                if s[disc] <= 0 or key not in stats:
                    continue
                med, emad = stats[key]
                if abs(s[disc] - med) < RELAY_MIN_DELTA:
                    continue
                if s[disc] > med + SLOW_MULT * emad:
                    insert_batch.append((race_id, aid, disc, 0.0, 'auto',
                                         f'{_leg_name(disc)} far off relay field pace; removed'))
                    s[disc] = 0.0
                    touched = True
                    summary['relay_mad'] += 1

            # R4 - leg time, only on rows R1-R3 left alone (a corrected row has
            # no splits sum left to reconcile against).
            if touched or not all(s[disc] > 0 for disc in RELAY_SPLITS):
                continue
            splits_sum = sum(s[disc] for disc in RELAY_SPLITS)
            if s['overall'] == 0:
                # Whole teams go unclassified with all four legs complete;
                # without this their legs never reach the relay overall ELO.
                insert_batch.append((race_id, aid, 'overall', splits_sum, 'auto',
                                     'Leg time recalculated from splits'))
                summary['relay_leg_recovered'] += 1
                continue
            overrun = splits_sum - s['overall']
            if overrun <= RELAY_LEG_RECOMPUTE_MIN:
                continue
            # Either leg_s is short or one split swallowed a handover wait. One
            # split sitting above its field median by most of the overrun is the
            # culprit; anything else means leg_s is the odd one out.
            culprits = [disc for disc in RELAY_MAIN
                        if (leg_num, gender, disc) in stats
                        and s[disc] - stats[(leg_num, gender, disc)][0] > RELAY_ROLL_IN_SHARE * overrun]
            if len(culprits) == 1:
                disc = culprits[0]
                insert_batch.append((race_id, aid, disc, 0.0, 'auto',
                                     f'{_leg_name(disc)} overruns the leg time; removed'))
                summary['relay_roll_in'] += 1
            else:
                insert_batch.append((race_id, aid, 'overall', splits_sum, 'auto',
                                     'Leg time recalculated from splits'))
                summary['relay_leg_recomputed'] += 1


def _compute_mad_flags(results):
    """Return a dict {(athlete_id, discipline): 'fast'|'slow'} of MAD outliers.

    Distribution is fit on finishers (stable reference) but the threshold is
    applied to every row with a non-zero split — including DNFs, who can have
    wildly short legs (e.g. pulled off the bike course) that need flagging.
    """
    flagged = {}
    finisher_rows = [r for r in results if r[1] == 'Finished' and r[2] > 0]
    if len(finisher_rows) < MIN_GROUP:
        return flagged

    # Positions of each discipline in the row tuple.
    cols = {'overall': 2, 'swim': 3, 'bike': 4, 'run': 5, 't1': 6, 't2': 7}
    for disc, idx in cols.items():
        vals = [r[idx] for r in finisher_rows if r[idx] > 0]
        if len(vals) < MIN_GROUP:
            continue
        med = statistics.median(vals)
        mad = statistics.median(abs(v - med) for v in vals)
        # Floor the MAD so a tight draft pack can't collapse the threshold onto
        # MIN_DELTA and flag legitimately-slow athletes as outliers.
        effective_mad = max(mad, MAD_FLOOR_FRAC * med)
        if effective_mad == 0:
            continue
        fast_cutoff = med - FAST_MULT * effective_mad
        slow_cutoff = med + SLOW_MULT * effective_mad
        for r in results:
            v = r[idx]
            if v <= 0:
                continue
            if abs(v - med) < MIN_DELTA:
                continue
            if v < fast_cutoff:
                flagged[(r[0], disc)] = 'fast'
            elif v > slow_cutoff:
                flagged[(r[0], disc)] = 'slow'
    return flagged


def _flush(conn, rows):
    if not rows:
        return
    conn.executemany(
        """INSERT OR REPLACE INTO corrections
               (race_id, athlete_id, discipline, value, source, reason)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--manual-only", action="store_true",
                        help="Skip auto detection; just reload corrections.csv manual rows.")
    args = parser.parse_args()

    conn = db.get_conn(read_only=False)
    if not args.manual_only:
        apply(conn)
    db.load_corrections(conn)
    conn.close()
