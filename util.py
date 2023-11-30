import os
import asyncio
from dataclasses import dataclass
from typing import Optional, List

import discord
from discord import app_commands

import openai

from dotenv import load_dotenv

load_dotenv()
SEPARATOR_TOKEN = "<|endoftext|>"
SYSTEM_PROMPT = os.getenv('SYSTEM_PROMPT')

@dataclass(frozen=True)
class MessageS:
    user: str
    text: Optional[str] = None

    def render(self):
        result = self.user + ":"
        if self.text is not None:
            result += " " + self.text
        return result

@dataclass
class Conversation:
    messages: List[MessageS]

    def prepend(self, message: MessageS):
        self.messages.insert(0, message)
        return self

    def render(self):
        return f"\n{SEPARATOR_TOKEN}".join(
            [message.render() for message in self.messages]
        )

@dataclass(frozen=True)
class Prompt:
    header: MessageS
    convo: Conversation

    def full_render(self, bot_name):
        messages = [
            {
                "role": "system",
                "content": f'{SYSTEM_PROMPT}',
            }
        ]
        for message in self.render_messages(bot_name):
            messages.append(message)
        return messages

    # def render_system_prompt(self):
    #     return f"\n{SEPARATOR_TOKEN}".join(
    #         [self.header.render()]
    #         + [MessageS("System", SYSTEM_PROMPT).render()]
    #         # + [conversation.render() for conversation in self.examples]
    #         # + [
    #         #     MessageS(
    #         #         "System", "Now, you will work with the actual current conversation."
    #         #     ).render()
    #         # ]
    #     )

    def render_messages(self, bot_name):
        for message in self.convo.messages:
            if not bot_name in message.user:
                yield {
                    "role": "user",
                    "content": f'{message.user}: {message.text}',
                }
            else:
                yield {
                    "role": "assistant",
                    "content": message.text,
                }


def discord_message_to_message(message: discord.Message) -> Optional[MessageS]:
    if (
        message.type == discord.MessageType.thread_starter_message
        and message.reference.cached_message
        and len(message.reference.cached_message.embeds) > 0
        and len(message.reference.cached_message.embeds[0].fields) > 0
    ):
        field = message.reference.cached_message.embeds[0].fields[0]
        if field.value:
            return MessageS(user=field.name, text=field.value)
    else:
        if message.content:
            return MessageS(user=message.author.name, text=message.content)
    return None

def split_into_shorter_messages(message: str) -> List[str]:
    return [
        message[i : i + 2000]
        for i in range(0, len(message), 2000)
    ]
