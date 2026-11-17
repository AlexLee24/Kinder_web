"""Hourly: Daily Trigger targets switched off more than obs.OFF_DAYS (3) days ago are deleted, unless kept.

A target's off_since is set when its switch goes off and cleared when it goes back on; "Keep" on the Daily Trigger
page (obs.targets.keep) exempts it. Targets that are on are never touched.
"""
import logging

logger = logging.getLogger(__name__)


def prune_off_targets():
    from app.db.obs import OFF_DAYS, prune_off_targets as prune
    try:
        gone = prune(OFF_DAYS)
    except Exception as e:
        logger.error('event=prune_off_targets_failed error=%s', e)
        return 0
    for t in gone:
        logger.info('event=off_target_deleted id=%s name=%s telescope=%s off_since=%s',
                    t['target_id'], t['name'], t['telescope'], t['off_since'])
    if gone:
        logger.info('event=prune_off_targets deleted=%d', len(gone))
    return len(gone)
