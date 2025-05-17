# food_ordering_flow.py
# Static food ordering flow for Agent2 (Pipecat Flows style)

from typing import Any, Dict, Optional

from loguru import logger


class FlowArgs(dict):
    pass


class FlowResult(dict):
    pass


class FlowConfig:
    def __init__(self, states: Dict[str, Any], initial_state: str):
        self.states = states
        self.initial_state = initial_state


class FlowManager:
    def __init__(self, flow_config: FlowConfig):
        self.flow_config = flow_config
        self.state = flow_config.initial_state
        self.context = {}
        self.customer_email = None

    async def process_user_input(self, user_input: str) -> Dict[str, str]:
        current_state = self.flow_config.states[self.state]

        # Handle email collection if in end state
        if self.state == "end":
            if self.customer_email:  # If we already have an email, don't ask again
                return {"response": "Your order is complete! Thank you for your order."}

            # Check if input contains an email
            if "@" in user_input and "." in user_input:
                self.customer_email = user_input
                order_details = self._format_order_details()
                if order_details:
                    try:
                        from multiPhone import zapier_gmail_tool_impl

                        result = await zapier_gmail_tool_impl(
                            self.customer_email, order_details
                        )
                        if result["success"]:
                            return {
                                "response": "Order confirmation email has been sent to your email address. Thank you for your order!"
                            }
                        else:
                            return {
                                "response": "Your order is complete, but I couldn't send the confirmation email. Please contact support."
                            }
                    except Exception as e:
                        logger.error(f"Error sending confirmation email: {e}")
                        return {
                            "response": "Your order is complete, but I couldn't send the confirmation email. Please contact support."
                        }

            # If no email provided, ask for it
            return {
                "response": "Please provide your email address for order confirmation."
            }

        # Process input based on current state
        for function in current_state.get("functions", []):
            if function.get("handler"):
                try:
                    result = await function["handler"](
                        FlowArgs({"input": user_input, "context": self.context})
                    )
                    if result:
                        self.context.update(result)
                        if function.get("transition"):
                            # Handle both string and callable transitions
                            if callable(function["transition"]):
                                next_state = function["transition"](result)
                                if next_state:
                                    self.state = next_state
                                    # Return the prompt for the new state
                                    return {
                                        "response": self.flow_config.states[next_state][
                                            "prompt"
                                        ]
                                    }
                            else:
                                self.state = function["transition"]
                                # Return the prompt for the new state
                                return {
                                    "response": self.flow_config.states[
                                        function["transition"]
                                    ]["prompt"]
                                }
                except Exception as e:
                    logger.error(
                        f"Error processing function {function.get('name')}: {e}"
                    )

        # If no function handled the input, return the current state's prompt
        return {"response": current_state.get("prompt", "")}

    def _format_order_details(self) -> Optional[str]:
        if "size" in self.context and "type" in self.context:
            return f"""
            Order Confirmation

            Your order has been received:
            - Item: {self.context['size']} {self.context['type']} pizza
            - Price: ${self.context.get('price', 'N/A')}
            - Status: Confirmed
            - Estimated preparation time: 20-30 minutes

            Thank you for your order!
            """
        elif "count" in self.context and "type" in self.context:
            return f"""
            Order Confirmation

            Your order has been received:
            - Item: {self.context['count']} {self.context['type']} roll(s)
            - Price: ${self.context.get('price', 'N/A')}
            - Status: Confirmed
            - Estimated preparation time: 15-25 minutes

            Thank you for your order!
            """
        return None

    def get_state(self) -> str:
        return self.state

    def get_context(self) -> dict:
        return self.context.copy()


# Type definitions
class PizzaOrderResult(FlowResult):
    size: str
    type: str
    price: float


class SushiOrderResult(FlowResult):
    count: int
    type: str
    price: float


# Function handlers
async def parse_choice(args: FlowArgs) -> Optional[Dict[str, Any]]:
    input_text = args["input"].lower()
    if "pizza" in input_text:
        return {"choice": "pizza"}
    elif "sushi" in input_text:
        return {"choice": "sushi"}
    return None


async def parse_pizza_size(args: FlowArgs) -> Optional[Dict[str, Any]]:
    input_text = args["input"].lower()
    size_map = {"small": "small", "medium": "medium", "large": "large"}
    for key, value in size_map.items():
        if key in input_text:
            return {"size": value}
    return None


async def parse_pizza_type(args: FlowArgs) -> Optional[Dict[str, Any]]:
    input_text = args["input"].lower()
    type_map = {
        "cheese": "cheese",
        "pepperoni": "pepperoni",
        "vegetarian": "vegetarian",
        "supreme": "supreme",
    }
    for key, value in type_map.items():
        if key in input_text:
            return {"type": value}
    return None


async def parse_sushi_count(args: FlowArgs) -> Optional[Dict[str, Any]]:
    input_text = args["input"].lower()
    words = input_text.split()
    number_map = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }

    for word in words:
        if word.isdigit():
            return {"count": int(word)}
        if word in number_map:
            return {"count": number_map[word]}
    return None


async def parse_sushi_type(args: FlowArgs) -> Optional[Dict[str, Any]]:
    input_text = args["input"].lower()
    type_map = {
        "california": "california",
        "spicy tuna": "spicy tuna",
        "salmon": "salmon",
        "dragon": "dragon",
        "tempura": "tempura",
    }
    for key, value in type_map.items():
        if key in input_text:
            return {"type": value}
    return None


async def calculate_pizza_price(args: FlowArgs) -> PizzaOrderResult:
    size = args["context"]["size"]
    pizza_type = args["context"]["type"]
    base_price = {"small": 10.00, "medium": 15.00, "large": 20.00}
    price = base_price[size]
    return {"size": size, "type": pizza_type, "price": price}


async def calculate_sushi_price(args: FlowArgs) -> SushiOrderResult:
    count = args["context"]["count"]
    roll_type = args["context"]["type"]
    price = 8.0 * count
    return {"count": count, "type": roll_type, "price": price}


async def confirm_order(args: FlowArgs) -> Optional[Dict[str, Any]]:
    input_text = args["input"].lower()
    if "@" in input_text and "." in input_text:
        return {"confirmed": True, "email": input_text}
    if "yes" in input_text or "complete" in input_text:
        return {"confirmed": True}
    elif "no" in input_text or "cancel" in input_text:
        return {"confirmed": False}
    return None


# Flow configuration
flow_config = FlowConfig(
    states={
        "start": {
            "prompt": "Welcome! Would you like to order pizza or sushi?",
            "functions": [
                {
                    "name": "parse_choice",
                    "handler": parse_choice,
                    "transition": lambda result: (
                        "choose_pizza_size"
                        if result.get("choice") == "pizza"
                        else "choose_sushi_count"
                    ),
                }
            ],
        },
        "choose_pizza_size": {
            "prompt": "What size pizza would you like? We have small ($10), medium ($15), or large ($20).",
            "functions": [
                {
                    "name": "parse_size",
                    "handler": parse_pizza_size,
                    "transition": "choose_pizza_type",
                }
            ],
        },
        "choose_pizza_type": {
            "prompt": "What type of pizza would you like? We have cheese, pepperoni, vegetarian, or supreme.",
            "functions": [
                {
                    "name": "parse_type",
                    "handler": parse_pizza_type,
                    "transition": "confirm",
                }
            ],
        },
        "choose_sushi_count": {
            "prompt": "How many rolls would you like? We have California, Spicy Tuna, Salmon, Dragon, and Tempura rolls. Each roll is $8.",
            "functions": [
                {
                    "name": "parse_count",
                    "handler": parse_sushi_count,
                    "transition": "choose_sushi_type",
                }
            ],
        },
        "choose_sushi_type": {
            "prompt": "What type of roll would you like? We have California, Spicy Tuna, Salmon, Dragon, and Tempura rolls.",
            "functions": [
                {
                    "name": "parse_type",
                    "handler": parse_sushi_type,
                    "transition": "confirm",
                }
            ],
        },
        "confirm": {
            "prompt": "Would you like to complete this order? Please provide your email address for order confirmation.",
            "functions": [
                {
                    "name": "confirm",
                    "handler": confirm_order,
                    "transition": lambda result: (
                        "end" if result.get("confirmed") else "start"
                    ),
                }
            ],
        },
        "end": {
            "prompt": "Please provide your email address for order confirmation.",
            "functions": [],
        },
    },
    initial_state="start",
)
