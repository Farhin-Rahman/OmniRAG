"""Hand-labelled campaigns for evaluating the moderation pipeline.

Each case carries the action a trained human reviewer *should* reach, per
the same policy the risk-assessment prompt describes (clear legitimate
purpose, target amount proportional to it, no financial-scheme / urgency /
untraceable-payment red flags).

Two `source`s:
  - "synthetic" — written for this project. A policy-based set, not live
    production data; a real deployment would evaluate against a historical
    set of campaigns with recorded human decisions. That's the honest
    limitation of a from-scratch project.
  - "public-live" — real public crowdfunding campaigns (title,
    description, goal), all of which had already passed their host
    platform's own vetting, so the expected action is APPROVE. These check the pipeline against real
    prose and real fundraising patterns, and one (the anime venture) is a
    deliberate near-boundary case.

`expected_action` is one of APPROVE / REJECT / ESCALATE.
`expect_hard_block` is whether a deterministic rule (not the LLM) should
stop it — these cases exist to confirm the cost-aware skip works (a hard
block must never spend an LLM call).

The ambiguous ESCALATE cases are deliberately the hardest: a reasonable
reviewer could disagree at the REJECT/ESCALATE boundary, and the LLM will
too. The metric that matters most is "missed risk" (something that should
not have been APPROVEd was), reported separately by the runner.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class GoldenCase:
    id: str
    title: str
    description: str
    target_amount: float
    expected_action: str
    expect_hard_block: bool
    note: str
    source: str = "synthetic"


GOLDEN_SET: list[GoldenCase] = [
    # --- Clearly legitimate: specific purpose, proportional amount ---------
    GoldenCase(
        id="clean-medical-surgery",
        title="Help Amir get his heart valve surgery",
        description=(
            "Amir is 9 and needs a heart valve replacement at St. Mary's "
            "Children's Hospital in March. His parents' insurance covers the "
            "procedure but not the $14,000 in follow-up cardiac rehab and "
            "travel for the three months after. We are his aunt and uncle and "
            "will post hospital receipts as costs come in."
        ),
        target_amount=14000,
        expected_action="APPROVE",
        expect_hard_block=False,
        note="Named hospital, itemised use, proportional amount, verifiable.",
    ),
    GoldenCase(
        id="clean-education-bootcamp",
        title="Coding bootcamp scholarships for 20 refugee youth",
        description=(
            "Our nonprofit runs a 12-week web development course for resettled "
            "refugee teenagers in Clarkston. This raises tuition for 20 "
            "students at $400 each, covering instructors, laptops on loan, and "
            "transit passes. We have run three cohorts since 2022; outcomes and "
            "budget are on our site."
        ),
        target_amount=8000,
        expected_action="APPROVE",
        expect_hard_block=False,
        note="Established org, clear per-unit budget, track record.",
    ),
    GoldenCase(
        id="clean-disaster-rebuild",
        title="Rebuild the Vargas family's home after the June floods",
        description=(
            "The Vargas family lost their ground floor to the river flooding in "
            "June. The county has declared the area a disaster zone. Funds go to "
            "drywall, flooring, electrical inspection, and a replacement water "
            "heater. Contractor quote attached; the family will share progress "
            "photos every two weeks."
        ),
        target_amount=25000,
        expected_action="APPROVE",
        expect_hard_block=False,
        note="Documented disaster, contractor quote, staged reporting.",
    ),
    GoldenCase(
        id="clean-community-garden",
        title="Tools and raised beds for the Elm Street community garden",
        description=(
            "Neighbours on Elm Street are converting a vacant lot the city "
            "leased to us into a vegetable garden. This covers eight raised "
            "beds, soil, a hose reel, and hand tools. Anything left over buys "
            "seeds for next spring. Receipts posted to the garden's public "
            "Facebook group."
        ),
        target_amount=1200,
        expected_action="APPROVE",
        expect_hard_block=False,
        note="Small, concrete, low-risk civic project.",
    ),
    GoldenCase(
        id="clean-funeral-costs",
        title="Funeral and burial costs for Mrs. Okafor",
        description=(
            "Mrs. Okafor passed away last week after a long illness. Her "
            "children are covering the funeral home service, burial plot, and "
            "headstone. The funeral home's itemised estimate is $6,200. Any "
            "surplus goes to her outstanding hospital bill."
        ),
        target_amount=6200,
        expected_action="APPROVE",
        expect_hard_block=False,
        note="Common legitimate use, itemised, modest.",
    ),
    # --- Hard rule blocks: banned phrases, LLM must be skipped ------------
    GoldenCase(
        id="block-guaranteed-return",
        title="Community investment pool - join now",
        description=(
            "Pool your savings with our group fund. We promise a guaranteed "
            "return of 8% every month paid from trading profits. The more "
            "members join, the higher everyone's payout. Withdraw any time "
            "after the first 90 days."
        ),
        target_amount=50000,
        expected_action="REJECT",
        expect_hard_block=True,
        note="Contains 'guaranteed return' + classic Ponzi structure.",
    ),
    GoldenCase(
        id="block-double-your-money",
        title="Help me grow the fund",
        description=(
            "One-time opportunity to double your money in 30 days through my "
            "forex system. I have done this for family for years and now "
            "opening it up. Send what you can and watch it grow."
        ),
        target_amount=20000,
        expected_action="REJECT",
        expect_hard_block=True,
        note="Contains 'double your money'.",
    ),
    GoldenCase(
        id="block-wire-directly",
        title="Urgent family emergency abroad",
        description=(
            "I am stranded overseas and the platform's payout is too slow. "
            "Please wire me directly using the bank details I will send by "
            "message. I will pay everyone back once I am home. Cannot explain "
            "more here, it is sensitive."
        ),
        target_amount=4000,
        expected_action="REJECT",
        expect_hard_block=True,
        note="Contains 'wire me directly' + off-platform payment ask.",
    ),
    # --- LLM-judgment rejects: no banned phrase, still clearly bad -------
    GoldenCase(
        id="scam-vague-urgent",
        title="PLEASE HELP URGENT NEED NOW",
        description=(
            "i need money urgent please god bless you send whatever you can "
            "right now it is very urgent situation i cannot say why just please "
            "help fast thank you"
        ),
        target_amount=3000,
        expected_action="REJECT",
        expect_hard_block=False,
        note="No stated purpose, pure urgency pressure, no verifiability.",
    ),
    GoldenCase(
        id="scam-gift-card-charity",
        title="Emergency relief fund - disaster victims",
        description=(
            "We are collecting for victims of the recent earthquake. The "
            "fastest way to help is to buy store gift cards and send us the "
            "codes by message - this avoids bank fees and gets aid there "
            "immediately. Every code goes straight to a family in need."
        ),
        target_amount=100000,
        expected_action="REJECT",
        expect_hard_block=False,
        note="Gift-card-code collection is a well-known fraud pattern.",
    ),
    GoldenCase(
        id="scam-amount-mismatch",
        title="Help me buy lunch this week",
        description=(
            "Money is tight this month and I would appreciate help covering "
            "groceries and lunches until my next paycheck in two weeks. Thank "
            "you to anyone who can spare a little."
        ),
        target_amount=750000,
        expected_action="REJECT",
        expect_hard_block=False,
        note="Target wildly disproportionate to the stated modest purpose.",
    ),
    GoldenCase(
        id="scam-weekly-payout-fund",
        title="Join the profit-sharing circle",
        description=(
            "Contribute to our members' fund and receive weekly payouts from "
            "our e-commerce arbitrage business. Limited spots this quarter. "
            "Existing members are seeing steady growth. Serious contributors "
            "only, message for the deck."
        ),
        target_amount=40000,
        expected_action="REJECT",
        expect_hard_block=False,
        note="Investment-scheme language, no banned phrase verbatim.",
    ),
    # --- Genuinely ambiguous: a human should look --------------------------
    GoldenCase(
        id="ambiguous-cancer-unspecified",
        title="Support my cancer treatment",
        description=(
            "I was recently diagnosed with cancer and the treatment is going to "
            "be expensive. Anything helps. Thank you so much for your kindness "
            "during this hard time."
        ),
        target_amount=40000,
        expected_action="ESCALATE",
        expect_hard_block=False,
        note="Plausible and sympathetic but zero specifics to verify.",
    ),
    GoldenCase(
        id="ambiguous-family-support-thin",
        title="Help support my family",
        description=(
            "Times have been really difficult for us this year with job loss "
            "and rising costs. I am raising money to keep us going and cover "
            "some debts we have fallen behind on. I appreciate any support."
        ),
        target_amount=75000,
        expected_action="ESCALATE",
        expect_hard_block=False,
        note="Large amount, vague use of funds, hard to assess proportionality.",
    ),
    GoldenCase(
        id="ambiguous-startup-vague",
        title="Fund my small business idea",
        description=(
            "I want to start a business in my community and need capital to get "
            "going. The plan is to sell products people need at fair prices. "
            "With enough backing I can launch within a few months and start "
            "hiring locally."
        ),
        target_amount=30000,
        expected_action="ESCALATE",
        expect_hard_block=False,
        note="No concrete deliverables; not obviously fraud, not approvable as-is.",
    ),
    GoldenCase(
        id="ambiguous-service-animal",
        title="Service dog for my PTSD",
        description=(
            "After my deployment I have been diagnosed with PTSD and a trained "
            "service dog would help me manage day to day. Trained service "
            "animals cost around $18,000 including the two-week handler "
            "program. I can provide a letter from my VA counsellor."
        ),
        target_amount=18000,
        expected_action="ESCALATE",
        expect_hard_block=False,
        note="Realistic cost and offer of documentation, but needs verification.",
    ),
    # --- Non-English: exercises translate -> rules/risk -------------------
    GoldenCase(
        id="clean-spanish-medical",
        title="Ayuda para la operacion de rodilla de mi madre",
        description=(
            "Mi madre necesita una operacion de reemplazo de rodilla en el "
            "Hospital General el proximo mes. El seguro cubre la cirugia pero "
            "no los 3.000 dolares de fisioterapia posterior ni el transporte. "
            "Publicare los recibos del hospital conforme lleguen."
        ),
        target_amount=3500,
        expected_action="APPROVE",
        expect_hard_block=False,
        note="Legitimate medical request written in Spanish; should translate then approve.",
    ),
    GoldenCase(
        id="suspicious-french-investment",
        title="Rejoignez notre fonds de placement collectif",
        description=(
            "Placez votre argent dans notre fonds et recevez un rendement "
            "mensuel fixe garanti grace a nos placements. Plus il y a de "
            "participants, plus les gains augmentent pour tout le monde. "
            "Retrait possible apres quatre-vingt-dix jours."
        ),
        target_amount=60000,
        expected_action="REJECT",
        expect_hard_block=False,
        note=(
            "French investment-scheme pitch. After translation the wording may "
            "not match a banned phrase verbatim, so this tests the LLM catching "
            "it post-translation rather than the rule layer."
        ),
    ),
    # --- Real public crowdfunding campaigns (Sept 2026). All had passed
    #     their host platform's own vetting, so expected_action is APPROVE.
    #     Title / description / goal; descriptions condensed. ---------------
    GoldenCase(
        id="live-ihr-gaza-orphans",
        title="Sponsor Gaza Orphans",
        description=(
            "International Humanitarian Relief (IHR), a registered 501(c)(3) "
            "founded in 2017 and based in Hickory Hills, Illinois, is sponsoring "
            "1,000 orphans in Gaza for one year. $50 sponsors an orphan for one "
            "month, covering nourishment, education, and psychological support. "
            "Over the past two years IHR has sponsored more than 1,000 orphans "
            "in Gaza; campaign updates document the deliveries and the children "
            "reached."
        ),
        target_amount=1_100_000,
        expected_action="APPROVE",
        expect_hard_block=False,
        note=(
            "Established 501(c)(3), itemised use, documented track record — a "
            "reviewer approves. The pipeline tends to ESCALATE it, noticing the "
            "$1.1M goal is ~2x the '1,000 orphans x $50/month' math; that's an "
            "incomplete inference (the goal is cumulative over 2+ years) but "
            "flagging it for a human rather than rejecting is the safe failure."
        ),
        source="public-live",
    ),
    GoldenCase(
        id="live-noor-orphan-girls",
        title="Help 150 Orphan Girls Keep Their Childhood",
        description=(
            "Losing her family shouldn't mean losing her childhood. This "
            "campaign by The Noor Project raises funds to keep orphan girls in "
            "Pakistan safe, cared for, and in school. A $50 donation helps "
            "support one girl. Zakat-verified."
        ),
        target_amount=5000,
        expected_action="ESCALATE",
        expect_hard_block=False,
        note=(
            "Real campaign, but the copy is internally inconsistent: '$50 helps "
            "support one girl' x 150 girls = $7,500, yet the goal is $5,000. A "
            "reviewer should ask about that before approving — ESCALATE. (The "
            "eval's own risk assessment caught this discrepancy; the label was "
            "originally APPROVE and was corrected.)"
        ),
        source="public-live",
    ),
    GoldenCase(
        id="live-sapa-sudan-newborns",
        title="Urgent: Save Newborn Lives in Sudan",
        description=(
            "In Sudan, mothers give birth in tents and overcrowded camps "
            "without medicine or trained care, and prematurity, hypothermia, "
            "and infection are ending newborn lives. The Sudanese American "
            "Physicians Association (SAPA) is establishing ICU and neonatal "
            "units, deploying mobile clinics, and delivering infant warmers and "
            "newborn survival kits while training midwives and rehabilitating "
            "maternity wards. Itemised impact: $25 supplies cord-care gel and "
            "syringes, $1,000 delivers a full newborn care kit. SAPA holds a "
            "4-star Charity Navigator rating and a Candid Platinum Seal."
        ),
        target_amount=30000,
        expected_action="APPROVE",
        expect_hard_block=False,
        note="Detailed, itemised, independently rated charity.",
        source="public-live",
    ),
    GoldenCase(
        id="live-iltizam-wells",
        title="The Prophet Said: Water Is The Best Charity. Help Us Build 150 Wells!",
        description=(
            "Iltizam Relief Society, active for 10 years, is raising funds to "
            "build 150 water wells over three months in rural communities in "
            "Pakistan, Sri Lanka, and Nepal, where falling water tables, "
            "contamination, and saltwater intrusion have made water unsafe. Each "
            "well serves 50-200 people daily. The organisation has already built "
            "over 500 wells with named partner organisations in each country; "
            "recent updates document 5 new wells completed in Sunsari, Nepal "
            "serving 35 families."
        ),
        target_amount=50000,
        expected_action="APPROVE",
        expect_hard_block=False,
        note="Long detailed case, named partners, 10-year track record.",
        source="public-live",
    ),
    GoldenCase(
        id="live-arzi-muslim-anime",
        title="Help Us Make History: The World's First Muslim Anime Movie",
        description=(
            "An individual fundraiser by Zaurbek Tsoroev to produce 'Arzi's "
            "Dream', billed as the first halal Muslim anime, and to build a "
            "Muslim media company. The campaign cites 700,000+ views on its "
            "first trailer and 8,000,000+ on its episode-1 announcement, a "
            "creative team including a Cannes-award-winning director, and "
            "addresses the permissibility of animated faces with scholarly "
            "fatwas. The organiser is a former UCLA graduate and senior "
            "software engineer who founded an AI company; a previous campaign "
            "for the project raised $22,006. Funds go to producing three "
            "episodes and a feature film, voice acting, halal music, and the "
            "animation pipeline."
        ),
        target_amount=100000,
        expected_action="APPROVE",
        expect_hard_block=False,
        note=(
            "The structurally unusual one: an individual raising $100K for a "
            "creative venture, not an NGO doing relief. Legit and vetted "
            "(traction, named team, a prior successful campaign), but an "
            "ESCALATE here — flag the amount / creator / deliverables for a "
            "human — is a correct call, not a failure."
        ),
        source="public-live",
    ),
]
