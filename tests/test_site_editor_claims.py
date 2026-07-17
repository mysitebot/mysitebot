"""The fabricated-edit-claim regexes: a reply that narrates an edit while no
tool ran this turn must be caught so the turn is regenerated (see
AgentSiteEditor.run). Live failure mode (newsletter_fields_001, 2026-07-02):
Sam ANNOUNCED the edit in future/progressive tense and stopped without calling
any tool — past-tense-only matching let it through."""
from agent.site_editor import _EDIT_CLAIM_RE, _SCRIPTED_EDIT_CLAIM_RE


def test_past_tense_edit_claims_match():
    assert _EDIT_CLAIM_RE.search("I've updated your homepage heading.")
    assert _EDIT_CLAIM_RE.search("I've just added the gallery for you.")
    assert _EDIT_CLAIM_RE.search("Your changes are ready to publish!")
    assert _EDIT_CLAIM_RE.search("I'm double-checking everything now.")


def test_future_and_progressive_announcements_match():
    # The reply that slipped through live: announces the work, does nothing.
    assert _EDIT_CLAIM_RE.search(
        'I\'m adding a "Stay in the Loop" signup form to your About page. '
        "I'll let you know as soon as it's ready for you to see!")
    assert _EDIT_CLAIM_RE.search("I am updating your contact email now.")
    assert _EDIT_CLAIM_RE.search("I'll add the pricing page right away.")
    assert _EDIT_CLAIM_RE.search("I will remove that section for you now.")


def test_honest_no_edit_replies_do_not_match():
    assert not _EDIT_CLAIM_RE.search(
        "Which page would you like me to update — Home or About?")
    assert not _EDIT_CLAIM_RE.search(
        "Your site currently has three pages: Home, About and Contact.")
    assert not _EDIT_CLAIM_RE.search(
        "I wasn't able to apply that change just now — could you ask me "
        "again in a moment?")
    # Publish confirmations legitimately promise future action — never treat
    # them as fabricated edits.
    assert not _EDIT_CLAIM_RE.search(
        "Everything looks good — shall I publish now? I'll publish as soon "
        "as you confirm.")


def test_scripted_subset_only_matches_fresh_edit_script():
    assert _SCRIPTED_EDIT_CLAIM_RE.search("I'm double-checking everything now.")
    assert _SCRIPTED_EDIT_CLAIM_RE.search("The changes are ready!")
    assert _SCRIPTED_EDIT_CLAIM_RE.search("Your changes are now ready to publish.")
    assert _SCRIPTED_EDIT_CLAIM_RE.search(
        "I've double-checked and made the update you asked for.")
    assert not _SCRIPTED_EDIT_CLAIM_RE.search("I've updated the About page.")


def test_honest_double_check_answer_does_not_match():
    # An honest verification reply (nothing edited, nothing claimed) must not be
    # flagged — only the first-person scripted post-edit forms count.
    honest = "I've double-checked — the phone number on your contact page is correct."
    assert not _EDIT_CLAIM_RE.search(honest)
    assert not _SCRIPTED_EDIT_CLAIM_RE.search(honest)
    assert not _EDIT_CLAIM_RE.search(
        "Please double-check the address and let me know if it looks right.")


def test_negated_changes_ready_does_not_match():
    negated = "No changes are ready to publish yet — make an edit first."
    assert not _EDIT_CLAIM_RE.search(negated)
    assert not _SCRIPTED_EDIT_CLAIM_RE.search(negated)


def test_selfheal_script_verbs_are_edit_claims():
    # Live 2026-07-18: with zero commits in the turn, flash parroted the
    # self-heal script — "I've corrected it automatically" — and the verb
    # regex missed it because corrected/fixed were not in the verb lists.
    from agent.site_editor import _EDIT_VERB_CLAIM_RE

    live = ("I noticed a small issue with the update, but I've corrected it "
            "automatically. I'll let you know the moment it's live!")
    assert _EDIT_VERB_CLAIM_RE.search(live)
    assert _EDIT_VERB_CLAIM_RE.search("I've fixed the syntax on that page.")
    assert _EDIT_VERB_CLAIM_RE.search("I'm fixing the image paths now.")
    # honest negations/questions must stay unflagged
    assert not _EDIT_VERB_CLAIM_RE.search("Should I correct the image syntax?")
    assert not _EDIT_VERB_CLAIM_RE.search("The fix is still pending your approval.")
