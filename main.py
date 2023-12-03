import os
import asyncio
from dataclasses import dataclass
from typing import Optional, List
import re

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

from prompts import (
    default_personality,
    get_prompt_from_name,
    get_personalities,
    personalities_dict,
)

load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
ALLOWED_SERVER_IDS: List[int] = []
server_ids = os.environ["ALLOWED_SERVER_IDS"].split(",")
for s in server_ids:
    ALLOWED_SERVER_IDS.append(int(s))
ALLOWED_CHANNEL_IDS: List[int] = []
channel_ids = os.environ["ALLOWED_CHANNEL_IDS"].split(",")
if channel_ids[0] != '':
    for c in channel_ids:
        ALLOWED_CHANNEL_IDS.append(int(c))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)

SECONDS_DELAY_RECEIVING_MSG=1

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
@app_commands.describe(message=f"The first message to start the chat with (default: {default_personality})")
@app_commands.describe(name=f"The name of the personality to interact with (default: {default_personality})")
@app_commands.describe(hidden=f"Should the thread be hidden? (default: True)")
@app_commands.choices(name=[
    app_commands.Choice(name=personality, value=personality)
    for personality in personalities_dict.keys()
])
async def slash_chat(
    interaction: discord.Interaction,
    message: str,  
    name: str = default_personality,
    hidden: bool = True,
):
    try:
        # only support creating thread in text channel
        if not isinstance(interaction.channel, discord.TextChannel):
            raise Exception("Not in text channel")           

        # block servers not in allow list
        if interaction.guild.id not in ALLOWED_SERVER_IDS:
            # not allowed in this server
            raise Exception(f"Guild {interaction.guild} is not whitelisted")
        
        #block channels not in allow list
        if interaction.channel.id not in ALLOWED_CHANNEL_IDS and len(ALLOWED_CHANNEL_IDS) != 0:
            raise Exception(f"Channel {interaction.channel} is not whitelisted")

        mention_pattern = r'<@!?(\d+)>'
    
        # Find all mentions in the message
        user_ids = re.findall(mention_pattern, message)

        for user_id in user_ids:
            # Get member object from the guild using user_id
            member = interaction.guild.get_member(int(user_id))
            if member:
                # Use member's nickname or name if nickname is None
                nickname = member.nick if member.nick else member.name
                # Replace the mention with the nickname
                mention_str = f'<@!{user_id}>' if '!' in message else f'<@{user_id}>'
                message = message.replace(mention_str, nickname)


        print(f'{interaction.user.name} created a thread: ' + message)

        embed = discord.Embed(
            description=f"<@{interaction.user.id}> started a chat with {name}",
            color=discord.Color.green(),
        )
        
        await interaction.response.send_message(embed=embed)
        embed.add_field(name=interaction.user.name, value=message)
        response = await interaction.original_response()

        if hidden:
            channel_type = discord.ChannelType.private_thread
        else:
            channel_type = discord.ChannelType.public_thread

        thread = await interaction.channel.create_thread(
            name = f"{interaction.user.name} - {name}",
            reason = "gpt-bot", 
            slowmode_delay=1,
            type = channel_type,
        )
        await thread.send(content=f'{interaction.user.mention}', embed=embed)
        async with thread.typing(): 
            completion = await openai.ChatCompletion.acreate(
                model="local-model",
                messages=[
                    {"role": "system", "content": get_prompt_from_name(name)},
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
        try:
            await interaction.response.send_message(
                f"Failed to start thread: {str(e)}", ephemeral=True
            )
            return
        except Exception as e:
            print(f'{e}')
        return


@client.event
async def on_message(message: discord.Message):
    try:
        #check message isn't actually a command
        if message.type != discord.MessageType.default and message.type != discord.MessageType.reply:
            return

        # block servers not in allow list
        if message.guild.id not in ALLOWED_SERVER_IDS:
            # not allowed in this server
            raise Exception(f"Guild {message.guild} is not whitelisted")
        
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

        initial_embed = [message async for message in thread.history(limit=1,oldest_first=True)]
        initial_embed_author = initial_embed[0].author.nick if initial_embed[0].author.nick else initial_embed[0].author.name
        initial_embed_description = initial_embed[0].embeds[0].description

        pattern = r"started a chat with (.*)"
        initial_personality = re.search(pattern, initial_embed_description).group(1)
        print(f'Initial personality: {initial_personality}')

        channel_messages = [
            discord_message_to_message(message) 
            async for message in thread.history()
        ]

        first_message: MessageS = MessageS(user=initial_embed_author, text=initial_embed[0].embeds[0].fields[0].value)
        channel_messages.append(first_message)

        #print(f'{channel_messages}')
        channel_messages = [x for x in channel_messages if x is not None]
        channel_messages.reverse()

        

        prompt = Prompt(
            header=MessageS(
                "system", f""
            ),
            convo=Conversation(channel_messages),
        )

        #print(f'{prompt.full_render(MY_BOT_NAME)}')


        bot_name = message.guild.me.nick if message.guild.me.nick else message.guild.me.name
        async with thread.typing():
            completion = await openai.ChatCompletion.acreate(
            model="local-model",
            messages=prompt.full_render(bot_name,message,get_prompt_from_name(initial_personality),initial_personality)
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
        try:
            await thread.send(
                f"Failed to start thread: {str(e)}"
            )
            return
        except Exception as e:
            print(f'{e}')
        return

@tree.command(name="personalities", description="Get the list of available personalities")
@discord.app_commands.checks.has_permissions(send_messages=True)
@discord.app_commands.checks.has_permissions(view_channel=True)
@discord.app_commands.checks.bot_has_permissions(send_messages=True)
@discord.app_commands.checks.bot_has_permissions(view_channel=True)
@discord.app_commands.checks.bot_has_permissions(manage_threads=True)
async def slash_personalities(
    interaction: discord.Interaction,
):  
    await interaction.response.send_message(get_personalities())

@tree.command(name="clear_threads", description="Deletes all threads on server")
@discord.app_commands.checks.has_permissions(send_messages=True)
@discord.app_commands.checks.has_permissions(view_channel=True)
@discord.app_commands.checks.has_permissions(administrator=True)
@discord.app_commands.checks.bot_has_permissions(send_messages=True)
@discord.app_commands.checks.bot_has_permissions(view_channel=True)
@discord.app_commands.checks.bot_has_permissions(manage_threads=True)
@app_commands.describe(verify=f"""Are you sure you want delete all threads? Type "yes" to confirm""")
async def slash_clear_threads(
    interaction: discord.Interaction,
    verify: str,
):  
    try:
        if verify != "yes":
            await interaction.response.send_message(f'verify was not "yes:", canceled', ephemeral=True)
            return

        threads = interaction.guild.threads
        
        bot_threads = [thread for thread in threads if thread.owner_id == client.user.id]

        if len(bot_threads) == 0:
            await interaction.response.send_message(f"No threads to delete", ephemeral=True)
            return

        for thread in bot_threads:
            try:
                await thread.delete()
            except Exception as e:
                print(f"Error deleting thread {thread.name}: {e}")
        await interaction.response.send_message(f"Deleted {len(bot_threads)} thread(s)", ephemeral=True)

    except Exception as e:
        print(f'{e}')
    return

client.run(TOKEN)       