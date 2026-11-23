"""A prompt that also says what it asks and carries its inputs.

Real providers only see the text (a Prompt is a str). A stand-in AI such as mock/ai.py reads `task` and `data`
instead of parsing the wording, so rewording a prompt can never silently break it.
"""

# The tasks the app asks the AI for. mock/ai.py must answer each one; a test checks that it does.
TASKS = ("test", "assess_type", "dependencies", "select_sources", "plan")


class Prompt(str):
    task: str
    data: dict

    def __new__(cls, text: str, task: str, **data):
        if task not in TASKS:
            raise ValueError(f"unknown AI task '{task}'")
        obj = super().__new__(cls, text)
        obj.task, obj.data = task, data
        return obj
