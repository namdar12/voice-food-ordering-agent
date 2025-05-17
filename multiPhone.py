# multi_agent_pipecat.py
# Lead Agent: AWS Nova Sonic (Voice-to-Voice)
# Sub-Agents: Amazon Nova Micro (Text-based via Bedrock Converse API)

import argparse
import asyncio

# import glob # Not used
import json
import os
from datetime import datetime

import boto3
from dotenv import load_dotenv
from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import (  # Used for defining tool structures
    ToolsSchema,
)
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask

# OpenAILLMContext will be used for the lead agent's context management with its aggregator
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.aws_nova_sonic.aws import AWSNovaSonicLLMService
from pipecat.services.llm_service import (  # For lead_llm's call_agent tool
    FunctionCallParams,
)
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.network.small_webrtc import SmallWebRTCTransport
from pipecat.transports.network.webrtc_connection import SmallWebRTCConnection

from food_ordering_flow import FlowManager, flow_config

load_dotenv(override=True)
BASE_FILENAME = "/tmp/pipecat_conversation_"  # Not actively used in this script snippet

# --- Credentials Setup ---
AWS_PROFILE_NAME = "e360-AdministratorAccess-120569624902"
AWS_REGION = "us-east-1"

# Get the credentials from the session
session = boto3.Session(profile_name=AWS_PROFILE_NAME)

# Get the credentials from the session
credentials = session.get_credentials()
if credentials is None:
    raise Exception("No AWS credentials found. Please run 'aws sso login' first.")

# Create a new session with the frozen credentials
session = boto3.Session(
    aws_access_key_id=credentials.access_key,
    aws_secret_access_key=credentials.secret_key,
    aws_session_token=credentials.token,
    region_name=AWS_REGION,
)

print("session ", session)
print("credentials ", credentials.access_key)

# Bedrock Runtime Client (for Sub-Agents)
bedrock_runtime = session.client(
    service_name="bedrock-runtime",
    region_name=AWS_REGION,
    aws_access_key_id=credentials.access_key,
    aws_secret_access_key=credentials.secret_key,
    aws_session_token=credentials.token,
)
logger.info(f"Using AWS Region: {AWS_REGION} for Bedrock.")


# --- Sub-agent Tool Implementations (Modified to return results directly) ---
async def send_email_tool_impl(to: str, subject: str, body: str):
    logger.info(
        f"Sub-Agent ACTION: Sending email to {to} with subject '{subject}' and body '{body}'"
    )
    # Fake implementation
    details = f"Email supposedly sent to {to} with subject '{subject}'."
    return {"success": True, "details": details}


async def change_password_tool_impl(username: str, new_password: str):
    logger.info(
        f"Sub-Agent ACTION: Changing password for user {username} to '{new_password}'."
    )
    # Fake implementation
    details = f"Password for user {username} supposedly changed."
    return {"success": True, "details": details}


# --- Map Tool Names to Implementations ---
tool_handlers = {
    "send_email": send_email_tool_impl,
    "change_password": change_password_tool_impl,
}

# --- Function Schemas for Sub-Agent Tools (as before) ---
send_email_tool_schema = FunctionSchema(
    name="send_email",
    description="Send an email with a given recipient, subject, and body.",
    properties={
        "to": {"type": "string", "description": "Recipient email address"},
        "subject": {"type": "string", "description": "Email subject"},
        "body": {"type": "string", "description": "Email body content"},
    },
    required=["to", "subject", "body"],
)

change_password_tool_schema = FunctionSchema(
    name="change_password",
    description="Change a user's password. Requires username and the new password.",
    properties={
        "username": {
            "type": "string",
            "description": "The username for which to change the password",
        },
        "new_password": {"type": "string", "description": "The new password to set"},
    },
    required=["username", "new_password"],
)

# --- Schema for Lead Agent's Tool ---
call_agent_tool_schema = FunctionSchema(
    name="call_agent",
    description="Orchestrates a call to a specialized sub-agent. Use 'agent1' for email or password tasks, and 'agent2' for food ordering. Provide a clear and concise instruction for the sub-agent.",
    properties={
        "agent": {
            "type": "string",
            "enum": ["agent1", "agent2"],
            "description": "The sub-agent to call: 'agent1' for email/password, 'agent2' for food ordering.",
        },
        "instruction": {
            "type": "string",
            "description": "The specific instruction or query for the sub-agent.",
        },
    },
    required=["agent", "instruction"],
)

# --- Group Tools into Schemas for Pipecat (Lead Agent) and Bedrock (Sub-Agents) ---
# For Pipecat Lead Agent (AWSNovaSonicLLMService)
lead_tools_pipecat = ToolsSchema(standard_tools=[call_agent_tool_schema])

# For Bedrock Sub-Agents (Amazon Nova Micro)
agent1_tools_list_bedrock = [send_email_tool_schema, change_password_tool_schema]


# Helper to convert Pipecat FunctionSchema to Bedrock Converse API tool specification
def convert_pipecat_tools_to_bedrock_tool_config(pipecat_tools_list):
    if not pipecat_tools_list:
        return None
    bedrock_tools = []
    for tool_schema in pipecat_tools_list:
        bedrock_tools.append(
            {
                "toolSpec": {
                    "name": tool_schema.name,
                    "description": tool_schema.description,
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": tool_schema.properties,
                            "required": (
                                tool_schema.required
                                if hasattr(tool_schema, "required")
                                and tool_schema.required
                                else []
                            ),
                        }
                    },
                }
            }
        )
    return {"tools": bedrock_tools}


# --- Sub-Agent Configurations ---
sub_agent_configs = {
    "agent1": {
        "system_prompt": "You are Agent1, an AI assistant specializing in email and password tasks. You must use the provided tools ('send_email', 'change_password') to fulfill requests. If an instruction lacks necessary details for a tool, ask clarifying questions to get all required parameters before using the tool. Respond with the outcome of the operation or any questions you have.",
        "tools_config": convert_pipecat_tools_to_bedrock_tool_config(
            agent1_tools_list_bedrock
        ),
        "model_id": "amazon.nova-micro-v1:0",  # As per doc section 2.3
    },
    "agent2": {
        "system_prompt": "You are Agent2, an AI assistant that handles food ordering via a multi-step workflow. Use the food ordering flow to guide the user through their order. If the user wants to order food, start the flow and manage the conversation state.",
        "flow_manager": FlowManager(flow_config=flow_config),
        "model_id": "amazon.nova-micro-v1:0",
    },
}

# --- Instantiate Lead Agent LLM Service (AWS Nova Sonic) ---
lead_llm = AWSNovaSonicLLMService(
    access_key_id=credentials.access_key,
    secret_access_key=credentials.secret_key,
    session_token=credentials.token,
    region=AWS_REGION,
    voice_id="tiffany",  # Example, ensure this is a valid voice for Nova Sonic in your region
    bedrock_runtime=bedrock_runtime,  # Pass the initialized bedrock runtime client
    audio_output_enabled=True,  # Explicitly enable audio output
    audio_input_enabled=True,  # Explicitly enable audio input
    audio_sample_rate=16000,  # Standard sample rate for Nova Sonic
    audio_channels=1,  # Mono audio
)

# --- Create Context for Lead Agent ---
lead_context = OpenAILLMContext(  # Pipecat context object for the lead agent
    messages=[
        {
            "role": "system",
            "content": "You are a friendly and helpful Lead Agent. Your role is to understand the user's intent and decide whether to answer directly or to delegate the task to a specialized sub-agent by using the 'call_agent' tool. 'agent1' handles email and password tasks. 'agent2' handles food ordering through a guided workflow. After a sub-agent responds, summarize its findings or actions clearly to the user. If a sub-agent cannot perform a task or returns an error, inform the user politely. Keep your responses concise and natural for voice interaction, typically 1-2 sentences. When you first start, introduce yourself and list the available options: 'I can help you with email tasks, password changes, or food ordering. What would you like to do?'",
        }
    ],
    tools=lead_tools_pipecat,  # ToolsSchema for Pipecat
)


# --- call_agent Handler (Lead Agent's Tool) ---
# This function is called by the Lead Agent (Nova Sonic)
# It then interacts with a Sub-Agent (Nova Micro via Bedrock Converse API)
async def call_agent(params: FunctionCallParams):
    target_agent_name = params.arguments.get("agent")
    instruction_for_sub_agent = params.arguments.get("instruction")

    logger.info(
        f"Lead Agent calling Sub-Agent '{target_agent_name}' with instruction: '{instruction_for_sub_agent}'"
    )

    agent_config = sub_agent_configs.get(target_agent_name)
    if not agent_config:
        logger.error(f"Unknown sub-agent: {target_agent_name}")
        await params.result_callback(
            {"error": f"Sub-agent {target_agent_name} not found."}
        )
        return

    if target_agent_name == "agent2":
        # Use the food ordering flow manager as a state machine
        flow_manager = agent_config["flow_manager"]
        # Pass the instruction as user input to the flow manager
        flow_result = await flow_manager.process_user_input(instruction_for_sub_agent)
        await params.result_callback({"result": flow_result["response"]})
        return

    # Initial messages for the sub-agent (Nova Micro)
    sub_agent_messages = [
        {
            "role": "user",
            "content": [
                {"text": f"System instructions: {agent_config['system_prompt']}"}
            ],
        },
        {"role": "user", "content": [{"text": instruction_for_sub_agent}]},
    ]

    max_turns = 5  # Safety break for tool use loop
    current_turn = 0
    final_text_response = ""

    try:
        while current_turn < max_turns:
            current_turn += 1
            logger.debug(
                f"Sub-agent '{target_agent_name}' turn {current_turn}. Messages: {sub_agent_messages}"
            )

            converse_response = await asyncio.to_thread(
                bedrock_runtime.converse,
                modelId=agent_config["model_id"],
                messages=sub_agent_messages,
                toolConfig=agent_config["tools_config"],  # Pass tool config here
                # system=[{"text": agent_config["system_prompt"]}] # Alternative way to pass system prompt
            )

            logger.debug(f"Bedrock Converse API response: {converse_response}")

            output_message = converse_response.get("output", {}).get("message", {})
            stop_reason = converse_response.get("stopReason")

            # Append assistant's response (can be text or tool_use request)
            # The 'role' is already part of output_message
            sub_agent_messages.append(output_message)

            if stop_reason == "tool_use":
                tool_use_requests = [
                    content
                    for content in output_message.get("content", [])
                    if "toolUse" in content
                ]
                if not tool_use_requests:
                    final_text_response = (
                        "Sub-agent indicated tool use but provided no tool details."
                    )
                    logger.error(final_text_response)
                    break

                # For simplicity, handling one tool call per turn. Bedrock may support parallel.
                tool_request = tool_use_requests[0]["toolUse"]
                tool_name = tool_request["name"]
                tool_use_id = tool_request["toolUseId"]
                tool_input_args = tool_request["input"]

                logger.info(
                    f"Sub-Agent '{target_agent_name}' wants to use tool: {tool_name} with args: {tool_input_args}"
                )

                if tool_name in tool_handlers:
                    tool_function = tool_handlers[tool_name]
                    try:
                        # Ensure args are passed correctly. tool_input_args is already a dict.
                        tool_result_data = await tool_function(**tool_input_args)
                        tool_result_content = {"json": tool_result_data}
                        tool_status = "success"
                    except Exception as e:
                        logger.error(f"Error executing tool {tool_name}: {e}")
                        tool_result_content = {
                            "text": f"Error executing tool {tool_name}: {str(e)}"
                        }
                        tool_status = "error"

                    # Construct tool result message to send back to Nova Micro
                    tool_result_message = {
                        "role": "user",  # Special role for tool results
                        "content": [
                            {
                                "toolResult": {
                                    "toolUseId": tool_use_id,
                                    "content": [
                                        tool_result_content
                                    ],  # Content is a list
                                    # "status": tool_status # Optional status field
                                }
                            }
                        ],
                    }
                    sub_agent_messages.append(tool_result_message)
                else:
                    logger.error(f"Unknown tool requested by sub-agent: {tool_name}")
                    tool_error_message = {
                        "role": "user",
                        "content": [
                            {
                                "toolResult": {
                                    "toolUseId": tool_use_id,
                                    "content": [
                                        {"text": f"Tool {tool_name} is not available."}
                                    ],
                                    "status": "error",
                                }
                            }
                        ],
                    }
                    sub_agent_messages.append(tool_error_message)
                    final_text_response = (
                        f"Sub-agent requested an unknown tool: {tool_name}."
                    )
                    # Potentially break here, or let the LLM react to the tool error
                    # For now, let's let it react.

            elif (
                stop_reason == "end_turn"
                or stop_reason == "stop_sequence"
                or stop_reason == "max_tokens"
            ):
                # Model finished generating text or expects user input
                # Extract text response
                text_parts = [
                    content.get("text")
                    for content in output_message.get("content", [])
                    if "text" in content
                ]
                final_text_response = " ".join(text_parts).strip()
                logger.info(
                    f"Sub-Agent '{target_agent_name}' final text response: {final_text_response}"
                )
                break  # Exit loop as we have a final text response
            else:
                logger.error(f"Unexpected stop_reason from Bedrock: {stop_reason}")
                final_text_response = "Sub-agent stopped for an unexpected reason."
                break

        if current_turn >= max_turns and not final_text_response:
            final_text_response = "Sub-agent interaction timed out after maximum turns."
            logger.warning(final_text_response)

    except Exception as e:
        logger.error(
            f"Error during sub-agent '{target_agent_name}' interaction: {e}",
            exc_info=True,
        )
        final_text_response = (
            f"An error occurred while communicating with sub-agent {target_agent_name}."
        )

    await params.result_callback(
        {
            "result": (
                final_text_response
                if final_text_response
                else "Sub-agent did not provide a response."
            )
        }
    )


# --- Register Lead Agent's Tool ---
lead_llm.register_function(call_agent_tool_schema.name, call_agent)


# --- Main Entry: Launch the Lead Agent Pipeline ---
async def run_bot(
    webrtc_connection: SmallWebRTCConnection, args: argparse.Namespace
):  # Added args type
    logger.info(
        "Starting multi-agent bot (Lead: Nova Sonic, Sub-Agents: Nova Micro via Bedrock)"
    )

    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(
                    stop_secs=(
                        args.vad_stop_secs if hasattr(args, "vad_stop_secs") else 0.8
                    ),
                    confidence=0.7,
                    start_secs=0.2,
                    min_volume=0.6,
                )
            ),
        ),
    )

    # Use a context aggregator for the lead agent for proper context management in Pipecat
    # The AWSNovaSonicLLMService (lead_llm) should provide a method to create its compatible aggregator.
    lead_context_aggregator = lead_llm.create_context_aggregator(lead_context)
    # Or, if AWSNovaSonicLLMService has its own:
    # lead_context_aggregator = lead_llm.create_context_aggregator(lead_context) # Check Pipecat docs for AWSNovaSonicLLMService

    pipeline = Pipeline(
        [
            transport.input(),
            lead_context_aggregator.user(),  # Process user input and update context
            lead_llm,  # Lead agent (AWS Nova Sonic)
            transport.output(),
            lead_context_aggregator.assistant(),  # Process assistant output and update context
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,  # Good for voice
            enable_metrics=True,
            enable_usage_metrics=True,
            report_only_initial_ttfb=True,  # Useful for latency measurement
            audio_output_enabled=True,  # Explicitly enable audio output
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(
        transport_param, client_param
    ):  # Renamed params to avoid conflict
        logger.info(f"Client connected to Lead Agent: {client_param}")
        # Queue the initial context frame to start the conversation
        await task.queue_frames([lead_context_aggregator.user().get_context_frame()])
        # Trigger the initial assistant response
        await lead_llm.trigger_assistant_response()

    @transport.event_handler("on_client_closed")
    async def on_client_closed(transport_param, client_param):  # Renamed params
        logger.info(f"Client disconnected from Lead Agent: {client_param}")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=True)  # Allow Ctrl+C to stop
    await runner.run(task)


if __name__ == "__main__":
    # Basic argument parsing for VAD, etc.
    # This typically comes from a run.py or similar in Pipecat examples.
    # For simplicity, we'll define a minimal args object here if not running through a main script.

    # If you have a run.py similar to pipecat examples:
    # from run import main (or your entry point)
    # main()
    # Else, for standalone execution:
    parser = argparse.ArgumentParser(description="Multi-agent Pipecat bot")
    parser.add_argument(
        "--vad_stop_secs",
        type=float,
        default=0.8,
        help="Seconds of silence to consider for VAD stop.",
    )
    # Add other relevant arguments from your Pipecat setup if needed

    # Placeholder for WebRTC connection setup - this is usually handled by a higher-level script in Pipecat examples
    # that sets up the WebRTC server and then calls run_bot for each connection.
    # For this snippet to be runnable directly, you'd need to mock or set up a SmallWebRTCConnection.
    # This part is highly dependent on your Pipecat project structure.

    # Example of how it might be invoked (conceptual, as WebRTC setup is external)
    # async def main_async():
    #     # Dummy connection for conceptual testing if not running in full Pipecat server
    #     class DummyWebRTCConnection:
    #         async def close(self): logger.info("Dummy WebRTC closed")
    #         async def send_message(self, message): logger.info(f"Dummy WebRTC send: {message}")
    #         async def recv_message(self): await asyncio.sleep(0.1); return None # Keep alive

    #     args = parser.parse_args()
    #     # In a real scenario, webrtc_connection comes from the transport server
    #     # await run_bot(DummyWebRTCConnection(), args)

    # if os.getenv("RUN_STANDALONE_CONCEPT_TEST"): # Define this env var to run the conceptual test
    #    asyncio.run(main_async())
    # else:
    #    logger.info("This script is intended to be run within a Pipecat WebRTC server environment.")
    #    logger.info("To run with a full Pipecat setup, integrate with your existing 'run.py' or similar.")

    # The following is a more common pattern if you have a `run.py` like in pipecat-ai/pipecat/examples/small-webrtc-server
    # Assuming you might adapt that structure:
    logger.warning(
        "To run this, you typically need a WebRTC server setup from Pipecat examples."
    )
    logger.warning(
        "This main block is a placeholder. Integrate `run_bot` into your Pipecat server runner."
    )

    # If your run.py from pipecat examples has a main() that sets up WebRTC server:
    # from run import main # Assuming your run.py is in the Python path and has main()
    # main() # This would start the server, and run_bot would be called by it on new connections.
