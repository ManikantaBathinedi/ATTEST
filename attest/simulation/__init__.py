"""User simulation module.

Simulates realistic user behavior to stress-test agents beyond hand-written scripts.
An LLM plays a user with a persona and goal, conversing with the agent under test
for multiple turns, then evaluators judge the full conversation.
"""

from attest.simulation.user_simulator import UserSimulator, SimulationResult

__all__ = ["UserSimulator", "SimulationResult"]
