# Prompts

The four prompts (hackathon riddles and the briefs written for them) that shaped LivingDoc, kept exactly as written. The README's *How each riddle shaped the project* section explains what each one changed.

---

## Prompt 1: What a small business runs on, and what quietly breaks first

From the outside a small business looks simple, someone sells something to someone. Inside, it runs on memory. favours, instinct and one person's long days, and that person is usually the buyer, the cashier, the accountant and the cleaner at once. Most of what keeps it going has never been written down, because nobody has ever had the time What is a small business actually running on, and what quietly breaks first?
This is hackathon problem I had, the solution I thought of was to make accounting in small or local businesses easier. An integrated platform which consists of two parts – a hardware part which is a scanner which feeds information about the influx and outflow of items and updates stock on the second part of this solution, a website that holds complicated information but has a simple to operate interface also providing support for local languages for Hindi and Gujarati as well as English. An AI which runs semi-locally and can solve out of workflow but basic problems by simple evaluation mainly designed for calculation of stock and running predictions using AI algorithms to predict stock shortages extremely early. If there are multiple branches of the same store then it uploads hourly to keep in link with all stores. The qr scanner like in walmart (hardware part) is to be assumed to work already and can feed information to the website efficiently. No code for the hardware has to be created. Create code for the website which runs predictions based on data fed and helps with stock calculation using the tips below:
for scalability, Build a scalable single-page app in Python (Streamlit + SQLite) called "LivingDoc: The Self-Updating Business Brain".
Requirements:
1. UI Layout: Two columns.
    * Left: A text area for messy voice notes/rambles (e.g., "Sold 4 coffees, used 2 milks, Dave paid $50 cash, reminded me to order beans").
    * Right: A clean, live "Google Doc"-style Markdown page showing:
        * 📦 Current Inventory (Calculated counts + ⚠️ Low Stock alerts)
        * 💰 Cash & Invoices (Total collected, pending debts)
        * 🤝 Handshakes & Promises (Checklist [ ] and [x])
        * 🚨 Quiet Breakage Warnings (Automated risk detection)
2. Scalable Event-Driven Logic (Crucial):
    * Do NOT rewrite the whole document with AI.
    * Use an LLM (OpenAI-compatible client pointing to http://localhost:11434/v1 or OpenAI) ONLY to extract structured JSON deltas: { "inventory_deltas": [{"item": "str", "change": -2}], "cash_events": [{"type": "collected|owed", "entity": "str", "amount": 50.0, "desc": "str"}], "promises": [{"person": "str", "task": "str", "completed": false}], "quiet_risk": "str" }
    * Deterministic Python/SQLite code must execute the additions/subtractions and update the database.
    * Re-render the Markdown document from SQLite state. Provide the complete, single-file runnable code with starter data already seeded.
Build a Python inventory prediction algorithm that specifically accommodates festive seasons, holidays, and supplier shutdowns for small businesses.
Requirements:
1. Inputs:
    * Current stock levels: e.g., {"Ghee": 20, "Flour": 50, "Gift Boxes": 30}
    * Normal daily burn rate (baseline velocity).
    * Upcoming Festival Calendar: e.g., {"name": "Diwali", "date": "2026-11-01", "surge_multiplier": 2.8, "supplier_blackout_days": 4}
    * Standard supplier lead time (e.g., 3 days).
2. Festive Prediction Engine:
    * Surge Calculation: Increase daily burn rate by the festival multiplier during the 7 days leading up to the festival.
    * Supplier Blackout Buffer: Because suppliers close or experience shipping delays during festivals, lead time must expand (Standard Lead Time + Supplier Blackout Days).
    * Reorder Date Adjustment: Back-calculate the reorder deadline so stock arrives at least 48 hours BEFORE the festival surge begins.
    * Post-Festival Overstock Guard: Flag perishable items that will spoil if over-ordered for the festival.
3. Output JSON: { "item": "Gift Boxes", "current_stock": 30, "baseline_burn": 2.0, "festive_burn": 5.6, "days_left_normal": 15, "days_left_festive": 5.3, "festival_name": "Diwali", "supplier_lead_time_adjusted": "7 days (3 normal + 4 holiday lag)", "must_order_by": "2026-10-21", "urgency": "CRITICAL", "alert": "Diwali surge will exhaust stock in 5 days instead of 15. Since suppliers close 4 days early, your last chance to order is Wednesday." }
Provide a clean, self-contained Python script with a test case showing the difference between normal vs. festive reorder dates.
the features of website include the inventory in google docs which is edited by the AI, the input and output from qr scanner automatically updates stock in the inventory and if there is a problem, try to solve it, make no mistakes.

---

## Prompt 2: Bets a small business cannot take back

Every day a small business places bets it cannot take back: how much to buy, who to hire, whether to raise a price, whether to take a big order, whether to borrow. Weather, mood, a festival, a rival and a rumour all move the answer, and none of them is written anywhere. The owner has instinct and a few scribbled yesterdays. How do you decide well about a day nobody can see, and how would you ever know afterwards whether you decided well? This is a hackathon problem. Assume inputs for unknown variables like location, weather, dates etc. I need to build a prediction model, intake weather API, say step by step, I want AI to use weather, location, upcoming festivals, local competition, local income levels and dates to predict when majority of people get paychecks and when people spend it the most, appropriately surging demand and applying economical sales for the most sought out products if any by searching the web once everyday. Show sophisticated predictions on a well made matplotlib graph, and accordingly suggest surge pricing and sales all in a website. Make the ai model on addition of previous assumed market trends. Give ability to the owner himself to add his inputs and suggest changes in the prediction to add factors and AI accommodates the prediction. Integrate this feature into the website too.

---

## Prompt 3: Promises as assets and private stories

A business is held together by promises: money owed, favours given, a worker's word, a supplier's goodwill, trust extended to a neighbour. These promises have value to the business, to outsiders who would love to see them, and to the people inside them, who would rather they stayed private or were treated fairly. When a promise is both an asset and someone's private story, who may see it, and who decides what it is worth?
add trust ledger,proof without exposure and promise to cashflow predictor to the final website

---

## Prompt 4: Being found and trusted without handing yourself over

Some of the best businesses in the cily are known only to their own street.
Everyone says being found is easy now. machines can write, design and spend on your behalf. But to the owner, these tools are a mystery, and so they avaid them.
The tools are powerful, and the people who need them are not using them. What would it take for a small business to be found and trusted, without handing itself over to something it doesn't understand?
The solution is:
Small shops stay unknown because the tools that could help are opaque and act on their own. The owner can’t see why they do things or stop them. What’s missing is not more power but a clear view of what the tool is doing and a veto over it. So the helper only drafts, and you decide every step:
* Private by default. The public page (shop.html?s=<slug>) doesn’t exist until you switch it on. Each field (name, product names, trust badge) stays hidden until you tick it. Stock, customers, debts and cash are never shown.
* Drafts only. The helper writes drafts in English, Hindi or Gujarati, and only when you press the button. It uses your tagline, the festival calendar and your signed proof. Each draft shows its source, what it used, and that it invented nothing, since it states no prices or discounts. You approve and publish in two separate taps.
* Spending has a cap. Boosts above the cap you set are refused. No ad account is connected, so a boost is recorded as planned spend and nothing is actually bought.
* Every action is logged. The log shows whether the helper or you did it. Turning the helper off stops suggestions. Revoking a proof removes the trust badge from the public page immediately.
* Found and trusted. The page includes the markup search engines and assistants read. It can also show the signed proof from the last feature, and a visitor can check that signature with one tap. This is checkable trust, not an audit.  add these solutions by yourself to the current designed website
