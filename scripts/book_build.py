r"""
Typeset the statistics mini-book PDF from the generated figures + stats.json.

Every technical term used anywhere in the project gets its own callout: a plain
definition plus a worked example from the author's data. Charts are the real
figures produced by book_charts.py. Output: reports/Trading_by_the_Numbers.pdf

Run:  .\.venv\Scripts\python.exe scripts\book_build.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import PROJECT_ROOT  # noqa: E402

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    BaseDocTemplate, Frame, Image, KeepTogether, NextPageTemplate, PageBreak,
    PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.lib.utils import ImageReader  # noqa: E402

FIGS = PROJECT_ROOT / "reports" / "book_figs"
OUT = PROJECT_ROOT / "reports" / "Trading_by_the_Numbers.pdf"
S = json.loads((FIGS / "stats.json").read_text(encoding="utf-8"))

INK = colors.HexColor("#1c1c1c")
MUTED = colors.HexColor("#5a5a5a")
ACCENT = colors.HexColor("#0d5fa8")
TERM_BG = colors.HexColor("#eef4fb")
TERM_EDGE = colors.HexColor("#b9d2ea")
WARN_BG = colors.HexColor("#fdf2e3")
WARN_EDGE = colors.HexColor("#eccf9a")
GREEN = colors.HexColor("#157a44")
RED = colors.HexColor("#b3372f")

st_body = ParagraphStyle("body", fontName="Helvetica", fontSize=10.5, leading=15.5,
                         textColor=INK, spaceAfter=7, alignment=0)
st_h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=19, leading=23,
                       textColor=INK, spaceBefore=2, spaceAfter=4)
st_kick = ParagraphStyle("kick", fontName="Helvetica-Bold", fontSize=9.5, leading=12,
                         textColor=ACCENT, spaceAfter=2)
st_h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12.5, leading=16,
                       textColor=INK, spaceBefore=10, spaceAfter=4)
st_cap = ParagraphStyle("cap", fontName="Helvetica-Oblique", fontSize=9, leading=12.5,
                        textColor=MUTED, spaceBefore=3, spaceAfter=10)
st_term_name = ParagraphStyle("tname", fontName="Helvetica-Bold", fontSize=10.5,
                              leading=14, textColor=ACCENT)
st_term_body = ParagraphStyle("tbody", parent=st_body, fontSize=9.8, leading=14, spaceAfter=0)
st_gloss = ParagraphStyle("gloss", parent=st_body, fontSize=9.6, leading=13.5, spaceAfter=4)
st_toc = ParagraphStyle("toc", parent=st_body, fontSize=11, leading=19)
st_title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=27, leading=33,
                          textColor=INK, alignment=1)
st_sub = ParagraphStyle("sub", fontName="Helvetica", fontSize=12.5, leading=18,
                        textColor=MUTED, alignment=1, spaceBefore=10)
st_author = ParagraphStyle("author", fontName="Helvetica-Bold", fontSize=13, leading=17,
                           textColor=INK, alignment=1, spaceBefore=6)
st_contact = ParagraphStyle("contact", fontName="Helvetica", fontSize=10.5, leading=15,
                            textColor=ACCENT, alignment=1)

AUTHOR = "Nitzan Ben Dror"
CONTACT = "[redacted-phone]  &nbsp;·&nbsp;  [redacted-email]"

story = []
_chapno = 0


def P(text):
    story.append(Paragraph(text, st_body))


def H2(text):
    story.append(Paragraph(text, st_h2))


def CH(title, kicker):
    global _chapno
    _chapno += 1
    story.append(PageBreak())
    story.append(Paragraph(f"CHAPTER {_chapno}", st_kick))
    story.append(Paragraph(title, st_h1))
    story.append(Paragraph(kicker, ParagraphStyle("k2", parent=st_cap, fontSize=10.5,
                                                  leading=14.5, spaceAfter=12)))


def _box(rows, bg, edge):
    t = Table(rows, colWidths=[16.6 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 0.75, edge),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
    ]))
    story.append(Spacer(1, 3))
    story.append(KeepTogether(t))
    story.append(Spacer(1, 7))


def TERM(name, definition, example=None):
    rows = [[Paragraph(f"TERM &nbsp;·&nbsp; {name}", st_term_name)],
            [Paragraph(definition, st_term_body)]]
    if example:
        rows.append([Paragraph(f"<b>From my data:</b> {example}", st_term_body)])
    _box(rows, TERM_BG, TERM_EDGE)


def WARN(title, text):
    _box([[Paragraph(title, ParagraphStyle("w", parent=st_term_name,
                                           textColor=colors.HexColor("#9a6a12")))],
          [Paragraph(text, st_term_body)]], WARN_BG, WARN_EDGE)


def FIG(fname, caption, width=16.2):
    img_path = str(FIGS / fname)
    iw, ih = ImageReader(img_path).getSize()
    w = width * cm
    story.append(KeepTogether([Spacer(1, 4), Image(img_path, width=w, height=w * ih / iw),
                               Paragraph(caption, st_cap)]))


# ============================ TITLE PAGE =====================================
story.append(Spacer(1, 3.4 * cm))
story.append(Paragraph("Trading by the Numbers", st_title))
story.append(Paragraph("An independent quantitative-research project on Polymarket's "
                       "short-term crypto markets — and a plain-language guide to the "
                       "statistics behind it.", st_sub))
story.append(Spacer(1, 1.0 * cm))
story.append(Paragraph(AUTHOR, st_author))
story.append(Paragraph(CONTACT, st_contact))
story.append(Spacer(1, 1.0 * cm))
ds = S["dataset"]
settled_phrase = ("all of them" if ds["settled"] == ds["buckets"]
                  else f"{ds['settled']:,} of them")
story.append(Paragraph(
    f"Every concept explained in plain language, and every example computed from my own "
    f"dataset: <b>{ds['buckets']:,} recorded markets</b> ({ds['by_window']['5']:,} five-minute, "
    f"{ds['by_window']['15']:,} fifteen-minute, {ds['by_window']['60']} sixty-minute), "
    f"{settled_phrase} settled with verified real outcomes, captured tick-by-tick "
    f"over four days of live crypto Up/Down trading.", st_sub))
story.append(Spacer(1, 1.6 * cm))
story.append(Paragraph("All trading discussed here is simulated. No real money was used.", st_sub))

# ============================ ABOUT THIS PROJECT =============================
story.append(PageBreak())
story.append(Paragraph("About this project", st_h1))
story.append(Paragraph("What it is, what I built, and what it demonstrates.", st_cap))
P("This is my independent quantitative-research project. Working solo, I designed and built "
  "an end-to-end system to answer one question honestly: can a simple, rule-based strategy "
  "make money trading Polymarket's short-term crypto Up/Down markets? Arriving at the answer "
  "<b>rigorously</b> — rather than fooling myself — is the entire point, and the discipline "
  "behind it is what this document is meant to show.")
H2("What I built (from scratch, simulation-only)")
for b in [
    "<b>A tick-level market-data recorder</b> — captures both order books of every live market "
    "over the exchange WebSocket, with millisecond timestamps and the full trade tape: ~16 GB "
    "across 3,300+ markets, streaming-compressed on disk.",
    "<b>An exact-fill backtesting engine</b> — reconstructs each order book tick-by-tick and "
    "simulates every trade by walking the real price ladder for a real dollar size, settling on "
    "the exchange's verified official outcomes (fetched, never guessed).",
    "<b>A statistical validation toolkit</b> — block-bootstrap significance testing, "
    "out-of-sample time splits, and latency + slippage modelling, so no result is trusted until "
    "it survives them.",
    "<b>A full-stack research dashboard</b> — Python / FastAPI backend and a React / TypeScript "
    "frontend to record, resolve, replay and visualise, plus a live paper-trading bot that "
    "trades the validated rule with a demo wallet.",
]:
    story.append(Paragraph(f"•&nbsp; {b}", ParagraphStyle("bul", parent=st_body, leftIndent=10,
                                                          fontSize=10, leading=14.5, spaceAfter=6)))
H2("What it demonstrates")
P("I found an early, exciting result — a first-minute \"momentum edge\" that looked worth real "
  "money — stress-tested it, and proved to myself with data that it was statistical noise. I "
  "then found a smaller but genuine, test-surviving edge on the hourly markets. Being willing "
  "and able to <b>kill my own best idea with evidence</b> is, I think, the most valuable thing "
  "in here.")
_box([[Paragraph("Technical skills demonstrated", st_term_name)],
      [Paragraph("Python data engineering &nbsp;·&nbsp; statistical inference (bootstrap, "
                 "hypothesis testing, calibration, out-of-sample validation) &nbsp;·&nbsp; market "
                 "microstructure &amp; execution modelling &nbsp;·&nbsp; full-stack web "
                 "(FastAPI, React / TypeScript) &nbsp;·&nbsp; building reproducible, honest "
                 "research pipelines &nbsp;·&nbsp; clear technical communication.", st_term_body)]],
     TERM_BG, TERM_EDGE)

# ============================ HOW TO READ ====================================
story.append(PageBreak())
story.append(Paragraph("How to read this book", st_h1))
P("This is the companion book to my trading research project. You do not need any math "
  "background: every term is introduced in a blue <b>TERM</b> box the first time it matters, "
  "with a plain-language definition and a real example from my own data. Orange boxes flag "
  "the classic mistakes — each one is a mistake I actually made and caught during the project, "
  "so they are not hypothetical.")
P("The story told across the chapters is the true story of the project: I had an idea, built "
  "honest measuring instruments, discovered my first exciting result was an illusion, learned "
  "the statistics that expose such illusions, and ended up with one strategy that survived "
  "every test I could throw at it — and a demo-money bot now trading it live.")
H2("Contents")
toc = [
    "1 &nbsp; The playground — prediction markets",
    "2 &nbsp; Reading a bet — probability, edge and expected value",
    "3 &nbsp; The marketplace — order books, spreads and slippage",
    "4 &nbsp; Is the market beatable? — calibration and efficiency",
    "5 &nbsp; The noise trap — why small samples lie",
    "6 &nbsp; Proving it isn't luck — p-values and the bootstrap",
    "7 &nbsp; Not fooling yourself — overfitting, splits and regimes",
    "8 &nbsp; The two strategies — fading vs riding the move",
    "9 &nbsp; Execution reality — latency, stop-losses and drawdowns",
    "10 &nbsp; Where I stand — the road to a live bot",
    "Glossary — every term on one page",
]
for line in toc:
    story.append(Paragraph(line, st_toc))

# ============================ CHAPTER 1 ======================================
CH("The playground — prediction markets",
   "What I am trading, and the single most important idea in this entire book: "
   "a price is a probability.")
P("A <b>prediction market</b> lets people bet on a yes/no question by trading shares. My "
  "playground is Polymarket's crypto <b>Up/Down markets</b>: every 5, 15 and 60 minutes, a new "
  "market opens asking, for example, \"Will Bitcoin's price be higher at the end of this hour "
  "than at the start?\" There are only two outcomes, Up and Down, and you can buy shares of "
  "either side at any moment while the market runs.")
TERM("Binary market",
     "A market with exactly two mutually exclusive outcomes. One share of the winning side pays "
     "exactly $1 when the market ends; a share of the losing side pays $0. Nothing in between.",
     "Every market in my dataset is binary: Up wins or Down wins, decided by the actual "
     "Bitcoin/Ethereum/Solana/XRP price move over the market's window.")
TERM("Resolution (settlement)",
     "The moment the outcome becomes official and shares pay out. Until resolution, prices can "
     "wobble freely; at resolution every share is worth exactly $1 or $0.",
     "I fetch each market's official resolved outcome from the exchange after it closes — "
     "never guessing from the last price. Chapter 5 shows how guessing corrupted an early analysis.")
P("Here is the key insight. Suppose Up shares trade at $0.72. If you think Up's true chance is "
  "higher than 72%, buying is attractive; if you think it is lower, selling is. The market price "
  "settles wherever buyers and sellers balance — which is the crowd's collective estimate of the "
  "probability itself.")
TERM("Price = probability",
     "In a binary market, the price of a share (between $0 and $1) IS the market's estimated "
     "probability of that outcome. A price of 0.72 means the crowd collectively says 72%.",
     "This is why the whole project is really a statistics project: to profit, you must find "
     "moments where the crowd's probability is measurably wrong.")
FIG("f1_price_path.png",
    f"Figure 1 — a real {S['path']['asset']} 60-minute market from my recordings, every tick. "
    "The price starts near 0.55 (a coin flip with a slight lean), climbs as Bitcoin rises, "
    "wobbles, and locks onto $1.00 as the outcome becomes certain. Reading the y-axis as "
    "\"probability of Up\" turns this chart into a story: the market growing more and more "
    "confident, with moments of doubt along the way.")
H2("My dataset")
P(f"Everything in this book is computed from data I recorded myself: <b>{ds['buckets']:,} "
  f"markets</b> captured tick-by-tick (every order book change and every trade, with millisecond "
  f"timestamps, for both the Up and Down side), {settled_phrase} carrying a verified "
  "official outcome. That level of detail matters because it lets me simulate trading with the "
  "exact prices and quantities that were really available — not optimistic approximations.")

# ============================ CHAPTER 2 ======================================
CH("Reading a bet — probability, edge and expected value",
   "The arithmetic of a single bet: what you pay, what you can win, and the one number "
   "that decides everything.")
P("Buy one Up share at $0.72. Two futures exist: Up wins and the share pays $1.00 (profit "
  "$0.28), or Down wins and it pays $0 (loss $0.72). Whether this was a good bet depends on "
  "one comparison only: how OFTEN does Up win from this situation, versus the 72% the price "
  "implied?")
TERM("Expected value (EV)",
     "The average profit per bet if you could repeat the same bet thousands of times: "
     "EV = (probability of winning x win amount) - (probability of losing x loss amount). "
     "A positive EV bet makes money in the long run even though any single bet can lose.",
     "Buying at $0.72 when the true win rate is 78%: EV = 0.78 x $0.28 - 0.22 x $0.72 = "
     "+$0.060 per $1 share — six cents of expected profit per bet.")
TERM("Break-even hit rate",
     "The win rate at which a bet exactly pays for itself. For a binary share it is simply the "
     "price you paid: buy at $0.72 and you break even winning exactly 72% of the time.",
     "This makes analysis wonderfully simple: a strategy profits exactly when its actual win "
     "rate beats the average price it paid. Everything I test reduces to that comparison.")
TERM("Edge",
     "How much better you do than break-even: edge = actual win rate - average price paid. "
     "Measured in percentage points (pp). Positive edge = profit; zero = the market priced it "
     "perfectly; negative = you are the one being profited from.",
     "My lead strategy wins 82.3% of its bets while paying an average of 72.0 cents — an edge "
     "of about +10pp. Most strategies I tested had an edge near zero or below.")
P("Edge is the single number this entire project hunts for. But note what it is NOT: it is not "
  "about winning often. A bet can win rarely and still be brilliant, or win nearly always and "
  "still be terrible, because the price already contains the frequency. The chart below makes "
  "this concrete with a strategy from early in the project that bought cheap shares around "
  "$0.26.")
FIG("f3_payout.png",
    f"Figure 2 — the payout asymmetry of a cheap share. Buying at ${S['payout']['price']:.2f}, "
    f"a win pays +{S['payout']['win_pay']:.2f} per $1 staked while a loss costs only -1. So a "
    f"win rate of just {S['payout']['hit']:.1%} — which sounds dreadful, but sits slightly "
    f"ABOVE the {S['payout']['price']:.1%} break-even — still nets a positive EV of "
    f"{S['payout']['ev']:+.3f} per $1. The lesson: never judge a strategy by its win rate "
    "alone; judge win rate AGAINST price.")
TERM("Hit rate",
     "The percentage of bets a strategy actually wins. Meaningful only when compared to the "
     "break-even rate (the average price paid).",
     "A strategy of mine that wins 82% of the time sounds great and IS great — but only because "
     "it pays 72 cents, not 82, for those wins. Another won just 28% and was also (slightly) "
     "profitable, because it paid 26.")
TERM("Percentage point (pp)",
     "The unit for differences between two percentages. If hit rate is 82.3% and break-even is "
     "72.0%, the edge is 10.3 percentage points (not \"10.3 percent\").",
     "I write edges as +10pp rather than +10% to avoid ambiguity — +10% of 72 would be 7.2, "
     "which is a different number.")

# ============================ CHAPTER 3 ======================================
CH("The marketplace — order books, spreads and slippage",
   "Prices do not float in space. Every trade happens against a queue of real orders, "
   "and the difference between theory and reality lives in that queue.")
P("At any moment, a market has people waiting to buy at various prices and people waiting to "
  "sell at various prices. That standing queue is the <b>order book</b>. Understanding it is "
  "what separates a paper edge from money, because you can only ever trade against what is "
  "actually waiting there.")
FIG("f2_orderbook.png",
    f"Figure 3 — the real order book of the market from Figure 1, mid-flight. Green bars: "
    f"buyers waiting (bids), topping out at ${S['book']['best_bid']:.2f}. Red bars: sellers "
    f"waiting (asks), starting at ${S['book']['best_ask']:.2f}. The gap between them is the "
    f"spread ({S['book']['spread']:.3f} here). To buy instantly you pay the ask; to sell "
    "instantly you accept the bid.")
TERM("Bid and ask",
     "The bid is the highest price any buyer is currently offering; the ask is the lowest price "
     "any seller will accept. Buying instantly costs the ask; selling instantly earns the bid.",
     f"In Figure 3 the best bid is {S['book']['best_bid']:.2f} with about "
     f"{S['book']['bid_size']:.0f} shares waiting, and the best ask is "
     f"{S['book']['best_ask']:.2f}.")
TERM("Spread",
     "Ask minus bid — the cost of an instant round trip. Buy and immediately sell and you lose "
     "exactly the spread. Tight spreads mean an active, competitive market; wide spreads make "
     "many small edges untradeable.",
     "My simulations refuse any entry where the spread exceeds 5 cents, because an edge "
     "smaller than the spread cannot be harvested by crossing it.")
TERM("Mid (midpoint)",
     "The average of bid and ask — the market's fair-value estimate. I use the mid as \"the "
     "probability\" when deciding whether a rule triggers, but I always CHARGE the real ask "
     "when simulating a buy. Confusing these two flatters results.",
     "An early analysis of mine used mid prices for fills and showed phantom profits; recharging "
     "every fill at the ask removed about 2pp of imaginary edge.")
TERM("Depth and liquidity",
     "How many shares are waiting at and near the best prices. Deep books absorb big orders "
     "without moving; shallow books mean even modest orders push the price against you.",
     "My tick recordings store the full ladder, so the simulator knows exactly how many shares "
     "were available at each price at every instant.")
TERM("Slippage (walking the ladder)",
     "When your order is bigger than the best level, it consumes deeper, worse-priced levels. "
     "Your average fill price ends up worse than the quoted touch price.",
     "In a test with a $10 order against a book quoting 0.30 (20 shares) then 0.31, the fill "
     "averaged 0.3039 — 0.4 cents of slippage, which mechanically shaved the measured edge.")
WARN("The mistake I made: trusting quoted prices",
     "Early results looked great partly because I assumed trades filled at the observed price. "
     "Real books are sometimes one-sided, thin, or stale. The fix that made every later result "
     "trustworthy: record BOTH sides' full books tick-by-tick, and simulate every fill by "
     "walking the actual ask ladder for the actual dollar amount. When I did this, one "
     "\"profitable\" idea reversed sign entirely (Chapter 8).")

# ============================ CHAPTER 4 ======================================
CH("Is the market beatable? — calibration and efficiency",
   "The question every strategy secretly asks. My data answers it twice: once with a "
   "brick wall, once with an open door.")
TERM("Calibration",
     "A market is calibrated if things priced at X% really do happen X% of the time. Perfectly "
     "calibrated prices leave zero edge: whatever you buy, you pay exactly its true probability.",
     "Left panel of Figure 4: on 5-minute markets, favorites priced 58.7 win 59.2; priced 91.4 "
     "win 90.8. The market's probabilities are almost perfectly honest.")
TERM("Efficient market",
     "A market where all available information is already reflected in the price, typically "
     "because fast professional traders compete away every mispricing within seconds. In an "
     "efficient market, no simple rule based on the price itself can profit.",
     "The 5-minute markets behave efficiently: across 2,360 recorded markets, every entry rule "
     "I tested — in both directions — earned about zero or lost money after real fills.")
FIG("f4_calibration.png",
    "Figure 4 — the central chart of this book. Each pair of bars asks: when you buy the "
    "leading side at a given price, how often does it actually win (green) versus what you "
    "paid (gray)? Left: 5-minute markets — the bars match almost exactly at every price. That "
    "is calibration; there is nothing to win. Right: 60-minute markets — green exceeds gray at "
    "every single price level. Favorites are systematically UNDERPRICED. That persistent gap "
    "is an edge.")
P("Why would the hourly market misprice what the 5-minute market prices perfectly? My working "
  "explanation is attention: the 5-minute markets turn over constantly and are patrolled by "
  "fast automated traders, while the slower hourly markets get less algorithmic scrutiny, "
  "leaving room for a systematic bias — favorites not being trusted quite as much as they "
  "deserve — to survive.")
TERM("Favorite-longshot bias",
     "A pattern documented for decades in betting markets: bettors systematically overpay for "
     "longshots (low-probability outcomes) and underpay for favorites. It is one of the "
     "best-replicated inefficiencies in the academic literature.",
     "My 60-minute finding is a textbook example: buying the favorite side earns +4 to +15 "
     "cents per $1 across every threshold, while buying longshots loses heavily (Figure 7).")

# ============================ CHAPTER 5 ======================================
CH("The noise trap — why small samples lie",
   "The most expensive lesson in trading, and the one this project learned in the most "
   "vivid possible way. This chapter is the heart of the book.")
P("Flip a fair coin 20 times and you should not be surprised to see 13 or 14 heads — 65-70% — "
  "even though the truth is 50%. Small samples routinely produce patterns that look like "
  "discoveries. In trading, where every tested rule is a coin being flipped, this manufactures "
  "convincing illusions on demand.")
TERM("Variance and noise",
     "The natural scatter of random outcomes around their true average. The smaller the sample, "
     "the wilder the scatter — and the easier it is to mistake scatter for signal.",
     "Figure 5 is my own +12.5pp \"discovery\" dissolving into noise as the sample grew 8x.")
TERM("Law of large numbers",
     "As the number of independent observations grows, the measured average converges to the "
     "true average. It is the reason casinos always win eventually — and the reason more data "
     "is the only real cure for noise.",
     "The same rule measured at 90 bets (+12.5pp), then continuously to 716 bets (-0.7pp). "
     "The law of large numbers ground the illusion down to the truth: nothing.")
FIG("f5_collapse.png",
    f"Figure 5 — the project's most important chart. A 5-minute momentum rule looked "
    f"spectacular (+{S['collapse']['early_edge']}pp) after ~90 bets — it had even passed "
    f"significance tests at that size. Measured over all {S['collapse']['n']} bets, the edge "
    f"is {S['collapse']['final_edge']}pp: nothing. Every wiggle in this line is luck arriving "
    "and evaporating. Burn this picture into memory before believing any backtest.")
TERM("Independent observations (and why mine are fewer than they look)",
     "Statistical confidence counts INDEPENDENT pieces of evidence. Bets whose outcomes move "
     "together — four crypto coins in the same five minutes, all following Bitcoin — are "
     "partially the SAME piece of evidence, not four.",
     "I group bets into clock windows: 96 bets on the lead rule collapse to just 31 "
     "independent windows. All my tests count windows, not bets; ignoring this once made "
     "results look four times more certain than they were.")
WARN("The mistake I made: believing 90 bets",
     "The +12.5pp rule had passed a latency test, a luck test AND an out-of-sample split — on "
     "~300 markets. At 2,360 markets it was gone. Small samples can fool even correct "
     "procedures, because the procedures themselves only see the data they are given. The only "
     "defense is humility scaled to sample size, and continuing to collect.")

# ============================ CHAPTER 6 ======================================
CH("Proving it isn't luck — p-values and the bootstrap",
   "Given a measured edge, the honest question is never \"how big is it?\" but \"how easily "
   "could pure chance have produced it?\"")
TERM("Null hypothesis",
     "The boring explanation you must rule out first: \"there is no edge; the results are "
     "chance.\" Statistical testing means asking how surprising your data would be if the "
     "boring explanation were true.",
     "For every rule I test, the null hypothesis is that its true profit per bet is zero "
     "or negative.")
TERM("Bootstrap (resampling)",
     "A way to measure luck without formulas: rebuild your dataset thousands of times by "
     "randomly re-drawing from your own results (with repetition allowed), recomputing the "
     "answer each time. The spread of those thousands of answers shows how much your result "
     "could wobble by chance alone.",
     "Figure 6 shows 4,000 such reconstructions of my lead rule. I resample whole clock "
     "windows rather than single bets, so correlated coins are never counted as independent "
     "evidence (a 'block bootstrap').")
FIG("f6_bootstrap.png",
    f"Figure 6 — 4,000 alternate worlds of the 60-minute rule \"buy the strong side at "
    f">= 0.65 within the first 24 minutes\" ({S['bootstrap']['n_bets']} bets, "
    f"{S['bootstrap']['n_windows']} independent windows). The measured result is "
    f"+{S['bootstrap']['obs_c']} cents per $1 bet; 90% of resampled worlds land between "
    f"+{S['bootstrap']['lo90']} and +{S['bootstrap']['hi90']} cents, and only "
    f"{S['bootstrap']['p_le_zero']:.1%} of them are zero or worse.")
TERM("p-value",
     "The probability of seeing a result at least as good as yours if the null hypothesis "
     "(pure luck) were true. Small p-value = luck is an implausible explanation. The common "
     "bar is p < 0.05, i.e. luck would produce this less than once in twenty tries.",
     f"My lead rule: p = {S['bootstrap']['p_le_zero']:.3f}. Chance produces a result this "
     "good about 2% of the time — unlikely, though not impossible. Compare: the collapsed "
     "5-minute rule of Figure 5 also once showed p = 0.043 on its small sample. p-values "
     "are evidence, not proof.")
TERM("Confidence interval (the 90% band)",
     "The range that contains the true value with stated confidence, given your data. A band "
     "that excludes zero is the visual version of a small p-value. Wide bands mean 'I do not "
     "know much yet' regardless of how good the central number looks.",
     f"The lead rule's 90% band is [+{S['bootstrap']['lo90']}, +{S['bootstrap']['hi90']}] "
     "cents — comfortably above zero, but its width (a factor of ~7) honestly reports how "
     "few independent windows I have.")
WARN("Multiple comparisons: the silent killer",
     "Test 28 rules at the p < 0.05 bar and you EXPECT about 1.4 of them to pass by pure "
     "luck. Scanning a grid and celebrating the best cell is how the +12.5pp illusion was "
     "born. Defenses: pre-commit to one rule before looking, demand the pattern hold across "
     "NEIGHBORING cells (a real effect is smooth, luck is spiky), and retest on fresh data. "
     "My 60-minute result is green across the entire grid — not one lucky cell.")

# ============================ CHAPTER 7 ======================================
CH("Not fooling yourself — overfitting, splits and regimes",
   "Statistics can certify that a pattern existed in your data. It cannot certify that the "
   "pattern will exist tomorrow. These tools attack that harder question.")
TERM("Overfitting",
     "Tuning a strategy until it fits the accidents of your particular dataset rather than a "
     "real, repeating phenomenon. An overfit strategy aces the past and fails the future.",
     "Sweeping 7 thresholds x 4 entry windows and picking the best cell is mild overfitting "
     "by construction — the winner is partly 'best' by luck. That is why I validate the "
     "whole neighborhood, never the single best cell.")
TERM("In-sample vs out-of-sample",
     "In-sample: the data you used to find the rule. Out-of-sample: fresh data the rule has "
     "never seen. Only out-of-sample performance predicts the future; in-sample performance "
     "mostly measures how hard you searched.",
     "My chronological split: does a rule earn money in BOTH the first and second half of "
     "the recording period independently?")
FIG("f7_split.png",
    f"Figure 7 — the split test on four rules. The 60-minute rules earn in both halves "
    f"(buy >= 0.65 / 24m: +{S['split']['60-min: buy >= 0.65 (24m)']['A']} then "
    f"+{S['split']['60-min: buy >= 0.65 (24m)']['B']} cents) — consistent evidence. The "
    f"5-minute rules FLIP: >= 0.75 earned +{S['split']['5-min: buy >= 0.75 (1st min)']['A']} "
    f"in half one and lost {S['split']['5-min: buy >= 0.75 (1st min)']['B']} in half two. "
    "A sign flip across time is the signature of noise or a temporary condition, not an edge.")
TERM("Regime",
     "A prevailing market mood — trending vs choppy, calm vs volatile — that can switch "
     "without warning. A strategy's true edge can be genuinely different in different regimes, "
     "so profits measured in one regime may simply not transfer.",
     "Momentum strategies naturally earn more in trending periods. Part of my 60-minute "
     "edge's size likely reflects the specific four days I recorded; direction is consistent, "
     "but I treat the magnitude as provisional until more regimes are in the data.")

# ============================ CHAPTER 8 ======================================
CH("The two strategies — fading vs riding the move",
   "One idea, two directions. The data destroyed one and endorsed the other, and the "
   "reasons teach more than the outcome.")
TERM("Mean reversion (\"fading\")",
     "Betting that an extreme move will come back: buy whatever crashed, sell whatever spiked. "
     "Profitable only where crowds systematically overreact.",
     "My original idea: buy the side that dips early to a low price. With exact fills and "
     "real outcomes it loses at EVERY price and EVERY horizon — dips in these markets are "
     "information, not overreaction.")
TERM("Momentum",
     "Betting that a move will continue: buy strength. Profitable where the crowd is too slow "
     "to fully believe genuine information.",
     "Buying the strong side of 60-minute markets earns +4 to +15 cents per $1 across the "
     "whole grid (Figure 8, left) — and it is the exact mirror of why fading loses.")
FIG("f8_heatmaps.png",
    "Figure 8 — every rule I tested on 60-minute markets, as profit per $1 bet in cents. "
    "Left (momentum): green nearly everywhere — the effect is broad and smooth, not one "
    "lucky cell. Right (fading): red everywhere, catastrophically so for deep dips (a 10-cent "
    "share that 'might bounce' loses ~half its stake per bet on average). Two panels, one "
    "phenomenon: early moves in these markets CONTINUE.")
FIG("f10_equity.png",
    f"Figure 9 — the lead rule's equity curve over its {S['equity']['n']} settled bets: "
    f"win rate {S['equity']['hit']}% vs break-even {S['equity']['paid']}%, final profit "
    f"+${S['equity']['final']} per $1 staked per bet, worst drawdown ${S['equity']['maxdd']}. "
    "A healthy curve grinds upward through losses rather than spiking on one lucky streak.")
TERM("Equity curve",
     "Cumulative profit plotted bet by bet. Its SHAPE is diagnostic: a real edge climbs "
     "steadily with contained dips; luck wanders, whipsaws, and depends on where the chart "
     "happens to end.",
     "An early 5-minute strategy spent 150 straight bets underwater, then 'ended positive' — "
     "a random walk. Figure 9 climbs with shallow dips — structurally different.")
TERM("Drawdown",
     "The drop from the highest point of the equity curve so far to the current point. "
     "Maximum drawdown measures the worst pain you would have endured — and whether you "
     "would realistically have kept going.",
     f"The lead rule's worst drawdown is ${S['equity']['maxdd']} against +${S['equity']['final']} "
     "total profit — about a third of the winnings, endured mid-run. Real strategies hurt "
     "sometimes; strategies that never hurt are usually fictions.")

# ============================ CHAPTER 9 ======================================
CH("Execution reality — latency, stop-losses and drawdowns",
   "Where good backtests go to die: the milliseconds, the exits, and the psychology.")
TERM("Latency",
     "The delay between seeing a trigger and your order actually reaching the market. If an "
     "edge exists only for the fastest reactor, normal humans and modest bots cannot collect it.",
     "I re-ran every simulation forcing a 300ms reaction delay — fills happen on the book as "
     "it stands a beat later. The 60-minute edge barely moved (+14.8 cents at the lead cell). "
     "It does not depend on being fast; an hourly trend is not a millisecond phenomenon.")
TERM("Stop-loss",
     "An exit rule that sells automatically once a position drops below a set level, to cap "
     "the loss on any single trade. Intuitive, protective — and, in a calibrated market, "
     "usually a way to pay for insurance you did not need.",
     "I tested stops at 0.45 and 0.35 on the 60-minute momentum rule. Both made it WORSE — "
     "dramatically (Figure 10).")
FIG("f9_stops.png",
    "Figure 10 — the same four profitable rules with no stop (green), a loose stop at 0.35 "
    "(amber) and a tighter stop at 0.45 (red). The tight stop destroys ~85% of the profit. "
    "Why: these positions dip below 0.45 on 32-48% of trades and STILL win ~83% of the time "
    "overall. The scary dip is usually on the way to victory; selling into it locks the loss "
    "and pays the spread, every time.")
P("The deeper reason stops fail here is calibration itself (Chapter 4): mid-flight, a favorite "
  "trading at 0.40 really does have about a 40% chance. Selling at a fair price is not "
  "protection — it is a coin-flip plus fees. All of this strategy's edge is collected at "
  "settlement, so the position must be held to settlement. The practical consequence is "
  "psychological: the demo bot's positions will regularly LOOK terrible mid-hour and then win. "
  "Panic-adding a stop-loss would quietly convert a winning system into a losing one.")
TERM("Take-profit",
     "The mirror exit: sell automatically once the position RISES to a set level, locking gains "
     "early. Same verdict for the same reason — selling at 0.94 what settles at $1.00 about 95% "
     "of the time gives up expected value and pays the spread for the privilege.",
     "Not even worth a simulation run: in a calibrated market, mechanical early exits in either "
     "direction can only subtract.")

# ============================ CHAPTER 10 =====================================
CH("Where I stand — the road to a live bot",
   "What four days of ticks, one destroyed illusion and one surviving edge add up to.")
H2("What I know with confidence")
P("(1) The 5-minute markets are efficient — across 2,360 markets, no price-based rule beats "
  "them in either direction after honest fills. (2) Fading dips loses everywhere, at every "
  "horizon. (3) Buying strength on 60-minute markets earned +4 to +15 cents per $1 across "
  "the whole rule grid, survived a 300ms latency handicap, a window-aware luck test "
  "(p = 0.018) and a chronological split — and its exact mirror (the fade losing) supports "
  "the same underlying story: hourly favorites are underpriced.")
H2("What I do NOT know yet")
P("The magnitude. The 60-minute evidence rests on ~31 independent windows recorded across "
  "four days that leaned trending. The direction of the effect is consistent everywhere I "
  "look, but the honest range for its true size is wide (roughly +3 to +25 cents per $1). "
  "Chapter 5 is the permanent reminder of what happens to magnitudes measured on small "
  "samples.")
H2("The validation ladder")
P("Step 1, build honest instruments — done: tick recorder (both books), exact-fill replay, "
  "verified real outcomes. Step 2, find and stress-test a candidate — done, with one "
  "casualty (the 5-minute illusion) and one survivor (60-minute momentum). Step 3, keep "
  "collecting across regimes while testing exits — done: stops rejected, hold-to-resolution "
  "confirmed. <b>Step 4 — where I am now:</b> a paper-trading bot trades the rule live "
  "with a demo wallet, filling against real books. Success is pre-defined: after ~50+ "
  "settled trades, its hit rate and profit must land near the replay's expectation "
  "(~72-77 cents paid, ~83-85% won). Step 5, only if paper matches replay: tiny real "
  "stakes with hard kill-switches, scaling only as live keeps matching.")
TERM("Paper trading",
     "Running a strategy live with fake money but real prices, real fills logic and real "
     "outcomes. The final exam before real money: it tests the signal, the execution, the "
     "infrastructure and the traders' nerves, all at zero cost.",
     "My paper bot buys the strong side of 15/60-minute markets by walking the live ask "
     "ladder, holds to resolution, and settles on official outcomes — the same pipeline the "
     "replay validated, now facing the future instead of the past.")
WARN("The three ways this can still fail",
     "(1) Regime: four trending days may overstate the edge — choppy weeks will test it. "
     "(2) Sample: 31 independent windows is thin; the true edge could sit at the low end of "
     "the band. (3) Frictions: fees (currently zero on this exchange, must be re-verified) "
     "or thinner books at size could eat several cents. The paper-trading phase exists "
     "precisely to expose all three before a real dollar is at risk.")

# ============================ GLOSSARY =======================================
story.append(PageBreak())
story.append(Paragraph("Glossary", st_h1))
story.append(Paragraph("Every term in one place, one breath each.", st_cap))
GLOSS = [
    ("Ask", "Lowest price a seller currently accepts. Buying instantly pays this."),
    ("Bid", "Highest price a buyer currently offers. Selling instantly receives this."),
    ("Binary market", "Two outcomes; winning shares pay $1, losing shares $0."),
    ("Block bootstrap", "Bootstrap that resamples groups of correlated bets together, so related outcomes are not counted as independent evidence."),
    ("Bootstrap", "Estimating luck by rebuilding your dataset thousands of times from its own rows."),
    ("Break-even hit rate", "Win rate at which a bet neither earns nor loses: equals the price paid."),
    ("Calibration", "Prices matching real frequencies: 70%-priced events happening 70% of the time."),
    ("Confidence interval", "Range that plausibly contains the true value; width = honesty about uncertainty."),
    ("Depth", "Shares waiting in the book at and near the best prices."),
    ("Drawdown", "Fall from the equity curve's peak; max drawdown = the worst suffered."),
    ("Edge", "Hit rate minus average price paid, in percentage points. The number that decides everything."),
    ("Efficient market", "All information already in the price; no simple rule profits."),
    ("Equity curve", "Cumulative profit, bet by bet. Shape reveals real edge vs luck."),
    ("Expected value (EV)", "Average profit per bet over many repetitions."),
    ("Favorite-longshot bias", "Crowds overpaying for longshots and underpaying favorites."),
    ("Fill", "Your order actually executing against the book."),
    ("Hit rate", "Share of bets won. Meaningless until compared with price paid."),
    ("In-sample / out-of-sample", "Data used to find a rule / fresh data used to verify it."),
    ("Independent observations", "Evidence items that do not move together; the real sample size."),
    ("Latency", "Delay between signal and execution."),
    ("Law of large numbers", "Averages converge to the truth as independent observations grow."),
    ("Liquidity", "Ease of trading size without moving the price."),
    ("Mean reversion", "Betting extremes return to normal; 'fading' the move."),
    ("Mid", "Average of bid and ask; fair-value proxy, not a tradeable price."),
    ("Momentum", "Betting a move continues; buying strength."),
    ("Multiple comparisons", "Testing many rules guarantees some pass by luck; the best cell lies."),
    ("Null hypothesis", "'It is just luck' — the claim every test tries to reject."),
    ("Order book", "The standing queue of all waiting buy and sell orders."),
    ("Overfitting", "Tuning to your data's accidents; acing the past, failing the future."),
    ("p-value", "Chance of results this good under pure luck. Small = suspicious of luck."),
    ("Paper trading", "Live trading with fake money: the final exam before real stakes."),
    ("Percentage point (pp)", "Absolute difference between percentages (82% - 72% = 10pp)."),
    ("Prediction market", "Market whose share prices are probabilities of events."),
    ("Regime", "Prevailing market condition (trending/choppy); edges can differ across regimes."),
    ("Resolution", "Official settlement; shares become $1 or $0."),
    ("Slippage", "Fill price worse than quoted because your order ate deeper book levels."),
    ("Spread", "Ask minus bid; the toll for trading instantly."),
    ("Stop-loss", "Auto-sell below a level. In calibrated markets, usually negative-value insurance."),
    ("Take-profit", "Auto-sell above a level. Same verdict, same reason."),
    ("Variance", "Random scatter around the true average; shrinks only with more data."),
]
for term, desc in GLOSS:
    story.append(Paragraph(f"<b>{term}</b> — {desc}", st_gloss))

# ============================ COLOPHON =======================================
story.append(Spacer(1, 1.4 * cm))
_box([[Paragraph("About the author", st_term_name)],
      [Paragraph(f"<b>{AUTHOR}</b> — independent quantitative-research and full-stack "
                 "engineering project. Every figure and number in this book was produced by my "
                 "own code from data I recorded, and regenerates automatically as the dataset "
                 "grows. Full source code and the live dashboard are available on request.",
                 st_term_body)],
      [Paragraph(f"Contact: &nbsp;{CONTACT}", st_term_body)]], TERM_BG, TERM_EDGE)


# ============================ BUILD ==========================================
def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#8a8a8a"))
    canvas.drawString(2 * cm, 1.1 * cm, f"Trading by the Numbers  ·  {AUTHOR}")
    canvas.drawRightString(A4[0] - 2 * cm, 1.1 * cm, f"{doc.page}")
    canvas.restoreState()


doc = BaseDocTemplate(str(OUT), pagesize=A4,
                      leftMargin=2 * cm, rightMargin=2 * cm,
                      topMargin=1.8 * cm, bottomMargin=1.8 * cm,
                      title="Trading by the Numbers — Nitzan Ben Dror",
                      author=AUTHOR)
frame = Frame(2 * cm, 1.8 * cm, A4[0] - 4 * cm, A4[1] - 3.6 * cm, id="main")
doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=on_page)])
doc.build(story)
print(f"built {OUT}")
