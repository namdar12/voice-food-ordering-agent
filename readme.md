# Voice Food-Ordering Agent (Pipecat + Amazon Nova)

A real-time voice assistant you talk to in the browser. Built on
**Pipecat** with **Amazon Nova Sonic** as the lead voice agent, it runs a
multi-agent system: the lead agent figures out what you want and delegates to
specialized sub-agents (Amazon Nova Micro via Bedrock) — one handles email and
password tasks, another walks you through ordering pizza or sushi with a
state-machine flow and emails you the confirmation.

## Architecture

```
Browser --WebRTC--> run.py (FastAPI + SmallWebRTC prebuilt UI)
                          |
                    multiPhone.py run_bot()
                          |
              Lead agent: Nova Sonic (voice-to-voice)
                          |  tool: call_agent(agent, instruction)
              +---------+---------+
              |                   |
        agent1 (Nova Micro)  agent2 (Nova Micro)
        email/password tools  food_ordering_flow state machine
                              (pizza/sushi) + Zapier MCP email
```

- `multiPhone.py` — the main bot: lead Nova Sonic agent + two Nova Micro
sub-agents, tool schemas, and the Pipecat pipeline (`run_bot`).
- `food_ordering_flow.py` — deterministic pizza/sushi ordering state machine
(size → type → confirm → email for receipt).
- `run.py` — WebRTC server runner with the prebuilt browser client
(Pipecat example runner).
- `phone.py`, `nova.py` — earlier single/multi-agent prototypes kept for
reference.
- `check_credentials.py` — verifies your AWS/Bedrock credentials.
- `test.py` — scratch script probing the Nova Sonic streaming API.

## Setup

1. Create and activate a virtualenv, then install:

   ```bash
   pip install -r requirements.txt
   ```

2. Configure environment:

   ```bash
   cp .env.example .env   # then fill in your AWS keys
   ```

   You need AWS credentials with Bedrock access to `amazon.nova-sonic-v1:0`
and `amazon.nova-micro-v1:0` (region `us-east-1`).

3. Run the bot (this example uses the multi-agent food-ordering bot):

   ```bash
   python run.py multiPhone.py
   ```

4. Open http://localhost:7860/client, allow the microphone, and talk.
Try: *"I'd like to order a pizza"*.

## Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` | yes | — | AWS credentials with Bedrock access |
| `AWS_REGION` | no | `us-east-1` | Bedrock region |
| `AWS_PROFILE` | no | — | Optional AWS CLI/SSO profile instead of keys |
| `ZAPIER_MCP_URL` | for email receipts | — | Zapier MCP endpoint for order-confirmation emails |

## Notes

- `run.py` is adapted from Pipecat's Small WebRTC prebuilt example
(Copyright Daily, BSD-2-Clause — header retained).
- Never commit `.env` — it's gitignored.
