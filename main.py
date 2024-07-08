import os

import discord
import requests
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)


def check_jadwal(date):
  empty_slots = set()
  payload = {"venue_id": 307, "date": date}

  response = requests.get(
      f"https://ayo.co.id/venues-ajax/op-times-and-fields?venue_id=307&date={date}",
      params=payload).json()

  if not len(response["op_time"]["hours"]):
    return f"Maaf, jadwal untuk {response['op_time']['day']}, {date} belum dibuka"

  for field in response["fields"]:
    for slot in field["slots"]:
      if slot["is_available"]:
        empty_slots.add(f"{slot['start_time']} - {slot['end_time']}")

  if not (len(empty_slots)):
    return f"Maaf, jadwal untuk {response['op_time']['day']}, {date} sudah penuh"

  empty_slots = list(empty_slots)
  empty_slots.sort()
  joined_slots = '\n'.join(empty_slots)
  text = f"""
Berikut jadwal GOR Kukusan yang tersedia untuk Hari {response['op_time']['day']}, Tanggal {date}:

{joined_slots}
  """

  return text


@bot.event
async def on_ready():
  print(f"{bot.user} Started")
  try:
    synced = await bot.tree.sync()
    print(f"Synced {len(synced)} command(s)")
  except Exception as e:
    print(e)


@bot.event
async def on_message(message):
  if message.author == bot.user:
    return

  if message.content.startswith("!hello"):
    await message.channel.send("Hello!")


@bot.tree.command(name='jadwal')
@app_commands.describe(place='Nama GOR', date='YYYY-MM-DD')
async def jadwal(interaction, place: str, date: str):
  if place.lower() != 'kukusan':
    await interaction.response.send_message(
        "Maaf, baru bisa gor kukusan Kak 😭😭")
    return
  res = check_jadwal(date)
  await interaction.response.send_message(res)


bot.run(TOKEN)