import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import os
import traceback
import json
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_TOKEN_HERE")
if TOKEN == "YOUR_TOKEN_HERE" or TOKEN is None:
    raise RuntimeError("Discord token not configured. Set DISCORD_TOKEN in .env or environment variables.")

# Anti alt protection
MIN_ACCOUNT_AGE_DAYS = 7

# Bonus entries by role
BONUS_ENTRIES = {
    "5inv": 2,
    "10inv": 5,
    "15inv": 10,
    "30inv": 20,
    ".": 150
}

# Storage file
GIVEAWAYS_FILE = "giveaways.json"

# Logging
import logging
logging.basicConfig(filename='giveaway_bot.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

giveaways = {}

# Anti-spam: track last join time per user
join_cooldowns = {}

def load_giveaways():
    global giveaways
    try:
        if os.path.exists(GIVEAWAYS_FILE):
            with open(GIVEAWAYS_FILE, 'r') as f:
                data = json.load(f)
                # Convert string keys back to int
                giveaways = {int(k): v for k, v in data.items()}
                logging.info(f"Loaded {len(giveaways)} giveaways from storage")
    except Exception as e:
        logging.error(f"Error loading giveaways: {e}")

def load_bonus_config():
    global BONUS_ENTRIES
    try:
        if os.path.exists("bonus_config.json"):
            with open("bonus_config.json", 'r') as f:
                BONUS_ENTRIES = json.load(f)
                logging.info(f"Loaded bonus config: {BONUS_ENTRIES}")
    except Exception as e:
        logging.error(f"Error loading bonus config: {e}")

def save_giveaways():
    try:
        with open(GIVEAWAYS_FILE, 'w') as f:
            json.dump(giveaways, f, indent=2)
        logging.info(f"Saved {len(giveaways)} giveaways to storage")
    except Exception as e:
        logging.error(f"Error saving giveaways: {e}")

def format_duration(seconds):
    days = seconds // 86400
    seconds %= 86400
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts)

def parse_duration(duration_text: str):
    duration_text = duration_text.lower().replace(' ', '')
    total = 0
    number = ''
    for char in duration_text:
        if char.isdigit():
            number += char
            continue
        if char in 'dhms' and number:
            value = int(number)
            if char == 'd':
                total += value * 86400
            elif char == 'h':
                total += value * 3600
            elif char == 'm':
                total += value * 60
            elif char == 's':
                total += value
            number = ''
        else:
            raise ValueError("Invalid duration format")
    if number:
        raise ValueError("Invalid duration format")
    return total

def total_seconds(days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0):
    return days * 86400 + hours * 3600 + minutes * 60 + seconds

class GiveawayView(discord.ui.View):

    def __init__(self, gid):
        super().__init__(timeout=None)
        self.gid = gid

    @discord.ui.button(label="Enter Giveaway 🎉", style=discord.ButtonStyle.green, custom_id="giveaway_enter")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            gid = self.gid
            user = interaction.user

            logging.info(f"Giveaway join clicked by {user} ({user.id}) for giveaway {gid}")

            if gid not in giveaways:
                await interaction.response.send_message(
                    "This giveaway no longer exists.",
                    ephemeral=True
                )
                return

            required_role_id = giveaways[gid].get("required_role_id")
            if required_role_id is not None:
                member = interaction.user
                if isinstance(member, discord.Member):
                    if member.get_role(required_role_id) is None:
                        required_role = interaction.guild.get_role(required_role_id) if interaction.guild else None
                        role_name = required_role.name if required_role is not None else "required role"
                        await interaction.response.send_message(
                            f"You need the '{role_name}' role to enter this giveaway.",
                            ephemeral=True
                        )
                        return

            # Anti-spam: 3 second cooldown
            now = datetime.now(timezone.utc)
            if user.id in join_cooldowns:
                last_join = join_cooldowns[user.id]
                if (now - last_join).total_seconds() < 3:
                    await interaction.response.send_message(
                        "Please wait before joining again.",
                        ephemeral=True
                    )
                    return
            join_cooldowns[user.id] = now

            # Anti alt check
            if datetime.now(timezone.utc) - user.created_at < timedelta(days=MIN_ACCOUNT_AGE_DAYS):
                await interaction.response.send_message(
                    "Your account is too new to enter giveaways.",
                    ephemeral=True
                )
                return

            if user.id in giveaways[gid]["participants"]:
                await interaction.response.send_message(
                    "You already entered!",
                    ephemeral=True
                )
                return

            giveaways[gid]["participants"].append(user.id)
            save_giveaways()
            logging.info(f"User {user} joined giveaway {gid}")

            await interaction.response.send_message(
                "You entered the giveaway!",
                ephemeral=True
            )
        except Exception as e:
            logging.error(f"Error in enter button: {e}")
            traceback.print_exception(type(e), e, e.__traceback__)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "An error occurred while joining.",
                    ephemeral=True
                )

    @discord.ui.button(label="Participants 👥", style=discord.ButtonStyle.gray, custom_id="giveaway_participants")
    async def participants(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            gid = self.gid

            if gid not in giveaways:
                await interaction.response.send_message(
                    "This giveaway no longer exists.",
                    ephemeral=True
                )
                return

            count = len(giveaways[gid]["participants"])
            response = [f"Participants: {count}"]

            if is_admin(interaction.user):
                details = []
                for uid in giveaways[gid]["participants"]:
                    member = interaction.guild.get_member(uid)
                    if member is None:
                        details.append(f"<@{uid}> — left server")
                        continue
                    entries = calculate_entries(member)
                    details.append(f"{member.display_name}: {entries} entries")
                response.append("\n".join(details) if details else "No member details available.")

            await interaction.response.send_message(
                "\n".join(response),
                ephemeral=True
            )
        except Exception as e:
            print(f"Error in participants button: {e}")
            traceback.print_exception(type(e), e, e.__traceback__)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "An error occurred.",
                    ephemeral=True
                )


def calculate_entries(member):

    entries = 1

    for role in member.roles:
        if role.name in BONUS_ENTRIES:
            entries += BONUS_ENTRIES[role.name]

    return entries


def is_admin(member):
    return member.guild_permissions.administrator or member.guild_permissions.manage_guild


def pick_winners(members, count):

    # Filter out None members (users who left the server)
    members = [m for m in members if m is not None]

    weighted_pool = []

    for member in members:

        entries = calculate_entries(member)

        weighted_pool += [member] * entries

    winners = []

    while len(winners) < count and weighted_pool:
        winner = random.choice(weighted_pool)

        if winner not in winners:
            winners.append(winner)

    return winners


def format_duration(seconds):
    days = seconds // 86400
    seconds %= 86400
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts)


def total_seconds(days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0):
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


@bot.event
async def on_ready():
    load_giveaways()
    load_bonus_config()
    # Register persistent views for all active giveaways
    for gid in giveaways:
        bot.add_view(GiveawayView(gid))
    await bot.tree.sync()
    logging.info(f"Logged in as {bot.user}")
    print(f"Logged in as {bot.user}")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    traceback.print_exception(type(error), error, error.__traceback__)
    if not interaction.response.is_done():
        await interaction.response.send_message(
            f"An error occurred: {error}",
            ephemeral=True
        )


@app_commands.checks.has_permissions(manage_guild=True)
@bot.tree.command(name="gstart", description="Start a giveaway")
@app_commands.describe(
    prize="Prize name",
    winners="Number of winners",
    duration="Giveaway duration as a short string like 7d or 1h30m",
    color="Embed color (hex, e.g. #ff0000)",
    title="Custom embed title",
    extra_info="Optional extra message displayed in the giveaway embed (use \\n for new lines)",
    mention_role="Optional role to mention when the giveaway starts",
    ping_everyone="Mention @everyone when starting the giveaway",
    image_url="Optional image URL to display in the embed",
    image_attachment="Optional image attachment from your device",
    required_role="Optional role required to enter the giveaway"
)
async def gstart(
    interaction: discord.Interaction,
    prize: str,
    winners: int,
    duration: str,
    color: str = "9b59b6",
    title: str = "🎉 Giveaway",
    extra_info: str = "",
    mention_role: discord.Role | None = None,
    ping_everyone: bool = False,
    image_url: str = "",
    image_attachment: discord.Attachment | None = None,
    required_role: discord.Role | None = None
):

    try:
        duration_seconds = parse_duration(duration)
    except ValueError:
        await interaction.response.send_message(
            "Invalid duration format. Use values like 7d, 1h30m, or 45m.",
            ephemeral=True
        )
        return

    if duration_seconds <= 0:
        await interaction.response.send_message(
            "Please provide a duration greater than 0.",
            ephemeral=True
        )
        return

    try:
        embed_color = int(color.lstrip('#'), 16) if color.startswith('#') else int(color, 16)
    except ValueError:
        embed_color = 0x9b59b6

    description = f"Prize: **{prize}**\nWinners: {winners}\n\nClick the button below to enter!"
    if extra_info:
        description += f"\n\n{extra_info}"

    if mention_role is not None:
        description = f"{mention_role.mention}\n\n" + description
    elif ping_everyone:
        description = "@everyone\n\n" + description

    if required_role is not None:
        description += f"\n\nRole Required: {required_role.mention}"

    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "Only admins can start giveaways.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title=title,
        description=description,
        color=embed_color
    )

    if image_attachment is not None:
        embed.set_image(url=image_attachment.url)
    elif image_url:
        embed.set_image(url=image_url)

    embed.set_footer(text=f"Ends in {format_duration(duration_seconds)}")

    allowed_mentions = discord.AllowedMentions(roles=True, everyone=True, users=True)
    content = None
    if mention_role is not None:
        content = mention_role.mention
    elif ping_everyone:
        content = "@everyone"

    msg = await interaction.channel.send(content=content, embed=embed, allowed_mentions=allowed_mentions)

    giveaways[msg.id] = {
        "participants": [],
        "prize": prize,
        "winners": winners,
        "channel": interaction.channel.id,
        "guild": interaction.guild.id,
        "end_time": (datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)).isoformat(),
        "embed_color": embed_color,
        "embed_title": title,
        "required_role_id": required_role.id if required_role is not None else None
    }
    save_giveaways()

    view = GiveawayView(msg.id)
    bot.add_view(view)
    await msg.edit(view=view)

    await interaction.response.send_message(
        "Giveaway started!",
        ephemeral=True
    )

    logging.info(f"Giveaway started: {prize} by {interaction.user}")

    await asyncio.sleep(duration_seconds)

    # Check if giveaway still exists
    if msg.id not in giveaways:
        return

    data = giveaways[msg.id]
    participants = data["participants"]
    channel = bot.get_channel(data["channel"])
    prize = data["prize"]

    if not participants:
        if channel:
            await channel.send("No participants joined.")
        del giveaways[msg.id]
        save_giveaways()
        return

    members = [interaction.guild.get_member(uid) for uid in participants]

    winners_list = pick_winners(members, data["winners"])

    if not winners_list:
        if channel:
            await channel.send("Could not select winners (all participants left).")
        del giveaways[msg.id]
        save_giveaways()
        return

    mentions = ", ".join([winner.mention for winner in winners_list])

    end_embed = discord.Embed(
        title="🎉 Giveaway Ended",
        description=f"Prize: **{prize}**\nWinner(s): {mentions}",
        color=embed_color
    )

    if channel:
        await channel.send(embed=end_embed)

    logging.info(f"Giveaway ended: {prize} - Winners: {mentions}")
    del giveaways[msg.id]
    save_giveaways()


@app_commands.checks.has_permissions(manage_guild=True)
@bot.tree.command(name="gend", description="End a giveaway early (admin only)")
@app_commands.describe(message_id="Message ID of the giveaway")
async def gend(interaction: discord.Interaction, message_id: str):
    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "You need admin permissions to end giveaways.",
            ephemeral=True
        )
        return

    try:
        gid = int(message_id)
    except ValueError:
        await interaction.response.send_message(
            "Invalid message ID.",
            ephemeral=True
        )
        return

    if gid not in giveaways:
        await interaction.response.send_message(
            "Giveaway not found.",
            ephemeral=True
        )
        return

    data = giveaways[gid]
    participants = data["participants"]
    channel = bot.get_channel(data["channel"])
    prize = data["prize"]
    embed_color = data.get("embed_color", 0x9b59b6)

    if not participants:
        if channel:
            await channel.send("No participants joined.")
        del giveaways[gid]
        save_giveaways()
        await interaction.response.send_message(
            "Giveaway ended with no participants.",
            ephemeral=True
        )
        return

    members = [interaction.guild.get_member(uid) for uid in participants]

    winners_list = pick_winners(members, data["winners"])

    if not winners_list:
        if channel:
            await channel.send("Could not select winners (all participants left).")
        del giveaways[gid]
        save_giveaways()
        await interaction.response.send_message(
            "Giveaway ended but no valid winners found.",
            ephemeral=True
        )
        return

    mentions = ", ".join([winner.mention for winner in winners_list])

    end_embed = discord.Embed(
        title="🎉 Giveaway Ended Early",
        description=f"Prize: **{prize}**\nWinner(s): {mentions}",
        color=embed_color
    )

    if channel:
        await channel.send(embed=end_embed)

    logging.info(f"Giveaway ended early: {prize} - Winners: {mentions}")
    del giveaways[gid]
    save_giveaways()

    await interaction.response.send_message(
        f"Giveaway ended! Winners: {mentions}",
        ephemeral=True
    )


@app_commands.checks.has_permissions(manage_guild=True)
@bot.tree.command(name="greroll", description="Reroll a giveaway")
async def greroll(interaction: discord.Interaction, message_id: str):

    try:
        gid = int(message_id)
    except ValueError:
        await interaction.response.send_message(
            "Invalid message ID.",
            ephemeral=True
        )
        return

    if gid not in giveaways:
        await interaction.response.send_message(
            "Giveaway not found.",
            ephemeral=True
        )
        return

    data = giveaways[gid]

    participants = data["participants"]

    if not participants:
        await interaction.response.send_message(
            "No participants.",
            ephemeral=True
        )
        return

    members = [interaction.guild.get_member(uid) for uid in participants]

    winners = pick_winners(members, data["winners"])

    if not winners:
        await interaction.response.send_message(
            "Could not select winners.",
            ephemeral=True
        )
        return

    mentions = ", ".join([winner.mention for winner in winners])

    await interaction.response.send_message(
        f"🎉 New Winner(s): {mentions}"
    )


@app_commands.checks.has_permissions(manage_guild=True)
@bot.tree.command(name="gconfig", description="Configure bonus roles (admin only)")
@app_commands.describe(
    role_name="Role name to add/remove bonus for",
    bonus_entries="Number of bonus entries (0 to remove)"
)
async def gconfig(interaction: discord.Interaction, role_name: str, bonus_entries: int):
    if not is_admin(interaction.user):
        await interaction.response.send_message(
            "You need admin permissions to configure bonuses.",
            ephemeral=True
        )
        return

    global BONUS_ENTRIES

    if bonus_entries <= 0:
        if role_name in BONUS_ENTRIES:
            del BONUS_ENTRIES[role_name]
            await interaction.response.send_message(
                f"Removed bonus for role '{role_name}'.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"Role '{role_name}' has no bonus to remove.",
                ephemeral=True
            )
    else:
        BONUS_ENTRIES[role_name] = bonus_entries
        await interaction.response.send_message(
            f"Set {bonus_entries} bonus entries for role '{role_name}'.",
            ephemeral=True
        )

    # Save config
    try:
        with open("bonus_config.json", 'w') as f:
            json.dump(BONUS_ENTRIES, f, indent=2)
        logging.info(f"Bonus config updated: {BONUS_ENTRIES}")
    except Exception as e:
        logging.error(f"Error saving bonus config: {e}")


bot.run(TOKEN)