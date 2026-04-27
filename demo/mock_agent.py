"""Demo mock agent server for testing ATTEST.

This simulates a customer support AI agent with:
- Greeting responses
- Order lookup (tool call)
- Refund processing (tool call)
- Safety guardrails (refuses harmful requests)
- FAQ answers

Run this server, then use `attest run` against it.

Usage:
    python demo/mock_agent.py
    # Server starts on http://localhost:9999
    # Then in another terminal: attest run
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 9999


class CustomerSupportAgent(BaseHTTPRequestHandler):
    """A mock AI customer support agent."""

    def do_POST(self):
        # Parse request
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length)) if content_length else {}
        user_message = body.get("message", "").lower()

        # Route to handler based on content
        response = self._handle_message(user_message)

        # Send response
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

    def do_GET(self):
        """Health check endpoint."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "healthy", "agent": "CustomerSupportBot v1.0"}).encode())

    def _handle_message(self, message: str) -> dict:
        """Route messages to the right handler."""

        # Greetings
        if any(word in message for word in ["hello", "hi", "hey", "good morning"]):
            return {
                "response": "Hello! Welcome to our support center. How can I help you today?",
                "tool_calls": [],
            }

        # Order tracking
        if "track" in message or "where is my order" in message or "order status" in message:
            order_id = self._extract_order_id(message)
            return {
                "response": f"I've looked up order #{order_id}. It's currently out for delivery and should arrive by tomorrow.",
                "tool_calls": [
                    {"name": "lookup_order", "arguments": {"order_id": order_id}}
                ],
            }

        # Refund requests
        if "refund" in message or "return" in message or "money back" in message:
            order_id = self._extract_order_id(message)
            return {
                "response": f"I've initiated a full refund for order #{order_id}. You'll receive it within 3-5 business days.",
                "tool_calls": [
                    {"name": "lookup_order", "arguments": {"order_id": order_id}},
                    {"name": "process_refund", "arguments": {"order_id": order_id, "amount": "full"}},
                ],
            }

        # Return policy
        if "return policy" in message or "refund policy" in message:
            return {
                "response": "Our return policy allows returns within 30 days of purchase for a full refund. Items must be in original condition.",
                "tool_calls": [],
            }

        # Shipping info
        if "shipping" in message or "deliver" in message:
            return {
                "response": "We offer free standard shipping (5-7 days) and express shipping ($9.99, 2-3 days). We ship to all 50 US states and 30+ international destinations.",
                "tool_calls": [],
            }

        # Payment methods
        if "payment" in message or "pay" in message:
            return {
                "response": "We accept Visa, Mastercard, American Express, PayPal, and Apple Pay.",
                "tool_calls": [],
            }

        # Safety guardrails — refuse harmful requests
        if any(word in message for word in ["hack", "steal", "attack", "exploit", "illegal"]):
            return {
                "response": "I'm sorry, but I can't assist with that request. I'm here to help with customer support questions only. Is there anything else I can help you with?",
                "tool_calls": [],
            }

        # Escalation
        if "speak to" in message or "manager" in message or "human" in message:
            return {
                "response": "I understand you'd like to speak with a human agent. Let me transfer you now. Please hold while I connect you.",
                "tool_calls": [
                    {"name": "transfer_to_human", "arguments": {"reason": "customer_request"}}
                ],
            }

        # Default / catch-all
        return {
            "response": f"Thank you for your question. Let me look into that for you. Could you provide more details about what you need help with?",
            "tool_calls": [],
        }

    def _extract_order_id(self, message: str) -> str:
        """Extract order ID from message, or return a default."""
        import re
        match = re.search(r"#?(\d{4,})", message)
        return match.group(1) if match else "12345"

    def log_message(self, format, *args):
        """Custom log format."""
        print(f"  [Agent] {args[0]}")


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), CustomerSupportAgent)
    print(f"""
╔══════════════════════════════════════════════════╗
║  🤖 Customer Support Agent — DEMO SERVER         ║
║                                                  ║
║  Running on: http://localhost:{PORT}               ║
║                                                  ║
║  Ready for ATTEST testing!                       ║
║  Open another terminal and run:                  ║
║    attest run                                    ║
║                                                  ║
║  Press Ctrl+C to stop                            ║
╚══════════════════════════════════════════════════╝
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
        server.shutdown()
