# Fact-check report: How Costco Actually Makes Its Money

**Status:** PASS (0 errors, 1 warnings)

## Warnings

- W3 fact 'net_sales' has a recorded source conflict: The Shelby Report headline says $297.3B (from the Sept 2026 monthly sales release); the earnings release says $297.2B. Script says "$297 billion", which is true under both.

## Spoken claims

| Scene | Claim | Fact | Value | Confidence | Sources |
|---|---|---|---|---|---|
| hook | $297 billion | net_sales | 2.972e+11 | official | costco_pr, costco_8k |
| thin-profit | $303 billion | total_revenue | 3.0311e+11 | calc | calc: `net_sales + membership_fees` |
| thin-profit | $9.2 billion | net_income | 9.226e+09 | official | costco_pr, costco_8k |
| per-100 | $3 | profit_per_100 | 3.044 | calc | calc: `net_income / total_revenue * 100` |
| per-100 | $100 | (allowed: illustrative) | | | |
| markup | 14% | markup_brand | 0.14 | reported | acquired_markup, yahoo_kirkland |
| markup | 15% | markup_kirkland | 0.15 | reported | acquired_markup, yahoo_kirkland |
| fees | $65 | gold_star_fee | 65 | official | cnn_fee, costco_cs_fee |
| fees | $5.9 billion | membership_fees | 5.91e+09 | official | costco_pr, costco_8k |
| fees-vs-profit | 64% | fee_share | 0.6406 | calc | calc: `membership_fees / net_income` |
| renewals | 92.3% | renewal_rate | 0.923 | official | costco_pr, fool_q4 |
| hot-dog | $1.50 | hotdog_price | 1.5 | reported | fox_hotdog, snopes_quote |
| hot-dog | 40 | hotdog_years | 41 | calc | calc: `2026 - 1985` |

## Fact ledger

- **net_sales** = 2.972e+11 USD — Costco net sales (FY2026 (52 weeks ended Aug 30, 2026)) · _official_ · sources: costco_pr, costco_8k
  - conflict: The Shelby Report headline says $297.3B (from the Sept 2026 monthly sales release); the earnings release says $297.2B. Script says "$297 billion", which is true under both.
- **membership_fees** = 5.91e+09 USD — Membership fee revenue (FY2026 (vs $5.32B in FY2025)) · _official_ · sources: costco_pr, costco_8k
- **net_income** = 9.226e+09 USD — Net income attributable to Costco (FY2026 (vs $8.099B in FY2025); includes a one-time tariff-refund benefit of about $0.15/share in Q4) · _official_ · sources: costco_pr, costco_8k
- **total_revenue** = 3.0311e+11 USD — Total revenue (net sales + membership fees) (FY2026) · _calc_ · calc `net_sales + membership_fees`
- **profit_per_100** = 3.044 USD — Net profit per $100 of revenue · _calc_ · calc `net_income / total_revenue * 100`
- **fee_share** = 0.6406 ratio — Membership fees as a share of net income (fees are pre-tax revenue; net income is after tax — framed as "equal to", not "part of") · _calc_ · calc `membership_fees / net_income`
- **paid_members** = 8.41e+07 people — Paid members at fiscal year end (Aug 30, 2026) · _official_ · sources: costco_pr, fool_q4
- **renewal_rate** = 0.923 ratio — US & Canada membership renewal rate (end of FY2026) · _official_ · sources: costco_pr, fool_q4
- **gold_star_fee** = 65 USD/year — Annual Gold Star (basic) membership fee in the US & Canada since Sept 1, 2024 (was $60) · _official_ · sources: cnn_fee, costco_cs_fee
- **hotdog_price** = 1.5 USD — Price of the hot dog + soda combo · _reported_ · sources: fox_hotdog, snopes_quote
- **hotdog_years** = 41 years — Years the combo has been $1.50 (since 1985) — spoken as "more than 40 years" · _calc_ · calc `2026 - 1985`
- **markup_brand** = 0.14 ratio — Reported maximum markup on brand-name items (company policy, not in SEC filings) · _reported_ · sources: acquired_markup, yahoo_kirkland
- **markup_kirkland** = 0.15 ratio — Reported maximum markup on Kirkland Signature items · _reported_ · sources: acquired_markup, yahoo_kirkland

## Sources

- **costco_pr** (primary) Costco Wholesale (investor relations), "Costco Wholesale Corporation Reports Fourth Quarter and Fiscal Year 2026 Operating Results" — https://investor.costco.com/news/news-details/2026/Costco-Wholesale-Corporation-Reports-Fourth-Quarter-and-Fiscal-Year-2026-Operating-Results/default.aspx (accessed 2026-09-29) — Figures read from search-index excerpts of the release; direct page fetch was blocked by the build environment's network policy.
- **costco_8k** (primary) U.S. SEC EDGAR, "Form 8-K, Exhibit 99.1 (FY2026 results press release)" — https://www.sec.gov/Archives/edgar/data/909832/000090983226000084/costex9918-k92426.htm (accessed 2026-09-29)
- **shelby** The Shelby Report, "Costco Caps FY26 With $297.3B In Sales, Up 10.2 Percent" — https://theshelbyreport.com/2026/09/15/costco-caps-fy26-with-297-3b-in-sales-up-10-2-percent/ (accessed 2026-09-29)
- **fool_q4** The Motley Fool, "Costco (COST) Q4 2026 Earnings Call Transcript" — https://www.fool.com/earnings/call-transcripts/2026/09/29/costco-cost-q4-2026-earnings-call-transcript/ (accessed 2026-09-29)
- **cnn_fee** CNN Business, "Costco's first membership price hike in 7 years just went into effect" — https://www.cnn.com/2024/09/03/business/costco-membership-fee-price-increase (accessed 2026-09-29)
- **costco_cs_fee** (primary) Costco Customer Service, "Membership Fee Increase" — https://customerservice.costco.com/app/answers/answer_view/a_id/1013504/~/membership-fee-increase (accessed 2026-09-29)
- **fox_hotdog** Fox Business, "Why Costco hot dogs have kept $1.50 price tag since 1985" — https://www.foxbusiness.com/lifestyle/why-costco-hot-dogs-have-kept-1-50-price-tag-since-1985 (accessed 2026-09-29)
- **snopes_quote** Snopes, "Did Costco Founder Say 'I Will Kill You' to CEO Who Wanted To Raise Hot Dog Price?" — https://www.snopes.com/fact-check/costco-founder-kill-hotdogs/ (accessed 2026-09-29) — Rated true, based on Craig Jelinek's own April 12, 2018 retelling.
- **acquired_markup** Acquired Briefing, "Costco (Acquired Briefing)" — https://www.acquiredbriefing.com/p/costco (accessed 2026-09-29)
- **yahoo_kirkland** Yahoo Finance, "How Costco Keeps Kirkland Signature Prices So Cheap" — https://www.yahoo.com/finance/news/costco-keeps-kirkland-signature-prices-123000186.html (accessed 2026-09-29)
