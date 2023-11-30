import os
import asyncio
from dataclasses import dataclass
from typing import Optional, List


import discord
from discord import app_commands

import openai

from dotenv import load_dotenv

from util import (
    MessageS,
    Prompt,
    discord_message_to_message,
    Conversation,
    split_into_shorter_messages,
)

load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
SYSTEM_PROMPT = os.getenv('SYSTEM_PROMPT')
ALLOWED_SERVER_IDS: List[int] = []
server_ids = os.environ["ALLOWED_SERVER_IDS"].split(",")
for s in server_ids:
    ALLOWED_SERVER_IDS.append(int(s))
SECONDS_DELAY_RECEIVING_MSG = 3

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)


openai.api_base = "http://localhost:1234/v1"
openai.api_key = ""



@client.event
async def on_ready():
    print(f'{client.user} has connected to Discord!')
    global MY_BOT_NAME
    MY_BOT_NAME=client.user.name
    await tree.sync()


@tree.command(name="chat", description="Create a new thread for conversation")
@discord.app_commands.checks.has_permissions(send_messages=True)
@discord.app_commands.checks.has_permissions(view_channel=True)
@discord.app_commands.checks.bot_has_permissions(send_messages=True)
@discord.app_commands.checks.bot_has_permissions(view_channel=True)
@discord.app_commands.checks.bot_has_permissions(manage_threads=True)
@app_commands.describe(message="The first prompt to start the chat with")
async def slash_command(
    interaction: discord.Interaction,
    message: str,
):
    try:
        # only support creating thread in text channel
        if not isinstance(interaction.channel, discord.TextChannel):
            return

        # block servers not in allow list
        if interaction.guild.id not in ALLOWED_SERVER_IDS:
            # not allowed in this server
            print(f"Guild {interaction.guild} not allowed")
            return 
        
        print(f'{interaction.user.name} created a thread: ' + message)

        embed = discord.Embed(
            description=f"<@{interaction.user.id}> started a chat",
            color=discord.Color.green(),
        )
        
        await interaction.response.send_message(embed=embed)
        embed.add_field(name=interaction.user.name, value=message)
        response = await interaction.original_response()

        thread = await interaction.channel.create_thread(
            name = f"{interaction.user.name} - {message}",
            reason = "gpt-bot", 
            slowmode_delay=1,
        )
        await thread.send(content=f'{interaction.user.mention}', embed=embed)
        async with thread.typing(): 
            completion = openai.ChatCompletion.create(
                model="local-model",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f'{interaction.user.name}:  {message}'}
                ]
            )

        #sent_message = None
        shorter_response = split_into_shorter_messages(f'{completion.choices[0].message.content.strip()}')
        for r in shorter_response:
            await thread.send(content=r)
        #await thread.send(content = f'{completion.choices[0].message.content.strip()}')

    except Exception as e:
        print(f'{e}')
        await int.response.send_message(
            f"Failed to start chat {str(e)}", ephemeral=True
        )


@client.event
async def on_message(message: discord.Message):
    try:
        # block servers not in allow list
        if message.guild.id not in ALLOWED_SERVER_IDS:
            # not allowed in this server
            print(f"Guild {message.guild} not allowed")
            return 

        # ignore messages from the bot
        if message.author == client.user:
            return

        # ignore messages not in a thread
        channel = message.channel
        if not isinstance(channel, discord.Thread):
            return

        # ignore threads not created by the bot
        thread = channel
        if thread.owner_id != client.user.id:
            return
        
        # ignore threads that are archived or locked
        if (
            thread.archived
            or thread.locked
        ):
            # ignore this thread
            return

        #filter messages that are only mentions (invites to thread)
        if message.mentions:
            mention_str = ''.join(f'<@{user.id}>' for user in message.mentions)
            if message.content.strip() == mention_str:
                print("The message contains only a mention.")
                return


        if SECONDS_DELAY_RECEIVING_MSG > 0:
            await asyncio.sleep(SECONDS_DELAY_RECEIVING_MSG)
            if message.id != thread.last_message.id and thread.last_message.author != client.user.id:
                # there is another message, so ignore this one
                return
        
        print(f'Recieved message from {message.author}: {message.content}')

        channel_messages = [
            discord_message_to_message(message)
            async for message in thread.history()
        ]

        channel_messages = [x for x in channel_messages if x is not None]
        channel_messages.reverse()

        #print(f'{channel_messages}')

        prompt = Prompt(
            header=MessageS(
                "system", f""
            ),
            convo=Conversation(channel_messages),
        )

        #print(f'{prompt.full_render(MY_BOT_NAME)}')

        async with thread.typing():
            completion = openai.ChatCompletion.create(
            model="local-model",
            messages=prompt.full_render(MY_BOT_NAME)
        )
            
        if SECONDS_DELAY_RECEIVING_MSG > 0:
            await asyncio.sleep(SECONDS_DELAY_RECEIVING_MSG)
            if message.id != thread.last_message.id and thread.last_message.author != client.user.id:
                # there is another message, so ignore this one
                return
            
        shorter_response = split_into_shorter_messages(f'{completion.choices[0].message.content.strip()}')
        for r in shorter_response:
            await thread.send(content=r)
        #await thread.send(content = f'{completion.choices[0].message.content.strip()}')

    except Exception as e:
        print(f'{e}')



client.run(TOKEN)       