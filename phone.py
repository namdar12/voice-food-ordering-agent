# multi_agent_pipecat.py
# Adapted from single-agent example to a multi-agent framework

import argparse
import asyncio
import glob
import json
import os
from datetime import datetime

import boto3
from dotenv import load_dotenv
from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.aws_nova_sonic.aws import AWSNovaSonicLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.network.small_webrtc import SmallWebRTCTransport
from pipecat.transports.network.webrtc_connection import SmallWebRTCConnection

load_dotenv(override=True)
BASE_FILENAME = "/tmp/pipecat_conversation_"


# --- Sub-agent 1 Handlers: Email & Password Tools ---
async def send_email(params: FunctionCallParams):
    # Fake implementation: send a Gmail
    details = f"Email sent to {params.arguments['to']} with subject '{params.arguments['subject']}'"
    await params.result_callback({"success": True, "details": details})


async def change_password(params: FunctionCallParams):
    # Fake implementation: change a password
    details = f"Password for user {params.arguments['username']} changed."
    await params.result_callback({"success": True, "details": details})


# --- Sub-agent 2 Handler: Weather Tool ---
async def fetch_weather_from_api(params: FunctionCallParams):
    temperature = 75 if params.arguments["format"] == "fahrenheit" else 24
    await params.result_callback(
        {
            "conditions": "nice",
            "temperature": temperature,
            "format": params.arguments["format"],
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        }
    )


# --- Function Schemas for Each Tool ---
send_email_tool = FunctionSchema(
    name="send_email",
    description="Send an email via Gmail",
    properties={
        "to": {"type": "string", "description": "Recipient email address"},
        "subject": {"type": "string", "description": "Email subject"},
        "body": {"type": "string", "description": "Email body"},
    },
    required=["to", "subject", "body"],
)

change_password_tool = FunctionSchema(
    name="change_password",
    description="Change a user's password",
    properties={
        "username": {"type": "string", "description": "Username"},
        "new_password": {"type": "string", "description": "New password"},
    },
    required=["username", "new_password"],
)

get_weather_tool = FunctionSchema(
    name="get_current_weather",
    description="Get the current weather",
    properties={
        "location": {
            "type": "string",
            "description": "City and state, e.g., San Francisco, CA",
        },
        "format": {
            "type": "string",
            "enum": ["celsius", "fahrenheit"],
            "description": "Temperature unit",
        },
    },
    required=["location", "format"],
)

# Tool to route from the lead agent to sub-agents
call_agent_tool = FunctionSchema(
    name="call_agent",
    description="Orchestrate a sub-agent call",
    properties={
        "agent": {
            "type": "string",
            "enum": ["agent1", "agent2"],
            "description": "Sub-agent to call",
        },
        "instruction": {
            "type": "string",
            "description": "Instruction for the sub-agent",
        },
    },
    required=["agent", "instruction"],
)
# Get the credentials from the session (via AWS_* environment variables, see .env.example)
session = boto3.Session(
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
    region_name=os.getenv("AWS_REGION", "us-east-1"),
)

# Get the credentials from the session
credentials = session.get_credentials()
if credentials is None:
    raise Exception(
        "No AWS credentials found. Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY "
        "(see .env.example)."
    )


# --- Group Tools into Schemas per Agent ---
agent1_tools = ToolsSchema(standard_tools=[send_email_tool, change_password_tool])
agent2_tools = ToolsSchema(standard_tools=[get_weather_tool])
lead_tools = ToolsSchema(standard_tools=[call_agent_tool])

# --- Instantiate AWS Nova Sonic Services per Agent ---
lead_llm = AWSNovaSonicLLMService(
    secret_access_key=credentials.secret_key,
    access_key_id=credentials.access_key,
    session_token=credentials.token,  # Add the session token
    region="us-east-1",
    voice_id="tiffany",
)
agent1_llm = AWSNovaSonicLLMService(
    secret_access_key=credentials.secret_key,
    access_key_id=credentials.access_key,
    session_token=credentials.token,  # Add the session token
    region="us-east-1",
    voice_id="matthew",
)
agent2_llm = AWSNovaSonicLLMService(
    secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    region=os.getenv("AWS_REGION"),
    voice_id="amy",
)

# --- Create Contexts for Each Agent ---
lead_context = OpenAILLMContext(
    messages=[
        {
            "role": "system",
            "content": "You are the Lead Agent: decide which sub-agent to invoke.",
        }
    ],
    tools=lead_tools,
)
agent1_context = OpenAILLMContext(
    messages=[
        {
            "role": "system",
            "content": "You are Agent1: handle email and password tasks.",
        }
    ],
    tools=agent1_tools,
)
agent2_context = OpenAILLMContext(
    messages=[
        {"role": "system", "content": "You are Agent2: provide weather information."}
    ],
    tools=agent2_tools,
)


# --- call_agent Handler: Routes to Sub-Agents ---
async def call_agent(params: FunctionCallParams):
    target = params.arguments["agent"]
    instr = params.arguments["instruction"]
    # NOTE: generate_text is a placeholder for your SDK's text-only call
    if target == "agent1":
        response_text = await agent1_llm.generate_text(agent1_context, instr)
    else:
        response_text = await agent2_llm.generate_text(agent2_context, instr)
    await params.result_callback({"result": response_text})


# --- Register Each Agent's Tools ---
lead_llm.register_function("call_agent", call_agent)
agent1_llm.register_function("send_email", send_email)
agent1_llm.register_function("change_password", change_password)
agent2_llm.register_function("get_current_weather", fetch_weather_from_api)


# --- Main Entry: Launch the Lead Agent Pipeline ---
async def run_bot(webrtc_connection: SmallWebRTCConnection, _: argparse.Namespace):
    logger.info("Starting multi-agent bot")

    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.8)),
        ),
    )

    # Use lead_context and lead_llm in the pipeline
    pipeline = Pipeline(
        [
            transport.input(),
            lead_context,
            lead_llm,
            transport.output(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
            enable_usage_metrics=True,
            report_only_initial_ttfb=True,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected to Lead Agent")
        await task.queue_frames([lead_context.messages])
        await lead_llm.trigger_assistant_response()

    @transport.event_handler("on_client_closed")
    async def on_client_closed(transport, client):
        logger.info("Client disconnected from Lead Agent")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)


if __name__ == "__main__":
    from run import main

    main()