# Little Makers Market

**Kids' drawings become plush 3D toys, stickers and prints that family can buy with PayPal — and AI agents can buy too.**

An AI maker agent turns one photo of a child's drawing into a complete PayPal shop in about a minute: it reads the drawing, asks the young artist two questions, keeps every quirk (three legs stay three legs), inflates the drawing into a printable plush 3D model, writes the listing and story, and opens checkout. Every sale is split automatically into the kid's **save / spend / give** jars — or shared with a church, school or team fundraiser.

> Work in progress for the [PayPal AI Hackathon](https://paypalaihackathon.devpost.com/). Full setup, demo and architecture docs coming before submission.

## Quick start (sandbox)

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # macOS/Linux: .venv/bin/pip
.venv/Scripts/pip install --no-deps paypal-agent-toolkit==1.11.0   # core toolkit only (skips its LangChain/CrewAI extras)
cp .env.example .env                             # add PayPal sandbox + OpenRouter keys
.venv/Scripts/python -m app.seed                 # optional: two demo markets (uses the AI, ~10 cents)
.venv/Scripts/python -m uvicorn app.main:app --reload
```

## License

MIT
