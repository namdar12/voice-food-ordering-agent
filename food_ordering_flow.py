# food_ordering_flow.py
# Static food ordering flow for Agent2 (Pipecat Flows style)

# Define minimal stubs for FlowArgs, FlowConfig, FlowManager, FlowResult if not available
from typing import Any, Dict


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

    async def process_user_input(self, user_input: str) -> Dict[str, str]:
        # Minimal state machine logic for demo/testing
        # In real use, replace with actual Pipecat Flows logic
        # For now, just echo the state and input
        response = f"[State: {self.state}] {user_input}"
        # Simulate state transition
        if self.state == "start":
            if "pizza" in user_input.lower():
                self.state = "choose_pizza_size"
                response = "What size pizza would you like? We have small ($10), medium ($15), or large ($20)."
            elif "sushi" in user_input.lower():
                self.state = "choose_sushi"
                response = "How many rolls and what type of sushi?"
            else:
                response = "Please say pizza or sushi."
        elif self.state == "choose_pizza_size":
            size = user_input.lower().strip()
            if size in ["small", "medium", "large"]:
                self.context["size"] = size
                self.state = "choose_pizza_type"
                response = "What type of pizza would you like? We have cheese, pepperoni, vegetarian, or supreme."
            else:
                response = "Please choose small, medium, or large."
        elif self.state == "choose_pizza_type":
            pizza_type = user_input.lower().strip()
            if pizza_type in ["cheese", "pepperoni", "vegetarian", "supreme"]:
                self.context["type"] = pizza_type
                self.state = "confirm"
                response = f"Great! You've ordered a {self.context['size']} {self.context['type']} pizza. Would you like to complete this order?"
            else:
                response = "Please choose cheese, pepperoni, vegetarian, or supreme."
        elif self.state == "choose_sushi":
            self.state = "confirm"
            response = "Review your sushi order. Would you like to complete it?"
        elif self.state == "confirm":
            if "yes" in user_input.lower() or "complete" in user_input.lower():
                self.state = "end"
                if "size" in self.context and "type" in self.context:
                    response = f"Thank you for your order! Your {self.context['size']} {self.context['type']} pizza will be ready soon."
                else:
                    response = "Thank you for your order!"
            else:
                self.state = "start"
                response = "Order cancelled. Would you like to start over?"
        elif self.state == "end":
            response = "Order complete."
        return {"response": response}


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
async def select_pizza_order(args: FlowArgs) -> PizzaOrderResult:
    size = args["size"]
    pizza_type = args["type"]
    base_price = {"small": 10.00, "medium": 15.00, "large": 20.00}
    price = base_price[size]
    return {"size": size, "type": pizza_type, "price": price}


async def select_sushi_order(args: FlowArgs) -> SushiOrderResult:
    count = args["count"]
    roll_type = args["type"]
    price = 8.0 * count
    return {"count": count, "type": roll_type, "price": price}


# Flow configuration (static, as in the example)
flow_config = FlowConfig(
    states={
        "start": {
            "prompt": "Welcome! Would you like to order pizza or sushi?",
            "functions": [
                {"name": "choose_pizza", "transition": "choose_pizza"},
                {"name": "choose_sushi", "transition": "choose_sushi"},
            ],
        },
        "choose_pizza": {
            "prompt": "What size pizza (small, medium, large) and what type?",
            "functions": [
                {"name": "select_pizza_order", "handler": select_pizza_order},
                {"name": "confirm_order", "transition": "confirm"},
            ],
        },
        "choose_sushi": {
            "prompt": "How many rolls and what type of sushi?",
            "functions": [
                {"name": "select_sushi_order", "handler": select_sushi_order},
                {"name": "confirm_order", "transition": "confirm"},
            ],
        },
        "confirm": {
            "prompt": "Review your order. Would you like to complete it?",
            "functions": [
                {"name": "complete_order", "transition": "end"},
            ],
        },
        "end": {
            "prompt": "Thank you for your order!",
            "functions": [],
            "post_actions": [{"type": "end_conversation"}],
        },
    },
    initial_state="start",
)
