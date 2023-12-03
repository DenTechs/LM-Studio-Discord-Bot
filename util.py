import os
import asyncio
from dataclasses import dataclass
from typing import Optional, List
import re

import discord
from discord import app_commands

import openai

from dotenv import load_dotenv

load_dotenv()
SEPARATOR_TOKEN = "<|endoftext|>"

@dataclass(frozen=False)
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

    def full_render(self, bot_name, messageOG: discord.Message, system_prompt: str, initial_personality: str):
        messages = [
            {
                "role": "system",
                "content": f'{system_prompt}',
            }
        ]
        for message in self.render_messages(bot_name, messageOG, initial_personality):
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

    def render_messages(self, bot_name, messageOG: discord.Message, initial_personality: str):
        for message in self.convo.messages:

            #print(f'Message: {message.text}')
            mention_pattern = r'<@!?(\d+)>'
        
            # Find all mentions in the message
            user_ids = re.findall(mention_pattern, message.text)
            #print(f'Found IDs: {user_ids}')

            for user_id in user_ids:
                # Get member object from the guild using user_id
                member = messageOG.guild.get_member(int(user_id))
                #print(f'Found member: {member}')

                if member:
                    # Use member's nickname or name if nickname is None
                    nickname = member.nick if member.nick else member.name
                    if nickname == bot_name:
                        nickname = initial_personality
                    #print(f'Found nickname for ID: {nickname}')
                    # Replace the mention with the nickname
                    mention_str = f'<@!{user_id}>' if '!' in message.text else f'<@{user_id}>'
                    message.text = message.text.replace(mention_str, nickname)
                    #print(f'changed to: {message.text}')

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
    if message.mentions:
        mention_str = ''.join(f'<@{user.id}>' for user in message.mentions)
        #print(f'message: {message.content}\nmention_str: {mention_str}')
        if message.content.strip() == mention_str:
            #print("The message contains only a mention.")
            return
        else:
            nickname = message.author.nick if message.author.nick else message.author.name

            return MessageS(user=nickname, text=message.content)
    else:
        if message.content:
            nickname = message.author.nick if message.author.nick else message.author.name
            return MessageS(user=nickname, text=message.content)
    return None

def split_into_shorter_messages(message: str) -> List[str]:
    return [
        message[i : i + 2000]
        for i in range(0, len(message), 2000)
    ]
