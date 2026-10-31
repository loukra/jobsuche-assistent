# /coverletter - The Missing Puzzle Piece

You are writing a cover letter whose only job is to supply what the CV cannot: the connection between the candidate's record and *this* posting. The reader already has the resume. The letter must not repeat it. It must answer the questions the resume leaves open for this role and supply the missing piece that turns a plausible candidate into the obvious one.

The target is given as `$ARGUMENTS`: a company name, a posting URL, or pasted posting text.

Follow these steps **in order**.

**Standing rules (shared with `/apply`):**
- Write new facts back to the profile. Any fact the user confirms, corrects or supplies during this run that is not yet in `.claude/skills/job-application-assistant/01-candidate-profile.md` goes there in the same turn. A fact that lives only in chat is stripped as a fabrication by the next session.
- Never fabricate. Every claim is grounded in `CLAUDE.md`, `01-candidate-profile.md`, `02-behavioral-profile.md` or the CV the user submits. Apply the interview backtrack test from `03-writing-style.md`; present every "stretch" sentence to the user as keep / soften / drop.
- Style rules from `03-writing-style.md` apply in full: no em-dashes (`--` or `—`), no cliches, no unverified company claims.

## Lessons from rejected drafts (read before Step 4, extend in the same turn)

Every letter goes through the user's review, and the same objections keep coming back. This list is the memory of those reviews. **Read it before drafting, test every sentence against it before compiling (Step 5), and when the user rejects a sentence in this run, append the sentence and the rule behind it here in the same turn** (`N. **Rule.** Rejected: "..." Accepted: "..." (Company, YYYY-MM-DD)`).

The rules below were collected over many review rounds on another user's letters and hold for letters in general. Treat them as the starting point; the user's own rejections refine them.

1. **Verified is not the same as convincing.** A company fact goes in only if the candidate would say it out loud. A forced link between a true fact and the candidate's wish reads as flattery; a genuine personal link stated plainly ("I use your app myself") is worth more.
2. **No stilted images.** If a phrase would sound odd when spoken across a table, rewrite it in plain words.
3. **Name one gap, framed with "but" and what carries over.** One sentence names the gap, the rest of the paragraph is the transfer. Never a pile of negatives ("not from aerospace, not from a project organisation, not done yet"), never a list of things the candidate cannot do.
4. **The "but" clause must name something concrete the candidate could explain in an interview.** If no true, concrete transfer exists for a gap, do not invent a vague one: name the gap plainly or leave it for the interview.
5. **No invented feelings about a place, a product or a mission.** If the candidate did not say it, it reads as a lie.
6. **No phrasing lifted from the posting, a press release or the website.** Readers recognise their own text ("copied from the website"). Say in the candidate's words what they want to do there.
7. **No posting quotes as a frame, and no bare self-attribution.** "Your posting describes X. That is exactly how I work." claims a match without showing it. Say what the candidate does and let the reader make the match; at most one posting reference per letter, followed by the bridge that shows the candidate already acts on it.
8. **Length is ideas, not layout.** Around 180 to 230 words, four paragraphs, each one idea. Over length means dropping an idea, never squeezing sentences or margins.
9. **Match the posting's register.** A "du" posting gets a "du" letter ("Liebes ...-Team," / "Viele Grüße"); a "Sie" posting a "Sie" letter.
10. **Never hang the letter on a standard requirement.** Skills that every current posting lists (AI tooling, Agile, communication) are no hook for an opening.
11. **No colon opening with a vague lead-in.** "Your posting names two things in one breath: ..." says nothing before the colon and reads as machine-written. Say the thing directly.
12. **Never contrast the wish against a work mode the company might actually have.** "In my own product instead of changing projects" backfires if the team does work on several projects. State the wish without the contrast.
13. **Open with a concrete personal thought, never with an inference about the company's setup and never with an abstraction the reader has to decode.** No third-person self-portrait, no aphorism, no colloquial exaggeration. Open with something the candidate did or cares about, in written register.
14. **Write for a recruiter, not for a specialist.** The first reader is often not an expert. Replace jargon the reader cannot picture with the effect it has, in everyday words.
15. **Tell a project the way the candidate would tell it out loud.** No clipped "So I ..." sentences that list techniques. A project paragraph states its puzzle piece (what it shows for this posting), it does not narrate the build step by step.
16. **No homespun reasoning images and no slogans.** "A rule that lives in one head does not hold" sounds folksy, a slogan-like company phrase sounds copied. Say the point plainly.
17. **Never write the candidate's years against the posting's requirement.** The CV shows the dates. Answer a years requirement with the scope the candidate has owned, never with a number next to theirs.
18. **Never invent how the candidate's work is delivered or used.** Release cycles, customers, team sizes and settings come from the profile, not from what would sound good.
19. **The gap paragraph is an argument, not a stack list.** Several sentences in a row that each name one technology still read as an enumeration. Lead with the posting's need, then the base with "but", then the gap.
20. **No claim whose referent the reader cannot name, and no opening that tells the posting what it obviously says.** "I know both sides of this work" (which work?) and "your posting is aimed at X" are empty. State the concrete fact.
21. **A conclusion names a concrete action, and its opposite must be a real option.** "Good software lets users do X themselves" is empty if no reasonable team would build the opposite. Only claims a reasonable team might disagree with earn their place.
22. **Examples come from this posting's gap map, never from habit.** A favourite story belongs in a letter only when the posting asks for what it shows.
23. **A way of working is a principle, not the habit of one project.** State the principle, then the project as one example ("That is how I like to work in general. On project X, for example, ...").
24. **One thread through the letter, tied to this company.** Not one CV fact per sentence. Pick the one link between the candidate's work and what this employer needs, and let every paragraph serve it.
25. **An example must show a decision the reader can follow, and why it mattered.** A UI micro-decision or a process detail is weak; for a demanding posting, show a hard problem solved and name the candidate's own contribution and the true reason, briefly.
26. **When the posting matches the CV almost item by item, the letter still does not walk through the CV.** A strong match is already visible in the CV; the letter adds only what the CV cannot show.
27. **CV facts with a stack or setting label are CV voice, even inside a conclusion.** "Web development I know from my project X, a web app in TypeScript" is a CV line in sentence form.
28. **Write like a person writing to a small team, in connected prose.** Neither constructed "AI sentences" nor telegram style: sentences follow from each other the way a letter in a book reads.
29. **Wit comes from one image, not from jokes in every paragraph.** One image tied to the employer's world is charming; more reads as trying too hard.

## Step 0: Resolve the posting

1. If `$ARGUMENTS` is a URL or pasted text: read it per `.claude/skills/job-application-assistant/09-web-research.md`, keep the **full posting text verbatim**, and derive `<company>_<role>` by the **Subfolder naming** rule in `documents/README.md`. Then check `documents/applications/<company>_<role>/` anyway: if it already holds an `application_brief.md` (written by an earlier evaluation) or `company_research/<slug>.json` exists, read them before drafting.
2. Otherwise treat `$ARGUMENTS` as a company name. Match it case-insensitively against folder names in `documents/applications/` and rows in `job_search_tracker.csv`. On exactly one match, use that folder's `job_posting.md` and, if present, `application_brief.md` and `company_research/<slug>.json`. **Always read the brief when it exists**: its requirement-match table seeds the Step 2 gap map, its company facts tell Step 3 where to verify (they are leads, not verified facts), and its interview questions show which gaps the letter should name. Say in the report that the brief was used. On several matches, ask which one. On none, ask for the posting URL or text.
3. Note the posting language. The letter is written in that language.
4. Note the named contact person if the posting states one. Otherwise the salutation is "Sehr geehrte Damen und Herren," (German) or "Dear Hiring Team," (English). Never invent a name.

## Step 1: Load what the reader already knows

Read the CV the user submits with this application: the tailored `cv/main_<company>_<role>.*` if one exists for this posting, otherwise the newest `cv/main_*` file or the CV file named in `CLAUDE.md`. **Then read the newest letters**: list `cover_letters/cover_*.tex`, sort by the tracker row date, and read up to the three most recent in full. They are the user's approved voice. Read the three profile sources named above. Treat every fact in the resume as **already known to the reader**. The profile sources are the pool of *true* facts the letter may draw on, including those the resume does not show.

## Step 2: Build the gap map

Produce a table with one row per posting requirement, duty or stated value. Columns:

| Posting item | Resume coverage | Puzzle piece the letter must add | Source fact |
|---|---|---|---|

`Resume coverage` is one of:
- **shown**: a resume bullet already proves it with evidence. The letter does not restate it. It may use it only as the *premise* of a conclusion the resume cannot draw (what it implies for this role, why it transfers, what it taught).
- **keyword only**: the resume lists it (a tool, a framework, a word) without a story. The letter supplies the story: how it is used, what it produced, what it says about the way the candidate works.
- **absent**: the resume does not cover it. The letter either supplies a true fact from the profile sources that covers it, or names the gap honestly with the transfer path or learning plan, or stays silent. A gap is never papered over with the posting's vocabulary.

Then add rows for what the posting is really asking beneath its bullet list. Typical questions a resume raises for a given role, each needing an answer in the letter:
- "Why does this background fit a role in a different setting?" (one industry to another, research to product, one tool landscape to another)
- "Why this seniority with these years?" Answer with scope, not years.
- "Why this company?" Only verified facts (Step 3), tied to what the candidate would do or change there.
- "How does this person actually work?" One concrete description of a working method, not an adjective. When AI tooling is relevant, name the tool explicitly in one clause attached to the example.

Keep the table. It is reported in Step 6 and it is the test every paragraph must pass.

## Step 3: Verify company facts yourself

Any company-specific statement (products, partnerships, acquisitions, figures, strategy) is verified in this run via `WebFetch`/`WebSearch` against sources you locate independently, never via URLs inside the posting text. An existing `company_research/<slug>.json` or `application_brief.md` tells you where to look; it does not vouch for a fact. Unverifiable facts are rephrased generically or dropped. Record what you verified and the source URLs for the report.

## Step 4: Draft

Write `cover_letters/cover_<company>_<role>.tex` using the template in `.claude/skills/job-application-assistant/06-cover-letter-templates.md` (or the active custom template registered via `/add-template`). If a letter for the same company and role already exists for a still-open application, ask before overwriting it.

**Content rules**
- **Short and sharp means few ideas, not clipped sentences.** 180 to 230 words of body text, four paragraphs, each one idea, each following from the one before. Sentences in natural language, never a colon followed by a list of three. No bullet list: the resume is the list, the letter is the argument. If a draft runs over 230 words, drop an idea, never squeeze the layout.
- **Tone reference: the newest approved letter** in `cover_letters/`. Reproduce its flow, not its sentences. Without one, use this flow: a personal thought about the work, one experience, the wish drawn from it, the next step named plainly, what the candidate wants to do *there*.
- **The company paragraph is in the candidate's own words** (lesson 6). Verified company facts (Step 3) inform the paragraph and the interview; at most one of them appears in the letter, and only when it carries the argument.
- Every paragraph must map to one or more "keyword only" / "absent" rows or to one of the open questions in Step 2. A paragraph that only restates "shown" rows is cut.
- The **CV-repetition test** on every sentence: if the sentence's information is already a resume bullet, replace it with the conclusion that bullet supports for this posting, or delete it.
- One honest paragraph where the fit is incomplete, phrased as transfer plus plan, never as apology (lessons 3 and 4).
- **Never sell above value.** When the candidate's setting differs from the posting's, name the difference in plain words and claim only what truthfully transfers. A different setting is a difference, not a disguised match, and saying so costs nothing.
- Closing: one sentence. "Ich freue mich darauf, Sie persönlich kennenzulernen." or the English equivalent.
- Never mention salary. Never state a start date or availability unless the user asks for it: that is interview material.

## Step 5: Compile and verify

Compile with the command from `06-cover-letter-templates.md` (stock template: `cd cover_letters && xelatex -interaction=nonstopmode cover_<company>_<role>.tex`), then delete the intermediate files. Verify and report as a pass/fail checklist:

- [ ] Compiled, **exactly 1 page**, signature block on the page
- [ ] PDF read via the Read tool; layout matches the template and the newest approved letter
- [ ] Text layer extracts cleanly (`python3 tools/verify_pdf.py`), email and phone present as literal text
- [ ] Word count 180 to 230, four paragraphs, no colon-plus-list sentences, company paragraph free of posting/website phrasing
- [ ] No em-dashes, no cliches, no filler
- [ ] Every sentence passed the sentence test against **Lessons from rejected drafts**
- [ ] Every paragraph passes the puzzle test: it adds something the resume does not say
- [ ] No sentence fails the CV-repetition test
- [ ] Every company-specific claim verified in Step 3, source recorded
- [ ] Every fact grounded in the profile sources; stretch sentences listed for the user
- [ ] No overselling: setting differences named plainly, transfer claims limited to what truthfully transfers
- [ ] Language, register (du/Sie), date format, salutation and closing match the posting

## Step 6: Record and report

1. Record the application exactly as `/apply` Step 6b (`.claude/commands/apply.md`) specifies: tracker row (`cv_file` = the CV submitted, `cover_letter_file` = the new `cover_<company>_<role>.tex`, status `drafted` on a new row, `redrafted` note on an open row), posting archived to `documents/applications/<company>_<role>/job_posting.md` only if absent, `job_scraper/seen_jobs.json` untouched.
2. Report, in this order:
   - the files written and the tracker row touched
   - the gap map from Step 2, with a final column stating which paragraph covers each "keyword only" / "absent" row
   - the verified company facts with their sources
   - the stretch sentences, each with keep / soften / drop
   - the verification checklist
3. If the user rejected sentences during this run, confirm in the report that each one was appended to **Lessons from rejected drafts** with its rule, and that any new profile fact went into `01-candidate-profile.md`.
4. Next steps: `/outcome <company>` once sent, `/interview` once invited.
